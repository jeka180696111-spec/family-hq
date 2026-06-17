"""Automation engine: evaluate user-defined IF-THEN rules every 5 min."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

import structlog
import asyncio as _asyncio_mod
import aiohttp as _aiohttp_mod
from sqlalchemy import delete as sql_delete, select, update as sql_update

# Aliases used by narrow except clauses below
aiohttp_ClientError = _aiohttp_mod.ClientError
asyncio_TimeoutError = _asyncio_mod.TimeoutError

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
# {"type": "power_outage", "state": "active"}             — light is off (fires once per outage)
# {"type": "power_outage", "state": "active", "within_min": 5}  — only first N min of outage
# {"type": "power_outage", "state": "ended"}              — light just came back (fires once)
# {"type": "power_outage", "state": "ended", "delay_min": 15}   — N min after restore
# {"type": "baby_sleeping", "min_minutes": 10}                — Матвей спит ≥10 мин (окно тишины)
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
        # Cache Tuya client across rule fires — auth + list_devices used
        # to be repeated on every device action because we built a new
        # client each time.
        self._tuya_client = None
        # Per-outage dedup: rule names we've already told the user are
        # 'deferred'. Cleared when outage closes via trigger_power_outage.
        self._outage_deferred_notified: set[str] = set()
        # Rule IDs that have already fired for the CURRENT outage event.
        # Standing rules with `power_outage` condition would otherwise
        # re-fire after every cooldown_min (60 by default) — toggling
        # an already-off boiler is pointless and spammy. Cleared on
        # outage close.
        self._outage_fired_rules: set[int] = set()

    def _get_tuya(self):
        from src.config import get_settings
        from src.integrations.tuya import TuyaClient
        if self._tuya_client is None:
            self._tuya_client = TuyaClient.from_settings(get_settings())
        return self._tuya_client

    async def trigger_power_outage(self, active: bool) -> None:
        """Fire all rules whose top-level condition matches the new outage state.

        Called by GridWatcher the moment grid loss/restore is detected, so
        boiler / heavy loads cut over immediately instead of waiting for the
        5-min tick.
        """
        state = "active" if active else "ended"
        # When grid comes back, allow deferred notifications to re-fire if
        # somehow we end up in another outage (e.g. quick on-off-on).
        if not active:
            self._outage_deferred_notified.clear()
            self._outage_fired_rules.clear()
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
                    # Single fire per outage event — don't repeat after
                    # cooldown lapses while still in the same outage.
                    if rule.id in self._outage_fired_rules:
                        continue
                    self._outage_fired_rules.add(rule.id)
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
        """Called by scheduler every minute."""
        # Periodic cleanup: drop one-shot datetime rules whose `at` time
        # passed more than an hour ago — they're either already executed
        # (lost the auto-delete in an older deploy) or stuck because the
        # device action keeps failing. Either way they pollute the table.
        try:
            await self._cleanup_expired_one_shots()
        except Exception:
            log.exception("automation_cleanup_failed")
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
                    # Outage takes priority over everything else — when
                    # the grid is down, ON-commands to power-hungry
                    # devices would just drain the battery. Skip the
                    # rule until grid is back; one-shot rules are
                    # NOT consumed (they'll re-fire on the next tick
                    # after grid recovery as long as their `at` time
                    # is still in the past and late_fire=true).
                    if await self._outage_blocks(action):
                        if rule.name not in self._outage_deferred_notified:
                            await self._notify_chat(
                                f"⏸ [{rule.name}] отложено — сейчас отключение света. "
                                "Сработает когда сеть вернётся."
                            )
                            self._outage_deferred_notified.add(rule.name)
                        log.info("automation_skipped_outage", rule=rule.name)
                        continue
                    # Standing power_outage rules: fire once per outage
                    # event, not every cooldown. Toggling an already-off
                    # boiler is pointless and spams the chat.
                    if cond.get("type") == "power_outage":
                        if rule.id in self._outage_fired_rules:
                            continue
                        self._outage_fired_rules.add(rule.id)
                    await self._execute(rule.name, action)
                    # One-shot rules (single datetime trigger) are removed
                    # after firing — keeps the rules table lean and avoids
                    # re-checking dead rules on every minute tick.
                    is_one_shot = (cond.get("type") == "datetime")
                    if is_one_shot:
                        async with self._memory._engine.begin() as conn:
                            await conn.execute(
                                sql_delete(AutomationRule).where(AutomationRule.id == rule.id)
                            )
                        # Mirror delete into the notebook tab
                        await self._notebook_delete_rule(rule.name)
                        log.info("automation_one_shot_consumed", rule=rule.name)
                    else:
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
            return await self._eval_power_outage(cond)
        if kind == "baby_sleeping":
            return await self._eval_baby_sleeping(cond)
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
        except (aiohttp_ClientError, asyncio_TimeoutError, ValueError, KeyError) as e:
            # Transient: network blip, bad field, malformed JSON. Treat
            # as «condition not met» so we re-evaluate next tick.
            log.warning("weather_eval_transient", error=str(e)[:120])
            return False
        # Other exceptions (TypeError, AttributeError = real bug in our
        # code) propagate to the engine's tick loop where they get
        # logged with full traceback and the rule shows up in chat as
        # a failure rather than silently never matching.

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
        # 1-minute tick window — fires within the exact target minute
        target_minutes = target_h * 60 + target_m
        now_minutes = now.hour * 60 + now.minute
        return 0 <= (now_minutes - target_minutes) < 1

    def _eval_datetime(self, cond: dict) -> bool:
        """Fire on or after `at` time.

        Default behaviour: fire within 120 min of `at`, then expire.
        With `late_fire: true` (recommended for one-shot reminders) —
        fire on the FIRST tick after `at`, no upper bound. So if the
        service was offline for hours or days, the task still happens
        eventually (you didn't want the boiler off forever, just turned
        on at 15:00 — fine if it lands at 17:00 after Railway recovers).
        """
        try:
            at = datetime.fromisoformat(cond["at"])
        except Exception:
            return False
        now = now_kyiv()
        if at.tzinfo is None:
            from src.utils.time import KYIV_TZ
            at = at.replace(tzinfo=KYIV_TZ)
        delta_min = (now - at).total_seconds() / 60
        if delta_min < 0:
            return False
        if cond.get("late_fire") is True:
            return True  # cooldown + last_fired ensure once-per-target
        catch_up = float(cond.get("catch_up_min", 120))
        return delta_min < catch_up

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
            client = self._get_tuya()
            if not client:
                return False
            device = cond.get("device", "")
            # Fallback: LLM frequently omits device → use the first sensor
            # that looks temperature-ish.
            if not device:
                devices = await client.list_devices()
                cand = next((d for d in devices if
                             "sensor" in (d.get("category", "") or "").lower()
                             or "темп" in (d.get("name", "") or "").lower()
                             or "датчик" in (d.get("name", "") or "").lower()
                             or "temp" in (d.get("name", "") or "").lower()),
                            None)
                if not cand:
                    return False
                device = cand["name"]
            reading = await client.read_sensor(device)
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
        # Simple proxy: there are no active alerts AND last NewsPost is_alert=1 within 10 min.
        # Previously did `NewsPost.date >= cutoff` as a SQL string compare —
        # that only works if both strings share an identical ISO format
        # with normalised timezone offset, which we can't rely on across
        # restarts. Pull the recent alert posts ordered by id (monotonic)
        # and filter the datetime in Python.
        from src.db.models import NewsPost
        if await self._eval_alert_active(region):
            return False
        cutoff_dt = now_kyiv() - timedelta(minutes=10)
        async with self._memory._engine.connect() as conn:
            stmt = (
                select(NewsPost)
                .where(NewsPost.is_alert == 1)
                .order_by(NewsPost.id.desc()).limit(20)
            )
            if region:
                stmt = stmt.where(NewsPost.alert_region == region)
            rows = list(await conn.execute(stmt))
        from src.utils.time import KYIV_TZ
        for r in rows:
            try:
                dt = datetime.fromisoformat(r.date)
            except (ValueError, TypeError):
                continue
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=KYIV_TZ)
            if dt >= cutoff_dt:
                return True
        return False

    async def _eval_baby_sleeping(self, cond: dict) -> bool:
        """True when BabyState.sleeping_since is set and recent (<6h).
        Optional `min_minutes` waits N minutes after sleep start before firing
        (so the rule fires once baby is reliably asleep, not at every micro-nap)."""
        from src.db.models import BabyState
        async with self._memory._engine.connect() as conn:
            row = (await conn.execute(select(BabyState).where(BabyState.id == 1))).first()
        if not row or not row.sleeping_since:
            return False
        try:
            since = datetime.fromisoformat(row.sleeping_since)
        except Exception:
            return False
        from src.utils.time import KYIV_TZ
        if since.tzinfo is None:
            since = since.replace(tzinfo=KYIV_TZ)
        elapsed_min = (now_kyiv() - since).total_seconds() / 60
        if elapsed_min < 0 or elapsed_min > 360:  # stale
            return False
        min_min = float(cond.get("min_minutes", 5))
        return elapsed_min >= min_min

    async def _eval_power_outage(self, cond: dict) -> bool:
        from src.db.models import PowerOutage
        state = cond.get("state", "active")
        async with self._memory._engine.connect() as conn:
            active_row = (await conn.execute(
                select(PowerOutage).where(PowerOutage.ended_at.is_(None)).limit(1)
            )).first()
            last_closed = (await conn.execute(
                select(PowerOutage).where(PowerOutage.ended_at.is_not(None))
                .order_by(PowerOutage.id.desc()).limit(1)
            )).first()
        if state == "active":
            if active_row is None:
                return False
            # Optional window: fire only in first N min of outage
            within = cond.get("within_min")
            if within is not None and active_row.started_at:
                try:
                    started = datetime.fromisoformat(active_row.started_at)
                    elapsed = (now_kyiv() - started).total_seconds() / 60
                    return 0 <= elapsed <= float(within)
                except Exception:
                    return True
            return True
        # state == "ended" — match only in a 5-min window after close
        # (optionally delayed by `delay_min` so rules can say
        # "включить бойлер через 15 минут после возвращения света").
        if active_row is not None or last_closed is None or not last_closed.ended_at:
            return False
        try:
            ended = datetime.fromisoformat(last_closed.ended_at)
        except Exception:
            return False
        delay = float(cond.get("delay_min", 0))
        elapsed_min = (now_kyiv() - ended).total_seconds() / 60 - delay
        return 0 <= elapsed_min < 5

    # ─── Action execution ────────────────────────────────────────────

    async def _cleanup_expired_one_shots(self) -> None:
        """Sweep the AutomationRule table: any datetime rule with `at`
        older than 1 hour gets deleted. Reasons:
          - It already fired and we kept it for backwards-compat → flush.
          - It's stuck because the action errors (Tuya offline, device
            renamed, …) and now keeps trying every tick → flush.
        User can always re-create the rule cleanly via Прораб."""
        now = now_kyiv()
        cutoff = now - timedelta(hours=1)
        async with self._memory._engine.connect() as conn:
            rules = list(await conn.execute(select(AutomationRule)))
        to_delete: list[tuple[int, str]] = []
        for r in rules:
            try:
                cond = json.loads(r.condition or "{}")
            except Exception:
                continue
            if cond.get("type") != "datetime":
                continue
            at_raw = cond.get("at") or ""
            try:
                at = datetime.fromisoformat(at_raw)
            except Exception:
                continue
            from src.utils.time import KYIV_TZ
            if at.tzinfo is None:
                at = at.replace(tzinfo=KYIV_TZ)
            if at < cutoff:
                to_delete.append((r.id, r.name))
        if not to_delete:
            return
        async with self._memory._engine.begin() as conn:
            for rid, _name in to_delete:
                await conn.execute(sql_delete(AutomationRule).where(AutomationRule.id == rid))
        for _rid, name in to_delete:
            await self._notebook_delete_rule(name)
        log.info("automation_expired_swept", count=len(to_delete),
                 names=[n for _, n in to_delete])

    async def _notebook_delete_rule(self, rule_name: str) -> None:
        """Remove a consumed one-shot rule from the ⚙️ Автоматизации tab."""
        try:
            nanny = self._agents.get("nanny")
            sheets = getattr(nanny, "_sheets", None) if nanny else None
            if not sheets:
                return
            from src.integrations.prorab_notebook import delete_rule
            await delete_rule(sheets, rule_name)
        except Exception:
            log.exception("automation_notebook_delete_failed", rule=rule_name)

    async def _outage_active(self) -> bool:
        """True if there's an open PowerOutage row (set by GridWatcher)."""
        try:
            from src.db.models import PowerOutage
            async with self._memory._engine.connect() as conn:
                row = (await conn.execute(
                    select(PowerOutage).where(PowerOutage.ended_at.is_(None))
                    .order_by(PowerOutage.id.desc()).limit(1)
                )).first()
            return row is not None
        except Exception:
            log.exception("automation_outage_check_failed")
            return False

    async def _outage_blocks(self, action: dict) -> bool:
        """Return True if an active power outage should block this action.
        Rules:
          • device action that turns something ON → blocked
          • ac_command (always implies powering AC) → blocked
          • OFF commands, alert-ended responses, set_mode, messages → OK
            (turning OFF is always safe; messages cost nothing)
          • Rules whose CONDITION is power_outage are exempt — they
            include the boiler-off-on-outage rule we explicitly want to fire.
        """
        kind = (action or {}).get("type", "")
        if kind == "device":
            act = (action.get("action") or "").lower()
            if act in ("on", "toggle"):
                return await self._outage_active()
            return False
        if kind == "ac_command":
            return await self._outage_active()
        return False

    async def _notify_chat(self, text: str) -> None:
        if not (self._bots and self._chat_id):
            return
        try:
            await self._bots.send_message(
                agent_id="devops", chat_id=self._chat_id, text=text,
            )
        except Exception:
            log.exception("automation_notify_failed")

    async def _execute(self, rule_name: str, action: dict) -> None:
        kind = action.get("type", "")
        if kind == "device":
            client = self._get_tuya()
            device = action.get("device", "")
            act = action.get("action", "off")
            if not client:
                msg = f"⚠️ [{rule_name}] не сработало: Tuya не настроен."
                log.warning("automation_no_tuya", rule=rule_name)
                await self._notify_chat(msg)
                return
            try:
                result = await client.control(device, act)
            except Exception as e:
                msg = (
                    f"⚠️ [{rule_name}] не получилось сделать {act} {device}: "
                    f"{type(e).__name__}: {str(e)[:140]}"
                )
                log.exception("automation_device_failed", rule=rule_name)
                await self._notify_chat(msg)
                return
            ok = isinstance(result, dict) and (result.get("success") or result.get("ok") or "error" not in result)
            log.info("automation_device_controlled", rule=rule_name, result=result)
            if not ok:
                err = (result or {}).get("error") if isinstance(result, dict) else str(result)
                msg = f"⚠️ [{rule_name}] {act} {device} → ответ Tuya: {str(err)[:160]}"
                await self._notify_chat(msg)
            else:
                # Success — short confirmation so user knows the rule fired.
                await self._notify_chat(f"⚙️ [{rule_name}] {device} → {act} ✅")
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
        if kind == "ac_command":
            # Compound AC action: set mode/temp/fan_speed in one shot via Tuya
            client = self._get_tuya()
            device = action.get("device", "")
            if not client:
                await self._notify_chat(f"⚠️ [{rule_name}] Tuya не настроен.")
                return
            mode = action.get("mode")
            temp = action.get("temperature")
            speed = action.get("fan_speed") or action.get("speed")
            try:
                if mode and temp is not None:
                    r = await client.set_mode(device, mode, temperature=int(temp))
                elif mode:
                    r = await client.set_mode(device, mode)
                elif temp is not None:
                    r = await client.set_temperature(device, int(temp))
                elif speed:
                    r = await client.set_fan_speed(device, speed)
                else:
                    r = await client.control(device, "on")
            except Exception as e:
                await self._notify_chat(
                    f"⚠️ [{rule_name}] ошибка кондера: {type(e).__name__}: {str(e)[:120]}"
                )
                return
            ok = isinstance(r, dict) and (r.get("success") or "error" not in r)
            if ok:
                summary = f"{device}"
                if mode: summary += f" {mode}"
                if temp is not None: summary += f" {temp}°"
                if speed: summary += f" вент.{speed}"
                await self._notify_chat(f"⚙️ [{rule_name}] {summary} ✅")
            else:
                err = (r or {}).get("error") if isinstance(r, dict) else str(r)
                await self._notify_chat(
                    f"⚠️ [{rule_name}] ответ Tuya: {str(err)[:160]}"
                )
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
    # 1-minute tick — `включи в 15:58` фактически должно срабатывать
    # в 15:58, а не на следующем 5-минутном тике (в 16:00).
    scheduler.add_job(
        engine.tick, "interval", minutes=1,
        id="automation_engine", replace_existing=True,
    )
    log.info("automation_engine_registered")
