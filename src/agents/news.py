from __future__ import annotations
from typing import Any
import structlog

from src.agents.base import BaseAgent

log = structlog.get_logger()

class NewsAgent(BaseAgent):
    """
    Дозорный — monitors news channels, alerts for air raid sirens.
    """

    agent_id = "news"
    emoji = "📰"
    name = "Дозорный"

    def get_system_prompt(self) -> str:
        from src.prompts.news import get_news_prompt
        return get_news_prompt(
            critical_regions=["Одесса", "Одесская область"],
            important_regions=["Киев", "Харьков"],
            digest_time="08:00",
        )

    def get_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "add_news_channel",
                "description": "Добавить Telegram-канал для мониторинга",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "username": {"type": "string"},
                        "category": {"type": "string", "enum": ["critical", "important", "background", "utility"]},
                        "region": {"type": "string"},
                    },
                    "required": ["username", "category"],
                },
            },
            {
                "name": "get_recent_alerts",
                "description": "Получить только тревоги (повітряна тривога, шахеди, ракети) за период",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "hours": {"type": "integer", "default": 24},
                        "region": {"type": "string"},
                    },
                },
            },
            {
                "name": "get_recent_news",
                "description": "Получить ВСЕ посты из каналов (не только тревоги) за период, сгруппированные по каналу. Используй когда просят 'последние новости', 'что нового', 'сводку'.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "hours": {"type": "integer", "default": 1, "description": "За сколько часов назад"},
                        "region": {"type": "string", "description": "Фильтр по региону (опционально): Одесса, Киев, Украина и т.д."},
                        "category": {"type": "string", "enum": ["critical", "important", "background", "utility"]},
                    },
                },
            },
            {
                "name": "remove_news_channel",
                "description": "Удалить канал из списка отслеживаемых (по username)",
                "input_schema": {
                    "type": "object",
                    "properties": {"username": {"type": "string"}},
                    "required": ["username"],
                },
            },
            {
                "name": "list_news_channels",
                "description": "Получить полный список каналов которые читает Дозорный из БД. Используй ВСЕГДА когда спрашивают «какие каналы», «сколько каналов», «список каналов».",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "category": {"type": "string", "enum": ["critical", "important", "background", "utility"]},
                    },
                },
            },
            {
                "name": "set_region_priority",
                "description": "Изменить приоритет региона",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "region": {"type": "string"},
                        "category": {"type": "string", "enum": ["critical", "important", "background", "utility"]},
                    },
                    "required": ["region", "category"],
                },
            },
            {
                "name": "channels_activity",
                "description": (
                    "Проверить активность каналов за последние N часов. "
                    "Показывает сколько постов пришло с каждого канала и "
                    "какие каналы молчат (0 постов) — сразу видно кто "
                    "заигнорен или отвалился. Триггеры: «какие каналы "
                    "молчат», «какие каналы работают», «активность "
                    "каналов», «сколько постов за сутки», «проверь "
                    "каналы»."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "hours": {"type": "integer", "description": "За сколько часов назад (по умолчанию 24)"},
                    },
                },
            },
        ]

    async def _call_tool(self, tool_name: str, tool_input: dict[str, Any]) -> Any:
        if tool_name == "add_news_channel":
            import hashlib
            username = (tool_input.get("username") or "").lstrip("@").strip()
            if not username:
                return {"success": False, "error": "empty username"}

            # Check if already exists
            from src.db.models import NewsChannel
            from sqlalchemy import select
            async with self._memory._engine.connect() as conn:
                existing = await conn.execute(
                    select(NewsChannel).where(NewsChannel.username == username)
                )
                existing_row = existing.first()
            if existing_row:
                return {
                    "success": False,
                    "already_exists": True,
                    "username": username,
                    "category": existing_row.category,
                    "region": existing_row.region,
                    "active": bool(existing_row.active),
                    "message": f"Канал @{username} уже отслеживается (категория {existing_row.category}).",
                }

            # Stable placeholder channel_id from username hash (negative to avoid
            # collisions with real Telegram channel IDs). Will be updated to the
            # real ID once the user-bot resolves it on startup.
            placeholder_id = -(int(hashlib.sha1(username.encode()).hexdigest()[:12], 16) % (10**11))
            async with self._memory._engine.begin() as conn:
                from sqlalchemy import insert
                from src.utils.time import iso_now
                await conn.execute(
                    insert(NewsChannel).prefix_with("OR IGNORE").values(
                        channel_id=placeholder_id,
                        username=username,
                        title=username,
                        category=tool_input.get("category", "background"),
                        region=tool_input.get("region"),
                        mode="digest" if tool_input.get("category") == "background" else "alert",
                        added_at=iso_now(),
                    )
                )
            return {"success": True, "username": username, "note": "User-bot will subscribe on next restart"}

        elif tool_name == "remove_news_channel":
            username = (tool_input.get("username") or "").lstrip("@").strip()
            if not username:
                return {"success": False, "error": "empty username"}
            async with self._memory._engine.begin() as conn:
                from src.db.models import NewsChannel
                from sqlalchemy import delete
                result = await conn.execute(
                    delete(NewsChannel).where(NewsChannel.username == username)
                )
                deleted = result.rowcount or 0
            return {"success": True, "deleted": deleted, "username": username}

        elif tool_name == "list_news_channels":
            async with self._memory._engine.connect() as conn:
                from src.db.models import NewsChannel
                from sqlalchemy import select
                stmt = select(NewsChannel).order_by(NewsChannel.category, NewsChannel.username)
                category = tool_input.get("category")
                if category:
                    stmt = stmt.where(NewsChannel.category == category)
                rows = await conn.execute(stmt)
                channels = [
                    {
                        "username": r.username,
                        "title": r.title,
                        "category": r.category,
                        "region": r.region,
                    }
                    for r in rows
                ]
                return {"count": len(channels), "channels": channels}

        elif tool_name == "channels_activity":
            from datetime import timedelta
            from src.utils.time import now_kyiv
            from src.db.models import NewsPost, NewsChannel
            from sqlalchemy import select, func
            hours = int(tool_input.get("hours", 24))
            since = (now_kyiv() - timedelta(hours=hours)).isoformat()
            async with self._memory._engine.connect() as conn:
                ch_rows = await conn.execute(select(NewsChannel))
                channels = list(ch_rows)
                # Кол-во постов по каналам за N часов
                counts_rows = await conn.execute(
                    select(NewsPost.channel_id, func.count(NewsPost.id))
                    .where(NewsPost.date >= since)
                    .group_by(NewsPost.channel_id)
                )
                counts: dict = {row[0]: row[1] for row in counts_rows}
            report = []
            silent = []
            active = []
            for c in channels:
                cnt = counts.get(c.channel_id, 0)
                entry = {
                    "username": c.username,
                    "title": c.title,
                    "category": c.category,
                    "region": c.region,
                    "active": bool(c.active),
                    "posts_last_h": cnt,
                }
                report.append(entry)
                if not c.active:
                    continue
                if cnt == 0:
                    silent.append(entry)
                else:
                    active.append(entry)
            active.sort(key=lambda x: -x["posts_last_h"])
            return {
                "hours": hours,
                "total_channels": len(channels),
                "active_channels": len(active),
                "silent_channels": len(silent),
                "silent_list": [x["username"] or x["title"] for x in silent],
                "top_active": active[:10],
                "all": report,
            }

        elif tool_name == "get_recent_alerts":
            from datetime import timedelta
            from src.utils.time import now_kyiv
            async with self._memory._engine.connect() as conn:
                from src.db.models import NewsPost
                from sqlalchemy import select
                hours = int(tool_input.get("hours", 24))
                since = (now_kyiv() - timedelta(hours=hours)).isoformat()
                stmt = (
                    select(NewsPost)
                    .where(NewsPost.is_alert == 1)
                    .where(NewsPost.date >= since)
                    .order_by(NewsPost.date.desc())
                    .limit(30)
                )
                region = tool_input.get("region")
                if region:
                    stmt = stmt.where(NewsPost.alert_region == region)
                rows = await conn.execute(stmt)
                items = [{"text": r.text[:200], "date": r.date, "region": r.alert_region} for r in rows]
                return {"count": len(items), "hours": hours, "alerts": items}

        elif tool_name == "get_recent_news":
            from datetime import timedelta
            from src.utils.time import now_kyiv
            from src.db.models import NewsPost, NewsChannel
            from sqlalchemy import select
            hours = int(tool_input.get("hours", 1))
            since = (now_kyiv() - timedelta(hours=hours)).isoformat()
            async with self._memory._engine.connect() as conn:
                # Build channel lookup
                ch_rows = await conn.execute(select(NewsChannel))
                ch_by_id = {r.channel_id: r for r in ch_rows}

                stmt = (
                    select(NewsPost)
                    .where(NewsPost.date >= since)
                    .order_by(NewsPost.date.desc())
                    .limit(200)
                )
                rows = list(await conn.execute(stmt))

            category = tool_input.get("category")
            region_filter = tool_input.get("region", "").lower()

            grouped: dict[str, list[dict]] = {}
            for r in rows:
                ch = ch_by_id.get(r.channel_id)
                if category and ch and ch.category != category:
                    continue
                if region_filter:
                    text_l = (r.text or "").lower()
                    ch_region = (ch.region or "").lower() if ch else ""
                    if region_filter not in text_l and region_filter not in ch_region:
                        continue
                ch_key = (ch.username or ch.title or f"id{r.channel_id}") if ch else f"id{r.channel_id}"
                grouped.setdefault(ch_key, []).append({
                    "text": (r.text or "")[:400],
                    "date": r.date,
                    "is_alert": bool(r.is_alert),
                })

            return {
                "hours": hours,
                "channels_count": len(grouped),
                "total_posts": sum(len(v) for v in grouped.values()),
                "by_channel": grouped,
            }

        return await super()._call_tool(tool_name, tool_input)
