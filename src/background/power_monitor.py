#!/usr/bin/env python3
"""Фоновый мониторинг инвертора для автоматической фиксации отключений света."""
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional

from src.integrations.luxpower import get_inverter_status
from src.tools.power_outage import log_power_outage

logger = logging.getLogger(__name__)

# Пороги напряжения сети
GRID_VOLTAGE_LOW_THRESHOLD = 50  # < 50V = света нет
GRID_VOLTAGE_HIGH_THRESHOLD = 180  # > 180V = свет есть

# Cooldown между фиксациями (защита от дребезга)
COOLDOWN_SECONDS = 120

# Интервал опроса инвертора
POLL_INTERVAL_SECONDS = 30


class PowerMonitor:
    def __init__(self):
        self.is_outage_active: bool = False
        self.last_transition_time: Optional[datetime] = None

    async def check_grid_status(self) -> None:
        """Опросить инвертор и зафиксировать изменение состояния сети."""
        try:
            status = await get_inverter_status()
            grid_voltage = status.get('grid_voltage', 0)

            # Защита от частых переключений
            if self.last_transition_time:
                elapsed = (datetime.now() - self.last_transition_time).total_seconds()
                if elapsed < COOLDOWN_SECONDS:
                    return

            # Определение отключения света
            if grid_voltage < GRID_VOLTAGE_LOW_THRESHOLD and not self.is_outage_active:
                logger.info(f"🔴 Автофиксация: света нет (grid_voltage={grid_voltage}V)")
                await log_power_outage(action='start', notes=f'Auto-detected: grid_voltage={grid_voltage}V')
                self.is_outage_active = True
                self.last_transition_time = datetime.now()

            # Определение возврата света
            elif grid_voltage > GRID_VOLTAGE_HIGH_THRESHOLD and self.is_outage_active:
                logger.info(f"🟢 Автофиксация: свет вернулся (grid_voltage={grid_voltage}V)")
                await log_power_outage(action='end', notes=f'Auto-detected: grid_voltage={grid_voltage}V')
                self.is_outage_active = False
                self.last_transition_time = datetime.now()

        except Exception as e:
            logger.error(f"Ошибка мониторинга инвертора: {e}")

    async def run(self) -> None:
        """Основной цикл фонового мониторинга."""
        logger.info("🛠️ Запуск автоматического мониторинга отключений света через инвертор")
        while True:
            await self.check_grid_status()
            await asyncio.sleep(POLL_INTERVAL_SECONDS)


if __name__ == '__main__':
    monitor = PowerMonitor()
    asyncio.run(monitor.run())
