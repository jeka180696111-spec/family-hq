"""Background poller: detect grid loss via inverter and auto-log power outages."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import structlog

log = structlog.get_logger()


_GRID_LOSS_KEYWORDS = (
    # English
    "grid lost", "grid loss", "ac loss", "grid disconnect",
    "power off", "off grid", "off-grid",
    "no ac connection", "no ac", "no grid", "grid down",
    "ac fault", "grid fault", "utility loss",
    # Russian — broadened to catch separated phrases like
    # «нет подключения к сети переменного тока AC» (LuxCloud W016 text)
    "пропала", "нет сети", "нет подключения к сети", "сеть пропала",
    "нет напряжения", "отключение сети", "нет переменного тока",
    "сеть отсутствует",
    # Ukrainian
    "відсутн", "немає мережі", "немає підключення",
    "мережа відсутня", "відключення мережі",
    # LuxPower/Lux fault codes — these directly mean grid is gone
    "w016",   # No AC grid connection
    "w017",   # AC grid voltage out of range
    "f016",
    "f017",
)
_GRID_OK_KEYWORDS = (
    "grid connect", "grid restore", "grid restored", "ac connect", "ac connected",
    "ac connection restored", "ac connection ok", "grid ok", "grid available",
    "power on", "on grid", "on-grid", "recovered",
    # Russian
    "восстанов", "сеть восстановлена", "подключение к сети восстановлено",
    "напряжение восстановлено", "сеть появилась", "появилось напряжение",
    # Ukrainian
    "поновлен", "мережа відновлена", "відновлення мережі",
    "мережа з'явилась", "мережа з'явилась",
)


class GridWatcher:
    """
    Every 60 seconds query the inverter. Detect grid loss via TWO channels:

    1) PRIMARY — LuxCloud event log: their own backend marks Grid Lost /
       Grid Restored. Same source as the push-notification you get in the
       Smart Life app. Most reliable.

    2) FALLBACK — battery/inverter state heuristics if events endpoint
       isn't available on this platform.

    Setup-specific note: NO solar panels installed. Battery can only
    charge from grid → battery_charge_w > 0 is a perfect "grid ON" signal.
    """

    # 3 minutes of consistent grid-off signals before firing — was 5, but
    # waiting 5 min for the boiler to switch off after a real outage is
    # too slow when the user can see it happen on their phone in 30s.
    THRESHOLD_DOWN = 3
    # Closing the outage requires 5 consecutive 'grid back' ticks (was 2)
    # plus a minimum total outage duration (see MIN_OUTAGE_MIN below).
    # The 2-tick threshold caused false 'свет дали' at 09:36 while the
    # real outage was still going.
    THRESHOLD_UP = 5
    # Minimum length of an outage before we'll close it. Real outages
    # last much longer than 4 minutes — if our detector wants to close
    # one inside this window it's almost certainly wrong.
    MIN_OUTAGE_MIN = 4
    # Inverter goes offline ≥ this many minutes + last seen state showed
    # battery discharge → presume grid is out. Covers the case where the
    # router itself is unpowered so the inverter can't push fresh data.
    INFERRED_OUTAGE_MIN = 3

    def __init__(self, memory: Any, devops_agent: Any, bot_manager: Any, chat_id: int, automation_engine: Any = None) -> None:
        self._memory = memory
        self._devops = devops_agent
        self._bots = bot_manager
        self._chat_id = chat_id
        self._automation = automation_engine
        self._down_streak = 0
        self._up_streak = 0
        self._outage_active = False  # Mirror of DB state at last tick
        self._last_event_time: str | None = None  # For event-log dedup
        self._battery_alerts_fired: set[int] = set()  # thresholds already pushed this outage
        self._last_seen_discharging: bool = False  # last tick saw battery feeding the house

    async def tick(self) -> None:
        try:
            from src.config import get_settings
            from src.integrations.luxcloud import LuxCloudClient
            client = LuxCloudClient.from_settings(get_settings())
            if not client:
                return
            data = await client.runtime()
        except Exception:
            # Inverter unreachable — don't draw conclusions
            log.debug("grid_watcher_tick_skip", reason="lux_unreachable")
            return

        # ── Channel 0: inferred outage — inverter went offline while it
        #    was last seen discharging the battery → grid most likely down
        #    AND the router is unpowered too (so we get no events).
        try:
            await self._maybe_infer_outage(data)
        except Exception:
            log.exception("grid_watcher_infer_failed")

        # ── Channel 1: event log from LuxCloud ──────────────────────────
        # If LuxCloud exposes recent events, trust them directly: no
        # thresholds, no hysteresis, just react to what their backend
        # already classified.
        try:
            events = await client.recent_events(hours=2)
        except Exception:
            events = []

        if events:
            grid_state_from_event = self._latest_state_from_events(events)
            if grid_state_from_event is not None:
                await self._sync_state_with_db()
                if grid_state_from_event is False and not self._outage_active:
                    # Opening on event-log is fine — quick reaction.
                    await self._open()
                    return
                if grid_state_from_event is True and self._outage_active:
                    # Closing is MUCH stricter: previously we closed on a
                    # single 'ok' event and got flapping (open 09:34 →
                    # false close 09:36 while the real outage was hours).
                    # Now we require BOTH conditions:
                    #   1. The outage has lasted at least 5 minutes
                    #   2. Heuristic channel also says grid is back
                    # The heuristic check happens in the rest of tick(),
                    # so we don't return early here — let it run, then
                    # close only when up_streak threshold is hit.
                    pass
                else:
                    # Event was inconclusive for current state — skip heuristic
                    return

        raw = data.get("raw", {}) or {}

        # ── Multi-signal grid detection ────────────────────────────────
        #
        # Главное правило: если есть напряжение сети > 100V — сеть ЕСТЬ,
        # вне зависимости от того, есть ли потребление.
        # Если напряжения нет/невозможно прочитать — смотрим на разряд
        # батареи как индикатор перехода на резерв.
        #
        # НИКОГДА не делаем вывод «света нет» по «import_w==0 and export_w==0» —
        # это норма для standby режима ночью когда дом ничего не потребляет.

        def first_present(d: dict, keys: list[str]) -> float | None:
            for k in keys:
                v = d.get(k)
                if v is None:
                    continue
                try:
                    fv = float(v)
                    if fv > 0:  # voltage 0 isn't valid either — skip
                        return fv
                except (TypeError, ValueError):
                    continue
            return None

        grid_voltage = first_present(raw, [
            "vac", "vacr", "vac1", "vGrid", "gridVoltage",
            "voltageGrid", "gridVolt", "vacR", "v_grid",
        ])
        battery_discharge_w = float(data.get("battery_discharge_w") or 0)
        battery_charge_w = float(data.get("battery_charge_w") or 0)
        home_w = float(data.get("home_consumption_w") or 0)
        import_w = float(data.get("grid_import_w") or 0)
        export_w = float(data.get("grid_export_w") or 0)

        # Setup-specific: NO solar panels, battery charges ONLY from grid.
        # Therefore battery_charge_w > 30W means grid is definitely ON.

        battery_pct = data.get("battery_pct")
        try:
            battery_pct = float(battery_pct) if battery_pct is not None else None
        except (TypeError, ValueError):
            battery_pct = None

        # Track battery SOC trajectory across ticks to catch sustained discharge
        # (covers long outages where instantaneous discharge_w may not always
        # show — e.g. inverter idle moments during a real outage)
        if not hasattr(self, "_soc_history"):
            self._soc_history = []
        if battery_pct is not None:
            from src.utils.time import now_kyiv
            self._soc_history.append((now_kyiv(), battery_pct))
            # Keep last 20 minutes
            from datetime import timedelta
            cutoff_dt = now_kyiv() - timedelta(minutes=20)
            self._soc_history = [(t, p) for t, p in self._soc_history if t >= cutoff_dt]

        soc_drop_signal = False
        if len(self._soc_history) >= 3:
            oldest_t, oldest_pct = self._soc_history[0]
            newest_t, newest_pct = self._soc_history[-1]
            delta_pct = oldest_pct - newest_pct
            from datetime import timedelta
            elapsed_min = max(1, (newest_t - oldest_t).total_seconds() / 60)
            # Self-discharge: ~3% per 5h → 0.6% per hour → 0.2% per 20min
            # If we lose >1% in <15min → real load on battery, no grid
            if delta_pct > 1.0 and elapsed_min < 15 and battery_charge_w < 5:
                soc_drop_signal = True

        if battery_charge_w > 30:
            # Battery is charging → grid must be present
            grid_off = False
        elif import_w > 30:
            # Energy flowing from grid → grid is on
            grid_off = False
        elif grid_voltage is not None and grid_voltage > 100:
            # Explicit voltage confirms grid is on
            grid_off = False
        elif battery_discharge_w > 30 and import_w == 0:
            # Battery actively powering the house AND no import → grid is off
            grid_off = True
        elif grid_voltage is not None and grid_voltage < 50:
            # Explicit voltage gone
            grid_off = True
        elif soc_drop_signal:
            # SOC trajectory shows battery actively discharging faster than
            # self-discharge — must be powering the house with no grid
            grid_off = True
        else:
            # Ambiguous (idle: nothing charging, nothing discharging, no flow).
            # Self-discharge ~3%/5h means battery may sit idle when full.
            # Default to "grid on" — never false-fire on standby.
            grid_off = False

        log.debug(
            "grid_watcher_signals",
            vgrid=grid_voltage, batt_dis=battery_discharge_w,
            batt_chg=battery_charge_w, home=home_w,
            imp=import_w, exp=export_w, grid_off=grid_off,
        )

        if grid_off:
            self._down_streak += 1
            self._up_streak = 0
        else:
            self._up_streak += 1
            self._down_streak = 0

        await self._sync_state_with_db()

        if not self._outage_active and self._down_streak >= self.THRESHOLD_DOWN:
            await self._open()
        elif self._outage_active and self._up_streak >= self.THRESHOLD_UP:
            await self._close()

        # Low-battery alerts while running on battery
        if self._outage_active and battery_pct is not None:
            await self._maybe_battery_alert(battery_pct)

    def _latest_state_from_events(self, events: list[dict]) -> bool | None:
        """Return True if grid is ON, False if OFF, None if no recent grid event."""
        # Walk events newest-first, take first grid-related one.
        # IMPORTANT: check loss keywords FIRST (since 'no ac connection' contains
        # the OK substring 'ac connection'). Also explicitly look at Status field
        # if LuxCloud provides one ('Recovered' / 'Active').
        for ev in events:
            text_blob = " ".join(str(v).lower() for v in (
                ev.get("name") or "", ev.get("type") or "",
                ev.get("code") or "", ev.get("status") or "",
            ))
            raw_status = str((ev.get("raw") or {}).get("status", "")).lower()
            full_blob = f"{text_blob} {raw_status}"

            # LOSS first
            if any(kw in full_blob for kw in _GRID_LOSS_KEYWORDS):
                # But if status says 'recovered', this is actually a closed past event,
                # not a new outage → treat as ON
                if "recovered" in full_blob or "восстанов" in full_blob:
                    ev_time = ev.get("time")
                    if ev_time and ev_time == self._last_event_time:
                        return None
                    self._last_event_time = ev_time
                    return True
                ev_time = ev.get("time")
                if ev_time and ev_time == self._last_event_time:
                    return None
                self._last_event_time = ev_time
                return False
            if any(kw in full_blob for kw in _GRID_OK_KEYWORDS):
                ev_time = ev.get("time")
                if ev_time and ev_time == self._last_event_time:
                    return None
                self._last_event_time = ev_time
                return True
        return None

    async def _sync_state_with_db(self) -> None:
        from sqlalchemy import select
        from src.db.models import PowerOutage
        async with self._memory._engine.connect() as conn:
            row = (await conn.execute(
                select(PowerOutage).where(PowerOutage.ended_at.is_(None)).limit(1)
            )).first()
        self._outage_active = row is not None

    _BATTERY_LEVELS = (
        (30, "⚠️ <b>Батарея 30%</b>\nСвета всё ещё нет. Заряди телефоны, прикинь план."),
        (15, "🟠 <b>Батарея 15%</b>\nПора собрать минимум: фонарь, термос, паверы."),
        (5,  "🔴 <b>Батарея 5%</b>\nИнвертор скоро вырубится. Доставай аварийку."),
    )

    async def _maybe_battery_alert(self, pct: float) -> None:
        for threshold, text in self._BATTERY_LEVELS:
            if pct <= threshold and threshold not in self._battery_alerts_fired:
                self._battery_alerts_fired.add(threshold)
                if self._bots and self._chat_id:
                    try:
                        await self._bots.send_message(
                            agent_id="devops", chat_id=self._chat_id, text=text,
                        )
                    except Exception:
                        log.exception("grid_watcher_battery_alert_failed", threshold=threshold)
                log.info("grid_watcher_battery_alert", threshold=threshold, pct=pct)

    async def _maybe_infer_outage(self, data: dict) -> None:
        """If the inverter went offline AND last contact showed it was
        discharging the battery — assume the grid is out (router lost
        power too, which is why we can't reach the inverter).

        Cleared automatically when LuxCloud starts returning fresh data
        again with `online: True` (handled in event-log channel).
        """
        from datetime import datetime as _dt
        from src.utils.time import KYIV_TZ, now_kyiv

        online = bool(data.get("online", True))
        battery_discharge_w = data.get("battery_discharge_w") or 0
        if online and battery_discharge_w > 0:
            self._last_seen_discharging = True
        elif online:
            self._last_seen_discharging = False

        if self._outage_active or online:
            return

        # Inverter is offline — how stale is the data?
        ts_raw = data.get("last_update") or data.get("ts") or data.get("timestamp")
        if not ts_raw:
            return
        try:
            last = _dt.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
            if last.tzinfo is None:
                last = last.replace(tzinfo=KYIV_TZ)
        except Exception:
            return
        age_min = (now_kyiv() - last).total_seconds() / 60
        if age_min < self.INFERRED_OUTAGE_MIN:
            return
        if not self._last_seen_discharging:
            # Inverter offline but last we knew it was on grid → could be
            # a network blip, not an outage. Stay silent.
            return
        log.warning(
            "grid_watcher_inferred_outage",
            stale_min=int(age_min),
        )
        await self._open(inferred=True, stale_min=int(age_min))

    async def _open(self, *, inferred: bool = False, stale_min: int = 0) -> None:
        from sqlalchemy import insert
        from src.db.models import PowerOutage
        from src.utils.time import iso_now
        notes = (
            f"Авто-детект (предполож.): инвертор offline {stale_min} мин, "
            "до этого видели разряд батареи"
            if inferred
            else "Авто-детект: инвертор перешёл на батарею"
        )
        async with self._memory._engine.begin() as conn:
            await conn.execute(insert(PowerOutage).values(
                started_at=iso_now(),
                notes=notes,
            ))
        self._outage_active = True
        self._battery_alerts_fired.clear()
        if self._bots and self._chat_id:
            msg = (
                f"⚡ <b>Похоже, света нет</b>\nИнвертор сам молчит ~{stale_min} мин, "
                "до этого видели разряд батареи — предполагаю отключение. "
                "Если ошибся, скажи «свет есть»."
                if inferred
                else "⚡ <b>Света нет</b>\nИнвертор перешёл на батарею. Автоматизации сработают."
            )
            try:
                await self._bots.send_message(
                    agent_id="devops", chat_id=self._chat_id, text=msg,
                )
            except Exception:
                log.exception("grid_watcher_open_push_failed")
        if self._automation:
            try:
                await self._automation.trigger_power_outage(active=True)
            except Exception:
                log.exception("grid_watcher_open_automation_failed")
        log.info("grid_watcher_outage_opened")

    async def _close(self) -> None:
        from sqlalchemy import select, update as sql_update
        from src.db.models import PowerOutage
        from src.utils.time import iso_now, now_kyiv
        # Refuse to close an outage that's lasted less than MIN_OUTAGE_MIN.
        # Real outages don't end in 90 seconds, and the inverter's status
        # signals can flicker briefly.
        async with self._memory._engine.connect() as conn:
            open_row = (await conn.execute(
                select(PowerOutage).where(PowerOutage.ended_at.is_(None))
                .order_by(PowerOutage.id.desc()).limit(1)
            )).first()
        if open_row:
            try:
                started_dt = datetime.fromisoformat(open_row.started_at)
                age_min = (now_kyiv() - started_dt).total_seconds() / 60
            except Exception:
                age_min = self.MIN_OUTAGE_MIN  # if we can't parse, allow close
            if age_min < self.MIN_OUTAGE_MIN:
                log.info(
                    "grid_watcher_close_too_soon",
                    age_min=int(age_min), needed=self.MIN_OUTAGE_MIN,
                )
                return
        async with self._memory._engine.begin() as conn:
            last = (await conn.execute(
                select(PowerOutage).where(PowerOutage.ended_at.is_(None))
                .order_by(PowerOutage.id.desc()).limit(1)
            )).first()
            if last:
                try:
                    started = datetime.fromisoformat(last.started_at)
                    duration_min = int((now_kyiv() - started).total_seconds() / 60)
                except Exception:
                    duration_min = 0
                await conn.execute(
                    sql_update(PowerOutage).where(PowerOutage.id == last.id).values(
                        ended_at=iso_now(), duration_min=duration_min,
                    )
                )
        self._outage_active = False
        self._battery_alerts_fired.clear()
        if self._bots and self._chat_id:
            try:
                await self._bots.send_message(
                    agent_id="devops", chat_id=self._chat_id,
                    text=f"✅ <b>Свет дали</b>\nСеть восстановлена. Автоматизации продолжения сработают.",
                )
            except Exception:
                log.exception("grid_watcher_close_push_failed")
        if self._automation:
            try:
                await self._automation.trigger_power_outage(active=False)
            except Exception:
                log.exception("grid_watcher_close_automation_failed")
        log.info("grid_watcher_outage_closed")


def register_grid_watcher_job(scheduler, watcher: GridWatcher) -> None:
    scheduler.add_job(
        watcher.tick, "interval", seconds=60,
        id="grid_watcher", replace_existing=True,
    )
    log.info("grid_watcher_registered")
