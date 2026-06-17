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

    # All voltage / battery / current heuristics removed — we now react
    # only to LuxCloud event-log notifications (same source as the
    # owner's SMS). No thresholds needed.

    def __init__(self, memory: Any, devops_agent: Any, bot_manager: Any, chat_id: int, automation_engine: Any = None) -> None:
        self._memory = memory
        self._devops = devops_agent
        self._bots = bot_manager
        self._chat_id = chat_id
        self._automation = automation_engine
        self._outage_active = False  # Mirror of DB state at last tick
        self._last_event_time: str | None = None  # For event-log dedup
        self._battery_alerts_fired: set[int] = set()  # thresholds already pushed this outage

    async def tick(self) -> None:
        """Event-driven detection: trust ONLY the inverter's own
        notifications (LuxCloud event log). No voltage heuristics, no
        battery-discharge guessing — just like the SMS the inverter
        sends the owner, we react to «grid lost» / «grid restored»
        events and nothing else.

        Battery-percentage alerts during an active outage remain — those
        are read straight from data and don't classify grid state."""
        try:
            from src.config import get_settings
            from src.integrations.luxcloud import LuxCloudClient
            client = LuxCloudClient.from_settings(get_settings())
            if not client:
                return
            data = await client.runtime()
        except Exception:
            log.debug("grid_watcher_tick_skip", reason="lux_unreachable")
            return

        try:
            events = await client.recent_events(hours=2)
        except Exception:
            events = []

        await self._sync_state_with_db()

        if events:
            grid_state_from_event = self._latest_state_from_events(events)
            if grid_state_from_event is False and not self._outage_active:
                # Inverter said: grid lost. Open the outage immediately.
                await self._open()
            elif grid_state_from_event is True and self._outage_active:
                # Inverter said: grid back. Close immediately.
                await self._close()
            # Inconclusive event OR no state change needed → no-op.

        # Low-battery alerts during an active outage. Battery % comes
        # straight from data; we don't use it to classify grid state.
        if self._outage_active:
            battery_pct = data.get("battery_pct")
            try:
                battery_pct = float(battery_pct) if battery_pct is not None else None
            except (TypeError, ValueError):
                battery_pct = None
            if battery_pct is not None:
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

    async def _open(self) -> None:
        from sqlalchemy import insert
        from src.db.models import PowerOutage
        from src.utils.time import iso_now
        async with self._memory._engine.begin() as conn:
            await conn.execute(insert(PowerOutage).values(
                started_at=iso_now(),
                notes="Авто-детект: уведомление инвертора «нет сети»",
            ))
        self._outage_active = True
        self._battery_alerts_fired.clear()
        if self._bots and self._chat_id:
            try:
                await self._bots.send_message(
                    agent_id="devops", chat_id=self._chat_id,
                    text="⚡ <b>Света нет</b>\nИнвертор сообщил об отключении сети. Автоматизации сработают.",
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
