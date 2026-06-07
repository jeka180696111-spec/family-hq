"""Background poller: detect grid loss via inverter and auto-log power outages."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import structlog

log = structlog.get_logger()


_GRID_LOSS_KEYWORDS = (
    "grid lost", "grid loss", "ac loss", "grid disconnect",
    "power off", "off grid", "off-grid",
    "no ac connection", "no ac", "no grid", "grid down",
    "ac fault", "grid fault", "utility loss",
    "пропала", "відсутн", "немає мережі", "нет сети",
)
_GRID_OK_KEYWORDS = (
    "grid connect", "grid restore", "grid restored", "ac connect", "ac connected",
    "ac connection restored", "ac connection ok", "grid ok", "grid available",
    "power on", "on grid", "on-grid", "recovered",
    "поновлен", "восстанов", "мережа відновлена", "сеть восстановлена",
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

    THRESHOLD_DOWN = 5
    THRESHOLD_UP = 2

    def __init__(self, memory: Any, devops_agent: Any, bot_manager: Any, chat_id: int) -> None:
        self._memory = memory
        self._devops = devops_agent
        self._bots = bot_manager
        self._chat_id = chat_id
        self._down_streak = 0
        self._up_streak = 0
        self._outage_active = False  # Mirror of DB state at last tick
        self._last_event_time: str | None = None  # For event-log dedup

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
                if grid_state_from_event is True and self._outage_active:
                    # Event says grid is back
                    await self._close()
                elif grid_state_from_event is False and not self._outage_active:
                    await self._open()
                # Skip heuristics — events were authoritative this tick
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

    async def _open(self) -> None:
        from sqlalchemy import insert
        from src.db.models import PowerOutage
        from src.utils.time import iso_now
        async with self._memory._engine.begin() as conn:
            await conn.execute(insert(PowerOutage).values(
                started_at=iso_now(),
                notes="Авто-детект: инвертор перешёл на батарею",
            ))
        self._outage_active = True
        if self._bots and self._chat_id:
            try:
                await self._bots.send_message(
                    agent_id="devops", chat_id=self._chat_id,
                    text="⚡ <b>Света нет</b>\nИнвертор перешёл на батарею. Автоматизации сработают.",
                )
            except Exception:
                log.exception("grid_watcher_open_push_failed")
        log.info("grid_watcher_outage_opened")

    async def _close(self) -> None:
        from sqlalchemy import select, update as sql_update
        from src.db.models import PowerOutage
        from src.utils.time import iso_now, now_kyiv
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
        if self._bots and self._chat_id:
            try:
                await self._bots.send_message(
                    agent_id="devops", chat_id=self._chat_id,
                    text=f"✅ <b>Свет дали</b>\nСеть восстановлена. Автоматизации продолжения сработают.",
                )
            except Exception:
                log.exception("grid_watcher_close_push_failed")
        log.info("grid_watcher_outage_closed")


def register_grid_watcher_job(scheduler, watcher: GridWatcher) -> None:
    scheduler.add_job(
        watcher.tick, "interval", seconds=60,
        id="grid_watcher", replace_existing=True,
    )
    log.info("grid_watcher_registered")
