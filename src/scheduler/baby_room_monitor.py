"""Proactive baby room monitoring.

Каждые 15 минут проверяет датчик в детской. Если температура/влажность
выходят за диапазон нормы — Дворецкий шлёт алерт в чат. Дедуп: не чаще
одного алерта на конкретный тип отклонения в час.
"""
from __future__ import annotations
import structlog
from typing import Any

log = structlog.get_logger()

# In-memory cache: {(kind): last_alert_ts}
_LAST_ALERT: dict[str, float] = {}
_ALERT_COOLDOWN_SEC = 3600  # 1 час


def _should_alert(kind: str) -> bool:
    import time as _t
    now = _t.monotonic()
    last = _LAST_ALERT.get(kind, 0)
    if now - last < _ALERT_COOLDOWN_SEC:
        return False
    _LAST_ALERT[kind] = now
    return True


async def check_baby_room(butler_agent: Any) -> None:
    try:
        from src.config import get_settings
        from src.integrations.tuya import TuyaClient
        settings = get_settings()
        client = TuyaClient.from_settings(settings)
        if not client:
            return

        sensor_name = settings.baby_room_sensor_name or "детская"
        result = await client.read_sensor(sensor_name)
        if not isinstance(result, dict) or "error" in result:
            return
        readings = result.get("readings") or {}
        temp_raw = readings.get("temperature", "")
        humi_raw = readings.get("humidity", "")

        # Извлечь числовые значения
        try:
            temp = float(str(temp_raw).replace("°C", "").strip()) if temp_raw else None
        except Exception:
            temp = None
        try:
            humi = float(str(humi_raw).replace("%", "").strip()) if humi_raw else None
        except Exception:
            humi = None

        alerts: list[str] = []
        if temp is not None:
            if temp > settings.baby_room_temp_max and _should_alert("temp_high"):
                alerts.append(f"🥵 Жарко в детской: {temp}°C (норма {settings.baby_room_temp_min}-{settings.baby_room_temp_max})")
            elif temp < settings.baby_room_temp_min and _should_alert("temp_low"):
                alerts.append(f"🥶 Холодно в детской: {temp}°C (норма {settings.baby_room_temp_min}-{settings.baby_room_temp_max})")
        if humi is not None:
            if humi > settings.baby_room_humidity_max and _should_alert("humi_high"):
                alerts.append(f"💦 Влажно в детской: {humi}% (норма {settings.baby_room_humidity_min}-{settings.baby_room_humidity_max})")
            elif humi < settings.baby_room_humidity_min and _should_alert("humi_low"):
                alerts.append(f"🏜 Сухо в детской: {humi}% (норма {settings.baby_room_humidity_min}-{settings.baby_room_humidity_max})")

        if not alerts:
            return
        body = "🏠 <b>Проверка детской</b>\n" + "\n".join(alerts)
        await butler_agent.send(body)
        log.info("baby_room_alert_sent", count=len(alerts))
    except Exception:
        log.exception("baby_room_monitor_failed")


def register_baby_room_monitor(scheduler, butler_agent) -> None:
    scheduler.add_job(
        check_baby_room,
        "interval", minutes=15,
        args=[butler_agent],
        id="baby_room_monitor", replace_existing=True,
        max_instances=1, coalesce=True,
    )
