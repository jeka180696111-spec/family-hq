from __future__ import annotations
import asyncio
import logging
import os
import sys
from typing import Any

import structlog


def setup_logging(log_level: str = "INFO") -> None:
    """Configure structlog for the application."""
    level = getattr(logging, log_level.upper(), logging.INFO)

    # Determine whether we're in a TTY / dev environment
    is_dev = sys.stderr.isatty() or os.environ.get("ENV", "production").lower() in (
        "dev",
        "development",
        "local",
    )

    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if is_dev:
        renderer: Any = structlog.dev.ConsoleRenderer(colors=True)
    else:
        renderer = structlog.processors.JSONRenderer()

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    # Root handler → stderr
    handler: logging.Handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(formatter)

    # Optional file sink
    log_file = os.environ.get("LOG_FILE")
    handlers: list[logging.Handler] = [handler]
    if log_file:
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(formatter)
        handlers.append(file_handler)

    # DB sink for ERROR+
    db_handler = DBLogHandler()
    db_handler.setLevel(logging.ERROR)
    db_handler.setFormatter(formatter)
    handlers.append(db_handler)

    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    root_logger.handlers = handlers


def get_logger(name: str, **context: Any) -> structlog.BoundLogger:
    """Get a bound logger with context."""
    logger: structlog.BoundLogger = structlog.get_logger(name)
    if context:
        logger = logger.bind(**context)
    return logger


class DBLogHandler(logging.Handler):
    """Async-compatible handler that writes ERROR+ logs to the event_log table.

    Actual DB writes are dispatched via asyncio.create_task so that this
    handler never blocks the caller, even when called from async code.
    If no running event loop is available (e.g. during startup / tests)
    the record is silently dropped rather than raising.
    """

    def emit(self, record: logging.LogRecord) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # No running loop — skip silently
            return

        loop.create_task(self._write(record))

    async def _write(self, record: logging.LogRecord) -> None:
        """Persist the log record to event_log.

        The actual DB session is obtained lazily to avoid import-time
        circular dependencies with src.db.
        """
        try:
            # Import here to avoid circular imports at module load time
            from src.db.models import EventLog  # noqa: PLC0415
            from src.db import get_session  # type: ignore[attr-defined]  # noqa: PLC0415

            async with get_session() as session:
                entry = EventLog(
                    level=record.levelname,
                    logger=record.name,
                    message=self.format(record),
                )
                session.add(entry)
                await session.commit()
        except Exception:  # noqa: BLE001
            # Never let logging errors propagate
            pass
