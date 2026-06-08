"""Database initialisation and seed data for Family HQ.

Provides:
    init_db() – create all tables and seed the 6 built-in agents.
    Фінн (finance) is an external agent and is NOT seeded here.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

import structlog
from sqlalchemy import text


_PATCH_LOG = structlog.get_logger()


# Columns that were added to existing tables after the DB schema's
# first creation. SQLite cleanly supports ALTER TABLE ADD COLUMN and
# is a no-op if the column already exists (we check first).
_COLUMN_PATCHES: list[tuple[str, str, str]] = [
    # (table, column, sql_type)
    ("baby_state", "walking_since", "TEXT"),
    ("baby_state", "walk_ended_at", "TEXT"),
    ("parcels", "member", "TEXT"),
]


def _apply_column_patches(conn) -> None:
    for table, column, col_type in _COLUMN_PATCHES:
        try:
            rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
            existing = {r[1] for r in rows}  # column name is index 1
            if not rows:
                continue  # table itself doesn't exist yet, create_all handles it
            if column in existing:
                continue
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"))
            _PATCH_LOG.info("db_column_patched", table=table, column=column)
        except Exception:
            _PATCH_LOG.exception("db_column_patch_failed", table=table, column=column)

import structlog
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.future import select

from .models import Agent, Base

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Seed data – the 6 built-in agents
# ---------------------------------------------------------------------------

_SEED_AGENTS: list[dict[str, str]] = [
    {
        "agent_id": "nanny",
        "name": "Nanny",
        "emoji": "👶",
        "bot_token_env": "NANNY_BOT_TOKEN",
        "zone": "family",
        "verbosity": "on_demand",
    },
    {
        "agent_id": "news",
        "name": "News",
        "emoji": "📰",
        "bot_token_env": "NEWS_BOT_TOKEN",
        "zone": "info",
        "verbosity": "proactive",
    },
    {
        "agent_id": "calendar",
        "name": "Calendar",
        "emoji": "📅",
        "bot_token_env": "CALENDAR_BOT_TOKEN",
        "zone": "planning",
        "verbosity": "proactive",
    },
    {
        "agent_id": "cook",
        "name": "Cook",
        "emoji": "🍳",
        "bot_token_env": "COOK_BOT_TOKEN",
        "zone": "household",
        "verbosity": "on_demand",
    },
    {
        "agent_id": "health",
        "name": "Health",
        "emoji": "🏥",
        "bot_token_env": "HEALTH_BOT_TOKEN",
        "zone": "health",
        "verbosity": "on_demand",
    },
    {
        "agent_id": "devops",
        "name": "DevOps",
        "emoji": "🛠️",
        "bot_token_env": "DEVOPS_BOT_TOKEN",
        "zone": "system",
        "verbosity": "silent",
    },
    {
        "agent_id": "navigator",
        "name": "Штурман",
        "emoji": "🧭",
        "bot_token_env": "NAVIGATOR_BOT_TOKEN",
        "zone": "travel",
        "verbosity": "on_demand",
    },
]


# ---------------------------------------------------------------------------
# Engine factory
# ---------------------------------------------------------------------------


def _make_engine(db_path: str) -> AsyncEngine:
    """Return a new async SQLite engine for *db_path*."""
    url = f"sqlite+aiosqlite:///{db_path}"
    return create_async_engine(url, echo=False, future=True)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def init_db(db_path: str | None = None) -> AsyncEngine:
    """Initialise the database and return the async engine.

    Steps:
    1. Resolve *db_path* (env var ``DB_PATH`` → ``/data/family_hq.db``).
    2. Create all tables via ``metadata.create_all``.
    3. Seed the 6 built-in agents if they are not already present.
    4. Return the engine so callers can create sessions from it.
    """
    resolved_path: str = db_path or os.environ.get("DB_PATH", "/data/family_hq.db")
    log.info("db.init_db.start", db_path=resolved_path)

    engine = _make_engine(resolved_path)

    # 1. Create schema
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # 1.5 Lightweight in-place migrations — add columns that the models
    # gained after this DB was first created. SQLite ALTER TABLE only
    # supports ADD COLUMN, which is exactly what we need.
    async with engine.begin() as conn:
        await conn.run_sync(_apply_column_patches)
    log.info("db.init_db.schema_created")

    # 2. Seed agents
    now_iso: str = datetime.now(timezone.utc).isoformat()
    async with AsyncSession(engine, expire_on_commit=False) as session:
        async with session.begin():
            for seed in _SEED_AGENTS:
                result = await session.execute(
                    select(Agent).where(Agent.agent_id == seed["agent_id"])
                )
                existing = result.scalar_one_or_none()
                if existing is None:
                    session.add(
                        Agent(
                            agent_id=seed["agent_id"],
                            name=seed["name"],
                            emoji=seed["emoji"],
                            bot_token_env=seed["bot_token_env"],
                            zone=seed["zone"],
                            verbosity=seed["verbosity"],
                            status="active",
                            hired_at=now_iso,
                        )
                    )
                    log.info("db.init_db.agent_seeded", agent_id=seed["agent_id"])
                else:
                    log.debug("db.init_db.agent_exists", agent_id=seed["agent_id"])

    log.info("db.init_db.done")
    return engine
