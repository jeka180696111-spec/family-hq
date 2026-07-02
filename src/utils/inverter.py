"""Battery autonomy estimator.

Given LuxCloud runtime + (optionally) live wattage readings of smart plugs,
estimate how long the battery will last and which devices, if turned off,
would extend autonomy the most.
"""
from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta
from typing import Any

import structlog

log = structlog.get_logger()

# Sliding window недавних замеров SOC — используется как fallback
# когда LuxCloud отдаёт home_consumption_w=0 (а батарея реально
# разряжается).  (ts, soc_pct)
_SOC_HISTORY: deque[tuple[datetime, float]] = deque(maxlen=20)


def _estimate_load_from_soc(capacity_wh: int, current_soc: float) -> float | None:
    """Если LuxCloud не отдаёт нагрузку, оцениваем через скорость
    разряда SOC. Берём первый замер из истории старше 5 мин и считаем
    среднюю мощность за этот интервал. Возвращает Вт или None."""
    now = datetime.now()
    _SOC_HISTORY.append((now, current_soc))
    # Чистим старше 30 мин
    cutoff = now - timedelta(minutes=30)
    while _SOC_HISTORY and _SOC_HISTORY[0][0] < cutoff:
        _SOC_HISTORY.popleft()
    if len(_SOC_HISTORY) < 2:
        return None
    # Ищем замер старше 5 мин с заметной разницей
    for ts, soc in _SOC_HISTORY:
        delta_min = (now - ts).total_seconds() / 60.0
        if delta_min < 5:
            continue
        delta_soc = soc - current_soc  # положительное если разряжается
        if delta_soc <= 0.3:
            continue
        wh_used = delta_soc / 100.0 * capacity_wh
        power_w = wh_used / (delta_min / 60.0)
        if power_w > 5:
            return power_w
    return None


def _fmt_duration(minutes: float) -> str:
    if minutes < 0:
        return "—"
    if minutes >= 60:
        h = int(minutes // 60)
        m = int(minutes % 60)
        return f"{h}ч {m:02d}м" if m else f"{h}ч"
    return f"{int(minutes)}м"


def _to_float(x: Any, default: float = 0.0) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


async def runtime_report(
    lux_data: dict,
    capacity_wh: int,
    reserve_pct: int,
    tuya_client: Any = None,
) -> dict:
    """Build a runtime report given the latest LuxCloud snapshot.

    Returns a dict with both raw numbers (for callers) and a `text` field
    ready to push to a chat.
    """
    battery_pct = _to_float(lux_data.get("battery_pct"))
    load_w = _to_float(lux_data.get("home_consumption_w"))
    load_source = "home_consumption_w"
    # Fallback to discharge_w if home_consumption is 0/missing
    if load_w <= 5:
        load_w = _to_float(lux_data.get("battery_discharge_w"))
        load_source = "battery_discharge_w"
    # Если оба поля 0 — оцениваем через скорость падения SOC.
    # Реальный кейс: LuxCloud вернул home_consumption=0 пока батарея
    # реально разряжалась 96→87%. Без этого fallback мы спамим
    # «нагрузка слишком маленькая» при работающем кондёре.
    if load_w <= 5:
        estimated = _estimate_load_from_soc(capacity_wh, battery_pct)
        if estimated:
            load_w = estimated
            load_source = "soc_delta_estimate"
    else:
        # Кормим SOC-историю даже когда у нас есть прямой load_w —
        # чтобы fallback был готов если LuxCloud начнёт врать.
        _estimate_load_from_soc(capacity_wh, battery_pct)

    usable_wh = max(0.0, (battery_pct - reserve_pct) / 100.0 * capacity_wh)

    if load_w <= 5:
        remaining_min: float | None = None
    else:
        remaining_min = usable_wh / load_w * 60.0

    suggestions: list[dict] = []
    if tuya_client and load_w > 5:
        # Один вызов list_devices() (кэшируется) — потом читаем DPs
        # прямо из этого же снапшота, без дополнительных API-запросов
        # на каждое устройство. Экономит квоту в разы.
        try:
            devices = await tuya_client.list_devices()
        except Exception:
            devices = []
        for d in devices:
            if not d.get("online"):
                continue  # offline устройство точно не жрёт
            status = d.get("status", []) or []
            codes = {s.get("code", ""): s.get("value") for s in status}
            # Мощность
            power_w = None
            for code, scale in (
                ("cur_power", 0.1), ("power_w", 1.0),
                ("va_power", 1.0), ("Power_consumption", 1.0),
                ("power", 1.0),
            ):
                if code in codes and codes[code] is not None:
                    try:
                        power_w = float(codes[code]) * scale
                        break
                    except (TypeError, ValueError):
                        continue
            if not power_w or power_w < 30:
                continue
            # Устройство включено?
            switched_on = None
            for s_code in ("switch", "switch_1", "switch_led"):
                if s_code in codes:
                    switched_on = bool(codes[s_code])
                    break
            if switched_on is False:
                continue
            new_load = max(5.0, load_w - power_w)
            new_min = usable_wh / new_load * 60.0
            gain = new_min - (remaining_min or 0)
            if gain >= 5:
                suggestions.append({
                    "device": d.get("name", ""),
                    "power_w": int(power_w),
                    "gain_min": int(gain),
                })
        suggestions.sort(key=lambda s: s["gain_min"], reverse=True)
        suggestions = suggestions[:3]

    # ── Format text ───────────────────────────────────────────────
    lines = []
    lines.append(f"🔋 <b>Батарея {int(battery_pct)}%</b>  ⚡ {int(load_w)} Вт нагрузка")
    if remaining_min is not None:
        lines.append(
            f"⏱ До {reserve_pct}% осталось <b>{_fmt_duration(remaining_min)}</b>"
        )
    else:
        lines.append("⏱ Нагрузка слишком маленькая чтобы оценить время")
    if suggestions:
        lines.append("")
        lines.append("💡 Если отключить:")
        for s in suggestions:
            lines.append(
                f"  • <b>{s['device']}</b> ({s['power_w']} Вт) → +{_fmt_duration(s['gain_min'])}"
            )

    return {
        "battery_pct": int(battery_pct),
        "load_w": int(load_w),
        "load_source": load_source,
        "remaining_min": int(remaining_min) if remaining_min is not None else None,
        "reserve_pct": reserve_pct,
        "capacity_wh": capacity_wh,
        "suggestions": suggestions,
        "text": "\n".join(lines),
    }
