"""Background poller: detect grid loss via inverter and auto-log power outages."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import structlog

log = structlog.get_logger()


class GridWatcher:
    """
    Every 60 seconds query the inverter; if grid voltage is 0 (or both
    import_w and export_w are 0) for THRESHOLD consecutive checks,
    auto-call log_power_outage('start'). On recovery → log_power_outage('end').

    Hysteresis: 3 down checks (3 min) to confirm outage; 2 up checks
    (2 min) to confirm restore — avoids flapping on brief glitches.
    """

    THRESHOLD_DOWN = 3
    THRESHOLD_UP = 2

    def __init__(self, memory: Any, devops_agent: Any, bot_manager: Any, chat_id: int) -> None:
        self._memory = memory
        self._devops = devops_agent
        self._bots = bot_manager
        self._chat_id = chat_id
        self._down_streak = 0
        self._up_streak = 0
        self._outage_active = False  # Mirror of DB state at last tick

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

        raw = data.get("raw", {}) or {}
        grid_voltage = raw.get("vGrid") or raw.get("gridVoltage") or raw.get("vac") or None
        import_w = float(data.get("grid_import_w") or 0)
        export_w = float(data.get("grid_export_w") or 0)

        # Grid is OFF when voltage is 0 (preferred) OR both flows are zero
        if grid_voltage is not None:
            grid_off = float(grid_voltage) < 50
        else:
            grid_off = (import_w == 0 and export_w == 0)

        if grid_off:
            self._down_streak += 1
            self._up_streak = 0
        else:
            self._up_streak += 1
            self._down_streak = 0

        # Sync DB state once per tick
        await self._sync_state_with_db()

        if not self._outage_active and self._down_streak >= self.THRESHOLD_DOWN:
            await self._open()
        elif self._outage_active and self._up_streak >= self.THRESHOLD_UP:
            await self._close()

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
