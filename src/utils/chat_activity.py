"""Shared «active conversation» tracker.

Когда юзер активно пишет в чат, автоматические пуши (sleep_predictor
«пора будить», runtime «батарея 30%», прививки follow-up) НЕ должны
вклиниваться. Эта мини-утилита хранит timestamp последнего юзерского
сообщения и предоставляет sync-проверку для cron'ов.
"""
from __future__ import annotations

from datetime import datetime, timedelta
import threading

_LAST_USER_MSG: dict[str, datetime] = {"ts": datetime.min}
_LOCK = threading.Lock()


def mark_user_message() -> None:
    """Вызывается из handle_new_message при каждом входящем юзерском
    сообщении. Сбрасывает таймер тишины."""
    with _LOCK:
        _LAST_USER_MSG["ts"] = datetime.now()


def is_chat_active(within_seconds: int = 90) -> bool:
    """True если юзер писал в последние N секунд — авто-пуши
    откладываются."""
    with _LOCK:
        ts = _LAST_USER_MSG["ts"]
    return datetime.now() - ts < timedelta(seconds=within_seconds)


def seconds_since_user() -> float:
    with _LOCK:
        ts = _LAST_USER_MSG["ts"]
    return (datetime.now() - ts).total_seconds()
