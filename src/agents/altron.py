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
- Состояние Матвея — сейчас (get_baby_state) и полный дневник за N дней (get_baby_diary)
- Достижения Матвея (get_milestones + record_milestone)
- События календаря
- Активная воздушная тревога + digest (что летит, куда, прилёты)
- Инвертор (заряд батареи, есть ли свет)
- Посылки Новой Почты
- УПРАВЛЯТЬ светом и сценами дома через run_scene (например «сцена ярко спальня»)
- ВКЛ/ВЫКЛ розетки (бойлер, телевизор, пылесос) через control_socket
- ЗАПИСЫВАТЬ события Матвея через record_baby_event: кормление, сон, подгузник,
  температура, симптомы, лекарства, заметки
- ЗАПИСЫВАТЬ достижения через record_milestone (перевернулся, сел, пошёл, первый зуб)
- ЗАПИСЫВАТЬ визиты к врачу и прививки через record_doctor_visit
- Всё про ПРИКОРМ: get_feeding_summary (что уже пробовал по категориям + что рекомендовано
  по возрасту), record_feeding (записать пробу с реакцией)

ВАЖНО про Матвея — источники данных:
- get_baby_state → быстрый статус (спит/бодрствует, последнее кормление,
  подгузник). Может быть пустым если Нянька давно не обновляла — тогда
  сразу зови get_baby_diary.
- get_baby_diary → полная история из Google Sheets. Всегда есть данные если
  за день что-то записывали. Используй когда пользователь спрашивает
  «что делает?», «что было сегодня?», «когда ел?», «когда какал?».
- Никогда не отвечай «данных нет» если ты не вызвал get_baby_diary!

Важно про запись событий:
- «Матвей поел» → record_baby_event(kind=food, event=«Кормление»)
- «покакал» → record_baby_event(kind=diaper, event=«Какал»)
- «поменяли памперс» → record_baby_event(kind=diaper, event=«Мокрый»)
- «уложили спать» / «уснул» → record_baby_event(kind=sleep, event=«Уснул»)
- «проснулся» → record_baby_event(kind=sleep, event=«Проснулся»)
- «съел смесь 150мл» → kind=food, event=«Смесь», amount=150, unit=мл
- «температура 37.2» → kind=symptom, event=«Температура», amount=37.2, unit=°C
- «дали парацетамол 2.5мл» → kind=medicine, event=«Парацетамол», amount=2.5, unit=мл
- «перевернулся первый раз» → record_milestone(milestone=«Перевернулся»)
- «сегодня был у педиатра» → record_doctor_visit(type=«Осмотр», name=«Педиатр»)
- «сделали АКДС» → record_doctor_visit(type=«Прививка», name=«АКДС»)
- «попробовал банан» → record_feeding(product=«Банан»)
- «дали тыкву, кушал с аппетитом» → record_feeding(product=«Тыква», reaction=«Хорошая»)
- «съел 2 ложки пюре кабачка» → record_feeding(product=«Кабачок», portion=«2 ч.л.»)
- «что уже ел?» / «что можно попробовать?» → get_feeding_summary
- После успешной записи коротко подтверди: «Записал. Матвей поел в 12:35.»

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
            {
                "name": "record_baby_event",
                "description": (
                    "Записать событие Матвея (в дневник Google Sheets + BabyState для UI). "
                    "Триггеры: «Матвей поел», «поменяли памперс», «уложили спать», "
                    "«проснулся», «съел смесь 150мл», «покакал», «замерили температуру 37.2»."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "kind": {
                            "type": "string",
                            "enum": ["food", "sleep", "diaper", "symptom", "medicine", "note"],
                            "description": "food=кормление, sleep=сон/пробуждение, diaper=подгузник, symptom=симптом/температура, medicine=лекарство, note=заметка",
                        },
                        "event": {
                            "type": "string",
                            "description": "Короткое описание события: «Уснул», «Проснулся», «Грудь Л», «Грудь П», «Смесь», «Мокрый», «Какал», «Смешанный», «Температура», «Прикорм»",
                        },
                        "amount": {
                            "type": "number",
                            "description": "Опционально: количество (мл смеси, градусы температуры, дозировка лекарства)",
                        },
                        "unit": {
                            "type": "string",
                            "description": "Опционально: единица измерения (мл, °C, мг)",
                        },
                        "details": {
                            "type": "string",
                            "description": "Опционально: дополнительная заметка",
                        },
                    },
                    "required": ["kind", "event"],
                },
            },
            {
                "name": "record_milestone",
                "description": (
                    "Записать достижение (веху) Матвея — первая улыбка, перевернулся, "
                    "сел, пополз, встал, пошёл, первое слово, первый зуб и т.п. "
                    "Уходит в лист «Достижения»."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "milestone": {
                            "type": "string",
                            "description": "Название достижения: «Перевернулся», «Сел сам», «Пополз», «Встал», «Пошёл», «Первый зуб», «Первое слово», «Улыбнулся», «Засмеялся»",
                        },
                        "details": {
                            "type": "string",
                            "description": "Опционально: подробности (напр. «сказал мама», «сам сел на попу»)",
                        },
                    },
                    "required": ["milestone"],
                },
            },
            {
                "name": "record_doctor_visit",
                "description": (
                    "Записать визит к врачу или медицинскую процедуру: прививка, "
                    "осмотр, анализ, УЗИ, консультация. Уходит в лист «Врач»."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "type": {
                            "type": "string",
                            "enum": ["Прививка", "Осмотр", "Анализ", "УЗИ", "Консультация", "Другое"],
                            "description": "Тип визита",
                        },
                        "name": {
                            "type": "string",
                            "description": "Конкретика: «АКДС», «Педиатр плановый», «Общий анализ крови», «УЗИ мозга»",
                        },
                        "next_due": {
                            "type": "string",
                            "description": "Опционально: когда следующий (например «через месяц», «в 9 мес», «12.04.2026»)",
                        },
                        "details": {
                            "type": "string",
                            "description": "Опционально: заметки врача, реакция ребёнка",
                        },
                    },
                    "required": ["type", "name"],
                },
            },
            {
                "name": "get_milestones",
                "description": "Прочитать список достижений Матвея (за всё время, новые сверху).",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "limit": {
                            "type": "integer",
                            "description": "Сколько последних (по умолчанию 15)",
                        },
                    },
                    "required": [],
                },
            },
            {
                "name": "get_baby_diary",
                "description": (
                    "Прочитать дневник Матвея из Google Sheets — все события за N последних дней "
                    "(кормления, сон, подгузники, прогулки, лекарства). Используй когда пользователь "
                    "спрашивает «что Матвей делает?», «что было сегодня?», «когда он последний раз ел?»."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "days": {
                            "type": "integer",
                            "description": "За сколько дней (по умолчанию 1 = сегодня)",
                        },
                        "kind": {
                            "type": "string",
                            "enum": ["all", "sleep", "food", "diaper", "walk", "medicine", "symptom"],
                            "description": "Фильтр по типу событий (по умолчанию all)",
                        },
                    },
                    "required": [],
                },
            },
            {
                "name": "get_feeding_summary",
                "description": (
                    "Прикорм Матвея: что уже пробовал (сгруппировано по категориям — крупы, "
                    "овощи, фрукты, мясо, рыба, молочка, ягоды, другое) с реакциями, "
                    "и что рекомендуется попробовать по возрасту. Используй когда спрашивают "
                    "«что уже ел?», «что попробовать?», «нам что можно?», «есть ли банан?»."
                ),
                "input_schema": {"type": "object", "properties": {}, "required": []},
            },
            {
                "name": "record_feeding",
                "description": (
                    "Записать пробу нового продукта прикорма с реакцией — в лист «Прикорм» Google Sheets. "
                    "Триггеры: «попробовал банан», «дали тыкву, кушал с аппетитом», "
                    "«впервые ел брокколи», «съел 2 ложки пюре кабачка»."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "product": {
                            "type": "string",
                            "description": "Что ел: «Банан», «Тыква», «Гречневая каша», «Кабачок»",
                        },
                        "portion": {
                            "type": "string",
                            "description": "Опционально: сколько (напр. «1 ч.л.», «30 г», «половина банки»)",
                        },
                        "reaction": {
                            "type": "string",
                            "enum": ["Отличная", "Хорошая", "Нейтральная", "Отказался", "Сыпь", "Аллергия", ""],
                            "description": "Реакция ребёнка. Пусто если не указано.",
                        },
                        "type": {
                            "type": "string",
                            "enum": ["Прикорм", "Перекус", "Рецепт", "Напиток", "Десерт", "Другое"],
                            "description": "Тип еды. По умолчанию «Прикорм»",
                        },
                        "details": {
                            "type": "string",
                            "description": "Опционально: заметки (напр. «съел с аппетитом», «выплюнул»)",
                        },
                    },
                    "required": ["product"],
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
            if name == "record_baby_event":
                return await self._tool_record_baby_event(
                    kind=args.get("kind") or "note",
                    event=args.get("event") or "",
                    amount=args.get("amount"),
                    unit=args.get("unit"),
                    details=args.get("details") or "",
                )
            if name == "record_milestone":
                return await self._tool_record_milestone(
                    milestone=args.get("milestone") or "",
                    details=args.get("details") or "",
                )
            if name == "record_doctor_visit":
                return await self._tool_record_doctor_visit(
                    type_=args.get("type") or "Другое",
                    name_=args.get("name") or "",
                    next_due=args.get("next_due") or "",
                    details=args.get("details") or "",
                )
            if name == "get_milestones":
                return await self._tool_get_milestones(limit=int(args.get("limit") or 15))
            if name == "get_baby_diary":
                return await self._tool_get_baby_diary(
                    days=int(args.get("days") or 1),
                    kind=args.get("kind") or "all",
                )
            if name == "get_feeding_summary":
                return await self._tool_get_feeding_summary()
            if name == "record_feeding":
                return await self._tool_record_feeding(
                    product=args.get("product") or "",
                    portion=args.get("portion") or "",
                    reaction=args.get("reaction") or "",
                    type_=args.get("type") or "Прикорм",
                    details=args.get("details") or "",
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

    async def _tool_record_baby_event(
        self, kind: str, event: str, amount: Any = None,
        unit: Any = None, details: str = "",
    ) -> dict:
        """Записать событие Матвея: в дневник Sheets + в BabyState для UI."""
        if not event.strip():
            return {"error": "event is empty"}
        try:
            from datetime import datetime
            from sqlalchemy import select, update
            from src.db.models import BabyState
            from src.utils.time import iso_now, now_kyiv

            now = now_kyiv()
            ts_iso = now.isoformat()

            # 1) Запись в Google Sheets (если есть Sheets-клиент)
            sheets_row = None
            try:
                from src.integrations.sheets import SheetsClient
                sa = self._settings.google_service_account_json
                if sa and self._settings.sheet_baby_id:
                    sc = SheetsClient(sa, self._settings.sheet_baby_id, "")
                    sheets_row = await sc.append_baby_diary(
                        kind=kind, event=event, time=now,
                        amount=float(amount) if amount is not None else None,
                        unit=str(unit) if unit else None,
                        details=details, author="Альтрон",
                    )
            except Exception:
                log.exception("altron_sheets_write_failed")

            # 2) Обновление BabyState (то же что делает Нянька)
            event_l = event.lower()
            kind_l = kind.lower()
            values: dict = {"updated_at": iso_now()}
            if kind_l == "sleep":
                if any(w in event_l for w in ("уснул", "уснула", "усн", "лёг", "лег", "спит", "начал спать")):
                    values["sleeping_since"] = ts_iso
                    values["awake_since"] = None
                elif any(w in event_l for w in ("проснул", "встал", "разбудил", "просып")):
                    values["awake_since"] = ts_iso
                    values["sleeping_since"] = None
            elif kind_l == "food":
                values["last_feed_at"] = ts_iso
            elif kind_l == "diaper":
                values["last_diaper_at"] = ts_iso

            if len(values) > 1:  # что-то помимо updated_at
                async with self._memory._engine.begin() as conn:
                    row = (await conn.execute(select(BabyState).where(BabyState.id == 1))).first()
                    if row:
                        await conn.execute(update(BabyState).where(BabyState.id == 1).values(**values))
                    else:
                        # Создаём если ещё нет
                        from sqlalchemy import insert
                        await conn.execute(insert(BabyState).values(id=1, **values))

            return {
                "success": True,
                "kind": kind,
                "event": event,
                "recorded_at": ts_iso,
                "sheets_row": sheets_row.data if sheets_row else None,
                "baby_state_updated": len(values) > 1,
            }
        except Exception as e:
            log.exception("altron_record_baby_failed", kind=kind, event=event)
            return {"error": str(e)[:200]}

    async def _tool_record_milestone(self, milestone: str, details: str = "") -> dict:
        """Записать веху Матвея в лист «Достижения»."""
        if not milestone.strip():
            return {"error": "milestone is empty"}
        try:
            from src.integrations.sheets import SheetsClient
            from src.utils.time import now_kyiv
            sa = self._settings.google_service_account_json
            if not (sa and self._settings.sheet_baby_id):
                return {"error": "Sheets не настроены"}
            sc = SheetsClient(sa, self._settings.sheet_baby_id, "")
            res = await sc.append_milestone(
                milestone=milestone, time=now_kyiv(),
                details=details, author="Альтрон",
            )
            return {"success": True, "milestone": milestone, "row": res.get("row")}
        except Exception as e:
            log.exception("altron_milestone_failed", milestone=milestone)
            return {"error": str(e)[:200]}

    async def _tool_record_doctor_visit(
        self, type_: str, name_: str, next_due: str = "", details: str = "",
    ) -> dict:
        """Записать визит к врачу / прививку / анализ в лист «Врач»."""
        if not name_.strip():
            return {"error": "name is empty"}
        try:
            from src.integrations.sheets import SheetsClient
            from src.utils.time import now_kyiv
            sa = self._settings.google_service_account_json
            if not (sa and self._settings.sheet_baby_id):
                return {"error": "Sheets не настроены"}
            sc = SheetsClient(sa, self._settings.sheet_baby_id, "")
            res = await sc.append_doctor(
                type_=type_, name=name_, time=now_kyiv(),
                next_due=next_due, details=details,
            )
            return {
                "success": True,
                "type": type_, "name": name_,
                "row": res.get("row"),
                "dedup": res.get("dedup", False),
            }
        except Exception as e:
            log.exception("altron_doctor_failed", type=type_, name=name_)
            return {"error": str(e)[:200]}

    async def _tool_get_milestones(self, limit: int = 15) -> dict:
        try:
            from src.integrations.sheets import SheetsClient
            sa = self._settings.google_service_account_json
            if not (sa and self._settings.sheet_baby_id):
                return {"milestones": []}
            sc = SheetsClient(sa, self._settings.sheet_baby_id, "")
            items = await sc.list_milestones(limit=limit)
            return {"milestones": items}
        except Exception as e:
            log.exception("altron_get_milestones_failed")
            return {"error": str(e)[:200], "milestones": []}

    async def _tool_get_baby_diary(self, days: int = 1, kind: str = "all") -> dict:
        """Прочитать записи дневника Матвея за N дней. Использует существующий
        SheetsClient.get_baby_diary."""
        try:
            from src.integrations.sheets import SheetsClient
            sa = self._settings.google_service_account_json
            if not (sa and self._settings.sheet_baby_id):
                return {"events": [], "note": "Sheets не настроены"}
            sc = SheetsClient(sa, self._settings.sheet_baby_id, "")
            kind_arg = None if (kind or "all").lower() in ("all", "*", "") else kind
            rows = await sc.get_baby_diary(days=max(1, days), kind=kind_arg)
            events = []
            for r in rows[-100:]:  # последние 100
                d = getattr(r, "data", {}) or {}
                events.append({
                    "date": d.get("date", ""),
                    "time": d.get("time", ""),
                    "kind": d.get("kind", ""),
                    "event": d.get("event", ""),
                    "amount": d.get("amount", ""),
                    "notes": d.get("notes", ""),
                })
            return {"events": events, "total": len(events)}
        except Exception as e:
            log.exception("altron_get_diary_failed")
            return {"error": str(e)[:200], "events": []}

    async def _tool_get_feeding_summary(self) -> dict:
        """Полная сводка по прикорму: что пробовал (по категориям) + что рекомендуется по возрасту."""
        try:
            from src.integrations.sheets import SheetsClient
            from src.utils.food_catalog import (
                CATEGORIES, guess_emoji, guess_category, to_try_now, _normalize,
            )
            from src.utils.baby import MATVEY_BIRTH_DATE
            from datetime import date

            sa = self._settings.google_service_account_json
            if not (sa and self._settings.sheet_baby_id):
                return {"error": "Sheets не настроены"}
            sc = SheetsClient(sa, self._settings.sheet_baby_id, "")
            rows = await sc.get_feeding(limit=1000)

            age_months = round((date.today() - MATVEY_BIRTH_DATE).days / 30.4375, 1)

            # Агрегируем: уникальные продукты, взяв самую свежую реакцию
            aggr: dict[str, dict] = {}
            for r in rows:
                p = (r.get("product") or "").strip()
                if not p:
                    continue
                type_ = (r.get("type") or "").lower()
                if any(x in type_ for x in ("груд", "смес", "молок")):
                    continue
                key = _normalize(p)
                if not key:
                    continue
                cur = aggr.get(key)
                item = {
                    "name": p,
                    "category": guess_category(p),
                    "emoji": guess_emoji(p),
                    "last_reaction": r.get("reaction", "") or "",
                    "last_date": r.get("date", ""),
                    "count": (cur["count"] + 1) if cur else 1,
                }
                aggr[key] = item

            # Раскладываем по категориям
            tried_by_cat: dict = {}
            for cat_slug, cat_em in CATEGORIES:
                tried_by_cat[cat_slug] = {"emoji": cat_em, "items": []}
            for item in aggr.values():
                cat = item["category"]
                if cat not in tried_by_cat:
                    tried_by_cat[cat] = {"emoji": "🥄", "items": []}
                tried_by_cat[cat]["items"].append({
                    "name": item["name"],
                    "reaction": item["last_reaction"],
                    "count": item["count"],
                })
            for cat in tried_by_cat.values():
                cat["items"].sort(key=lambda x: x["name"].lower())

            to_try = to_try_now(age_months, set(aggr.keys()))

            return {
                "age_months": age_months,
                "tried_by_category": tried_by_cat,
                "total_products_tried": len(aggr),
                "recommended_next": [t.get("name") if isinstance(t, dict) else t for t in (to_try or [])][:12],
            }
        except Exception as e:
            log.exception("altron_feeding_summary_failed")
            return {"error": str(e)[:200]}

    async def _tool_record_feeding(
        self, product: str, portion: str = "", reaction: str = "",
        type_: str = "Прикорм", details: str = "",
    ) -> dict:
        """Записать пробу продукта в лист «Прикорм»."""
        if not product.strip():
            return {"error": "product is empty"}
        try:
            from src.integrations.sheets import SheetsClient
            from src.utils.time import now_kyiv
            sa = self._settings.google_service_account_json
            if not (sa and self._settings.sheet_baby_id):
                return {"error": "Sheets не настроены"}
            sc = SheetsClient(sa, self._settings.sheet_baby_id, "")
            res = await sc.append_feeding(
                type_=type_ or "Прикорм", product=product, time=now_kyiv(),
                portion=portion, reaction=reaction, details=details,
                author="Альтрон",
            )
            return {
                "success": True,
                "product": product,
                "reaction": reaction,
                "row": res.get("row"),
                "dedup": res.get("skipped", False),
            }
        except Exception as e:
            log.exception("altron_record_feeding_failed", product=product)
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
