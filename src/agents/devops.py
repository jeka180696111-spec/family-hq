from __future__ import annotations
from typing import Any
import structlog

from src.agents.base import BaseAgent

log = structlog.get_logger()

class DevOpsAgent(BaseAgent):
    """
    Прораб — monitors system health, creates GitHub PRs for fixes,
    manages agent hiring/firing workflow.
    """

    agent_id = "devops"
    emoji = "🛠️"
    name = "Прораб"

    def __init__(self, *args, github_client=None, railway_client=None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._railway = railway_client
        self._github = github_client

    def get_system_prompt(self) -> str:
        from src.prompts.devops import get_devops_prompt
        return get_devops_prompt(active_agents=[])

    def get_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "read_logs",
                "description": "Прочитать логи системы",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "level": {"type": "string", "enum": ["INFO", "WARNING", "ERROR", "CRITICAL"], "default": "ERROR"},
                        "agent_id": {"type": "string"},
                        "limit": {"type": "integer", "default": 50},
                    },
                },
            },
            {
                "name": "create_github_pr",
                "description": "Создать Pull Request в GitHub",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "branch": {"type": "string"},
                        "body": {"type": "string"},
                        "files": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "path": {"type": "string"},
                                    "content": {"type": "string"},
                                },
                            },
                        },
                    },
                    "required": ["title", "branch", "body"],
                },
            },
            {
                "name": "ping_external",
                "description": "Проверить внешний сервис",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "service": {"type": "string", "enum": ["matveika_bot", "finance_bot", "anthropic_api"]},
                    },
                    "required": ["service"],
                },
            },
            {
                "name": "read_file",
                "description": "Прочитать файл проекта",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Путь относительно корня проекта"},
                    },
                    "required": ["path"],
                },
            },
            {
                "name": "system_status",
                "description": (
                    "Полная диагностика системы. Используй когда: «статус», «как дела», "
                    "«что там у тебя», «проверь систему», «здоровье системы». "
                    "Покажет: каналы Дозорного (подписки/последний пост), активные тревоги, "
                    "Sheets/Calendar/GitHub/Railway статус, последние ошибки в логах."
                ),
                "input_schema": {"type": "object", "properties": {}},
            },
            {
                "name": "cost_report",
                "description": (
                    "Сколько потратили на Anthropic API. Используй когда: «сколько спалили», "
                    "«отчёт по тратам», «сколько стоит за день/месяц», «cost»."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "days": {"type": "integer", "description": "За сколько дней назад (по умолчанию 30)"},
                    },
                },
            },
            {
                "name": "set_family_fact",
                "description": (
                    "Изменить факт о семье без правки кода. Используй когда: "
                    "«запомни Матвей весит 9.5кг», «измерили рост 73», «новый помощник», "
                    "«у Марины аллергия на X». Также используй для переезда/отпуска: "
                    "set_family_fact('current_location.city', 'Львов'). "
                    "Доступные ключи (примеры): "
                    "matvey.weight_g, matvey.height_cm, "
                    "current_location.city, current_location.district, current_location.until_date, "
                    "father.weight_kg, mother.weight_kg, mother.blood_type."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "key": {"type": "string"},
                        "value": {"type": "string"},
                    },
                    "required": ["key", "value"],
                },
            },
            {
                "name": "restart_main_service",
                "description": "Перезапустить главный сервис family-hq на Railway. Применяется когда Дозорный добавил новые каналы и нужно чтобы userbot подписался, или когда AI ведёт себя странно. Требует подтверждения от пользователя.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "reason": {"type": "string", "description": "Кратко зачем рестарт"},
                    },
                    "required": ["reason"],
                },
            },
        ]

    async def _call_tool(self, tool_name: str, tool_input: dict[str, Any]) -> Any:
        if tool_name == "read_logs":
            async with self._memory._engine.connect() as conn:
                from src.db.models import EventLog
                from sqlalchemy import select
                query = select(EventLog).order_by(EventLog.created_at.desc()).limit(tool_input.get("limit", 50))
                if tool_input.get("level"):
                    query = query.where(EventLog.level == tool_input["level"])
                if tool_input.get("agent_id"):
                    query = query.where(EventLog.agent_id == tool_input["agent_id"])
                rows = await conn.execute(query)
                return [{"level": r.level, "agent": r.agent_id, "msg": r.message, "at": r.created_at} for r in rows]

        elif tool_name == "create_github_pr" and self._github:
            branch = tool_input["branch"]
            await self._github.create_branch(branch)

            for file_info in tool_input.get("files", []):
                await self._github.create_or_update_file(
                    path=file_info["path"],
                    content=file_info["content"],
                    message=f"[Прораб] {tool_input['title']}",
                    branch=branch,
                )

            pr = await self._github.create_pull_request(
                title=tool_input["title"],
                body=tool_input["body"],
                head_branch=branch,
            )
            return {"pr_url": pr.html_url, "pr_number": pr.number}

        elif tool_name == "ping_external":
            import httpx
            service = tool_input["service"]
            if service == "anthropic_api":
                try:
                    async with httpx.AsyncClient() as client:
                        resp = await client.get("https://api.anthropic.com/v1/models", timeout=10)
                        return {"status": "ok" if resp.status_code < 500 else "degraded"}
                except Exception as e:
                    return {"status": "down", "error": str(e)}
            return {"status": "unknown", "service": service}

        elif tool_name == "read_file":
            import aiofiles
            import os
            path = tool_input["path"].lstrip("/")
            # Security: only allow reading project files
            safe_path = os.path.normpath(os.path.join("/home/user/many", path))
            if not safe_path.startswith("/home/user/many"):
                return {"error": "Access denied"}
            try:
                async with aiofiles.open(safe_path, "r") as f:
                    content = await f.read()
                return {"content": content[:5000], "truncated": len(content) > 5000}
            except FileNotFoundError:
                return {"error": f"File not found: {path}"}

        elif tool_name == "system_status":
            return await self._system_status()

        elif tool_name == "cost_report":
            return await self._cost_report(int(tool_input.get("days", 30)))

        elif tool_name == "set_family_fact":
            return await self._set_family_fact(tool_input.get("key", ""), tool_input.get("value", ""))

        elif tool_name == "restart_main_service":
            from src.config import get_settings
            settings = get_settings()
            reason = tool_input.get("reason", "")

            # Strategy 1: Railway GraphQL API (fails on Hobby plan)
            railway_error: str | None = None
            if self._railway and settings.matveika_service_id:
                try:
                    await self._railway.restart_service(
                        settings.matveika_service_id, environment_id=""
                    )
                    return {"success": True, "via": "railway_api", "reason": reason}
                except Exception as e:
                    railway_error = str(e)
                    log.warning("railway_restart_failed", error=railway_error)

            # Strategy 2: trigger redeploy via empty commit on main (works on Hobby)
            if self._github:
                try:
                    sha = await self._github.trigger_redeploy_via_commit(
                        branch="main", reason=reason or "devops restart"
                    )
                    return {
                        "success": True,
                        "via": "github_empty_commit",
                        "sha": sha,
                        "reason": reason,
                        "note": "Railway autodeploy picks this up in 1-2 min",
                        "railway_api_error": railway_error,
                    }
                except Exception as e:
                    return {
                        "error": "Both Railway API and GitHub fallback failed",
                        "railway_api_error": railway_error,
                        "github_error": str(e),
                    }

            return {
                "error": "No restart method available — Railway не настроен и GitHub-токен отсутствует",
                "railway_api_error": railway_error,
            }

        return await super()._call_tool(tool_name, tool_input)

    async def analyze_error(self, error_log: dict[str, Any]) -> str:
        """Analyze an error log entry and decide if PR is needed."""
        resp = await self._claude.complete(
            model=self._get_model(),
            system=self.get_system_prompt(),
            messages=[{
                "role": "user",
                "content": f"Вижу ошибку:\n{error_log}\n\nПроанализируй и скажи нужен ли патч.",
            }],
            max_tokens=1024,
        )
        return resp

    async def _system_status(self) -> dict:
        from datetime import timedelta
        from sqlalchemy import func, select
        from src.db.models import ActiveAlert, NewsChannel, NewsPost
        from src.utils.time import now_kyiv

        async with self._memory._engine.connect() as conn:
            channels = list(await conn.execute(select(NewsChannel)))
            alerts = list(await conn.execute(select(ActiveAlert)))
            last_post = (await conn.execute(
                select(NewsPost.date).order_by(NewsPost.date.desc()).limit(1)
            )).first()

        ch_by_cat: dict[str, int] = {}
        inactive = 0
        for c in channels:
            ch_by_cat[c.category] = ch_by_cat.get(c.category, 0) + 1
            if not c.active:
                inactive += 1

        last_post_iso = last_post[0] if last_post else None
        last_post_lag_min = None
        if last_post_iso:
            try:
                from datetime import datetime
                lag = now_kyiv() - datetime.fromisoformat(last_post_iso)
                last_post_lag_min = int(lag.total_seconds() / 60)
            except Exception:
                pass

        from src.config import get_settings
        settings = get_settings()
        return {
            "userbot": {
                "enabled": settings.enable_userbot,
                "hq_chat_id": settings.hq_chat_id,
                "phone": settings.tg_phone[:6] + "…" if settings.tg_phone else None,
            },
            "news_channels": {
                "total": len(channels),
                "by_category": ch_by_cat,
                "inactive": inactive,
            },
            "news_posts": {
                "last_saved_at": last_post_iso,
                "minutes_ago": last_post_lag_min,
                "stale": (last_post_lag_min or 0) > 120 if last_post_lag_min is not None else None,
            },
            "active_alerts": [
                {"region": a.region, "started": a.started_at, "last_update": a.last_update_at}
                for a in alerts
            ],
            "integrations": {
                "google_sheets": bool(settings.sheet_baby_id and settings.google_service_account_b64),
                "google_calendar": bool(settings.calendar_id and settings.google_service_account_b64),
                "github": bool(settings.github_token),
                "railway": bool(settings.railway_api_token and settings.railway_project_id),
            },
            "model": {
                "main": settings.model_main,
                "cheap": settings.model_cheap,
            },
        }

    async def _cost_report(self, days: int) -> dict:
        from datetime import date, timedelta
        from sqlalchemy import func, select
        from src.db.models import ApiUsage

        # Pricing per 1M tokens (USD) — public Anthropic rates (June 2026)
        prices = {
            "sonnet": {"in": 3.0, "out": 15.0, "cache_w": 3.75, "cache_r": 0.30},
            "haiku":  {"in": 0.80, "out": 4.0, "cache_w": 1.00, "cache_r": 0.08},
            "opus":   {"in": 15.0, "out": 75.0, "cache_w": 18.75, "cache_r": 1.50},
        }

        def family_of(model_name: str) -> str:
            n = (model_name or "").lower()
            if "opus" in n: return "opus"
            if "haiku" in n: return "haiku"
            return "sonnet"

        cutoff = (date.today() - timedelta(days=days - 1)).isoformat()
        async with self._memory._engine.connect() as conn:
            rows = list(await conn.execute(
                select(ApiUsage).where(ApiUsage.date >= cutoff)
            ))

        per_day: dict[str, float] = {}
        per_model: dict[str, dict] = {}
        total_in = total_out = total_cw = total_cr = 0
        total_cost = 0.0
        for r in rows:
            fam = family_of(r.model)
            p = prices[fam]
            cost = (
                r.input_tokens * p["in"] / 1e6
                + r.output_tokens * p["out"] / 1e6
                + r.cache_creation_tokens * p["cache_w"] / 1e6
                + r.cache_read_tokens * p["cache_r"] / 1e6
            )
            per_day[r.date] = per_day.get(r.date, 0.0) + cost
            pm = per_model.setdefault(r.model, {"in": 0, "out": 0, "cw": 0, "cr": 0, "cost": 0.0})
            pm["in"] += r.input_tokens
            pm["out"] += r.output_tokens
            pm["cw"] += r.cache_creation_tokens
            pm["cr"] += r.cache_read_tokens
            pm["cost"] += cost
            total_in += r.input_tokens
            total_out += r.output_tokens
            total_cw += r.cache_creation_tokens
            total_cr += r.cache_read_tokens
            total_cost += cost

        return {
            "days": days,
            "total_cost_usd": round(total_cost, 4),
            "today_usd": round(per_day.get(date.today().isoformat(), 0.0), 4),
            "tokens": {
                "input": total_in,
                "output": total_out,
                "cache_write": total_cw,
                "cache_read": total_cr,
            },
            "per_day_usd": {d: round(v, 4) for d, v in sorted(per_day.items())},
            "per_model": {m: {**v, "cost": round(v["cost"], 4)} for m, v in per_model.items()},
        }

    async def _set_family_fact(self, key: str, value: str) -> dict:
        if not key:
            return {"success": False, "error": "key пуст"}
        from sqlalchemy import insert
        from src.db.models import FamilyOverride
        from src.utils.family import apply_overrides
        from src.utils.time import iso_now

        async with self._memory._engine.begin() as conn:
            await conn.execute(
                insert(FamilyOverride).prefix_with("OR REPLACE").values(
                    key=key,
                    value=value,
                    updated_at=iso_now(),
                    updated_by=getattr(self, "_current_sender", "") or "",
                )
            )
            from sqlalchemy import select
            rows = list(await conn.execute(select(FamilyOverride)))
        apply_overrides({r.key: r.value for r in rows})
        return {"success": True, "key": key, "value": value, "total_overrides": len(rows)}
