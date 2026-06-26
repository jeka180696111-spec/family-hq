"""Weekly family-style memo.

Раз в неделю (воскресенье 23:50) LLM анализирует последние 14 дней
переписки в чате, вытаскивает сленг, тон и привычки каждого юзера.
Сохраняет в БД (FamilyMode с name='family_style_memo'). При сборке
family_context_block эта заметка инжектится во все промпты — агенты
видят и адаптируют тон.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Any

import structlog

log = structlog.get_logger()


async def refresh_family_style(
    devops_agent: Any, memory: Any,
) -> None:
    try:
        from sqlalchemy import select, insert
        from src.db.models import Message, FamilyMode
        from src.utils.time import now_kyiv, iso_now

        since = (now_kyiv() - timedelta(days=14)).isoformat()
        async with memory._engine.connect() as conn:
            rows = list(await conn.execute(
                select(Message).where(Message.created_at >= since)
                .where(Message.agent_id.is_(None))  # только юзерские
            ))
        if len(rows) < 30:
            log.info("family_style_skipped", reason="too_few_messages", n=len(rows))
            return

        # Сгруппируем по author user_id
        from collections import defaultdict
        per_user: dict[int, list[str]] = defaultdict(list)
        for r in rows:
            uid = r.user_id
            if uid is None:
                continue
            per_user[uid].append(r.text or "")

        if not per_user:
            return

        # Собираем компактный sample
        samples_text = ""
        for uid, msgs in per_user.items():
            sample = msgs[-40:]  # последние 40 сообщений каждого
            samples_text += f"\n=== user#{uid} ({len(msgs)} сообщ.) ===\n"
            for m in sample:
                if m:
                    samples_text += f"  · {m[:120]}\n"

        prompt = (
            "Изучи стиль речи каждого автора в чате семьи. Для каждого "
            "user# напиши 3-5 строк: характерный сленг (любимые слова, "
            "обращения), длина сообщений (короткие/развёрнутые), тон "
            "(тёплый/деловой/ироничный), типичные эмодзи, время "
            "активности если видно.\n\n"
            "Цель: чтобы агенты адаптировали тон. Не перечисляй "
            "очевидное («использует кириллицу»), бери ХАРАКТЕРНОЕ.\n\n"
            "Формат ответа:\n"
            "user#XXX (имя если знаешь):\n"
            "- Сленг: ...\n"
            "- Длина: ...\n"
            "- Тон: ...\n"
            "- Эмодзи: ...\n\n"
            f"СООБЩЕНИЯ:\n{samples_text[:8000]}"
        )

        try:
            memo = await devops_agent._claude.complete(
                model=devops_agent._get_model(),
                system=(
                    "Ты — лингвист-аналитик. Делаешь компактный профайл "
                    "стиля каждого участника чата."
                ),
                messages=[{"role": "user", "content": prompt}],
                max_tokens=900,
            )
        except Exception:
            log.exception("family_style_llm_failed")
            return

        if not memo or len(memo.strip()) < 50:
            return

        # Сохраняем как FamilyMode row (это удобный k/v)
        async with memory._engine.begin() as conn:
            await conn.execute(insert(FamilyMode).prefix_with("OR REPLACE").values(
                name="family_style_memo",
                enabled=1,
                payload=memo.strip()[:4000],
                started_at=iso_now(),
                expires_at=None,
            ))
        # Обновляем in-memory cache, который family_context_block читает
        # синхронно.
        try:
            from src.utils.family import update_style_cache
            update_style_cache(memo.strip())
        except Exception:
            log.exception("style_cache_update_failed")
        log.info("family_style_refreshed", chars=len(memo))
    except Exception:
        log.exception("family_style_refresh_failed")


def register_family_style_job(scheduler, devops_agent, memory) -> None:
    # Воскресенье в 23:50 Киева — собирает стиль за неделю.
    scheduler.add_job(
        refresh_family_style, "cron",
        day_of_week="sun", hour=23, minute=50,
        args=[devops_agent, memory],
        id="family_style_refresh", replace_existing=True,
    )
    # Однократный warm-up через 5 мин после старта чтобы при свежем
    # деплое не ждать неделю до первой записи.
    from datetime import datetime, timedelta
    scheduler.add_job(
        refresh_family_style, "date",
        run_date=datetime.now() + timedelta(minutes=5),
        args=[devops_agent, memory],
        id="family_style_warmup", replace_existing=True,
    )
    log.info("family_style_registered")
