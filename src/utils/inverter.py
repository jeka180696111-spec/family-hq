"""Battery autonomy estimator.

Given LuxCloud runtime + (optionally) live wattage readings of smart plugs,
estimate how long the battery will last and which devices, if turned off,
would extend autonomy the most.
"""
from __future__ import annotations

from typing import Any

import structlog

log = structlog.get_logger()

# Heavy household appliances we MAY suggest turning off during an outage.
# We only suggest a device if it has a smart-plug live wattage reading
# (cur_power / power_w via Tuya). If no reading, we don't guess — silent.
_OUTAGE_SUGGEST_DEVICES = ("бойлер", "boiler", "обогреватель", "heater")


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
    # Fallback to discharge_w if home_consumption is 0/missing
    if load_w <= 5:
        load_w = _to_float(lux_data.get("battery_discharge_w"))

    usable_wh = max(0.0, (battery_pct - reserve_pct) / 100.0 * capacity_wh)

    if load_w <= 5:
        remaining_min: float | None = None
    else:
        remaining_min = usable_wh / load_w * 60.0

    suggestions: list[dict] = []
    if tuya_client and load_w > 5:
        for hint in _OUTAGE_SUGGEST_DEVICES:
            try:
                info = await tuya_client.read_device_power_w(hint)
            except Exception:
                continue
            if not isinstance(info, dict) or info.get("error"):
                continue
            p = info.get("power_w")
            if not p or p < 50:  # below 50W не интересно
                continue
            if not info.get("on"):
                continue
            new_load = max(5.0, load_w - p)
            new_min = usable_wh / new_load * 60.0
            gain = new_min - (remaining_min or 0)
            if gain >= 5:
                suggestions.append({
                    "device": info["device"],
                    "power_w": int(p),
                    "gain_min": int(gain),
                })

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
        "remaining_min": int(remaining_min) if remaining_min is not None else None,
        "reserve_pct": reserve_pct,
        "capacity_wh": capacity_wh,
        "suggestions": suggestions,
        "text": "\n".join(lines),
    }
