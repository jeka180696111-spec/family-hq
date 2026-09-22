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
- КАЛЕНДАРЬ: get_calendar_today (что впереди), create_calendar_event (поставить встречу),
  delete_calendar_event (отменить)
- СПИСОК ПОКУПОК: get_shopping_list, add_shopping_item, mark_shopping_done
- ПОСЫЛКИ: get_parcels, add_parcel (отслеживать по TTN), refresh_parcel (обновить статус),
  mark_parcel_received (забрал)
- ДОЗОРНЫЙ / НОВОСТИ: get_recent_news (последние посты), get_active_alert (тревога сейчас),
  list_news_channels, add_news_channel, remove_news_channel
- НАВИГАТОР: remember_parking (запомнить где машина), get_parking (спросить)
- ДОЛГОВРЕМЕННАЯ ПАМЯТЬ: remember_fact (аллергии, вкусы, размеры), get_facts
- АВТОНОМИЯ: get_inverter_forecast («на сколько хватит?»), activate_blackout_mode
  (выключить лишнее в блэкаут — ТОЛЬКО с явного согласия юзера!)

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
- «завтра в 10 к педиатру» → create_calendar_event(title=«Педиатр», start_iso=«завтра 10:00 +03:00»)
- «купи молоко и хлеб» → два вызова add_shopping_item
- «купил хлеб» → mark_shopping_done(item=«хлеб»)
- «что в списке?» → get_shopping_list
- «отмени встречу с врачом» → сперва get_calendar_today чтобы узнать event_id, потом delete_calendar_event
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
                            "enum": ["Отличная", "Хорошая", "Нейтральная", "Отказался", "Сыпь", "Аллергия"],
                            "description": "Реакция ребёнка. Не указывай если не знаешь.",
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
            {
                "name": "create_calendar_event",
                "description": (
                    "Создать событие в Google Календаре семьи. Триггеры: «поставь встречу», "
                    "«запиши в календарь», «завтра в 10 к педиатру», «в среду годовщина»."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "title": {
                            "type": "string",
                            "description": "Название события",
                        },
                        "start_iso": {
                            "type": "string",
                            "description": "Начало в ISO-8601 с часовым поясом (напр. 2026-09-25T10:00:00+03:00). Всегда используй время Одессы (+03:00).",
                        },
                        "duration_min": {
                            "type": "integer",
                            "description": "Длительность в минутах. По умолчанию 60.",
                        },
                        "location": {
                            "type": "string",
                            "description": "Опционально: где",
                        },
                        "description": {
                            "type": "string",
                            "description": "Опционально: заметки",
                        },
                    },
                    "required": ["title", "start_iso"],
                },
            },
            {
                "name": "delete_calendar_event",
                "description": "Удалить событие календаря по id (id берётся из get_calendar_today).",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "event_id": {"type": "string", "description": "Google Calendar event id"},
                    },
                    "required": ["event_id"],
                },
            },
            {
                "name": "get_shopping_list",
                "description": "Прочитать текущий список покупок (только невыполненные пункты).",
                "input_schema": {"type": "object", "properties": {}, "required": []},
            },
            {
                "name": "add_shopping_item",
                "description": (
                    "Добавить пункт в список покупок. Триггеры: «купи молоко», "
                    "«добавь в список: хлеб, гречка», «нужен памперс»."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "item": {"type": "string", "description": "Что купить"},
                        "quantity": {"type": "string", "description": "Опционально: сколько"},
                        "place": {
                            "type": "string",
                            "description": "Опционально: где купить (АТБ, Сільпо, аптека)",
                        },
                    },
                    "required": ["item"],
                },
            },
            {
                "name": "mark_shopping_done",
                "description": (
                    "Отметить пункт списка покупок как купленный. Триггеры: «купил молоко», "
                    "«взял хлеб», «вычеркни памперсы»."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "item": {"type": "string", "description": "Что было куплено (по имени)"},
                    },
                    "required": ["item"],
                },
            },
            {
                "name": "add_parcel",
                "description": (
                    "Добавить посылку Новой Почты в отслеживание по TTN (14 цифр). "
                    "Триггеры: «отследи посылку 20 4515 0027 4857», «жду посылку», "
                    "«вот ТТН». Автоматически подтянет статус и город."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "ttn": {
                            "type": "string",
                            "description": "14-значный ТТН Новой Почты (пробелы и дефисы ок, вырежу)",
                        },
                        "title": {
                            "type": "string",
                            "description": "Опционально: короткое имя (напр. «памперсы», «наушники»)",
                        },
                        "member": {
                            "type": "string",
                            "description": "Опционально: кому (Евгений/Марина/семье)",
                        },
                    },
                    "required": ["ttn"],
                },
            },
            {
                "name": "refresh_parcel",
                "description": (
                    "Принудительно обновить статус конкретной посылки в НП. "
                    "По TTN если задан, иначе — все активные."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "ttn": {
                            "type": "string",
                            "description": "Опционально: ТТН конкретной посылки",
                        },
                    },
                    "required": [],
                },
            },
            {
                "name": "mark_parcel_received",
                "description": (
                    "Отметить посылку как забранную (после самовывоза с отделения). "
                    "Триггеры: «забрал посылку», «получил заказ», «вычеркни памперсы из посылок»."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "ttn": {
                            "type": "string",
                            "description": "ТТН или fuzzy-часть имени посылки",
                        },
                    },
                    "required": ["ttn"],
                },
            },
            {
                "name": "get_recent_news",
                "description": (
                    "Прочитать последние N постов из мониторинга новостей (тревожные каналы). "
                    "Используй когда пользователь спрашивает «что нового?», «что за посты сегодня?», "
                    "«что происходит?». Не путать с get_active_alert (это про активную тревогу)."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "limit": {"type": "integer", "description": "Сколько постов (по умолчанию 15)"},
                        "alerts_only": {"type": "boolean", "description": "Только тревожные посты"},
                    },
                    "required": [],
                },
            },
            {
                "name": "list_news_channels",
                "description": "Список каналов которые сейчас мониторит Дозорный (для тревог).",
                "input_schema": {"type": "object", "properties": {}, "required": []},
            },
            {
                "name": "add_news_channel",
                "description": (
                    "Добавить Telegram-канал в мониторинг Дозорного. Триггеры: "
                    "«добавь канал @xxx», «мониторь odessa_inform», «подпишись на»."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "username": {
                            "type": "string",
                            "description": "@username канала или https://t.me/xxx или ссылка",
                        },
                        "title": {
                            "type": "string",
                            "description": "Опционально: имя для отображения",
                        },
                        "category": {
                            "type": "string",
                            "enum": ["critical", "important", "background"],
                            "description": "critical=тревоги/удары, important=важные новости, background=фон",
                        },
                        "region": {
                            "type": "string",
                            "description": "Опционально: регион (Одесская область, Николаев, и т.д.)",
                        },
                    },
                    "required": ["username"],
                },
            },
            {
                "name": "remove_news_channel",
                "description": "Убрать канал из мониторинга. Fuzzy по username или title.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "@username или часть имени"},
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "remember_parking",
                "description": (
                    "Запомнить где припарковался. Триггеры: «запомни где машина», "
                    "«припарковался на Дерибасовской», «поставил у ТРЦ Ривьера»."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "location": {
                            "type": "string",
                            "description": "Место (адрес, ориентир, координаты — как сказал)",
                        },
                        "notes": {
                            "type": "string",
                            "description": "Опционально: уровень паркинга, номер места, оплатил и т.п.",
                        },
                    },
                    "required": ["location"],
                },
            },
            {
                "name": "get_parking",
                "description": "Где припаркована машина в последний раз (что записал remember_parking).",
                "input_schema": {"type": "object", "properties": {}, "required": []},
            },
            {
                "name": "remember_fact",
                "description": (
                    "Запомнить факт о члене семьи. Триггеры: «запомни, у Матвея аллергия на банан», "
                    "«Марина любит ромашковый чай», «у меня размер обуви 43». Используется всеми "
                    "будущими ответами Альтрона как контекст."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "member": {
                            "type": "string",
                            "enum": ["eugene", "marina", "matvey", "family"],
                            "description": "О ком факт. eugene=Евгений, marina=Марина, matvey=Матвей, family=про семью",
                        },
                        "key": {
                            "type": "string",
                            "description": "Категория: «аллергия», «любит», «не любит», «размер», «предпочтение», «привычка»",
                        },
                        "value": {"type": "string", "description": "Значение факта"},
                    },
                    "required": ["member", "key", "value"],
                },
            },
            {
                "name": "get_facts",
                "description": (
                    "Прочитать все факты семьи (что кто любит, аллергии, размеры, привычки). "
                    "Используй перед ответами про еду, покупки, подарки."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "member": {
                            "type": "string",
                            "description": "Опционально: фильтр по человеку (eugene/marina/matvey/family)",
                        },
                    },
                    "required": [],
                },
            },
            {
                "name": "get_inverter_forecast",
                "description": (
                    "Прогноз автономии инвертора: сколько батареи хватит при текущем потреблении "
                    "до резервного уровня (обычно 20%). Учитывает солнце и заряд/разряд. "
                    "Триггеры: «на сколько хватит батареи?», «сколько ещё продержимся?»."
                ),
                "input_schema": {"type": "object", "properties": {}, "required": []},
            },
            {
                "name": "activate_blackout_mode",
                "description": (
                    "Активировать аварийный режим: включить сцены минимального потребления "
                    "(выключить бойлер, ТВ, лишний свет). Триггеры: «свет вырубили», "
                    "«режим экономии», «блэкаут». Требует явного согласия пользователя."
                ),
                "input_schema": {"type": "object", "properties": {}, "required": []},
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
            if name == "create_calendar_event":
                return await self._tool_create_calendar_event(
                    title=args.get("title") or "",
                    start_iso=args.get("start_iso") or "",
                    duration_min=int(args.get("duration_min") or 60),
                    location=args.get("location") or "",
                    description=args.get("description") or "",
                )
            if name == "delete_calendar_event":
                return await self._tool_delete_calendar_event(event_id=args.get("event_id") or "")
            if name == "get_shopping_list":
                return await self._tool_get_shopping_list()
            if name == "add_shopping_item":
                return await self._tool_add_shopping_item(
                    item=args.get("item") or "",
                    quantity=args.get("quantity") or "",
                    place=args.get("place") or "",
                )
            if name == "mark_shopping_done":
                return await self._tool_mark_shopping_done(item=args.get("item") or "")
            if name == "add_parcel":
                return await self._tool_add_parcel(
                    ttn=args.get("ttn") or "",
                    title=args.get("title") or "",
                    member=args.get("member") or "family",
                )
            if name == "refresh_parcel":
                return await self._tool_refresh_parcel(ttn=args.get("ttn") or "")
            if name == "mark_parcel_received":
                return await self._tool_mark_parcel_received(ttn=args.get("ttn") or "")
            if name == "get_recent_news":
                return await self._tool_get_recent_news(
                    limit=int(args.get("limit") or 15),
                    alerts_only=bool(args.get("alerts_only") or False),
                )
            if name == "list_news_channels":
                return await self._tool_list_news_channels()
            if name == "add_news_channel":
                return await self._tool_add_news_channel(
                    username=args.get("username") or "",
                    title=args.get("title") or "",
                    category=args.get("category") or "important",
                    region=args.get("region") or "",
                )
            if name == "remove_news_channel":
                return await self._tool_remove_news_channel(query=args.get("query") or "")
            if name == "remember_parking":
                return await self._tool_remember_parking(
                    location=args.get("location") or "",
                    notes=args.get("notes") or "",
                )
            if name == "get_parking":
                return await self._tool_get_parking()
            if name == "remember_fact":
                return await self._tool_remember_fact(
                    member=args.get("member") or "family",
                    key=args.get("key") or "",
                    value=args.get("value") or "",
                )
            if name == "get_facts":
                return await self._tool_get_facts(member=args.get("member") or "")
            if name == "get_inverter_forecast":
                return await self._tool_get_inverter_forecast()
            if name == "activate_blackout_mode":
                return await self._tool_activate_blackout_mode()
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

    async def _tool_create_calendar_event(
        self, title: str, start_iso: str, duration_min: int = 60,
        location: str = "", description: str = "",
    ) -> dict:
        if not title.strip() or not start_iso.strip():
            return {"error": "title and start_iso required"}
        try:
            from datetime import datetime, timedelta
            from src.integrations.gcalendar import CalendarClient
            if not self._settings.google_service_account_json or not self._settings.calendar_id:
                return {"error": "Календарь не настроен"}
            # Парсим start_iso; если без TZ — считаем что это время Одессы (+03:00)
            start = datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
            if start.tzinfo is None:
                from datetime import timezone
                start = start.replace(tzinfo=timezone(timedelta(hours=3)))
            end = start + timedelta(minutes=max(15, duration_min))
            cal = CalendarClient(self._settings.google_service_account_json, self._settings.calendar_id)
            ev = await cal.create_event(
                title=title, start=start, end=end,
                description=description, location=location,
            )
            return {
                "success": True,
                "event_id": getattr(ev, "event_id", None) or getattr(ev, "id", None),
                "title": getattr(ev, "title", title),
                "start_iso": start.isoformat(),
            }
        except Exception as e:
            log.exception("altron_calendar_create_failed", title=title)
            return {"error": str(e)[:200]}

    async def _tool_delete_calendar_event(self, event_id: str) -> dict:
        if not event_id.strip():
            return {"error": "event_id required"}
        try:
            from src.integrations.gcalendar import CalendarClient
            if not self._settings.google_service_account_json or not self._settings.calendar_id:
                return {"error": "Календарь не настроен"}
            cal = CalendarClient(self._settings.google_service_account_json, self._settings.calendar_id)
            ok = await cal.delete_event(event_id)
            return {"success": bool(ok)}
        except Exception as e:
            log.exception("altron_calendar_delete_failed", event_id=event_id)
            return {"error": str(e)[:200]}

    async def _tool_get_shopping_list(self) -> dict:
        try:
            from sqlalchemy import select
            from src.db.models import ShoppingItem
            async with self._memory._engine.connect() as conn:
                rows = list(await conn.execute(
                    select(ShoppingItem).where(ShoppingItem.done_at.is_(None))
                    .order_by(ShoppingItem.added_at.desc()).limit(50)
                ))
            items = []
            for r in rows:
                obj = r[0] if hasattr(r, "_mapping") else r
                items.append({
                    "id": getattr(obj, "id", None),
                    "item": getattr(obj, "item", ""),
                    "quantity": getattr(obj, "quantity", "") or "",
                    "place": getattr(obj, "place", "") or "",
                    "added_by": getattr(obj, "added_by", "") or "",
                    "added_at": getattr(obj, "added_at", "") or "",
                })
            return {"items": items, "total": len(items)}
        except Exception as e:
            log.exception("altron_shopping_read_failed")
            return {"error": str(e)[:200], "items": []}

    async def _tool_add_shopping_item(self, item: str, quantity: str = "", place: str = "") -> dict:
        if not item.strip():
            return {"error": "item required"}
        try:
            from sqlalchemy import insert
            from src.db.models import ShoppingItem
            from src.utils.time import iso_now
            async with self._memory._engine.begin() as conn:
                await conn.execute(insert(ShoppingItem).values(
                    item=item.strip(), quantity=quantity or None,
                    place=place or None, added_by="Альтрон",
                    added_at=iso_now(),
                ))
            return {"success": True, "item": item}
        except Exception as e:
            log.exception("altron_shopping_add_failed", item=item)
            return {"error": str(e)[:200]}

    async def _tool_mark_shopping_done(self, item: str) -> dict:
        if not item.strip():
            return {"error": "item required"}
        try:
            from sqlalchemy import select, update
            from src.db.models import ShoppingItem
            from src.utils.time import iso_now
            item_norm = item.strip().lower()
            async with self._memory._engine.begin() as conn:
                rows = list(await conn.execute(
                    select(ShoppingItem).where(ShoppingItem.done_at.is_(None))
                ))
                # Fuzzy: подстрочный матч
                target = None
                for r in rows:
                    obj = r[0] if hasattr(r, "_mapping") else r
                    if item_norm in (obj.item or "").lower() or (obj.item or "").lower() in item_norm:
                        target = obj
                        break
                if not target:
                    names = [(r[0].item if hasattr(r, "_mapping") else r.item) for r in rows]
                    return {
                        "success": False,
                        "reason": f"не нашёл «{item}» в списке",
                        "available": names[:20],
                    }
                await conn.execute(
                    update(ShoppingItem).where(ShoppingItem.id == target.id)
                    .values(done_at=iso_now())
                )
            return {"success": True, "item": target.item}
        except Exception as e:
            log.exception("altron_shopping_done_failed", item=item)
            return {"error": str(e)[:200]}

    async def _tool_add_parcel(self, ttn: str, title: str = "", member: str = "family") -> dict:
        """Добавить посылку по TTN. Подтягиваем статус из НП и сохраняем в Parcel."""
        import re
        clean = re.sub(r"[\s\-]", "", ttn or "")
        if not clean or not clean.isdigit():
            return {"error": "TTN должен состоять из цифр"}
        try:
            from sqlalchemy import insert, select
            from sqlalchemy import update as sql_update
            from src.db.models import Parcel
            from src.integrations.nova_poshta import NovaPoshtaClient
            from src.utils.time import iso_now
            client = NovaPoshtaClient.from_settings(self._settings)
            if not client:
                return {"error": "Новая Почта не настроена (NOVA_POSHTA_API_KEY)"}
            status = await client.track(clean)
            async with self._memory._engine.begin() as conn:
                existing = (await conn.execute(
                    select(Parcel).where(Parcel.ttn == clean)
                )).first()
                now = iso_now()
                values = {
                    "status": status.get("status"),
                    "status_code": str(status.get("status_code") or ""),
                    "city_from": status.get("city_from") or None,
                    "city_to": status.get("city_to") or None,
                    "warehouse": status.get("warehouse") or None,
                    "weight_kg": status.get("weight_kg"),
                    "cost_uah": status.get("total_uah"),
                    "scheduled_at": status.get("scheduled_at") or None,
                    "last_checked_at": now,
                }
                if any(k in (status.get("status") or "").lower()
                       for k in ("отримано", "получено", "delivered", "видано")):
                    values["delivered_at"] = now
                if existing:
                    if title:
                        values["title"] = title
                    if member:
                        values["member"] = member
                    await conn.execute(sql_update(Parcel).where(Parcel.ttn == clean).values(**values))
                else:
                    values.update({
                        "ttn": clean,
                        "title": title or clean,
                        "member": member or "family",
                        "created_at": now,
                    })
                    await conn.execute(insert(Parcel).values(**values))
            return {
                "success": True,
                "ttn": clean,
                "status": status.get("status"),
                "city_to": status.get("city_to"),
                "warehouse": status.get("warehouse"),
                "scheduled_at": status.get("scheduled_at"),
            }
        except Exception as e:
            log.exception("altron_add_parcel_failed", ttn=clean)
            return {"error": str(e)[:200]}

    async def _tool_refresh_parcel(self, ttn: str = "") -> dict:
        """Принудительно опросить НП: одну по TTN или все активные."""
        try:
            from sqlalchemy import select
            from sqlalchemy import update as sql_update
            from src.db.models import Parcel
            from src.integrations.nova_poshta import NovaPoshtaClient
            from src.utils.time import iso_now
            client = NovaPoshtaClient.from_settings(self._settings)
            if not client:
                return {"error": "Новая Почта не настроена"}
            async with self._memory._engine.connect() as conn:
                if ttn.strip():
                    import re
                    clean = re.sub(r"[\s\-]", "", ttn)
                    rows = list(await conn.execute(select(Parcel).where(Parcel.ttn == clean)))
                else:
                    rows = list(await conn.execute(
                        select(Parcel).where(Parcel.delivered_at.is_(None))
                    ))
            updated = 0
            for r in rows:
                obj = r[0] if hasattr(r, "_mapping") else r
                try:
                    status = await client.track(obj.ttn)
                    values = {
                        "status": status.get("status"),
                        "warehouse": status.get("warehouse") or None,
                        "last_checked_at": iso_now(),
                    }
                    if any(k in (status.get("status") or "").lower()
                           for k in ("отримано", "получено", "delivered", "видано")):
                        values["delivered_at"] = iso_now()
                    async with self._memory._engine.begin() as w:
                        await w.execute(sql_update(Parcel).where(Parcel.ttn == obj.ttn).values(**values))
                    updated += 1
                except Exception:
                    log.exception("altron_refresh_parcel_one_failed", ttn=obj.ttn)
            return {"success": True, "updated": updated}
        except Exception as e:
            log.exception("altron_refresh_parcel_failed")
            return {"error": str(e)[:200]}

    async def _tool_mark_parcel_received(self, ttn: str) -> dict:
        """Отметить посылку как забранную. TTN может быть подстрокой имени."""
        if not ttn.strip():
            return {"error": "ttn required"}
        try:
            import re
            from sqlalchemy import select
            from sqlalchemy import update as sql_update
            from src.db.models import Parcel
            from src.utils.time import iso_now
            clean = re.sub(r"[\s\-]", "", ttn)
            async with self._memory._engine.connect() as conn:
                rows = list(await conn.execute(
                    select(Parcel).where(Parcel.delivered_at.is_(None))
                ))
            target = None
            for r in rows:
                obj = r[0] if hasattr(r, "_mapping") else r
                if clean.isdigit() and clean in (obj.ttn or ""):
                    target = obj
                    break
                title_norm = (obj.title or "").lower()
                if ttn.lower() in title_norm or title_norm in ttn.lower():
                    target = obj
                    break
            if not target:
                names = []
                for r in rows:
                    obj = r[0] if hasattr(r, "_mapping") else r
                    names.append(f"{obj.title or obj.ttn}")
                return {
                    "success": False,
                    "reason": f"не нашёл активную посылку по «{ttn}»",
                    "available": names[:20],
                }
            async with self._memory._engine.begin() as conn:
                await conn.execute(
                    sql_update(Parcel).where(Parcel.ttn == target.ttn)
                    .values(delivered_at=iso_now())
                )
            return {"success": True, "ttn": target.ttn, "title": target.title}
        except Exception as e:
            log.exception("altron_mark_parcel_received_failed", ttn=ttn)
            return {"error": str(e)[:200]}

    async def _tool_get_recent_news(self, limit: int = 15, alerts_only: bool = False) -> dict:
        """Прочитать последние посты из мониторинга."""
        try:
            from sqlalchemy import select
            from src.db.models import NewsPost, NewsChannel
            async with self._memory._engine.connect() as conn:
                q = select(NewsPost)
                if alerts_only:
                    q = q.where(NewsPost.is_alert == 1)
                q = q.order_by(NewsPost.date.desc()).limit(max(1, min(50, limit)))
                rows = list(await conn.execute(q))
                # Загружаем каналы для читаемых имён
                chans_rows = list(await conn.execute(select(NewsChannel)))
                chans = {}
                for cr in chans_rows:
                    obj = cr[0] if hasattr(cr, "_mapping") else cr
                    chans[obj.channel_id] = obj.title or (obj.username or f"ch{obj.channel_id}")
            posts = []
            for r in rows:
                obj = r[0] if hasattr(r, "_mapping") else r
                posts.append({
                    "channel": chans.get(obj.channel_id, f"ch{obj.channel_id}"),
                    "date": obj.date,
                    "is_alert": bool(obj.is_alert),
                    "region": obj.alert_region or "",
                    "text": (obj.text or "")[:400],
                })
            return {"posts": posts, "total": len(posts)}
        except Exception as e:
            log.exception("altron_get_news_failed")
            return {"error": str(e)[:200], "posts": []}

    async def _tool_list_news_channels(self) -> dict:
        try:
            from sqlalchemy import select
            from src.db.models import NewsChannel
            async with self._memory._engine.connect() as conn:
                rows = list(await conn.execute(
                    select(NewsChannel).where(NewsChannel.active == 1)
                ))
            channels = []
            for r in rows:
                obj = r[0] if hasattr(r, "_mapping") else r
                channels.append({
                    "channel_id": obj.channel_id,
                    "username": obj.username or "",
                    "title": obj.title or "",
                    "category": obj.category or "",
                    "region": obj.region or "",
                    "mode": obj.mode or "silent",
                })
            return {"channels": channels, "total": len(channels)}
        except Exception as e:
            log.exception("altron_list_channels_failed")
            return {"error": str(e)[:200], "channels": []}

    async def _tool_add_news_channel(
        self, username: str, title: str = "",
        category: str = "important", region: str = "",
    ) -> dict:
        """Добавить канал в мониторинг Дозорного. Резолвим channel_id через Telethon userbot."""
        import re
        clean = re.sub(r"https?://t\.me/|@", "", (username or "").strip()).strip("/ ")
        if not clean:
            return {"error": "username required"}
        try:
            from sqlalchemy import insert, select
            from sqlalchemy import update as sql_update
            from sqlalchemy.dialects.sqlite import insert as _sqlite_insert
            from src.db.models import NewsChannel
            from src.utils.time import iso_now
            # channel_id узнать без Telethon сложно; сохраняем через хэш имени
            # как временный ключ. NewsIngestor подхватит правильный id при
            # следующем сообщении. Если username есть — этого хватит.
            fake_id = abs(hash(clean.lower())) % (10 ** 9)
            async with self._memory._engine.begin() as conn:
                stmt = _sqlite_insert(NewsChannel).values(
                    channel_id=fake_id, username=clean, title=title or clean,
                    category=category, region=region or None,
                    mode="silent", added_at=iso_now(), active=1,
                )
                stmt = stmt.on_conflict_do_update(
                    index_elements=["channel_id"],
                    set_={
                        "username": clean, "title": title or clean,
                        "category": category, "region": region or None, "active": 1,
                    },
                )
                await conn.execute(stmt)
            return {
                "success": True,
                "note": "Канал добавлен. Полный id подтянется автоматом после первого сообщения из него.",
                "username": clean,
                "category": category,
            }
        except Exception as e:
            log.exception("altron_add_channel_failed", username=username)
            return {"error": str(e)[:200]}

    async def _tool_remove_news_channel(self, query: str) -> dict:
        if not query.strip():
            return {"error": "query required"}
        try:
            import re
            from sqlalchemy import select
            from sqlalchemy import update as sql_update
            from src.db.models import NewsChannel
            q_norm = re.sub(r"https?://t\.me/|@", "", query.strip()).lower()
            async with self._memory._engine.connect() as conn:
                rows = list(await conn.execute(
                    select(NewsChannel).where(NewsChannel.active == 1)
                ))
            target = None
            for r in rows:
                obj = r[0] if hasattr(r, "_mapping") else r
                username_n = (obj.username or "").lower()
                title_n = (obj.title or "").lower()
                if q_norm in username_n or q_norm in title_n:
                    target = obj
                    break
            if not target:
                names = [((r[0].username or r[0].title) if hasattr(r, "_mapping") else (r.username or r.title)) for r in rows]
                return {
                    "success": False,
                    "reason": f"не нашёл канал по «{query}»",
                    "available": names[:20],
                }
            async with self._memory._engine.begin() as conn:
                await conn.execute(
                    sql_update(NewsChannel).where(NewsChannel.channel_id == target.channel_id)
                    .values(active=0)
                )
            return {"success": True, "removed": target.title or target.username}
        except Exception as e:
            log.exception("altron_remove_channel_failed", query=query)
            return {"error": str(e)[:200]}

    async def _tool_remember_parking(self, location: str, notes: str = "") -> dict:
        """Запомнить где припарковался — через FamilyFact (member=family, key=парковка)."""
        if not location.strip():
            return {"error": "location required"}
        return await self._upsert_fact("family", "парковка", location + ((" · " + notes) if notes else ""))

    async def _tool_get_parking(self) -> dict:
        try:
            from sqlalchemy import select
            from src.db.models import FamilyFact
            async with self._memory._engine.connect() as conn:
                rows = list(await conn.execute(
                    select(FamilyFact).where(FamilyFact.key == "парковка")
                    .order_by(FamilyFact.updated_at.desc()).limit(1)
                ))
            if not rows:
                return {"parked": False, "note": "не помню где машина"}
            obj = rows[0][0] if hasattr(rows[0], "_mapping") else rows[0]
            return {
                "parked": True,
                "location": obj.value,
                "when": obj.updated_at,
            }
        except Exception as e:
            log.exception("altron_get_parking_failed")
            return {"error": str(e)[:200]}

    async def _tool_remember_fact(self, member: str, key: str, value: str) -> dict:
        if not (member and key and value):
            return {"error": "member, key, value required"}
        return await self._upsert_fact(member.lower(), key, value)

    async def _upsert_fact(self, member: str, key: str, value: str) -> dict:
        try:
            from sqlalchemy import select, insert
            from sqlalchemy import update as sql_update
            from src.db.models import FamilyFact
            from src.utils.time import iso_now
            now = iso_now()
            async with self._memory._engine.begin() as conn:
                existing = list(await conn.execute(
                    select(FamilyFact).where(
                        FamilyFact.member == member,
                        FamilyFact.key == key,
                    )
                ))
                if existing:
                    obj = existing[0][0] if hasattr(existing[0], "_mapping") else existing[0]
                    await conn.execute(
                        sql_update(FamilyFact).where(FamilyFact.id == obj.id)
                        .values(value=value, source="altron", updated_at=now)
                    )
                    fact_id = obj.id
                else:
                    res = await conn.execute(insert(FamilyFact).values(
                        member=member, key=key, value=value,
                        source="altron", created_at=now, updated_at=now,
                    ))
                    fact_id = res.inserted_primary_key[0] if res.inserted_primary_key else None
            return {"success": True, "id": fact_id, "member": member, "key": key, "value": value}
        except Exception as e:
            log.exception("altron_upsert_fact_failed", member=member, key=key)
            return {"error": str(e)[:200]}

    async def _tool_get_facts(self, member: str = "") -> dict:
        try:
            from sqlalchemy import select
            from src.db.models import FamilyFact
            async with self._memory._engine.connect() as conn:
                q = select(FamilyFact)
                if member.strip():
                    q = q.where(FamilyFact.member == member.strip().lower())
                q = q.order_by(FamilyFact.member, FamilyFact.key)
                rows = list(await conn.execute(q))
            facts = []
            for r in rows:
                obj = r[0] if hasattr(r, "_mapping") else r
                facts.append({
                    "member": obj.member,
                    "key": obj.key,
                    "value": obj.value,
                    "updated_at": obj.updated_at,
                })
            return {"facts": facts, "total": len(facts)}
        except Exception as e:
            log.exception("altron_get_facts_failed")
            return {"error": str(e)[:200], "facts": []}

    async def _tool_get_inverter_forecast(self) -> dict:
        """Прогноз автономии: время до достижения резервного SOC."""
        try:
            from src.integrations.luxcloud import LuxCloudClient
            lux = LuxCloudClient.from_settings(self._settings)
            if not lux:
                return {"error": "инвертор не настроен"}
            rt = await lux.runtime()
            soc = rt.get("battery_pct") or rt.get("soc")
            load_w = rt.get("home_consumption_w") or rt.get("load_w") or 0
            discharge_w = rt.get("battery_discharge_w") or 0
            charge_w = rt.get("battery_charge_w") or 0
            solar_w = rt.get("pv_total_w") or 0
            capacity_wh = getattr(self._settings, "battery_capacity_wh", 5184)
            reserve_pct = getattr(self._settings, "battery_reserve_pct", 20)
            if soc is None:
                return {"error": "SoC не получен от инвертора"}

            usable_wh = capacity_wh * (max(0, soc - reserve_pct) / 100.0)
            net_discharge_w = max(0, discharge_w - charge_w)

            # Если сеть работает и батарея не разряжается — сети хватит бесконечно
            grid_import = rt.get("grid_import_w") or 0
            if grid_import > 20 and discharge_w < 50:
                return {
                    "soc_pct": soc,
                    "on_grid": True,
                    "note": "работает от сети, батарея не тратится",
                    "load_w": load_w,
                    "solar_w": solar_w,
                }

            if net_discharge_w < 20:
                return {
                    "soc_pct": soc,
                    "on_grid": False,
                    "note": "почти не разряжается — солнце покрывает нагрузку",
                    "load_w": load_w,
                    "solar_w": solar_w,
                }

            hours_left = usable_wh / net_discharge_w if net_discharge_w else 0
            h = int(hours_left)
            m = int((hours_left - h) * 60)
            return {
                "soc_pct": soc,
                "reserve_pct": reserve_pct,
                "load_w": load_w,
                "net_discharge_w": net_discharge_w,
                "solar_w": solar_w,
                "usable_wh": round(usable_wh),
                "hours_left": round(hours_left, 2),
                "human": f"{h}ч {m:02d}м до резерва {reserve_pct}%",
            }
        except Exception as e:
            log.exception("altron_inverter_forecast_failed")
            return {"error": str(e)[:200]}

    async def _tool_activate_blackout_mode(self) -> dict:
        """Аварийный режим: гонит сцены выключения + отрубает тяжёлые розетки."""
        results: list[dict] = []
        try:
            from src.integrations.tuya import TuyaClient
            tuya = TuyaClient.from_settings(self._settings)
            if not tuya:
                return {"error": "Tuya не настроен"}

            # 1. Пробуем найти сцену «блэкаут» / «свет выкл везде» / «эконом»
            candidates = ["Блэкаут", "Свет выкл везде", "Эконом", "Выкл везде", "Вырубили свет", "Отключили свет"]
            scene_hit = None
            for q in candidates:
                sc = await tuya.find_scene(q)
                if sc:
                    await tuya.run_scene(sc.get("id"))
                    scene_hit = sc.get("name")
                    results.append({"scene": sc.get("name"), "success": True})
                    break

            # 2. Выключаем большие розетки: бойлер, ТВ
            for dev_name in ("бойлер", "телевизор"):
                try:
                    r = await tuya.control(dev_name, "off")
                    results.append({"device": dev_name, "result": r})
                except Exception as e:
                    results.append({"device": dev_name, "error": str(e)[:100]})

            return {
                "success": True,
                "scene_used": scene_hit,
                "actions": results,
                "note": "Аварийный режим активирован. Бойлер и ТВ отключены. Проверь холодильник и модем чтоб не разряжали батарею.",
            }
        except Exception as e:
            log.exception("altron_blackout_failed")
            return {"error": str(e)[:200], "actions": results}

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
