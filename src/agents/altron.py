"""Альтрон — экспериментальный единый семейный ассистент (v2).

Отличие от старой архитектуры: вместо 8 отдельных Telegram-ботов
(Дворецкий, Нянька, Гурман, Дозорный, Прораб, ДевОпс, Навигатор,
Калень) — ОДИН бот с полным набором tools и общим контекстом.

Живёт в отдельном чате (ALTRON_CHAT_ID), никак не пересекается со
старыми агентами. LLM — Gemini (пока), tools — read-only на первом
этапе, чтобы понять качество ответов до подключения контроля.

Разработка идёт параллельно с рабочим кодом, чтобы Марина продолжала
пользоваться привычными агентами.
"""
from __future__ import annotations

import json
from typing import Any

import structlog

from src.utils.time import now_kyiv

log = structlog.get_logger()


_SYSTEM_PROMPT = """Ты Альтрон — семейный ассистент штаба Евгения и Марины.
Семья: Евгений, Марина, сын Матвей (родился 03.12.2025), Одесса.

Стиль:
- Отвечай коротко и по делу. Без «Я готов помочь», «Спасибо за вопрос».
- Живой русский, без канцелярита. Как друг который в теме.
- Если не знаешь — говори «не знаю» вместо выдумок.
- Если вопрос неоднозначный — переспрашивай.

Что умеешь (используй tools):
- Погода, время
- Состояние Матвея (спит / бодрствует / когда кормили)
- События календаря
- Активная воздушная тревога + digest (что летит, куда, прилёты)
- Инвертор (заряд батареи, есть ли свет)
- Посылки Новой Почты
- УПРАВЛЯТЬ светом и сценами дома через run_scene (например «сцена ярко спальня»)
- ВКЛ/ВЫКЛ розетки (бойлер, телевизор, пылесос) через control_socket

Важно про управление:
- Если фраза похожа на команду («включи», «выключи», «запусти», «включай»,
  «дай света», «сделай темнее», «на базу», «пусти пылесос») — сразу вызывай нужный tool
  без переспрашивания.
- Если после вызова run_scene вернулось success:false с available_scenes —
  честно скажи «не нашёл, есть такие:» и перечисли варианты.
- Не задавай уточнений которые сам мог бы решить (напр. «спальня» и так очевидно).
- После успешной команды коротко подтверди («Готово. Свет в спальне яркий.») —
  без бюрократии.

Голосом называй родителей по именам, ребёнка — Матвейкой или Матвеем.
"""


class AltronAgent:
    """Единый ассистент. Отвечает на сообщения из ALTRON_CHAT_ID.

    Не пересекается со старыми агентами: своя LLM-сессия, свой промпт,
    свой набор tools. Читает из общей БД (BabyState, ActiveAlert и т.д.),
    но пишет только в свою историю сообщений (таблица altron_messages).
    """

    def __init__(
        self,
        memory: Any,
        gemini_client: Any,
        settings: Any,
    ) -> None:
        self._memory = memory
        self._gemini = gemini_client
        self._settings = settings
        # История разговора по chat_id. In-memory; при перезапуске обнуляется —
        # для Этапа 2 нормально. Позже переедет в БД.
        self._history: dict[int, list[dict]] = {}
        self._HISTORY_LIMIT = 20  # сообщений (user + assistant), суммарно

    def _append_history(self, chat_id: int, role: str, content: Any) -> None:
        h = self._history.setdefault(chat_id, [])
        h.append({"role": role, "content": content})
        # Обрезаем — но не в середине tool-цепочки. Простая эвристика:
        # держим ровно ×2 лимита элементов, потом отрезаем от начала.
        if len(h) > self._HISTORY_LIMIT * 2:
            del h[: len(h) - self._HISTORY_LIMIT]

    def _get_history(self, chat_id: int) -> list[dict]:
        return list(self._history.get(chat_id, []))

    def reset_history(self, chat_id: int) -> None:
        self._history[chat_id] = []

    # ─── Tools ─────────────────────────────────────────────────────

    def _tools(self) -> list[dict]:
        """Список функций доступных Альтрону. Формат совместим с Anthropic
        и Gemini (наш GeminiClient переводит на лету)."""
        return [
            {
                "name": "get_time_and_weather",
                "description": "Текущее время в Одессе, погода за окном (температура, ощущение, влажность, ветер, описание).",
                "input_schema": {"type": "object", "properties": {}, "required": []},
            },
            {
                "name": "get_baby_state",
                "description": "Состояние Матвея прямо сейчас: спит/бодрствует, сколько времени в текущем состоянии, время последнего кормления, время последнего подгузника, температура в детской.",
                "input_schema": {"type": "object", "properties": {}, "required": []},
            },
            {
                "name": "get_calendar_today",
                "description": "События календаря на сегодня и ближайшие 3 дня. Возвращает список: время начала, название, локация.",
                "input_schema": {"type": "object", "properties": {}, "required": []},
            },
            {
                "name": "get_active_alert",
                "description": "Активна ли воздушная тревога в Одесской области. Если да — возвращает digest: что летит (шахеды, ракеты, КАБы), курс, прилёты, длительность.",
                "input_schema": {"type": "object", "properties": {}, "required": []},
            },
            {
                "name": "get_inverter_state",
                "description": "Заряд батареи инвертора (%), есть ли свет от сети, потребление в ваттах, направление потока (заряжается/разряжается).",
                "input_schema": {"type": "object", "properties": {}, "required": []},
            },
            {
                "name": "get_parcels",
                "description": "Посылки Новой Почты: те что в пути и те что прибыли на почту и ждут выдачи. Возвращает TTN, статус, куда идёт.",
                "input_schema": {"type": "object", "properties": {}, "required": []},
            },
            {
                "name": "run_scene",
                "description": (
                    "Запустить сцену умного дома Tuya. Используй когда пользователь просит: "
                    "«включи свет ярко в спальне», «выключи всё в детской», «сцена ночь на кухне», "
                    "«кондиционер 24». Аргумент `query` — свободный текст с названием сцены "
                    "и/или комнаты, я сам найду ближайшую сцену по совпадению."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Название сцены + комната (напр. «спальня ярко», «кондер 24», «детская ночь»).",
                        },
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "control_socket",
                "description": (
                    "Включить или выключить розетку по имени: бойлер, телевизор, пылесос-Гоша и т.п. "
                    "Только для устройств-выключателей, НЕ для света (для света используй run_scene)."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "device": {
                            "type": "string",
                            "description": "Имя розетки: «бойлер», «телевизор», «гоша», «пылесос», «зарядка».",
                        },
                        "action": {
                            "type": "string",
                            "enum": ["on", "off", "toggle"],
                            "description": "on=включить, off=выключить, toggle=переключить.",
                        },
                    },
                    "required": ["device", "action"],
                },
            },
        ]

    async def _exec_tool(self, name: str, args: dict) -> dict:
        """Выполнить вызов tool'a и вернуть результат в JSON-serializable виде."""
        try:
            if name == "get_time_and_weather":
                return await self._tool_time_weather()
            if name == "get_baby_state":
                return await self._tool_baby_state()
            if name == "get_calendar_today":
                return await self._tool_calendar()
            if name == "get_active_alert":
                return await self._tool_alert()
            if name == "get_inverter_state":
                return await self._tool_inverter()
            if name == "get_parcels":
                return await self._tool_parcels()
            if name == "run_scene":
                return await self._tool_run_scene(args.get("query") or "")
            if name == "control_socket":
                return await self._tool_control_socket(
                    args.get("device") or "", args.get("action") or "toggle",
                )
            return {"error": f"unknown tool: {name}"}
        except Exception as e:
            log.exception("altron_tool_failed", tool=name)
            return {"error": str(e)[:200]}

    async def _tool_time_weather(self) -> dict:
        now = now_kyiv()
        out = {"time_local": now.strftime("%H:%M"), "date_local": now.strftime("%d.%m.%Y (%A)")}
        try:
            from src.integrations.weather import WeatherClient
            wc = WeatherClient.from_settings(self._settings)
            if wc:
                w = await wc.current(self._settings.city, self._settings.country_code or "UA")
                if w:
                    out.update({
                        "temp_c": w.get("temp"),
                        "feels_like_c": w.get("feels_like"),
                        "humidity_pct": w.get("humidity"),
                        "wind_ms": w.get("wind"),
                        "description": w.get("description"),
                    })
        except Exception:
            log.exception("altron_weather_failed")
        return out

    async def _tool_baby_state(self) -> dict:
        from sqlalchemy import select
        from src.db.models import BabyState
        async with self._memory._engine.connect() as conn:
            row = (await conn.execute(select(BabyState))).first()
        out: dict = {}
        if row:
            bs = row[0] if hasattr(row, "_mapping") else row
            out = {
                "sleeping_since": getattr(bs, "sleeping_since", None),
                "awake_since": getattr(bs, "awake_since", None),
                "last_feed_at": getattr(bs, "last_feed_at", None),
                "last_diaper_at": getattr(bs, "last_diaper_at", None),
            }
        # Температура в детской — из state.devices
        try:
            from src.web.tablet import _build_tablet_state
            # Проще: читаем из BabyState хватит на первый этап
            pass
        except Exception:
            pass
        return out

    async def _tool_calendar(self) -> dict:
        try:
            from src.integrations.gcalendar import CalendarClient
            if not self._settings.google_service_account_json or not self._settings.calendar_id:
                return {"events": []}
            cal = CalendarClient(self._settings.google_service_account_json, self._settings.calendar_id)
            events = await cal.list_upcoming(days=3)
            out = []
            for e in events[:15]:
                out.append({
                    "title": getattr(e, "title", ""),
                    "when": getattr(e, "start", None).isoformat() if getattr(e, "start", None) else "",
                    "location": getattr(e, "location", "") or "",
                })
            return {"events": out}
        except Exception:
            log.exception("altron_calendar_failed")
            return {"events": []}

    async def _tool_alert(self) -> dict:
        from sqlalchemy import select
        from src.db.models import ActiveAlert
        async with self._memory._engine.connect() as conn:
            row = (await conn.execute(
                select(
                    ActiveAlert.region, ActiveAlert.started_at,
                    ActiveAlert.last_update_at, ActiveAlert.digest_json,
                ).order_by(ActiveAlert.started_at.desc()).limit(1)
            )).first()
        if not row:
            return {"active": False}
        digest = None
        if row.digest_json:
            try:
                digest = json.loads(row.digest_json)
            except Exception:
                digest = None
        return {
            "active": True,
            "region": row.region,
            "started_at": row.started_at,
            "digest": digest,
        }

    async def _tool_inverter(self) -> dict:
        try:
            from src.integrations.luxcloud import LuxCloudClient
            lux = LuxCloudClient.from_settings(self._settings)
            if not lux:
                return {"error": "inverter not configured"}
            rt = await lux.runtime()
            grid_import = rt.get("grid_import_w") or 0
            grid_export = rt.get("grid_export_w") or 0
            discharge_w = rt.get("battery_discharge_w") or 0
            charge_w = rt.get("battery_charge_w") or 0
            status_lc = str(rt.get("status") or "").lower()
            if discharge_w > 20 and grid_import <= 20 and grid_export <= 20:
                grid_active = False
            elif grid_import > 20 or grid_export > 20:
                grid_active = True
            elif status_lc in ("off-grid", "offgrid", "island"):
                grid_active = False
            else:
                grid_active = True
            return {
                "soc_pct": rt.get("battery_pct") or rt.get("soc"),
                "load_w": rt.get("home_consumption_w") or rt.get("load_w") or 0,
                "grid_active": grid_active,
                "battery_flow": "charging" if charge_w > discharge_w + 20 else
                                "discharging" if discharge_w > charge_w + 20 else "idle",
                "solar_w": rt.get("pv_total_w") or 0,
            }
        except Exception:
            log.exception("altron_inverter_failed")
            return {"error": "inverter read failed"}

    async def _tool_parcels(self) -> dict:
        from sqlalchemy import select
        from src.db.models import Parcel
        async with self._memory._engine.connect() as conn:
            rows = list(await conn.execute(
                select(Parcel).where(Parcel.delivered_at.is_(None))
                .order_by(Parcel.created_at.desc()).limit(15)
            ))
        out = []
        for r in rows:
            out.append({
                "ttn": r.ttn,
                "title": r.title or r.ttn,
                "status": r.status or "",
                "city_from": r.city_from or "",
                "city_to": r.city_to or "",
                "warehouse": r.warehouse or "",
                "scheduled_at": r.scheduled_at or "",
            })
        return {"parcels": out}

    async def _tool_run_scene(self, query: str) -> dict:
        """Найти сцену Tuya по free-text и запустить."""
        if not query.strip():
            return {"error": "query is empty"}
        try:
            from src.integrations.tuya import TuyaClient
            tuya = TuyaClient.from_settings(self._settings)
            if not tuya:
                return {"error": "Tuya не настроен"}
            scene = await tuya.find_scene(query)
            if not scene:
                # Список кандидатов чтобы Альтрон мог переспросить
                all_scenes = await tuya.list_scenes()
                names = [s.get("name") for s in all_scenes if s.get("name") and not s.get("is_automation")]
                return {
                    "success": False,
                    "reason": f"не нашёл сцену по «{query}»",
                    "available_scenes": names[:20],
                }
            result = await tuya.run_scene(scene.get("id"))
            return {
                "success": True,
                "scene_name": scene.get("name"),
                "scene_id": scene.get("id"),
                "tuya_response": result,
            }
        except Exception as e:
            log.exception("altron_scene_failed", query=query)
            return {"error": str(e)[:200]}

    async def _tool_control_socket(self, device: str, action: str) -> dict:
        """Включить/выключить розетку по имени. Переиспользуем tuya.control."""
        if not device.strip():
            return {"error": "device is empty"}
        if action not in ("on", "off", "toggle"):
            action = "toggle"
        try:
            from src.integrations.tuya import TuyaClient
            tuya = TuyaClient.from_settings(self._settings)
            if not tuya:
                return {"error": "Tuya не настроен"}
            result = await tuya.control(device, action)
            return result
        except Exception as e:
            log.exception("altron_socket_failed", device=device, action=action)
            return {"error": str(e)[:200]}

    # ─── Main entry: handle user message ────────────────────────────

    async def handle(self, text: str, user_name: str = "Пользователь", chat_id: int = 0) -> str:
        """Обработать входящее сообщение и вернуть ответ.

        Использует историю сообщений (по chat_id), защита от цикла tool-loop.
        """
        if not text or not text.strip():
            return "Слушаю?"

        # Спецкоманда «сброс» — обнулить историю
        if text.strip().lower() in ("/reset", "/clear", "сброс", "забудь"):
            self.reset_history(chat_id)
            return "🧹 Забыл. Начинаем с чистого листа."

        tools = self._tools()
        history = self._get_history(chat_id)
        user_msg = {"role": "user", "content": f"[{user_name}]: {text}"}
        messages = history + [user_msg]

        # Учёт какие tool+args уже вызывались — чтобы не крутить один и тот же
        called_signatures: set[str] = set()
        MAX_ITER = 5

        for iteration in range(MAX_ITER):
            # На последней итерации выключаем tools и заставляем ответить текстом
            force_final = iteration == MAX_ITER - 1
            try:
                resp = await self._gemini.complete_with_tools(
                    system=_SYSTEM_PROMPT,
                    messages=messages,
                    tools=[] if force_final else tools,
                    max_tokens=800,
                )
            except Exception as e:
                log.exception("altron_llm_failed", iteration=iteration)
                return f"Что-то с LLM: {str(e)[:100]}"

            content_blocks = list(getattr(resp, "content", []) or [])
            tool_calls = [b for b in content_blocks if getattr(b, "type", "") == "tool_use"]
            text_blocks = [b for b in content_blocks if getattr(b, "type", "") == "text"]

            # Финальный ответ — модель не запросила tool
            if not tool_calls:
                text_out = " ".join(getattr(b, "text", "") for b in text_blocks).strip()
                # Сохраняем в историю (user + assistant текст)
                self._append_history(chat_id, user_msg["role"], user_msg["content"])
                self._append_history(chat_id, "assistant", text_out or "…")
                return text_out or "Не смог сформулировать ответ. Спроси ещё раз?"

            # Есть tool_use — проверяем на цикл
            new_calls = []
            duplicate_calls = []
            for tc in tool_calls:
                sig = f"{tc.name}:{json.dumps(tc.input or {}, sort_keys=True)}"
                if sig in called_signatures:
                    duplicate_calls.append(tc)
                else:
                    called_signatures.add(sig)
                    new_calls.append(tc)

            # Если ВСЕ вызовы дублирующие — цикл. Возвращаем текст если есть,
            # иначе форсим финальный вопрос без tools.
            if not new_calls:
                log.warning("altron_tool_loop_detected", iteration=iteration)
                text_out = " ".join(getattr(b, "text", "") for b in text_blocks).strip()
                if text_out:
                    self._append_history(chat_id, user_msg["role"], user_msg["content"])
                    self._append_history(chat_id, "assistant", text_out)
                    return text_out
                # Форс: ещё один вызов без tools — пусть отвечает по тому что есть
                try:
                    final = await self._gemini.complete_with_tools(
                        system=_SYSTEM_PROMPT + "\n\nОТВЕТЬ пользователю на основе уже собранной информации из tool_results выше. НЕ вызывай tools.",
                        messages=messages,
                        tools=[],
                        max_tokens=500,
                    )
                    fblocks = list(getattr(final, "content", []) or [])
                    ftext = " ".join(getattr(b, "text", "") for b in fblocks if getattr(b, "type", "") == "text").strip()
                    if ftext:
                        self._append_history(chat_id, user_msg["role"], user_msg["content"])
                        self._append_history(chat_id, "assistant", ftext)
                        return ftext
                except Exception:
                    log.exception("altron_forced_final_failed")
                return "Что-то залип. Спроси иначе?"

            # Выполняем новые вызовы, добавляем результаты
            messages.append({"role": "assistant", "content": content_blocks})
            tool_results = []
            for tc in tool_calls:
                sig = f"{tc.name}:{json.dumps(tc.input or {}, sort_keys=True)}"
                if sig in called_signatures and tc in duplicate_calls:
                    # Дублирующему возвращаем прошлый результат-ссылку
                    result = {"note": "already called this tool, use previous result"}
                else:
                    result = await self._exec_tool(tc.name, tc.input or {})
                    log.info("altron_tool_ran", name=tc.name, keys=list(result.keys())[:5])
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tc.id,
                    "content": json.dumps(result, ensure_ascii=False, default=str),
                })
            messages.append({"role": "user", "content": tool_results})

        return "Слишком долго думаю. Попробуй перефразировать?"
