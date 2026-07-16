"""Пенды подтверждений действий Дворецкого.

Когда другой агент просит запустить сцену (Няня → Дворецкий), мы не
запускаем сразу, а постим подтверждение с текущими показаниями датчика
и inline-кнопками Да/Нет. Юзер выбирает — и только тогда сцена
исполняется.
"""
from __future__ import annotations
import secrets
import time
from typing import Any

_PENDING: dict[str, dict] = {}
_TTL_SEC = 600  # 10 минут


def _cleanup() -> None:
    now = time.monotonic()
    stale = [k for k, v in _PENDING.items() if now - v.get("ts", 0) > _TTL_SEC]
    for k in stale:
        _PENDING.pop(k, None)


def add_pending(scene_id: str, scene_name: str, origin_agent: str) -> str:
    """Сохраняет ожидающее подтверждение, возвращает короткий id."""
    _cleanup()
    sid = secrets.token_hex(4)  # 8 символов
    _PENDING[sid] = {
        "scene_id": scene_id,
        "scene_name": scene_name,
        "origin": origin_agent,
        "ts": time.monotonic(),
    }
    return sid


def pop_pending(sid: str) -> dict | None:
    _cleanup()
    return _PENDING.pop(sid, None)


def peek_pending(sid: str) -> dict | None:
    _cleanup()
    return _PENDING.get(sid)
