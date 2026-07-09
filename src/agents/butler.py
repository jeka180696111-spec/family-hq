"""Дворецкий — умный дом + шопер. Наследует Прораба, но с укороченным
списком тулов и своим промптом."""
from __future__ import annotations
from typing import Any
import structlog

from src.agents.devops import DevOpsAgent

log = structlog.get_logger()


# Тулы Прораба которые остаются у Дворецкого. Всё что не в списке —
# отсекается (Дворецкий не видит create_github_pr, cost_report и т.п.).
_BUTLER_TOOL_NAMES = {
    # Устройства
    "list_smart_devices", "control_smart_device", "control_device_for_duration",
    "smart_set_temperature", "smart_set_mode", "smart_set_fan_speed",
    "smart_sensor_read", "temperature_full", "dump_device_dps",
    # Сцены Tuya
    "run_tuya_scene", "list_tuya_scenes", "diagnose_tuya_scenes",
    # Автоматизации (для устройств)
    "add_automation_rule", "list_automation_rules", "toggle_automation_rule",
    "delete_automation_rule", "edit_automation_rule", "inspect_automation_rule",
    "schedule_device_action",
    # Инвертор / электричество
    "solar_status", "solar_today", "inverter_diagnose", "inverter_runtime",
    "battery_autonomy", "log_power_outage", "record_past_outage",
    "clean_outage_records", "power_history_from_inverter", "power_outage_stats",
    "probe_luxcloud_hosts", "probe_luxcloud_events",
    # Пылесос
    "vacuum_status", "vacuum_start", "vacuum_stop",
    # Сценарии дом/поездки
    "enter_away_mode", "exit_away_mode", "schedule_homecoming", "plan_trip",
    # Погода
    # (weather тул возьмётся из base если есть)
    # Шопер
    "shopper_search",
}


class ButlerAgent(DevOpsAgent):
    """Дворецкий — узкий фокус на дом. Промпт короче, тулов меньше →
    LLM (особенно Gemini) стабильнее."""

    agent_id = "butler"
    emoji = "🏠"
    name = "Дворецкий"

    def get_system_prompt(self) -> str:
        from src.prompts.butler import get_butler_prompt
        return get_butler_prompt(active_agents=[])

    def get_tools(self) -> list[dict[str, Any]]:
        # Берём тулы Прораба, фильтруем по белому списку, добавляем shopper.
        parent_tools = super().get_tools()
        filtered = [t for t in parent_tools if t.get("name") in _BUTLER_TOOL_NAMES]
        # Тул шопера — новый
        filtered.append({
            "name": "shopper_search",
            "description": (
                "Поиск товара в украинских магазинах (Rozetka/OLX/Prom). "
                "Триггеры: «нужно X», «купи X», «найди X», «где купить», "
                "«какое лучше X». Возвращает 3-5 вариантов: название, цена, "
                "магазин, ссылка. НЕ выдумывай — если пусто, скажи честно."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Что искать (свободный текст)"},
                    "max_price": {"type": "integer", "description": "Верхний бюджет в грн (опц)"},
                    "category": {"type": "string", "description": "Категория/подсказка (опц)"},
                },
                "required": ["query"],
            },
        })
        return filtered

    async def _call_tool(self, tool_name: str, tool_input: dict) -> Any:
        # Шопер обрабатывается локально; всё остальное — родительская логика.
        if tool_name == "shopper_search":
            from src.integrations.shopper import ShopperClient
            client = ShopperClient()
            results = await client.search(
                query=tool_input.get("query", ""),
                max_price=tool_input.get("max_price"),
                category=tool_input.get("category"),
            )
            if not results:
                return {"success": False, "message": "Ничего не нашлось. Уточни запрос."}
            return {"success": True, "results": results}
        return await super()._call_tool(tool_name, tool_input)
