"""Automation engine: evaluate user-defined IF-THEN rules every 5 min."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import select, update as sql_update

from src.db.memory import SharedMemory
from src.db.models import ActiveAlert, AutomationRule
from src.utils.time import iso_now, now_kyiv

log = structlog.get_logger()


# ─── Condition schema ────────────────────────────────────────────────
# {"type": "time", "cron": "22:00"}                       — daily at HH:MM
# {"type": "time", "weekday": "sun", "hour": 10}          — weekly
# {"type": "sensor", "device": "детская", "metric":
#   "temperature", "op": ">", "value": 25}                — sensor threshold
# {"type": "alert_active", "region": "Одесса"}            — alert is on
# {"type": "alert_ended", "region": "Одесса"}             — just отбой (≤5 min)
# {"type": "power_outage", "state": "active"}             — light is off
# {"type": "and", "rules": [...]}                         — logical AND
# {"type": "or",  "rules": [...]}                         — logical OR
#
# ─── Action schema ────────────────────────────────────────────────────
# {"type": "device", "device": "бойлер", "action": "off"}
# {"type": "device", "device": "телевизор", "action": "on"}
# {"type": "message", "agent": "devops", "text": "Внимание ..."}
# {"type": "set_mode", "mode": "sick", "enabled": true}
# {"type": "tool", "agent": "calendar", "tool": "list_upcoming", "input": {"days": 1}}


class AutomationEngine:
    def __init__(self, memory: SharedMemory, bot_manager: Any, chat_id: int, agents: dict) -> None:
        self._memory = memory
        self._bots = bot_manager
        self._chat_id = chat_id
        self._agents = agents

    async def trigger_power_outage(self, active: bool) -> None:
        """Fire all rules whose top-level condition matches the new outage state.

        Called by GridWatcher the moment grid loss/restore is detected, so
        boiler / heavy loads cut over immediately instead of waiting for the
        5-min tick.
        """
        state = "active" if active else "ended"
        try:
            async with self._memory._engine.connect() as conn:
                rules = list(await conn.execute(select(AutomationRule).where(AutomationRule.enabled == 1)))
            for rule in rules:
                try:
                    cond = json.loads(rule.condition)
                    if not self._cond_matches_power_outage(cond, state):
                        continue
                    if not await self._eval(cond):
                        continue
                    action = json.loads(rule.action)
                    await self._execute(rule.name, action)
                    async with self._memory._engine.begin() as conn:
                        await conn.execute(
                            sql_update(AutomationRule).where(AutomationRule.id == rule.id).values(
                                last_fired_at=iso_now(),
                                fired_count=rule.fired_count + 1,
                            )
                        )
                    log.info("automation_power_outage_fired", rule=rule.name, state=state)
                except Exception:
                    log.exception("automation_power_outage_rule_failed", rule=rule.name)
        except Exception:
            log.exception("automation_power_outage_trigger_failed")

    def _cond_matches_power_outage(self, cond: dict, state: str) -> bool:
        kind = cond.get("type", "")
        if kind == "power_outage":
            return cond.get("state", "active") == state
        if kind in ("and", "or"):
            return any(self._cond_matches_power_outage(s, state) for s in cond.get("rules", []))
        return False

    async def tick(self) -> None:
        """Called by scheduler every 5 minutes."""
        try:
            async with self._memory._engine.connect() as conn:
                rules = list(await conn.execute(select(AutomationRule).where(AutomationRule.enabled == 1)))

            for rule in rules:
                try:
                    cond = json.loads(rule.condition)
                    if not await self._eval(cond):
                        continue
                    # Cooldown
                    if rule.last_fired_at:
                        try:
                            last = datetime.fromisoformat(rule.last_fired_at)
                            if (now_kyiv() - last) < timedelta(minutes=rule.cooldown_min):
                                continue
                        except Exception:
                            pass
                    action = json.loads(rule.action)
                    await self._execute(rule.name, action)
                    async with self._memory._engine.begin() as conn:
                        await conn.execute(
                            sql_update(AutomationRule).where(AutomationRule.id == rule.id).values(
                                last_fired_at=iso_now(),
                                fired_count=rule.fired_count + 1,
                            )
                        )
                    log.info("automation_fired", rule=rule.name)
                except Exception:
                    log.exception("automation_rule_failed", rule=rule.name)
        except Exception:
            log.exception("automation_tick_failed")

    # ─── Condition evaluation ────────────────────────────────────────

    async def _eval(self, cond: dict) -> bool:
        kind = cond.get("type", "")
        if kind == "and":
            for sub in cond.get("rules", []):
                if not await self._eval(sub):
                    return False
            return True
        if kind == "or":
            for sub in cond.get("rules", []):
                if await self._eval(sub):
                    return True
            return False
        if kind == "time":
            return self._eval_time(cond)
        if kind == "datetime":
            return self._eval_datetime(cond)
        if kind == "datetime_range":
            return self._eval_datetime_range(cond)
        if kind == "sensor":
            return await self._eval_sensor(cond)
        if kind == "alert_active":
            return await self._eval_alert_active(cond.get("region", ""))
        if kind == "alert_ended":
            return await self._eval_alert_ended(cond.get("region", ""))
        if kind == "power_outage":
            return await self._eval_power_outage(cond.get("state", "active"))
        if kind == "weather":
            return await self._eval_weather(cond)
        return False

    async def _eval_weather(self, cond: dict) -> bool:
        """{type:weather, metric:'temp'|'rain'|'humidity', op:'>'|'<'|'>='|'<=', value, when:'now'|'24h'}"""
        try:
            from src.config import get_settings
            from src.integrations.weather import WeatherClient
            client = WeatherClient.from_settings(get_settings())
            if not client:
                return False
            metric = cond.get("metric", "temp")
            when = cond.get("when", "now")
            if when == "now":
                w = await client.current()
                value = {
                    "temp": w.get("temp_c", 0),
                    "feels_like": w.get("feels_like_c", 0),
                    "humidity": w.get("humidity_pct", 0),
                    "wind": w.get("wind_ms", 0),
                }.get(metric, 0)
            else:
                fc = await client.forecast(hours=int(when.replace("h", "")) if when.endswith("h") else 24)
                if metric == "rain":
                    value = sum((it.get("rain_mm") or 0) for it in fc)
                elif metric == "pop":  # probability max
                    value = max((it.get("pop_pct") or 0) for it in fc) if fc else 0
                else:
                    value = max((it.get(f"{metric}_c", 0) or 0) for it in fc) if fc else 0
            threshold = float(cond.get("value", 0))
            op = cond.get("op", ">")
            return {
                ">": value > threshold, "<": value < threshold,
                ">=": value >= threshold, "<=": value <= threshold,
                "==": value == threshold, "!=": value != threshold,
            }.get(op, False)
        except Exception:
            log.exception("weather_eval_failed")
            return False

    def _eval_time(self, cond: dict) -> bool:
        """Fires once within the 5-min tick window starting at HH:MM."""
        now = now_kyiv()
        # weekday filter
        wd = cond.get("weekday")
        if wd:
            wd_map = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
            if now.weekday() != wd_map.get(wd.lower(), -1):
                return False
        cron = cond.get("cron", "")
        if cron and ":" in cron:
            h, m = cron.split(":")
            target_h, target_m = int(h), int(m)
        else:
            target_h = int(cond.get("hour", -1))
            target_m = int(cond.get("minute", 0))
        if target_h < 0:
            return False
        # Within the current 5-min tick
        target_minutes = target_h * 60 + target_m
        now_minutes = now.hour * 60 + now.minute
        return 0 <= (now_minutes - target_minutes) < 5

    def _eval_datetime(self, cond: dict) -> bool:
        """One-shot fire within the 5-min tick after `at`."""
        try:
            at = datetime.fromisoformat(cond["at"])
        except Exception:
            return False
        now = now_kyiv()
        # Treat naive `at` as Kyiv local
        if at.tzinfo is None:
            from src.utils.time import KYIV_TZ
            at = at.replace(tzinfo=KYIV_TZ)
        delta = (now - at).total_seconds()
        return 0 <= delta < 300  # within 5 min after target

    def _eval_datetime_range(self, cond: dict) -> bool:
        try:
            start = datetime.fromisoformat(cond["from"])
            end = datetime.fromisoformat(cond["to"])
        except Exception:
            return False
        from src.utils.time import KYIV_TZ
        if start.tzinfo is None:
            start = start.replace(tzinfo=KYIV_TZ)
        if end.tzinfo is None:
            end = end.replace(tzinfo=KYIV_TZ)
        return start <= now_kyiv() <= end

    async def _eval_sensor(self, cond: dict) -> bool:
        try:
            from src.config import get_settings
            from src.integrations.tuya import TuyaClient
            client = TuyaClient.from_settings(get_settings())
            if not client:
                return False
            reading = await client.read_sensor(cond.get("device", ""))
            if "error" in reading:
                return False
            metric = cond.get("metric", "")
            value_str = (reading.get("readings", {}) or {}).get(metric, "")
            # Strip units like '%' / '°C'
            num_part = "".join(c for c in str(value_str) if c.isdigit() or c == "." or c == "-")
            if not num_part:
                return False
            value = float(num_part)
            threshold = float(cond.get("value", 0))
            op = cond.get("op", ">")
            return {
                ">":  value > threshold,
                "<":  value < threshold,
                ">=": value >= threshold,
                "<=": value <= threshold,
                "==": value == threshold,
                "!=": value != threshold,
            }.get(op, False)
        except Exception:
            log.exception("sensor_eval_failed")
            return False

    async def _eval_alert_active(self, region: str) -> bool:
        async with self._memory._engine.connect() as conn:
            stmt = select(ActiveAlert)
            if region:
                stmt = stmt.where(ActiveAlert.region == region)
            row = (await conn.execute(stmt)).first()
        return row is not None

    async def _eval_alert_ended(self, region: str) -> bool:
        """True if a *previous* tick had an active alert and now it's gone (within 10 min)."""
        # Simple proxy: there are no active alerts AND last NewsPost is_alert=1 within 10 min
        from src.db.models import NewsPost
        if await self._eval_alert_active(region):
            return False
        async with self._memory._engine.connect() as conn:
            cutoff = (now_kyiv() - timedelta(minutes=10)).isoformat()
            stmt = select(NewsPost).where(NewsPost.is_alert == 1).where(NewsPost.date >= cutoff)
            if region:
                stmt = stmt.where(NewsPost.alert_region == region)
            row = (await conn.execute(stmt.limit(1))).first()
        return row is not None

    async def _eval_power_outage(self, state: str) -> bool:
        from src.db.models import PowerOutage
        async with self._memory._engine.connect() as conn:
            row = (await conn.execute(
                select(PowerOutage).where(PowerOutage.ended_at.is_(None)).limit(1)
            )).first()
        return (row is not None) if state == "active" else (row is None)

    # ─── Action execution ────────────────────────────────────────────

    async def _execute(self, rule_name: str, action: dict) -> None:
        kind = action.get("type", "")
        if kind == "device":
            from src.config import get_settings
            from src.integrations.tuya import TuyaClient
            client = TuyaClient.from_settings(get_settings())
            if client:
                result = await client.control(action.get("device", ""), action.get("action", "off"))
                log.info("automation_device_controlled", rule=rule_name, result=result)
            return
        if kind == "message":
            agent_id = action.get("agent", "devops")
            text = action.get("text", "")
            if self._bots and self._chat_id:
                await self._bots.send_message(agent_id=agent_id, chat_id=self._chat_id, text=f"🤖 [{rule_name}]\n{text}")
            return
        if kind == "set_mode":
            from sqlalchemy import insert
            from src.db.models import FamilyMode
            async with self._memory._engine.begin() as conn:
                await conn.execute(insert(FamilyMode).prefix_with("OR REPLACE").values(
                    name=action.get("mode", ""),
                    enabled=1 if action.get("enabled") else 0,
                    payload=None, started_at=iso_now(),
                    expires_at=action.get("until"),
                ))
            return
        if kind == "tool":
            agent = self._agents.get(action.get("agent"))
            if agent:
                try:
                    result = await agent._call_tool(action.get("tool", ""), action.get("input", {}))
                    log.info("automation_tool_fired", rule=rule_name, tool=action.get("tool"))
                    if action.get("notify"):
                        await self._bots.send_message(
                            agent_id=agent.agent_id, chat_id=self._chat_id,
                            text=f"🤖 [{rule_name}]: {result}",
                        )
                except Exception:
                    log.exception("automation_tool_failed")
            return


def register_automation_job(scheduler, engine: AutomationEngine) -> None:
    scheduler.add_job(
        engine.tick, "interval", minutes=5,
        id="automation_engine", replace_existing=True,
    )
    log.info("automation_engine_registered")
