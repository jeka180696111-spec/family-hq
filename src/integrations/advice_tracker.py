"""Tracking of agent advice vs reality.

Pattern:
1. Agent gives a concrete recommendation → record_advice(...)
2. Time passes, реальные данные появляются в Дневнике / etc.
3. evaluate_pending() сравнивает совет с реальностью → outcome.
4. Перед следующим советом — recent_advice_summary(agent_id) для
   контекста LLM (учиться на ошибках, ссылаться на прошлые).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

import structlog

log = structlog.get_logger()


async def record_advice(
    memory: Any,
    agent_id: str,
    advice_type: str,
    target: dict,
) -> int | None:
    """Save an advice record. Returns row id or None on failure."""
    try:
        from sqlalchemy import insert
        from src.db.models import AgentAdvice
        from src.utils.time import iso_now
        async with memory._engine.begin() as conn:
            r = await conn.execute(insert(AgentAdvice).values(
                agent_id=agent_id,
                advice_type=advice_type,
                given_at=iso_now(),
                target_payload=json.dumps(target, ensure_ascii=False),
            ))
            return r.inserted_primary_key[0] if r.inserted_primary_key else None
    except Exception:
        log.exception("advice_record_failed")
        return None


async def evaluate_pending(memory: Any, sheets_client: Any) -> int:
    """Walk un-evaluated advice older than 12h, compare with reality,
    set outcome. Returns count evaluated."""
    from sqlalchemy import select, update as sql_update
    from src.db.models import AgentAdvice
    from src.utils.time import iso_now, now_kyiv

    cutoff = (now_kyiv() - timedelta(hours=12)).isoformat()
    async with memory._engine.connect() as conn:
        rows = list(await conn.execute(
            select(AgentAdvice)
            .where(AgentAdvice.outcome.is_(None))
            .where(AgentAdvice.given_at <= cutoff)
        ))

    if not rows:
        return 0

    evaluated = 0
    for row in rows:
        try:
            target = json.loads(row.target_payload)
            outcome, actual = await _evaluate_one(row.advice_type, target, sheets_client)
            if outcome is None:
                continue
            async with memory._engine.begin() as conn:
                await conn.execute(
                    sql_update(AgentAdvice).where(AgentAdvice.id == row.id).values(
                        evaluated_at=iso_now(),
                        outcome=outcome,
                        actual_payload=json.dumps(actual, ensure_ascii=False),
                    )
                )
            evaluated += 1
        except Exception:
            log.exception("advice_evaluate_failed", advice_id=row.id)
    if evaluated:
        log.info("advice_evaluated", count=evaluated)
    return evaluated


async def _evaluate_one(advice_type: str, target: dict, sheets_client: Any) -> tuple[str | None, dict]:
    """Return (outcome, actual_dict) or (None, {}) if нельзя оценить."""
    if advice_type == "nap_target":
        # target: {target_at, target_duration_min, source_awake_since}
        from src.integrations.sleep_coach import _load_sleep_entries, _pair_episodes
        try:
            entries = await _load_sleep_entries(sheets_client, days=2)
            episodes = _pair_episodes(entries)
        except Exception:
            return None, {}
        target_at_str = target.get("target_at")
        if not target_at_str:
            return None, {}
        try:
            target_at = datetime.fromisoformat(target_at_str)
        except Exception:
            return None, {}
        # Найти эпизод чей start ближайший к target_at (в пределах 90 мин)
        best = None
        for ep in episodes:
            if ep["is_night"]:
                continue
            delta = abs((ep["start"] - target_at).total_seconds() / 60.0)
            if delta <= 90 and (best is None or delta < best[0]):
                best = (delta, ep)
        if best is None:
            return "miss", {"reason": "не уложили в окно ±90 мин от плана"}
        delta_min, ep = best
        target_dur = target.get("target_duration_min") or 0
        actual_dur = ep["duration_min"]
        actual = {
            "actual_start": ep["start"].strftime("%H:%M"),
            "actual_duration_min": actual_dur,
            "start_diff_min": int(delta_min),
            "duration_diff_min": int(actual_dur - target_dur) if target_dur else None,
        }
        if delta_min <= 15 and (not target_dur or abs(actual_dur - target_dur) <= 20):
            return "hit", actual
        if delta_min <= 30 and (not target_dur or abs(actual_dur - target_dur) <= 30):
            return "partial", actual
        return "miss", actual
    return None, {}


async def recent_advice_summary(memory: Any, agent_id: str, days: int = 4) -> str:
    """Краткая сводка по последним советам: 3 hits / 1 partial / 1 miss.
    Используется как контекст для LLM, чтобы агент ссылался на прошлый
    опыт и не повторял неработающие схемы."""
    from sqlalchemy import select
    from src.db.models import AgentAdvice
    from src.utils.time import now_kyiv

    since = (now_kyiv() - timedelta(days=days)).isoformat()
    async with memory._engine.connect() as conn:
        rows = list(await conn.execute(
            select(AgentAdvice)
            .where(AgentAdvice.agent_id == agent_id)
            .where(AgentAdvice.given_at >= since)
            .order_by(AgentAdvice.given_at.desc())
        ))
    if not rows:
        return ""
    counts = {"hit": 0, "partial": 0, "miss": 0, "pending": 0}
    examples: list[str] = []
    for r in rows[:10]:
        oc = r.outcome or "pending"
        counts[oc] = counts.get(oc, 0) + 1
        try:
            tgt = json.loads(r.target_payload)
            act = json.loads(r.actual_payload) if r.actual_payload else {}
        except Exception:
            tgt, act = {}, {}
        if r.advice_type == "nap_target" and oc in ("hit", "partial", "miss"):
            target_at = tgt.get("target_at", "")[-5:] or "?"
            actual_start = act.get("actual_start", "?")
            actual_dur = act.get("actual_duration_min")
            line = f"{r.given_at[5:16]} советовала {target_at}"
            if oc != "miss":
                line += f" → факт {actual_start} ({actual_dur}м)"
            else:
                line += f" → {act.get('reason','промах')}"
            line += f" [{oc}]"
            examples.append(line)
    parts = [
        f"📊 Совет vs факт за {days}д: "
        f"✅ {counts.get('hit',0)} hit | "
        f"🟡 {counts.get('partial',0)} partial | "
        f"🔴 {counts.get('miss',0)} miss | "
        f"⏳ {counts.get('pending',0)} pending"
    ]
    if examples:
        parts.append("Примеры:")
        parts.extend(f"  • {e}" for e in examples[:5])
    parts.append(
        "Используй эти данные: если последние советы miss — менять "
        "подход. Если стабильно hit — продолжать линию."
    )
    return "\n".join(parts)
