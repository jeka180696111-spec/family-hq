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

import asyncio
import json
from typing import Any

import structlog

from src.utils.time import now_kyiv

log = structlog.get_logger()


_SYSTEM_PROMPT = """Ты Альтрон — семейный ИИ штаба Евгения и Марины (Одесса). Сын Матвей род. 03.12.2025.
Ты как Джарвис у Старка: спокойный, лаконичный, умный, чуть-чуть ироничный.
Партнёр по разговору, не безмолвный исполнитель.

ТОН
- Коротко, живой русский, без канцелярита и «Я готов помочь».
- Обращайся к пользователю на «ты», по имени если знаешь.
- Мягкая ирония уместна, но не глумись и не преувеличивай.
- Не знаешь — говори «не знаю». Не выдумывай факты.

ИНИЦИАТИВА (главное отличие от простого бота)
1. Если запрос неоднозначный — задай ОДИН короткий уточняющий вопрос.
   Но если контекст очевиден — сразу делай.
2. АВТО-FOLLOW-THROUGH: для типовых кейсов НЕ переспрашивай — сделай сразу
   второй логичный шаг, сообщи одной строкой. Пользователь может отменить
   если не надо. Список кейсов:
   - record_doctor_visit(«АКДС») → сразу create_calendar_event на дату
     +30 дней с title=«Ревакцинация АКДС». Ответ: «Записал АКДС.
     Ревакцинация 25.10 — уже в календаре».
   - record_doctor_visit(«Педиатр плановый») → set_reminder за 1 день
     до следующего планового приёма (если next_due указан).
   - mark_shopping_done делает список <3 пунктов → в ответе упомяни
     «В списке осталось 2 пункта: X, Y».
   - record_baby_event(kind=symptom, event=Температура, amount≥38) →
     сразу add_shopping_item(жаропонижающее) если нет в списке, И
     напомни дозу через get_medication_dose.
   - create_calendar_event на завтра до 10:00 → set_reminder за 30 мин.
   - remember_fact(marina, «аллергия», X) → сразу add_shopping_item НЕ
     нужен, но упомяни «учту при покупках».
3. Мягкие предложения — вместо просьбы напечатать, ЗОВИ ask_with_buttons
   с 2-3 вариантами. Пользователь тапнет — быстрее чем печатать.
   Примеры:
   - ask_with_buttons("Матвей уснул в 21:15. Приглушить свет?",
     ["Да, детская", "Не надо", "Вырубить везде"])
   - ask_with_buttons("Свет вырубили. Батарея 89%. Активировать блэкаут?",
     ["Да, блэкаут", "Не надо"])
   - ask_with_buttons("В списке 8 пунктов. Заказать доставку?",
     ["Glovo", "Bolt Food", "Не сейчас"])
4. Замечай паттерны и предупреждай:
   - Если Матвей не ел > 4 часов — упомяни это.
   - Тревога длится > 30 мин и много прилётов — предложи проверить окна.
   - Инвертор < 30% и нет сети → сам предложи блэкаут.
5. Проблема без чёткого решения — уточни симптомы, потом дай 2-3
   варианта с трейд-оффами. Коротко.

КОМАНДЫ vs ВОПРОСЫ про Матвея
- ВОПРОСЫ («сколько не спит?», «когда проснулся?», «давно спит?»,
  «что делает?», «когда ел?») → get_baby_state / get_baby_diary. НИКОГДА
  не зови record_baby_event на вопрос.
- ФАКТЫ («уснул», «проснулся», «поел», «покакал» + опц. время) →
  record_baby_event с параметром at="HH:MM" если время указано.

СОСТАВНЫЕ ВОПРОСЫ — ЗОВИ НЕСКОЛЬКО ТУЛОВ В ОДНОМ ОТВЕТЕ
Когда вопрос широкий, распадается на 2-3 части — ВЫЗЫВАЙ параллельно.
Пример: «завтра к педиатру, что подготовить?»
  → parallel: prepare_doctor_visit(matvey) + get_calendar_today
             + get_baby_state + get_feeding_summary
  → потом одним связным ответом: ключевые симптомы недели / вес / прикорм /
    время визита / вопросы врачу. НЕ по одному тулу за раз.

Ещё примеры составных:
- «как ситуация в целом?» → get_active_alert + get_inverter_state
  + get_baby_state + get_calendar_today
- «покажи полный статус» → get_system_status + get_railway_status
  + list_open_prs
- «нам куда съездить?» → get_time_and_weather + get_calendar_today
  + get_facts (проверить кто чего не любит)

Быстрые одиночные маппинги (простые случаи):
- «температура 37.2» → record_baby_event(kind=symptom, event=Температура, amount=37.2)
- «попробовал банан» → record_feeding
- «перевернулся» / «сел» → record_milestone
- «АКДС» / «педиатр» → record_doctor_visit
- «завтра в 10 к врачу» → create_calendar_event
- «купи X» / «купил X» → add_shopping_item / mark_shopping_done
- «свет ярко в кухне» → run_scene(query=«кухня ярко»)
- «бойлер выкл» → control_socket
- «где машина?» / «припарковался...» → get_parking / remember_parking
- «найди X» → web_search; «что писали про Y?» → search_telegram_posts

Все возможности — только через tools в API. Не придумывай tools которых нет.
"""


_WRITE_TOOLS = frozenset({
    "run_scene", "control_socket",
    "record_baby_event", "record_milestone", "record_doctor_visit", "record_feeding",
    "create_calendar_event", "delete_calendar_event",
    "add_shopping_item", "mark_shopping_done",
    "add_parcel", "refresh_parcel", "mark_parcel_received",
    "add_news_channel", "remove_news_channel",
    "remember_parking", "remember_fact",
    "activate_blackout_mode",
    "log_health_event", "log_parent_sleep",
    "write_cooking_note",
    "log_fuel",
    "toggle_automation", "delete_automation",
    "set_reminder",
    "wiki_set", "wiki_delete",
    "speak_reply",
    "ask_with_buttons",
    "set_quiet_hours",
    "set_recurring_reminder", "delete_recurring_reminder",
    "track_stock", "record_stock_purchase", "untrack_stock",
    "remember", "set_baby_routine",
    "set_home_location",
})

# Только эти инструменты уходят по fast-path (мгновенный ответ без второго
# turn LLM). Всё остальное — идёт через LLM, чтобы Альтрон мог добавить
# инициативу («Матвей уснул. Приглушить свет?»). Разница цены — 2-4 сек,
# зато ассистент реально ведёт разговор.
_FAST_PATH_TOOLS = frozenset({
    "run_scene", "control_socket",
    "activate_blackout_mode",
    "toggle_automation", "delete_automation",
})


class _ResilientLLM:
    """Обёртка над Gemini с fallback на Claude. Никаких схемных изменений
    для агента — просто пересылает calls с ретраем на альтернативный API.

    Ключ решения: определяем «quota-подобные» ошибки по сообщению
    RuntimeError'а. Если поймали — делаем ту же операцию через Claude,
    возвращаем результат в Anthropic-совместимом виде (у обеих моделей
    он одинаковый — duck-typed message с .content блоками)."""

    QUOTA_MARKERS = ("429", "quota", "all keys", "rate limit", "all keys×models failed")

    def __init__(self, primary: Any, fallback: Any, settings: Any) -> None:
        self._primary = primary
        self._fallback = fallback
        self._settings = settings

    def _is_quota_err(self, exc: Exception) -> bool:
        msg = str(exc).lower()
        return any(m in msg for m in self.QUOTA_MARKERS)

    async def complete(self, **kwargs) -> str:
        try:
            return await self._primary.complete(**kwargs)
        except Exception as e:
            if not self._is_quota_err(e):
                raise
            log.warning("altron_llm_fallback_claude_complete", err=str(e)[:150])
            model = getattr(self._settings, "model_cheap", "") or "claude-haiku-4-5-20251001"
            return await self._fallback.complete(
                model=model, system=kwargs.get("system", ""),
                messages=kwargs.get("messages") or [],
                max_tokens=kwargs.get("max_tokens", 1024),
            )

    async def complete_with_tools(self, **kwargs) -> Any:
        try:
            return await self._primary.complete_with_tools(**kwargs)
        except Exception as e:
            if not self._is_quota_err(e):
                raise
            log.warning("altron_llm_fallback_claude_tools", err=str(e)[:150])
            model = getattr(self._settings, "model_cheap", "") or "claude-haiku-4-5-20251001"
            return await self._fallback.complete_with_tools(
                model=model, system=kwargs.get("system", ""),
                messages=kwargs.get("messages") or [],
                tools=kwargs.get("tools") or [],
                max_tokens=kwargs.get("max_tokens", 2048),
            )

    async def complete_stream(self, **kwargs):
        """Проксирует streaming. Если Gemini квоту исчерпал —
        Claude тоже поддерживает stream, но интерфейс другой; для
        простоты fallback просто отдаёт весь текст одним чанком."""
        try:
            async for chunk in self._primary.complete_stream(**kwargs):
                yield chunk
            return
        except Exception as e:
            if not self._is_quota_err(e):
                raise
        # Fallback — один чанк через Claude non-stream
        try:
            model = getattr(self._settings, "model_cheap", "") or "claude-haiku-4-5-20251001"
            text = await self._fallback.complete(
                model=model, system=kwargs.get("system", ""),
                messages=kwargs.get("messages") or [],
                max_tokens=kwargs.get("max_tokens", 1024),
            )
            yield text or ""
        except Exception:
            log.exception("altron_llm_fallback_stream_failed")

    # Пробросим оставшиеся методы (vision, transcribe, etc) прямо в primary
    def __getattr__(self, item):
        return getattr(self._primary, item)


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
        claude_client: Any = None,
    ) -> None:
        self._memory = memory
        # Обёртка: primary=Gemini (дешевле), fallback=Claude Haiku.
        # Если Gemini даёт квоту-ошибку (429 / all keys failed), автоматически
        # ретраит запрос через Claude. Пользователь не видит разницы.
        self._gemini = _ResilientLLM(
            primary=gemini_client, fallback=claude_client,
            settings=settings,
        ) if claude_client is not None else gemini_client
        self._settings = settings
        # История разговора по chat_id. In-memory; при перезапуске обнуляется —
        # для Этапа 2 нормально. Позже переедет в БД.
        self._history: dict[int, list[dict]] = {}
        self._HISTORY_LIMIT = 20  # сообщений (user + assistant), суммарно
        # Маркер что Альтрон сам недавно записал переход сна ребёнка —
        # чтобы фоновый baby-watcher в AltronBot не дублировал уведомление.
        # Ключи: "asleep", "awake". Значение — unix timestamp момента записи.
        self._recent_baby_transition: dict[str, float] = {}

    @staticmethod
    def _synth_from_results(results: list[dict]) -> str:
        """Собрать финальный ответ прямо из свежих результатов write-tools —
        чтобы не гонять ещё один turn Gemini после успешной команды."""
        parts: list[str] = []
        for res in results:
            if not isinstance(res, dict):
                continue
            if res.get("success") is True:
                nm = (
                    res.get("scene_name")
                    or res.get("device")
                    or res.get("title")
                    or res.get("milestone")
                    or res.get("product")
                    or res.get("event")
                )
                parts.append(f"Готово: {nm}." if nm else "Готово.")
            elif res.get("reason"):
                variants = res.get("available_scenes") or res.get("available") or []
                if variants:
                    parts.append(
                        f"Не нашёл: {res['reason']}. Есть: "
                        + ", ".join(str(v) for v in variants[:8]) + "."
                    )
                else:
                    parts.append(f"Не получилось: {res['reason']}")
            elif res.get("error"):
                parts.append(f"Не смог: {str(res['error'])[:120]}")
            elif res.get("note"):
                parts.append(str(res["note"])[:200])
            else:
                # Успех без явного success:True (напр. record_baby_event
                # возвращает {"row_id": ..., "when": ...})
                parts.append("Готово.")
        return " ".join(parts).strip()

    @staticmethod
    def _synth_from_tool_results(messages: list[dict]) -> str:
        """Собрать вменяемый ответ из последних tool_results в messages —
        когда Gemini на force_final вернул пустой text. Ищем success/error/note
        поля и склеиваем короткий человеческий отчёт.
        """
        # Найти последний user turn с tool_result-блоками
        last_results: list[dict] = []
        for m in reversed(messages):
            content = m.get("content") if isinstance(m, dict) else None
            if not isinstance(content, list):
                continue
            block_types = {b.get("type") for b in content if isinstance(b, dict)}
            if "tool_result" in block_types:
                for b in content:
                    if isinstance(b, dict) and b.get("type") == "tool_result":
                        raw = b.get("content", "")
                        try:
                            last_results.append(json.loads(raw))
                        except Exception:
                            last_results.append({"note": str(raw)[:200]})
                break
        if not last_results:
            return ""
        parts: list[str] = []
        for res in last_results:
            if not isinstance(res, dict):
                continue
            if res.get("success") is True:
                nm = res.get("scene_name") or res.get("device") or res.get("title") or "Готово"
                parts.append(f"Готово: {nm}.")
            elif res.get("error"):
                parts.append(f"Не смог: {str(res['error'])[:120]}")
            elif res.get("reason"):
                variants = res.get("available_scenes") or res.get("available") or []
                if variants:
                    parts.append(
                        f"Не нашёл: {res['reason']}. Есть: {', '.join(str(v) for v in variants[:8])}."
                    )
                else:
                    parts.append(f"Не получилось: {res['reason']}")
            elif res.get("note"):
                parts.append(str(res["note"])[:200])
        return " ".join(parts).strip()

    def _append_history(self, chat_id: int, role: str, content: Any) -> None:
        h = self._history.setdefault(chat_id, [])
        h.append({"role": role, "content": content})
        if len(h) > self._HISTORY_LIMIT * 2:
            del h[: len(h) - self._HISTORY_LIMIT]
        # Персистим в БД чтобы переживать рестарты. Не блокирует ответ:
        # ошибки логируем и продолжаем.
        try:
            asyncio.create_task(self._persist_message(chat_id, role, content))
        except Exception:
            log.exception("altron_persist_task_failed")

    async def _persist_message(self, chat_id: int, role: str, content: Any) -> None:
        try:
            from sqlalchemy import insert
            from src.db.models import AltronMessage
            from src.utils.time import iso_now
            content_json = json.dumps(content, ensure_ascii=False, default=str)
            async with self._memory._engine.begin() as conn:
                await conn.execute(insert(AltronMessage).values(
                    chat_id=chat_id, role=role,
                    content_json=content_json, created_at=iso_now(),
                ))
        except Exception:
            log.exception("altron_persist_message_failed")

    def _get_history(self, chat_id: int) -> list[dict]:
        return list(self._history.get(chat_id, []))

    async def load_history_from_db(self, chat_id: int) -> None:
        """Подтянуть последние N сообщений из БД в память. Вызывается лениво
        когда для chat_id ещё нет истории (например после рестарта)."""
        if chat_id in self._history:
            return
        try:
            from sqlalchemy import select
            from src.db.models import AltronMessage
            async with self._memory._engine.connect() as conn:
                rows = list(await conn.execute(
                    select(AltronMessage)
                    .where(AltronMessage.chat_id == chat_id)
                    .order_by(AltronMessage.id.desc())
                    .limit(self._HISTORY_LIMIT)
                ))
            rows.reverse()
            hist: list[dict] = []
            for r in rows:
                try:
                    content = json.loads(r.content_json)
                except Exception:
                    content = r.content_json
                hist.append({"role": r.role, "content": content})
            self._history[chat_id] = hist
            log.info("altron_history_loaded", chat_id=chat_id, count=len(hist))
        except Exception:
            log.exception("altron_history_load_failed", chat_id=chat_id)
            self._history[chat_id] = []

    def reset_history(self, chat_id: int) -> None:
        self._history[chat_id] = []
        # Асинхронно очищаем и в БД
        async def _clear():
            try:
                from sqlalchemy import delete
                from src.db.models import AltronMessage
                async with self._memory._engine.begin() as conn:
                    await conn.execute(
                        delete(AltronMessage).where(AltronMessage.chat_id == chat_id)
                    )
            except Exception:
                log.exception("altron_history_clear_failed", chat_id=chat_id)
        try:
            asyncio.create_task(_clear())
        except Exception:
            pass

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
                        "at": {
                            "type": "string",
                            "description": (
                                "Опционально: когда событие произошло. Формат HH:MM (сегодня в это время) "
                                "или полный ISO с датой и TZ. Если пользователь говорит «в 7:30 проснулся» — "
                                "передай at=\"07:30\". Без параметра берём текущее время."
                            ),
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
                "name": "set_home_location",
                "description": (
                    "Сохранить домашние координаты (широта, долгота). Альтрон будет "
                    "определять когда пользователь дома, а когда в отъезде. "
                    "Триггеры: «дом здесь», «сохрани домашние координаты»."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "lat": {"type": "number"},
                        "lon": {"type": "number"},
                    },
                    "required": ["lat", "lon"],
                },
            },
            {
                "name": "get_location_status",
                "description": (
                    "Где я сейчас относительно дома: дома / рядом / далеко, дистанция в км. "
                    "Триггеры: «где я?», «далеко ли от дома?»."
                ),
                "input_schema": {"type": "object", "properties": {}, "required": []},
            },
            {
                "name": "set_baby_routine",
                "description": (
                    "Настроить типичное расписание Матвея (когда обычно ложится, встаёт). "
                    "Альтрон будет предлагать заранее: за 20 мин до bedtime — «приглушить свет?». "
                    "Триггеры: «Матвей обычно ложится в 21:00», «просыпается в 7:30», "
                    "«режим сна 21-07»."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "bedtime": {"type": "string", "description": "HH:MM когда обычно ложится (напр. 21:00)"},
                        "wake_time": {"type": "string", "description": "HH:MM когда обычно встаёт (напр. 07:30)"},
                    },
                    "required": [],
                },
            },
            {
                "name": "remember",
                "description": (
                    "Запомнить факт/решение/предпочтение НАВСЕГДА в долговременную память "
                    "с семантическим поиском. Используй когда пользователь говорит «запомни:», "
                    "«не забудь что...», «на будущее». Также САМ вызывай когда в разговоре "
                    "звучит важное решение («договорились не давать красную рыбу до года») "
                    "или устойчивое предпочтение («Марина не любит мяту»)."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "kind": {
                            "type": "string",
                            "enum": ["decision", "preference", "fact", "event"],
                            "description": "decision=решение, preference=вкус/привычка, fact=факт, event=прошлое событие",
                        },
                        "content": {"type": "string", "description": "Что запомнить, одним предложением"},
                    },
                    "required": ["kind", "content"],
                },
            },
            {
                "name": "recall",
                "description": (
                    "Семантический поиск по долговременной памяти. Возвращает топ-5 "
                    "релевантных заметок. Триггеры: «мы решали про X?», «что мы говорили "
                    "про Y?», «помнишь как...». Также вызывай ПЕРЕД ответом когда вопрос "
                    "явно ссылается на прошлое."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "limit": {"type": "integer", "description": "Топ N (default 5)"},
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "track_stock",
                "description": (
                    "Начать отслеживать регулярную покупку (памперсы, смесь, кофе). "
                    "Триггеры: «отслеживай памперсы, покупаем раз в 2 недели», "
                    "«следи за смесью каждые 5 дней»."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Название товара"},
                        "frequency_days": {"type": "integer", "description": "Как часто покупаем (дни)"},
                        "typical_qty": {"type": "string", "description": "Опц.: обычная упаковка (напр. «пачка 100 шт»)"},
                    },
                    "required": ["name", "frequency_days"],
                },
            },
            {
                "name": "record_stock_purchase",
                "description": (
                    "Зафиксировать покупку отслеживаемого товара. Триггеры: "
                    "«купил памперсы», «взял смесь». Обновит last_purchased_at."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                    },
                    "required": ["name"],
                },
            },
            {
                "name": "check_stock",
                "description": (
                    "Статус отслеживаемых товаров: сколько дней прошло, до истечения. "
                    "Триггеры: «что скоро кончится?», «что купить?»."
                ),
                "input_schema": {"type": "object", "properties": {}, "required": []},
            },
            {
                "name": "untrack_stock",
                "description": "Убрать товар из отслеживания.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                    },
                    "required": ["name"],
                },
            },
            {
                "name": "set_recurring_reminder",
                "description": (
                    "Поставить повторяющееся напоминание. Триггеры: «каждый день в 9 "
                    "витамин D», «по понедельникам мусор», «25 числа плата за интернет». "
                    "Формат schedule: 'daily HH:MM' / 'weekly Mon HH:MM' / 'monthly DD HH:MM'. "
                    "Дни недели: Mon/Tue/Wed/Thu/Fri/Sat/Sun."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Уникальное имя (напр. «Витамин D»)"},
                        "schedule": {"type": "string", "description": "'daily 09:00' / 'weekly Mon 08:00' / 'monthly 25 09:00'"},
                        "text": {"type": "string", "description": "Что напомнить"},
                    },
                    "required": ["name", "schedule", "text"],
                },
            },
            {
                "name": "list_recurring_reminders",
                "description": "Список повторяющихся напоминаний.",
                "input_schema": {"type": "object", "properties": {}, "required": []},
            },
            {
                "name": "delete_recurring_reminder",
                "description": "Удалить повторяющееся напоминание по имени.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                    },
                    "required": ["name"],
                },
            },
            {
                "name": "set_quiet_hours",
                "description": (
                    "Настроить тихие часы Альтрона — окно когда все уведомления, "
                    "кроме реальной критики (тревога, свет), идут без звука. "
                    "Триггеры: «тихие часы с 22 до 7», «поставь режим тишины», "
                    "«отключи тихие часы»."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "from_time": {"type": "string", "description": "HH:MM начало (напр. 22:00)"},
                        "to_time": {"type": "string", "description": "HH:MM конец (напр. 07:00)"},
                        "enabled": {"type": "boolean", "description": "true=включить, false=отключить полностью"},
                    },
                    "required": [],
                },
            },
            {
                "name": "ask_with_buttons",
                "description": (
                    "Отправить сообщение с inline-кнопками вместо просьбы напечатать ответ. "
                    "Пользователь тапнет — Альтрон получит текст кнопки как следующее сообщение. "
                    "Используй когда предлагаешь варианты: «Приглушить свет?» + [Да]/[Нет], "
                    "«Какую сцену?» + [Спальня ярко]/[Кухня ночь]/[Отмена]. "
                    "НЕ используй если пользователю проще ответить свободным текстом."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "Вопрос/сообщение"},
                        "options": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Варианты кнопок (2-6). Короткие — до 32 симв.",
                        },
                    },
                    "required": ["text", "options"],
                },
            },
            {
                "name": "speak_reply",
                "description": (
                    "Отправить ответ ГОЛОСОМ (мужской голос) — только когда пользователь "
                    "явно просит: «скажи голосом», «озвучь», «прочитай вслух», «ответь голосом». "
                    "НЕ используй по своей инициативе. Текст-параметр — то что должно "
                    "прозвучать (короткое, до 500 симв)."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "Что произнести"},
                    },
                    "required": ["text"],
                },
            },
            {
                "name": "web_search",
                "description": (
                    "Общий поиск в интернете (DuckDuckGo). Возвращает 5 ссылок. "
                    "Триггеры: «найди в интернете X», «что там про Y?», «поищи новости про Z», "
                    "«гугли X». Отличается от search_recipe — здесь запросы любые."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Свободный запрос"},
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "search_telegram_posts",
                "description": (
                    "Поиск по постам мониторинга Дозорного (NewsPost) — свежие "
                    "новости из отслеживаемых Telegram-каналов. "
                    "Триггеры: «что писали про Одессу?», «есть посты про удары?», "
                    "«что там за прилёт?», «поищи в мониторинге про X»."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Ключевые слова"},
                        "hours_back": {"type": "integer", "description": "За сколько часов (по умолчанию 24)"},
                        "alerts_only": {"type": "boolean", "description": "Только помеченные как alert-related"},
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "get_weekly_insights",
                "description": (
                    "Инсайты за неделю: паттерны сна Матвея, кормлений, "
                    "родительского сна, топливо, здоровье. Возвращает "
                    "структурированные числа + отклонения от нормы. "
                    "Триггеры: «недельная сводка», «как прошла неделя?», "
                    "«есть паттерны?», «инсайты за неделю»."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "days": {"type": "integer", "description": "За сколько дней (по умолчанию 7)"},
                    },
                    "required": [],
                },
            },
            {
                "name": "prepare_doctor_visit",
                "description": (
                    "Собрать справку перед визитом к врачу: симптомы, лекарства, прививки, "
                    "приёмы врача за N последних дней. Даёт готовый чек-лист к визиту. "
                    "Триггеры: «завтра к педиатру», «подготовь к приёму», «что рассказать врачу»."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "member": {
                            "type": "string",
                            "enum": ["matvey", "eugene", "marina"],
                        },
                        "days_back": {"type": "integer", "description": "За сколько дней (по умолчанию 30)"},
                    },
                    "required": ["member"],
                },
            },
            {
                "name": "get_medication_dose",
                "description": (
                    "Справочная информация по дозировкам детских препаратов "
                    "(парацетамол, ибупрофен, эффералган, нурофен) с расчётом по весу. "
                    "Триггеры: «сколько нурофена дать?», «доза парацетамола Матвею»."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "medication": {"type": "string", "description": "Название препарата"},
                        "weight_kg": {"type": "number", "description": "Вес в кг"},
                    },
                    "required": ["medication"],
                },
            },
            {
                "name": "wiki_set",
                "description": (
                    "Сохранить произвольную семейную заметку в вики (member=wiki, key=заголовок, value=текст). "
                    "Триггеры: «запиши в вики», «сохрани заметку про X», «запомни: пароль от роутера — Y»."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "Короткий заголовок"},
                        "text": {"type": "string", "description": "Содержимое заметки"},
                    },
                    "required": ["title", "text"],
                },
            },
            {
                "name": "wiki_list",
                "description": (
                    "Список всех заметок семейной вики (заголовки). "
                    "Триггеры: «покажи вики», «что в вики?», «список заметок»."
                ),
                "input_schema": {"type": "object", "properties": {}, "required": []},
            },
            {
                "name": "wiki_search",
                "description": (
                    "Найти заметки в вики по подстроке (в заголовке или тексте). "
                    "Триггеры: «найди в вики Y», «есть заметка про пароль?»."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Что искать"},
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "wiki_delete",
                "description": (
                    "Удалить заметку из вики по заголовку. "
                    "Триггеры: «удали заметку X», «убери из вики»."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                    },
                    "required": ["title"],
                },
            },
            {
                "name": "set_reminder",
                "description": (
                    "Поставить напоминание в Google Календаре с всплывающим уведомлением. "
                    "Триггеры: «напомни завтра в 8 дать капли», «через час позвонить маме», "
                    "«поставь напоминание на 15:00»."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "Что напомнить"},
                        "when_iso": {
                            "type": "string",
                            "description": "Когда в ISO-8601 с TZ (+03:00 для Одессы). Напр. 2026-09-25T08:00:00+03:00",
                        },
                    },
                    "required": ["text", "when_iso"],
                },
            },
            {
                "name": "list_automations",
                "description": (
                    "Список правил автоматизации умного дома (IF-THEN). "
                    "Триггеры: «какие автоматизации?», «покажи правила», «что работает автоматом»."
                ),
                "input_schema": {"type": "object", "properties": {}, "required": []},
            },
            {
                "name": "toggle_automation",
                "description": (
                    "Включить/выключить правило автоматизации по имени. "
                    "Триггеры: «выключи правило X», «включи автоматизацию Y»."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Имя правила"},
                        "enabled": {"type": "boolean", "description": "true=вкл, false=выкл"},
                    },
                    "required": ["name", "enabled"],
                },
            },
            {
                "name": "delete_automation",
                "description": (
                    "Удалить правило автоматизации по имени. "
                    "Триггеры: «удали правило X», «убери автоматизацию»."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                    },
                    "required": ["name"],
                },
            },
            {
                "name": "plan_route",
                "description": (
                    "Построить маршрут через Google Maps: расстояние, время в пути с пробками, "
                    "оценка топлива и стоимости бензина. Триггеры: «сколько ехать до X», "
                    "«маршрут до Киева», «как ехать в Затоку»."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "origin": {"type": "string", "description": "Откуда (адрес или «Одесса»)"},
                        "destination": {"type": "string", "description": "Куда"},
                    },
                    "required": ["destination"],
                },
            },
            {
                "name": "log_fuel",
                "description": (
                    "Записать заправку в FuelLog. Триггеры: «залил 40 литров», "
                    "«заправился на 2000», «заправка WOG A95 50л 55.50»."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "liters": {"type": "number", "description": "Сколько литров"},
                        "total_uah": {"type": "number", "description": "Опционально: общая сумма в грн"},
                        "price_per_l": {"type": "number", "description": "Опционально: цена за литр"},
                        "station": {"type": "string", "description": "Опционально: WOG/OKKO/Укрнафта"},
                        "fuel_kind": {"type": "string", "description": "Опционально: A95/A92/дизель"},
                        "odometer_km": {"type": "number", "description": "Опционально: пробег"},
                    },
                    "required": ["liters"],
                },
            },
            {
                "name": "get_vehicle_stats",
                "description": (
                    "Статистика авто: последние заправки, средний расход, потрачено грн. "
                    "Триггеры: «сколько потратил на бензин?», «средний расход», «статистика авто»."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "days": {"type": "integer", "description": "За сколько дней (по умолчанию 30)"},
                    },
                    "required": [],
                },
            },
            {
                "name": "search_recipe",
                "description": (
                    "Найти рецепт в интернете (DuckDuckGo) — вернёт 5 ссылок с описаниями. "
                    "Триггеры: «как приготовить X», «рецепт борща», «идея на ужин», «что приготовить из курицы»."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Что ищем: «борщ украинский рецепт», «паста карбонара»"},
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "food_delivery",
                "description": (
                    "Сгенерировать прямые ссылки на Glovo, Bolt Food, Rocket для доставки еды в Одессе. "
                    "Триггеры: «закажи пиццу», «доставка суши», «есть хочу», «glovo»."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Что заказать: «пицца Margherita», «суши Philadelphia», «борщ»"},
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "write_cooking_note",
                "description": (
                    "Сохранить кулинарную заметку/рецепт в лист «Заметки» Google Sheets. "
                    "Триггеры: «запиши рецепт», «сохрани заметку про плов», «запомни как готовили»."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "Текст заметки"},
                    },
                    "required": ["text"],
                },
            },
            {
                "name": "log_health_event",
                "description": (
                    "Записать событие здоровья для любого члена семьи (matvey/eugene/marina). "
                    "Триггеры: «у Матвея температура 37.5», «Марина приняла нурофен», "
                    "«у меня давление 130/80», «сделали прививку», «Евгений заболел»."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "member": {
                            "type": "string",
                            "enum": ["matvey", "eugene", "marina"],
                            "description": "Кому",
                        },
                        "kind": {
                            "type": "string",
                            "enum": ["symptom", "medication", "visit", "vaccine"],
                            "description": "symptom=симптом (темпер., боль), medication=лекарство, visit=приём врача, vaccine=прививка",
                        },
                        "description": {
                            "type": "string",
                            "description": "Что именно: «температура», «нурофен 200мг», «педиатр», «АКДС»",
                        },
                        "value": {
                            "type": "string",
                            "description": "Опционально: значение (37.5, 130/80, 5мл)",
                        },
                    },
                    "required": ["member", "kind", "description"],
                },
            },
            {
                "name": "get_health_history",
                "description": (
                    "История здоровья члена семьи за последние N дней. "
                    "Триггеры: «что было по здоровью?», «когда Матвей болел?», "
                    "«последняя прививка», «сколько раз Марина принимала нурофен?»."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "member": {
                            "type": "string",
                            "enum": ["matvey", "eugene", "marina"],
                        },
                        "days": {
                            "type": "integer",
                            "description": "За сколько дней (по умолчанию 30)",
                        },
                    },
                    "required": ["member"],
                },
            },
            {
                "name": "log_parent_sleep",
                "description": (
                    "Записать сон родителя (Евгения/Марины). "
                    "Триггеры: «лёг в 23», «Марина проспала 7 часов», «плохо спал, просыпался»."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "member": {"type": "string", "enum": ["eugene", "marina"]},
                        "bedtime": {"type": "string", "description": "HH:MM когда лёг"},
                        "wake_time": {"type": "string", "description": "HH:MM когда встал"},
                        "quality": {
                            "type": "string",
                            "enum": ["ok", "awakened", "bad"],
                            "description": "ok=норм, awakened=просыпался, bad=плохо",
                        },
                    },
                    "required": ["member"],
                },
            },
            {
                "name": "parent_sleep_stats",
                "description": (
                    "Статистика сна родителя за N дней (среднее время сна, качество). "
                    "Триггеры: «как сплю?», «сколько Марина спала за неделю?»."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "member": {"type": "string", "enum": ["eugene", "marina"]},
                        "days": {"type": "integer", "description": "По умолчанию 7"},
                    },
                    "required": ["member"],
                },
            },
            {
                "name": "get_system_status",
                "description": (
                    "Здоровье Family HQ: сколько каналов Дозорный мониторит, "
                    "когда был последний пост, активные тревоги, что настроено "
                    "(Sheets/Calendar/GitHub/Railway/Tuya), какая модель LLM. "
                    "Триггеры: «как система?», «всё работает?», «статус HQ», «здоровье»."
                ),
                "input_schema": {"type": "object", "properties": {}, "required": []},
            },
            {
                "name": "list_open_prs",
                "description": (
                    "Открытые pull request-ы в репо family-hq на GitHub. "
                    "Триггеры: «какие PR открыты?», «что в работе?», «показать PR»."
                ),
                "input_schema": {"type": "object", "properties": {}, "required": []},
            },
            {
                "name": "get_railway_status",
                "description": (
                    "Статус сервисов на Railway (задеплоено ли, крашится ли). "
                    "Триггеры: «Railway живой?», «деплой прошёл?», «что с прод?»."
                ),
                "input_schema": {"type": "object", "properties": {}, "required": []},
            },
            {
                "name": "get_home_map",
                "description": (
                    "Карта квартиры: устройства и сцены Tuya сгруппированные по комнатам "
                    "(спальня, детская, кухня, гостиная, ванная, коридор, балкон). "
                    "Показывает какие розетки/лампы/датчики в какой комнате, онлайн ли, "
                    "и какие сцены к комнате привязаны. Триггеры: «что у нас в спальне?», "
                    "«какие есть сцены?», «покажи все устройства», «карта дома»."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "room": {
                            "type": "string",
                            "description": "Опционально: фильтр по комнате (спальня/детская/кухня/гостиная/ванная/коридор/балкон)",
                        },
                    },
                    "required": [],
                },
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
                    at=args.get("at") or "",
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
            if name == "set_home_location":
                return await self._tool_set_home_location(
                    lat=float(args.get("lat") or 0),
                    lon=float(args.get("lon") or 0),
                )
            if name == "get_location_status":
                return await self._tool_get_location_status()
            if name == "set_baby_routine":
                return await self._tool_set_baby_routine(
                    bedtime=args.get("bedtime") or "",
                    wake_time=args.get("wake_time") or "",
                )
            if name == "remember":
                return await self._tool_remember(
                    kind=args.get("kind") or "fact",
                    content=args.get("content") or "",
                )
            if name == "recall":
                return await self._tool_recall(
                    query=args.get("query") or "",
                    limit=int(args.get("limit") or 5),
                )
            if name == "track_stock":
                return await self._tool_track_stock(
                    name_=args.get("name") or "",
                    frequency_days=int(args.get("frequency_days") or 14),
                    typical_qty=args.get("typical_qty") or "",
                )
            if name == "record_stock_purchase":
                return await self._tool_record_stock_purchase(name_=args.get("name") or "")
            if name == "check_stock":
                return await self._tool_check_stock()
            if name == "untrack_stock":
                return await self._tool_untrack_stock(name_=args.get("name") or "")
            if name == "set_recurring_reminder":
                return await self._tool_set_recurring_reminder(
                    name_=args.get("name") or "",
                    schedule=args.get("schedule") or "",
                    text_=args.get("text") or "",
                )
            if name == "list_recurring_reminders":
                return await self._tool_list_recurring_reminders()
            if name == "delete_recurring_reminder":
                return await self._tool_delete_recurring_reminder(name_=args.get("name") or "")
            if name == "set_quiet_hours":
                return await self._tool_set_quiet_hours(
                    from_time=args.get("from_time") or "",
                    to_time=args.get("to_time") or "",
                    enabled=args.get("enabled"),
                )
            if name == "ask_with_buttons":
                return await self._tool_ask_with_buttons(
                    text_=args.get("text") or "",
                    options=args.get("options") or [],
                )
            if name == "speak_reply":
                return await self._tool_speak_reply(args.get("text") or "")
            if name == "web_search":
                return await self._tool_web_search(args.get("query") or "")
            if name == "search_telegram_posts":
                return await self._tool_search_telegram_posts(
                    query=args.get("query") or "",
                    hours_back=int(args.get("hours_back") or 24),
                    alerts_only=bool(args.get("alerts_only")),
                )
            if name == "get_weekly_insights":
                return await self._tool_get_weekly_insights(days=int(args.get("days") or 7))
            if name == "prepare_doctor_visit":
                return await self._tool_prepare_doctor_visit(
                    member=args.get("member") or "matvey",
                    days_back=int(args.get("days_back") or 30),
                )
            if name == "get_medication_dose":
                return await self._tool_get_medication_dose(
                    medication=args.get("medication") or "",
                    weight_kg=args.get("weight_kg"),
                )
            if name == "wiki_set":
                return await self._tool_wiki_set(
                    title=args.get("title") or "", text_=args.get("text") or "",
                )
            if name == "wiki_list":
                return await self._tool_wiki_list()
            if name == "wiki_search":
                return await self._tool_wiki_search(query=args.get("query") or "")
            if name == "wiki_delete":
                return await self._tool_wiki_delete(title=args.get("title") or "")
            if name == "set_reminder":
                return await self._tool_set_reminder(
                    text_=args.get("text") or "",
                    when_iso=args.get("when_iso") or "",
                )
            if name == "list_automations":
                return await self._tool_list_automations()
            if name == "toggle_automation":
                return await self._tool_toggle_automation(
                    name_=args.get("name") or "",
                    enabled=bool(args.get("enabled")),
                )
            if name == "delete_automation":
                return await self._tool_delete_automation(name_=args.get("name") or "")
            if name == "plan_route":
                return await self._tool_plan_route(
                    origin=args.get("origin") or "Одесса",
                    destination=args.get("destination") or "",
                )
            if name == "log_fuel":
                return await self._tool_log_fuel(
                    liters=float(args.get("liters") or 0),
                    total_uah=args.get("total_uah"),
                    price_per_l=args.get("price_per_l"),
                    station=args.get("station") or "",
                    fuel_kind=args.get("fuel_kind") or "",
                    odometer_km=args.get("odometer_km"),
                )
            if name == "get_vehicle_stats":
                return await self._tool_get_vehicle_stats(days=int(args.get("days") or 30))
            if name == "search_recipe":
                return await self._tool_search_recipe(args.get("query") or "")
            if name == "food_delivery":
                return await self._tool_food_delivery(args.get("query") or "")
            if name == "write_cooking_note":
                return await self._tool_write_cooking_note(args.get("text") or "")
            if name == "log_health_event":
                return await self._tool_log_health_event(
                    member=args.get("member") or "",
                    kind=args.get("kind") or "",
                    description=args.get("description") or "",
                    value=args.get("value") or "",
                )
            if name == "get_health_history":
                return await self._tool_get_health_history(
                    member=args.get("member") or "",
                    days=int(args.get("days") or 30),
                )
            if name == "log_parent_sleep":
                return await self._tool_log_parent_sleep(
                    member=args.get("member") or "",
                    bedtime=args.get("bedtime") or "",
                    wake_time=args.get("wake_time") or "",
                    quality=args.get("quality") or "",
                )
            if name == "parent_sleep_stats":
                return await self._tool_parent_sleep_stats(
                    member=args.get("member") or "",
                    days=int(args.get("days") or 7),
                )
            if name == "get_system_status":
                return await self._tool_get_system_status()
            if name == "list_open_prs":
                return await self._tool_list_open_prs()
            if name == "get_railway_status":
                return await self._tool_get_railway_status()
            if name == "get_home_map":
                return await self._tool_get_home_map(room=args.get("room") or "")
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
        """Текущее состояние Матвея + предвычисленные длительности.

        Возвращает не сырые ISO, а готовые «awake_for_min=78» / human-текст,
        чтобы LLM не запуталась при вопросах «сколько уже не спит?»,
        «когда ел последний раз?» и т.п.
        """
        from datetime import datetime
        from sqlalchemy import select
        from src.db.models import BabyState

        async with self._memory._engine.connect() as conn:
            row = (await conn.execute(select(BabyState))).first()

        if not row:
            return {
                "state": "unknown",
                "hint": "BabyState пуст. Вызови get_baby_diary(days=1) — там свежие события за сегодня.",
            }

        bs = row[0] if hasattr(row, "_mapping") else row
        sleeping_since = getattr(bs, "sleeping_since", None)
        awake_since = getattr(bs, "awake_since", None)
        last_feed_at = getattr(bs, "last_feed_at", None)
        last_diaper_at = getattr(bs, "last_diaper_at", None)

        now = now_kyiv()

        def _minutes_since(iso: str | None) -> int | None:
            if not iso:
                return None
            try:
                dt = datetime.fromisoformat(iso)
                if dt.tzinfo is None:
                    from src.utils.time import KYIV_TZ
                    dt = dt.replace(tzinfo=KYIV_TZ)
                return max(0, int((now - dt).total_seconds() / 60))
            except Exception:
                return None

        def _hm(iso: str | None) -> str | None:
            if not iso:
                return None
            try:
                return datetime.fromisoformat(iso).strftime("%H:%M")
            except Exception:
                return None

        def _human_dur(mins: int | None) -> str:
            if mins is None:
                return "?"
            h, m = divmod(mins, 60)
            if h and m:
                return f"{h}ч {m}м"
            if h:
                return f"{h}ч"
            return f"{m}м"

        # Текущее состояние
        if sleeping_since and not awake_since:
            state = "sleeping"
            slept_for = _minutes_since(sleeping_since)
            headline = f"💤 Спит уже {_human_dur(slept_for)} (уснул в {_hm(sleeping_since)})"
        elif awake_since and not sleeping_since:
            state = "awake"
            awake_for = _minutes_since(awake_since)
            headline = f"👶 Бодрствует {_human_dur(awake_for)} (проснулся в {_hm(awake_since)})"
        elif awake_since:
            state = "awake"
            awake_for = _minutes_since(awake_since)
            headline = f"👶 Бодрствует {_human_dur(awake_for)} (проснулся в {_hm(awake_since)})"
        else:
            state = "unknown"
            headline = "Состояние неизвестно"

        feed_ago = _minutes_since(last_feed_at)
        diaper_ago = _minutes_since(last_diaper_at)

        return {
            "state": state,
            "headline": headline,
            "sleeping_since_iso": sleeping_since,
            "awake_since_iso": awake_since,
            "sleeping_for_min": _minutes_since(sleeping_since) if state == "sleeping" else None,
            "awake_for_min": _minutes_since(awake_since) if state == "awake" else None,
            "last_feed_at_iso": last_feed_at,
            "last_feed_ago_min": feed_ago,
            "last_feed_ago_human": _human_dur(feed_ago),
            "last_diaper_at_iso": last_diaper_at,
            "last_diaper_ago_min": diaper_ago,
            "last_diaper_ago_human": _human_dur(diaper_ago),
            "now": now.isoformat(),
        }

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
        unit: Any = None, details: str = "", at: str = "",
    ) -> dict:
        """Записать событие Матвея: в дневник Sheets + в BabyState для UI.

        Если пользователь указал время (at="07:30" или ISO) — используем его
        вместо now. Так «Матвей проснулся в 7:30» пишет 7:30, а не 7:45.
        """
        if not event.strip():
            return {"error": "event is empty"}
        try:
            from datetime import datetime
            from sqlalchemy import select, update
            from src.db.models import BabyState
            from src.utils.time import iso_now, now_kyiv, KYIV_TZ

            now = now_kyiv()
            if at.strip():
                try:
                    at_s = at.strip()
                    # HH:MM или HH.MM — сегодняшняя дата с этим временем
                    if len(at_s) <= 5 and (":" in at_s or "." in at_s):
                        sep = ":" if ":" in at_s else "."
                        hh, mm = at_s.split(sep)
                        parsed = now.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
                        # Если получилось будущее — считаем что это вчера
                        if parsed > now:
                            from datetime import timedelta
                            parsed = parsed - timedelta(days=1)
                        now = parsed
                    else:
                        parsed = datetime.fromisoformat(at_s)
                        if parsed.tzinfo is None:
                            parsed = parsed.replace(tzinfo=KYIV_TZ)
                        now = parsed
                except Exception:
                    log.warning("altron_at_parse_failed", at=at)
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
            import re as _re
            event_l = event.lower().strip()
            kind_l = kind.lower()
            values: dict = {"updated_at": iso_now()}
            # Отсекаем негации типа «не спит», «не уснул», «не проснулся» —
            # это ВОПРОСЫ/описания, а не переходы состояния.
            has_negation = bool(_re.search(r"\bне\s+", event_l)) or event_l.startswith("не ")
            if kind_l == "sleep" and not has_negation:
                # Только чёткие глаголы засыпания (по границам слов).
                asleep_re = _re.compile(r"\b(уснул|уснула|засн[ыу]|зас[ы]пает|лёг\s+спать|лег\s+спать)\b")
                # Только чёткие глаголы пробуждения.
                awake_re = _re.compile(r"\b(проснул|проснулся|проснулась|разбудил|встал|подъём|подъем)\b")
                if asleep_re.search(event_l):
                    values["sleeping_since"] = ts_iso
                    values["awake_since"] = None
                elif awake_re.search(event_l):
                    values["awake_since"] = ts_iso
                    values["sleeping_since"] = None
                # Всё остальное («шевелится», «плачет», «не спит») — пишем
                # только в дневник, состояние не переворачиваем.
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
                # Пометка для baby-watcher чтобы не дублировать «Матвей проснулся»
                import time as _time
                if "sleeping_since" in values:
                    self._recent_baby_transition["asleep"] = _time.time()
                if "awake_since" in values:
                    self._recent_baby_transition["awake"] = _time.time()

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

    async def _tool_set_home_location(self, lat: float, lon: float) -> dict:
        """Сохранить домашние координаты в FamilyFact(family, home_location)."""
        if not lat or not lon:
            return {"error": "lat и lon обязательны"}
        try:
            from sqlalchemy import insert, select, update as sql_update
            from src.db.models import FamilyFact
            from src.utils.time import iso_now
            now_ = iso_now()
            value = f"{lat:.6f},{lon:.6f}"
            async with self._memory._engine.begin() as conn:
                row = (await conn.execute(
                    select(FamilyFact)
                    .where(FamilyFact.member == "family")
                    .where(FamilyFact.key == "home_location")
                )).first()
                if row:
                    await conn.execute(
                        sql_update(FamilyFact)
                        .where(FamilyFact.id == row.id)
                        .values(value=value, updated_at=now_)
                    )
                else:
                    await conn.execute(insert(FamilyFact).values(
                        member="family", key="home_location", value=value,
                        source="altron", created_at=now_, updated_at=now_,
                    ))
            return {"success": True, "lat": lat, "lon": lon}
        except Exception as e:
            log.exception("altron_set_home_failed")
            return {"error": str(e)[:200]}

    async def _tool_get_location_status(self) -> dict:
        """Где я относительно дома по последнему поинту."""
        try:
            from sqlalchemy import select
            from src.db.models import FamilyFact
            import math
            async with self._memory._engine.connect() as conn:
                rows = list(await conn.execute(
                    select(FamilyFact).where(FamilyFact.member == "family")
                ))
            data = {r.key: r.value for r in rows}
            home = data.get("home_location")
            last = data.get("last_location")
            if not home:
                return {"error": "домашние координаты не заданы. Скажи «дом здесь»"}
            if not last:
                return {"note": "Последнее местоположение неизвестно. Пришли Location в Telegram."}
            try:
                hlat, hlon = [float(x) for x in home.split(",")]
                llat, llon = [float(x) for x in last.split(",")[:2]]
            except Exception:
                return {"error": "не смог разобрать координаты"}
            # Haversine
            R = 6371.0
            a = math.radians(llat - hlat) / 2
            b = math.radians(llon - hlon) / 2
            h = (math.sin(a) ** 2 + math.cos(math.radians(hlat)) *
                 math.cos(math.radians(llat)) * math.sin(b) ** 2)
            dist_km = 2 * R * math.asin(math.sqrt(h))
            if dist_km < 0.2:
                where = "дома"
            elif dist_km < 2:
                where = "рядом с домом"
            else:
                where = "в отъезде"
            return {"where": where, "distance_km": round(dist_km, 2)}
        except Exception as e:
            log.exception("altron_location_status_failed")
            return {"error": str(e)[:200]}

    async def _tool_set_baby_routine(self, bedtime: str = "", wake_time: str = "") -> dict:
        """Сохранить типичное расписание в FamilyFact(member='matvey_routine')."""
        if not bedtime and not wake_time:
            return {"error": "нужно bedtime или wake_time"}
        try:
            from sqlalchemy import insert, select, update as sql_update
            from src.db.models import FamilyFact
            from src.utils.time import iso_now
            now_ = iso_now()
            updates: dict[str, str] = {}
            if bedtime:
                updates["bedtime"] = bedtime.strip()
            if wake_time:
                updates["wake_time"] = wake_time.strip()
            async with self._memory._engine.begin() as conn:
                for k, v in updates.items():
                    row = (await conn.execute(
                        select(FamilyFact)
                        .where(FamilyFact.member == "matvey_routine")
                        .where(FamilyFact.key == k)
                    )).first()
                    if row:
                        await conn.execute(
                            sql_update(FamilyFact)
                            .where(FamilyFact.id == row.id)
                            .values(value=v, updated_at=now_)
                        )
                    else:
                        await conn.execute(insert(FamilyFact).values(
                            member="matvey_routine", key=k, value=v,
                            source="altron", created_at=now_, updated_at=now_,
                        ))
            return {"success": True, **updates}
        except Exception as e:
            log.exception("altron_set_routine_failed")
            return {"error": str(e)[:200]}

    async def _tool_remember(self, kind: str, content: str) -> dict:
        """Embed content через Gemini + insert в AltronLongMemory."""
        if not content.strip():
            return {"error": "content обязателен"}
        try:
            from sqlalchemy import insert
            from src.db.models import AltronLongMemory
            from src.utils.time import iso_now
            import json as _json
            emb: list[float] = []
            gem = getattr(self._gemini, "embed", None) or getattr(
                getattr(self._gemini, "_primary", None), "embed", None
            )
            if gem:
                try:
                    emb = await gem(content)
                except Exception:
                    emb = []
            emb_json = _json.dumps(emb) if emb else None
            chat_id = int(getattr(self._settings, "altron_chat_id", 0) or 0)
            async with self._memory._engine.begin() as conn:
                await conn.execute(insert(AltronLongMemory).values(
                    chat_id=chat_id, kind=kind, content=content,
                    embedding_json=emb_json, created_at=iso_now(),
                ))
            return {"success": True, "kind": kind,
                    "content": content[:80], "embedded": bool(emb)}
        except Exception as e:
            log.exception("altron_remember_failed")
            return {"error": str(e)[:200]}

    async def _tool_recall(self, query: str, limit: int = 5) -> dict:
        """Топ-N по cosine similarity. Fallback — LIKE-поиск если embeddings нет."""
        if not query.strip():
            return {"error": "query обязателен"}
        try:
            from sqlalchemy import select
            from src.db.models import AltronLongMemory
            import json as _json
            import math
            async with self._memory._engine.connect() as conn:
                rows = list(await conn.execute(select(AltronLongMemory)))
            if not rows:
                return {"count": 0, "results": []}
            gem = getattr(self._gemini, "embed", None) or getattr(
                getattr(self._gemini, "_primary", None), "embed", None
            )
            q_emb: list[float] = []
            if gem:
                try:
                    q_emb = await gem(query)
                except Exception:
                    q_emb = []
            scored: list[tuple[float, Any]] = []
            if q_emb:
                q_norm = math.sqrt(sum(x * x for x in q_emb)) or 1.0
                for r in rows:
                    if not r.embedding_json:
                        continue
                    try:
                        emb = _json.loads(r.embedding_json)
                    except Exception:
                        continue
                    if len(emb) != len(q_emb):
                        continue
                    dot = sum(a * b for a, b in zip(emb, q_emb))
                    r_norm = math.sqrt(sum(x * x for x in emb)) or 1.0
                    scored.append((dot / (q_norm * r_norm), r))
            if not scored:
                # Фолбэк — простой substring
                q_l = query.lower()
                for r in rows:
                    if q_l in (r.content or "").lower():
                        scored.append((1.0, r))
            scored.sort(key=lambda x: -x[0])
            top = scored[:limit]
            return {
                "count": len(top),
                "results": [
                    {"kind": r.kind, "content": r.content,
                     "created_at": r.created_at, "score": round(s, 3)}
                    for s, r in top
                ],
            }
        except Exception as e:
            log.exception("altron_recall_failed")
            return {"error": str(e)[:200]}

    async def _tool_track_stock(
        self, name_: str, frequency_days: int, typical_qty: str = "",
    ) -> dict:
        if not name_:
            return {"error": "name обязателен"}
        try:
            from sqlalchemy import insert, select, update as sql_update
            from src.db.models import AltronStockItem
            from src.utils.time import iso_now
            now_ = iso_now()
            async with self._memory._engine.begin() as conn:
                existing = (await conn.execute(
                    select(AltronStockItem).where(AltronStockItem.name == name_)
                )).first()
                if existing:
                    await conn.execute(
                        sql_update(AltronStockItem)
                        .where(AltronStockItem.id == existing.id)
                        .values(typical_frequency_days=frequency_days,
                                typical_qty=typical_qty or None)
                    )
                    return {"success": True, "updated": True, "name": name_}
                await conn.execute(insert(AltronStockItem).values(
                    name=name_, typical_frequency_days=frequency_days,
                    typical_qty=typical_qty or None, created_at=now_,
                ))
            return {"success": True, "name": name_}
        except Exception as e:
            log.exception("altron_track_stock_failed")
            return {"error": str(e)[:200]}

    async def _tool_record_stock_purchase(self, name_: str) -> dict:
        if not name_:
            return {"error": "name обязателен"}
        try:
            from sqlalchemy import select, update as sql_update
            from src.db.models import AltronStockItem
            from src.utils.time import iso_now
            async with self._memory._engine.begin() as conn:
                row = (await conn.execute(
                    select(AltronStockItem).where(AltronStockItem.name == name_)
                )).first()
                if not row:
                    return {"error": f"Не отслеживаю «{name_}». Сначала track_stock."}
                await conn.execute(
                    sql_update(AltronStockItem)
                    .where(AltronStockItem.id == row.id)
                    .values(last_purchased_at=iso_now(), last_reminded_at=None)
                )
            return {"success": True, "name": name_}
        except Exception as e:
            log.exception("altron_record_purchase_failed")
            return {"error": str(e)[:200]}

    async def _tool_check_stock(self) -> dict:
        try:
            from datetime import datetime, timedelta
            from sqlalchemy import select
            from src.db.models import AltronStockItem
            async with self._memory._engine.connect() as conn:
                rows = list(await conn.execute(
                    select(AltronStockItem).order_by(AltronStockItem.name)
                ))
            now = now_kyiv()
            items = []
            urgent = []
            for r in rows:
                days_since = None
                days_left = None
                status = "no_data"
                if r.last_purchased_at:
                    try:
                        dt = datetime.fromisoformat(r.last_purchased_at)
                        days_since = (now - dt).days
                        days_left = r.typical_frequency_days - days_since
                        if days_left <= 0:
                            status = "overdue"
                        elif days_left <= 3:
                            status = "urgent"
                        else:
                            status = "ok"
                    except Exception:
                        pass
                info = {
                    "name": r.name, "frequency_days": r.typical_frequency_days,
                    "typical_qty": r.typical_qty, "last_purchased_at": r.last_purchased_at,
                    "days_since": days_since, "days_left": days_left, "status": status,
                }
                items.append(info)
                if status in ("overdue", "urgent"):
                    urgent.append(info)
            return {"count": len(items), "urgent_count": len(urgent),
                    "items": items, "urgent": urgent}
        except Exception as e:
            log.exception("altron_check_stock_failed")
            return {"error": str(e)[:200]}

    async def _tool_untrack_stock(self, name_: str) -> dict:
        if not name_:
            return {"error": "name обязателен"}
        try:
            from sqlalchemy import delete
            from src.db.models import AltronStockItem
            async with self._memory._engine.begin() as conn:
                await conn.execute(
                    delete(AltronStockItem).where(AltronStockItem.name == name_)
                )
            return {"success": True, "name": name_, "deleted": True}
        except Exception as e:
            log.exception("altron_untrack_stock_failed")
            return {"error": str(e)[:200]}

    async def _tool_set_recurring_reminder(
        self, name_: str, schedule: str, text_: str,
    ) -> dict:
        if not name_ or not schedule or not text_:
            return {"error": "name, schedule и text обязательны"}
        try:
            from sqlalchemy import insert, select, update as sql_update
            from src.db.models import AltronReminder
            from src.utils.time import iso_now
            now_ = iso_now()
            async with self._memory._engine.begin() as conn:
                existing = (await conn.execute(
                    select(AltronReminder).where(AltronReminder.name == name_)
                )).first()
                if existing:
                    await conn.execute(
                        sql_update(AltronReminder)
                        .where(AltronReminder.id == existing.id)
                        .values(schedule=schedule, text=text_, enabled=1)
                    )
                    return {"success": True, "updated": True, "name": name_}
                await conn.execute(insert(AltronReminder).values(
                    name=name_, schedule=schedule, text=text_,
                    enabled=1, created_at=now_,
                ))
            return {"success": True, "name": name_, "schedule": schedule}
        except Exception as e:
            log.exception("altron_set_recurring_failed")
            return {"error": str(e)[:200]}

    async def _tool_list_recurring_reminders(self) -> dict:
        try:
            from sqlalchemy import select
            from src.db.models import AltronReminder
            async with self._memory._engine.connect() as conn:
                rows = list(await conn.execute(
                    select(AltronReminder).order_by(AltronReminder.name)
                ))
            return {
                "count": len(rows),
                "reminders": [
                    {"name": r.name, "schedule": r.schedule, "text": r.text,
                     "enabled": bool(r.enabled), "last_fired_at": r.last_fired_at}
                    for r in rows
                ],
            }
        except Exception as e:
            log.exception("altron_list_recurring_failed")
            return {"error": str(e)[:200]}

    async def _tool_delete_recurring_reminder(self, name_: str) -> dict:
        if not name_:
            return {"error": "name обязателен"}
        try:
            from sqlalchemy import delete, select
            from src.db.models import AltronReminder
            async with self._memory._engine.begin() as conn:
                existing = (await conn.execute(
                    select(AltronReminder).where(AltronReminder.name == name_)
                )).first()
                if not existing:
                    return {"error": f"Не нашёл «{name_}»"}
                await conn.execute(
                    delete(AltronReminder).where(AltronReminder.name == name_)
                )
            return {"success": True, "name": name_, "deleted": True}
        except Exception as e:
            log.exception("altron_delete_recurring_failed")
            return {"error": str(e)[:200]}

    async def _tool_set_quiet_hours(
        self, from_time: str = "", to_time: str = "", enabled: Any = None,
    ) -> dict:
        """Записать окно тишины в FamilyFact(member='altron', key='quiet_hours')."""
        try:
            from sqlalchemy import insert, select, update as sql_update
            from src.db.models import FamilyFact
            from src.utils.time import iso_now
            now_ = iso_now()
            if enabled is False:
                value = "off"
            elif from_time and to_time:
                value = f"{from_time.strip()}-{to_time.strip()}"
            else:
                return {"error": "нужно from_time+to_time или enabled=false"}
            async with self._memory._engine.begin() as conn:
                row = (await conn.execute(
                    select(FamilyFact)
                    .where(FamilyFact.member == "altron")
                    .where(FamilyFact.key == "quiet_hours")
                )).first()
                if row:
                    await conn.execute(
                        sql_update(FamilyFact)
                        .where(FamilyFact.id == row.id)
                        .values(value=value, updated_at=now_)
                    )
                else:
                    await conn.execute(insert(FamilyFact).values(
                        member="altron", key="quiet_hours", value=value,
                        source="altron", created_at=now_, updated_at=now_,
                    ))
            # Инвалидируем кэш в боте если есть
            bridge = getattr(self, "_voice_bot", None)
            if bridge is not None and hasattr(bridge, "_quiet_window_cache"):
                bridge._quiet_window_cache = None
            return {"success": True, "value": value}
        except Exception as e:
            log.exception("altron_set_quiet_failed")
            return {"error": str(e)[:200]}

    async def _tool_ask_with_buttons(self, text_: str, options: list) -> dict:
        """Отправить сообщение с inline-кнопками через bridge к боту."""
        if not text_.strip() or not options:
            return {"error": "text и options обязательны"}
        bridge = getattr(self, "_voice_bot", None)
        if bridge is None:
            return {"error": "bot bridge не подключён"}
        try:
            opts = [str(o) for o in options if o][:6]
            await bridge.send_with_buttons(text_, opts)
            return {"success": True, "sent": True, "options": opts}
        except Exception as e:
            log.exception("altron_ask_buttons_failed")
            return {"error": str(e)[:200]}

    async def _tool_speak_reply(self, text_: str) -> dict:
        """Отправить голосом (мужской). Требует bot bridge — установлен
        в main.py после создания AltronBot."""
        if not text_.strip():
            return {"error": "text is empty"}
        bridge = getattr(self, "_voice_bot", None)
        if bridge is None:
            return {"error": "voice bridge не подключён"}
        try:
            await bridge._send_voice(text_)
            return {"success": True, "spoken": text_[:80]}
        except Exception as e:
            log.exception("altron_speak_reply_failed")
            return {"error": str(e)[:200]}

    async def _tool_web_search(self, query: str) -> dict:
        """Общий поиск (DuckDuckGo) — 5 результатов."""
        if not query.strip():
            return {"error": "query is empty"}
        try:
            from src.integrations.web_search import WebSearchClient
            client = WebSearchClient()
            results = await client.search(query, max_results=5)
            return {
                "query": query,
                "count": len(results),
                "results": [
                    {"title": r.title, "url": r.url, "snippet": r.snippet[:250]}
                    for r in results
                ],
            }
        except Exception as e:
            log.exception("altron_web_search_failed")
            return {"error": str(e)[:200]}

    async def _tool_search_telegram_posts(
        self, query: str, hours_back: int = 24, alerts_only: bool = False,
    ) -> dict:
        """Поиск по NewsPost — свежие посты из мониторинга Дозорного."""
        if not query.strip():
            return {"error": "query is empty"}
        try:
            from sqlalchemy import select
            from src.db.models import NewsPost, NewsChannel
            from datetime import timedelta
            since = (now_kyiv() - timedelta(hours=hours_back)).isoformat()
            q = query.lower()
            async with self._memory._engine.connect() as conn:
                stmt = (
                    select(NewsPost, NewsChannel.title)
                    .join(NewsChannel, NewsPost.channel_id == NewsChannel.channel_id, isouter=True)
                    .where(NewsPost.date >= since)
                    .order_by(NewsPost.date.desc())
                    .limit(400)
                )
                if alerts_only:
                    stmt = stmt.where(NewsPost.is_alert == 1)
                rows = list(await conn.execute(stmt))
            hits = []
            for post, channel_title in rows:
                if q in (post.text or "").lower():
                    hits.append({
                        "channel": channel_title or f"chan_{post.channel_id}",
                        "date": post.date,
                        "text": (post.text or "")[:400],
                        "is_alert": bool(post.is_alert),
                        "alert_region": post.alert_region,
                    })
                    if len(hits) >= 15:
                        break
            return {
                "query": query,
                "hours_back": hours_back,
                "alerts_only": alerts_only,
                "count": len(hits),
                "hits": hits,
            }
        except Exception as e:
            log.exception("altron_tg_search_failed")
            return {"error": str(e)[:200]}

    async def _tool_get_weekly_insights(self, days: int = 7) -> dict:
        """Собрать структурированные метрики за N дней. LLM формулирует
        человеческие инсайты уже над этим объектом."""
        try:
            from datetime import timedelta
            from sqlalchemy import select
            from src.db.models import (
                HealthRecord, ParentSleep, FuelLog,
            )
            since_dt = now_kyiv() - timedelta(days=days)
            since_iso = since_dt.isoformat()
            since_date = since_dt.date().isoformat()

            insights: dict = {"days": days, "since": since_iso}

            # Родительский сон — среднее и разбивка качества
            for m in ("eugene", "marina"):
                try:
                    stats = await self._tool_parent_sleep_stats(member=m, days=days)
                    insights[f"{m}_sleep"] = {
                        "avg_hours": stats.get("avg_hours"),
                        "nights_recorded": stats.get("records_count"),
                        "quality": stats.get("quality_breakdown"),
                    }
                except Exception:
                    insights[f"{m}_sleep"] = {"error": "не удалось посчитать"}

            # Здоровье семьи — свежие записи по каждому
            health: dict = {}
            for m in ("matvey", "eugene", "marina"):
                try:
                    async with self._memory._engine.connect() as conn:
                        rows = list(await conn.execute(
                            select(HealthRecord)
                            .where(HealthRecord.member_id == m)
                            .where(HealthRecord.date >= since_iso)
                            .order_by(HealthRecord.date.desc())
                            .limit(50)
                        ))
                    by_kind: dict[str, int] = {}
                    for r in rows:
                        by_kind[r.kind] = by_kind.get(r.kind, 0) + 1
                    health[m] = {"total": len(rows), "by_kind": by_kind}
                except Exception:
                    health[m] = {"error": "не удалось"}
            insights["health"] = health

            # Топливо
            try:
                fuel = await self._tool_get_vehicle_stats(days=days)
                insights["fuel"] = {
                    "refuels": fuel.get("refuels_count"),
                    "total_liters": fuel.get("total_liters"),
                    "total_uah": fuel.get("total_uah"),
                    "km_run": fuel.get("km_run"),
                    "avg_l_per_100km": fuel.get("avg_l_per_100km"),
                }
            except Exception:
                insights["fuel"] = {"error": "не удалось"}

            # Дневник Матвея — агрегируем по типам
            try:
                diary = await self._tool_get_baby_diary(days=days, kind="all")
                events = diary.get("events") or []
                by_kind: dict[str, int] = {}
                sleep_starts = []
                sleep_ends = []
                for ev in events:
                    k = str(ev.get("kind", "note")).lower()
                    by_kind[k] = by_kind.get(k, 0) + 1
                    # Простейший паттерн: время пробуждений
                    e_l = str(ev.get("event", "")).lower()
                    ts = ev.get("time", "")
                    if "проснул" in e_l:
                        sleep_ends.append(ts)
                    elif "уснул" in e_l or "лёг" in e_l:
                        sleep_starts.append(ts)
                insights["matvey"] = {
                    "total_events": len(events),
                    "by_kind": by_kind,
                    "wake_ups": len(sleep_ends),
                    "sleep_starts": len(sleep_starts),
                    "wake_up_times": sleep_ends[:10],
                }
            except Exception:
                insights["matvey"] = {"error": "не удалось"}

            return insights
        except Exception as e:
            log.exception("altron_weekly_insights_failed")
            return {"error": str(e)[:200]}

    async def _tool_prepare_doctor_visit(self, member: str, days_back: int = 30) -> dict:
        """Свежие HealthRecord + doctor визиты по человеку."""
        try:
            from sqlalchemy import select
            from src.db.models import HealthRecord
            from datetime import timedelta
            cutoff = (now_kyiv() - timedelta(days=days_back)).isoformat()
            async with self._memory._engine.connect() as conn:
                recs = list(await conn.execute(
                    select(HealthRecord)
                    .where(HealthRecord.member_id == member)
                    .where(HealthRecord.date >= cutoff)
                    .order_by(HealthRecord.date.desc())
                    .limit(80)
                ))
            grouped: dict[str, list] = {"symptom": [], "medication": [], "visit": [], "vaccine": []}
            for r in recs:
                grouped.setdefault(r.kind, []).append({
                    "date": r.date[:10] if r.date else "",
                    "description": r.description,
                    "value": r.value,
                })
            return {
                "member": member,
                "days_back": days_back,
                "total_events": len(recs),
                "symptoms": grouped.get("symptom", []),
                "medications": grouped.get("medication", []),
                "visits": grouped.get("visit", []),
                "vaccines": grouped.get("vaccine", []),
                "checklist_hint": (
                    "Спроси врача о: 1) актуальных симптомах, 2) реакциях на лекарства, "
                    "3) плане прививок, 4) новых симптомах для наблюдения"
                ),
            }
        except Exception as e:
            log.exception("altron_doctor_prep_failed")
            return {"error": str(e)[:200]}

    async def _tool_get_medication_dose(self, medication: str, weight_kg: Any = None) -> dict:
        """Справочные дозы часто используемых детских препаратов."""
        if not medication.strip():
            return {"error": "medication is empty"}
        med = medication.lower().strip()
        # Основные детские жаропонижающие с типовыми дозировками
        dosage_data = {
            "парацетамол": {
                "mg_per_kg": "10-15",
                "max_daily_mg_per_kg": "60",
                "interval_h": "4-6",
                "note": "Не более 4 раз в сутки",
            },
            "ибупрофен": {
                "mg_per_kg": "5-10",
                "max_daily_mg_per_kg": "30",
                "interval_h": "6-8",
                "note": "Не давать до 3 мес",
            },
            "нурофен": {
                "mg_per_kg": "5-10",
                "max_daily_mg_per_kg": "30",
                "interval_h": "6-8",
                "note": "Ибупрофен 100мг/5мл. Не давать до 3 мес",
            },
            "эффералган": {
                "mg_per_kg": "10-15",
                "max_daily_mg_per_kg": "60",
                "interval_h": "4-6",
                "note": "Парацетамол сироп 30мг/мл",
            },
        }
        found_key = None
        for k in dosage_data:
            if k in med:
                found_key = k
                break
        if not found_key:
            return {
                "medication": medication,
                "note": "Нет справочных данных. Следуй инструкции к препарату или проконсультируйся с педиатром.",
            }
        info = dosage_data[found_key]
        result = {"medication": found_key, **info}
        if weight_kg:
            try:
                w = float(weight_kg)
                low, high = info["mg_per_kg"].split("-")
                dose_low = round(w * float(low))
                dose_high = round(w * float(high))
                max_daily = round(w * float(info["max_daily_mg_per_kg"]))
                result["for_weight_kg"] = w
                result["single_dose_mg"] = f"{dose_low}-{dose_high}"
                result["max_daily_mg"] = max_daily
                if found_key == "нурофен":
                    ml_low = round(dose_low / 20, 1)
                    ml_high = round(dose_high / 20, 1)
                    result["single_dose_ml"] = f"{ml_low}-{ml_high} мл (100мг/5мл)"
                elif found_key == "эффералган":
                    ml_low = round(dose_low / 30, 1)
                    ml_high = round(dose_high / 30, 1)
                    result["single_dose_ml"] = f"{ml_low}-{ml_high} мл (30мг/мл)"
            except Exception:
                pass
        result["disclaimer"] = "Справочная информация. Итоговая доза — по инструкции и с педиатром."
        return result

    async def _tool_wiki_set(self, title: str, text_: str) -> dict:
        """Заметка вики — храним в FamilyFact(member=wiki, key=title, value=text)."""
        if not title.strip() or not text_.strip():
            return {"error": "title и text обязательны"}
        try:
            from sqlalchemy import insert, select, update
            from src.db.models import FamilyFact
            from src.utils.time import iso_now
            now_ = iso_now()
            async with self._memory._engine.begin() as conn:
                existing = (await conn.execute(
                    select(FamilyFact)
                    .where(FamilyFact.member == "wiki")
                    .where(FamilyFact.key == title)
                )).first()
                if existing:
                    await conn.execute(
                        update(FamilyFact)
                        .where(FamilyFact.id == existing.id)
                        .values(value=text_, updated_at=now_)
                    )
                else:
                    await conn.execute(insert(FamilyFact).values(
                        member="wiki", key=title, value=text_,
                        source="altron", created_at=now_, updated_at=now_,
                    ))
            return {"success": True, "title": title, "updated": bool(existing)}
        except Exception as e:
            log.exception("altron_wiki_set_failed")
            return {"error": str(e)[:200]}

    async def _tool_wiki_list(self) -> dict:
        try:
            from sqlalchemy import select
            from src.db.models import FamilyFact
            async with self._memory._engine.connect() as conn:
                rows = list(await conn.execute(
                    select(FamilyFact)
                    .where(FamilyFact.member == "wiki")
                    .order_by(FamilyFact.updated_at.desc())
                ))
            return {
                "count": len(rows),
                "titles": [r.key for r in rows],
            }
        except Exception as e:
            log.exception("altron_wiki_list_failed")
            return {"error": str(e)[:200]}

    async def _tool_wiki_search(self, query: str) -> dict:
        if not query.strip():
            return {"error": "query is empty"}
        try:
            from sqlalchemy import select
            from src.db.models import FamilyFact
            q = query.lower()
            async with self._memory._engine.connect() as conn:
                rows = list(await conn.execute(
                    select(FamilyFact).where(FamilyFact.member == "wiki")
                ))
            hits = [
                {"title": r.key, "text": r.value, "updated": r.updated_at}
                for r in rows
                if q in (r.key or "").lower() or q in (r.value or "").lower()
            ]
            return {"query": query, "count": len(hits), "results": hits[:10]}
        except Exception as e:
            log.exception("altron_wiki_search_failed")
            return {"error": str(e)[:200]}

    async def _tool_wiki_delete(self, title: str) -> dict:
        if not title.strip():
            return {"error": "title is empty"}
        try:
            from sqlalchemy import delete, select
            from src.db.models import FamilyFact
            async with self._memory._engine.begin() as conn:
                existing = (await conn.execute(
                    select(FamilyFact)
                    .where(FamilyFact.member == "wiki")
                    .where(FamilyFact.key == title)
                )).first()
                if not existing:
                    return {"error": f"Заметка «{title}» не найдена"}
                await conn.execute(
                    delete(FamilyFact)
                    .where(FamilyFact.member == "wiki")
                    .where(FamilyFact.key == title)
                )
            return {"success": True, "title": title, "deleted": True}
        except Exception as e:
            log.exception("altron_wiki_delete_failed")
            return {"error": str(e)[:200]}

    async def _tool_set_reminder(self, text_: str, when_iso: str) -> dict:
        """Напоминание = 15-минутное событие с префиксом 🔔 в Google Календаре."""
        if not text_.strip() or not when_iso.strip():
            return {"error": "text и when_iso обязательны"}
        try:
            from datetime import datetime, timedelta
            from src.integrations.gcalendar import CalendarClient
            import base64, json as _json
            sa_b64 = getattr(self._settings, "google_service_account_b64", "")
            cal_id = getattr(self._settings, "calendar_id", "")
            if not sa_b64 or not cal_id:
                return {"error": "Google Calendar не настроен"}
            sa_info = _json.loads(base64.b64decode(sa_b64).decode())
            cal = CalendarClient(service_account_info=sa_info, calendar_id=cal_id)
            start = datetime.fromisoformat(when_iso)
            end = start + timedelta(minutes=15)
            event = await cal.create_event(
                title=f"🔔 {text_}",
                start=start, end=end,
                description="Напоминание Альтрона",
                color_id="5",  # Banana / жёлтый
            )
            return {
                "success": True,
                "text": text_,
                "when": event.start.isoformat(),
                "event_id": event.event_id,
            }
        except Exception as e:
            log.exception("altron_set_reminder_failed")
            return {"error": str(e)[:200]}

    async def _tool_list_automations(self) -> dict:
        """Список AutomationRule."""
        try:
            from sqlalchemy import select
            from src.db.models import AutomationRule
            async with self._memory._engine.connect() as conn:
                rows = list(await conn.execute(
                    select(AutomationRule).order_by(AutomationRule.name)
                ))
            return {
                "count": len(rows),
                "rules": [
                    {
                        "name": r.name,
                        "description": r.description or "",
                        "enabled": bool(r.enabled),
                        "fired_count": r.fired_count,
                        "last_fired_at": r.last_fired_at,
                    }
                    for r in rows
                ],
            }
        except Exception as e:
            log.exception("altron_list_automations_failed")
            return {"error": str(e)[:200]}

    async def _tool_toggle_automation(self, name_: str, enabled: bool) -> dict:
        if not name_.strip():
            return {"error": "name is empty"}
        try:
            from sqlalchemy import select, update
            from src.db.models import AutomationRule
            async with self._memory._engine.begin() as conn:
                r = (await conn.execute(
                    select(AutomationRule).where(AutomationRule.name == name_)
                )).first()
                if not r:
                    return {"error": f"Правило «{name_}» не найдено"}
                await conn.execute(
                    update(AutomationRule)
                    .where(AutomationRule.name == name_)
                    .values(enabled=1 if enabled else 0)
                )
            return {"success": True, "name": name_, "enabled": enabled}
        except Exception as e:
            log.exception("altron_toggle_automation_failed")
            return {"error": str(e)[:200]}

    async def _tool_delete_automation(self, name_: str) -> dict:
        if not name_.strip():
            return {"error": "name is empty"}
        try:
            from sqlalchemy import delete, select
            from src.db.models import AutomationRule
            async with self._memory._engine.begin() as conn:
                r = (await conn.execute(
                    select(AutomationRule).where(AutomationRule.name == name_)
                )).first()
                if not r:
                    return {"error": f"Правило «{name_}» не найдено"}
                await conn.execute(
                    delete(AutomationRule).where(AutomationRule.name == name_)
                )
            return {"success": True, "name": name_, "deleted": True}
        except Exception as e:
            log.exception("altron_delete_automation_failed")
            return {"error": str(e)[:200]}

    async def _tool_plan_route(self, origin: str, destination: str) -> dict:
        """Google Maps directions + грубая оценка топлива."""
        if not destination.strip():
            return {"error": "destination is empty"}
        try:
            from src.integrations.gmaps import GMapsClient
            gmaps = GMapsClient.from_settings(self._settings)
            if not gmaps:
                return {"error": "GMAPS_API_KEY не настроен"}
            route = await gmaps.directions(origin or "Одесса", destination)
            distance = route.get("distance_km", 0)
            dur = route.get("duration_traffic_min") or route.get("duration_min") or 0
            # Приблизительный расход: 9.5 л/100 (highway assumption)
            fuel_l = round(distance / 100 * 9.5, 1)
            fuel_uah = round(fuel_l * 56.0)  # рефа A95
            return {
                "origin": origin,
                "destination": destination,
                "distance_km": distance,
                "duration_min": dur,
                "duration_h_m": f"{dur // 60}ч {dur % 60}м" if dur else "?",
                "fuel_l_estimate": fuel_l,
                "fuel_uah_estimate": fuel_uah,
                "summary": route.get("summary", ""),
            }
        except Exception as e:
            log.exception("altron_plan_route_failed")
            return {"error": str(e)[:200]}

    async def _tool_log_fuel(
        self, liters: float,
        total_uah: Any = None, price_per_l: Any = None,
        station: str = "", fuel_kind: str = "",
        odometer_km: Any = None,
    ) -> dict:
        """Запись заправки в FuelLog. Автосоздаёт vehicle если нет."""
        if liters <= 0:
            return {"error": "liters должно быть > 0"}
        try:
            from sqlalchemy import insert, select
            from src.db.models import FuelLog, Vehicle
            from src.utils.time import iso_now
            async with self._memory._engine.begin() as conn:
                v = (await conn.execute(select(Vehicle).limit(1))).first()
                if not v:
                    now = iso_now()
                    await conn.execute(insert(Vehicle).values(
                        name="Авто", make="—", model="—", year=2020,
                        fuel_type="бензин", tank_l=60.0,
                        avg_city_l_100=11.5, avg_highway_l_100=9.5,
                        odometer_km=0.0, tank_remaining_l=0.0,
                        created_at=now, updated_at=now,
                    ))
                    v = (await conn.execute(select(Vehicle).limit(1))).first()
                total_val = float(total_uah) if total_uah is not None else None
                ppl_val = float(price_per_l) if price_per_l is not None else None
                if total_val and not ppl_val and liters:
                    ppl_val = round(total_val / liters, 2)
                if ppl_val and not total_val:
                    total_val = round(ppl_val * liters, 2)
                await conn.execute(insert(FuelLog).values(
                    vehicle_id=v.id,
                    station=station or None,
                    liters=liters,
                    price_per_l=ppl_val,
                    total_uah=total_val,
                    odometer_km=float(odometer_km) if odometer_km is not None else None,
                    fuel_kind=fuel_kind or None,
                    created_at=iso_now(),
                ))
            return {
                "success": True,
                "liters": liters, "total_uah": total_val, "price_per_l": ppl_val,
                "station": station, "fuel_kind": fuel_kind,
            }
        except Exception as e:
            log.exception("altron_log_fuel_failed")
            return {"error": str(e)[:200]}

    async def _tool_get_vehicle_stats(self, days: int = 30) -> dict:
        """Сумма заправок, средний расход, число."""
        try:
            from sqlalchemy import select
            from src.db.models import FuelLog
            from datetime import timedelta
            since = (now_kyiv() - timedelta(days=days)).isoformat()
            async with self._memory._engine.connect() as conn:
                rows = list(await conn.execute(
                    select(FuelLog)
                    .where(FuelLog.created_at >= since)
                    .order_by(FuelLog.created_at.desc())
                ))
            total_l = sum((r.liters or 0) for r in rows)
            total_uah = sum((r.total_uah or 0) for r in rows)
            odo_vals = [r.odometer_km for r in rows if r.odometer_km]
            km_run = (max(odo_vals) - min(odo_vals)) if len(odo_vals) >= 2 else None
            avg_l_100 = round(total_l / km_run * 100, 1) if km_run else None
            return {
                "days": days,
                "refuels_count": len(rows),
                "total_liters": round(total_l, 1),
                "total_uah": round(total_uah),
                "km_run": km_run,
                "avg_l_per_100km": avg_l_100,
                "recent": [
                    {
                        "date": r.created_at[:10] if r.created_at else "",
                        "station": r.station, "liters": r.liters,
                        "total_uah": r.total_uah, "price_per_l": r.price_per_l,
                    }
                    for r in rows[:5]
                ],
            }
        except Exception as e:
            log.exception("altron_vehicle_stats_failed")
            return {"error": str(e)[:200]}

    async def _tool_search_recipe(self, query: str) -> dict:
        if not query.strip():
            return {"error": "query is empty"}
        try:
            from src.integrations.web_search import WebSearchClient
            client = WebSearchClient()
            results = await client.search(query, max_results=5)
            return {
                "query": query,
                "count": len(results),
                "results": [
                    {"title": r.title, "url": r.url, "snippet": r.snippet[:200]}
                    for r in results
                ],
            }
        except Exception as e:
            log.exception("altron_search_recipe_failed")
            return {"error": str(e)[:200]}

    async def _tool_food_delivery(self, query: str) -> dict:
        if not query.strip():
            return {"error": "query is empty"}
        try:
            from src.integrations.food_delivery import build_deeplinks
            links = build_deeplinks(query, city="Odessa")
            return {"query": query, "links": links}
        except Exception as e:
            log.exception("altron_food_delivery_failed")
            return {"error": str(e)[:200]}

    async def _tool_write_cooking_note(self, text: str) -> dict:
        if not text.strip():
            return {"error": "text is empty"}
        try:
            from src.integrations.sheets import SheetsClient
            sheets = SheetsClient.from_settings(self._settings)
            if not sheets:
                return {"error": "Google Sheets не настроен"}
            res = await sheets.append_note(text=text, time=now_kyiv(), author="Альтрон")
            return {"success": True, "text": text[:80], "sheet_result": res}
        except Exception as e:
            log.exception("altron_cook_note_failed")
            return {"error": str(e)[:200]}

    async def _tool_log_health_event(
        self, member: str, kind: str, description: str, value: str = "",
    ) -> dict:
        """Запись в HealthRecord."""
        if not member or not kind or not description:
            return {"error": "member/kind/description обязательны"}
        try:
            from sqlalchemy import insert
            from src.db.models import HealthRecord
            from src.utils.time import iso_now
            async with self._memory._engine.begin() as conn:
                await conn.execute(
                    insert(HealthRecord).values(
                        member_id=member,
                        kind=kind,
                        description=description,
                        value=value or None,
                        date=iso_now(),
                    )
                )
            return {"success": True, "member": member, "kind": kind, "description": description}
        except Exception as e:
            log.exception("altron_log_health_failed")
            return {"error": str(e)[:200]}

    async def _tool_get_health_history(self, member: str, days: int = 30) -> dict:
        """История здоровья за N дней."""
        if not member:
            return {"error": "member обязателен"}
        try:
            from sqlalchemy import select
            from src.db.models import HealthRecord
            async with self._memory._engine.connect() as conn:
                rows = list(await conn.execute(
                    select(HealthRecord)
                    .where(HealthRecord.member_id == member)
                    .order_by(HealthRecord.date.desc())
                    .limit(50)
                ))
            return {
                "member": member,
                "count": len(rows),
                "records": [
                    {"kind": r.kind, "description": r.description, "value": r.value, "date": r.date}
                    for r in rows
                ],
            }
        except Exception as e:
            log.exception("altron_get_health_failed")
            return {"error": str(e)[:200]}

    async def _tool_log_parent_sleep(
        self, member: str, bedtime: str = "", wake_time: str = "", quality: str = "",
    ) -> dict:
        """Запись сна родителя."""
        if member not in ("eugene", "marina"):
            return {"error": "member должен быть eugene/marina"}
        try:
            from sqlalchemy import insert
            from src.db.models import ParentSleep
            from src.utils.time import now_kyiv
            today = now_kyiv().date().isoformat()
            async with self._memory._engine.begin() as conn:
                await conn.execute(
                    insert(ParentSleep).values(
                        member=member,
                        bedtime=bedtime or None,
                        wake_time=wake_time or None,
                        quality=quality or None,
                        date=today,
                    )
                )
            return {
                "success": True, "member": member, "date": today,
                "bedtime": bedtime, "wake_time": wake_time, "quality": quality,
            }
        except Exception as e:
            log.exception("altron_log_sleep_failed")
            return {"error": str(e)[:200]}

    async def _tool_parent_sleep_stats(self, member: str, days: int = 7) -> dict:
        """Статистика сна за N дней."""
        if member not in ("eugene", "marina"):
            return {"error": "member должен быть eugene/marina"}
        try:
            from sqlalchemy import select
            from src.db.models import ParentSleep
            from src.utils.time import now_kyiv
            from datetime import timedelta
            since = (now_kyiv().date() - timedelta(days=days)).isoformat()
            async with self._memory._engine.connect() as conn:
                rows = list(await conn.execute(
                    select(ParentSleep)
                    .where(ParentSleep.member == member)
                    .where(ParentSleep.date >= since)
                    .order_by(ParentSleep.date.desc())
                ))

            total_hours = 0.0
            counted = 0
            quality_counts: dict[str, int] = {}
            for r in rows:
                if r.bedtime and r.wake_time:
                    try:
                        bh, bm = [int(x) for x in r.bedtime.split(":")[:2]]
                        wh, wm = [int(x) for x in r.wake_time.split(":")[:2]]
                        b_min = bh * 60 + bm
                        w_min = wh * 60 + wm
                        # если утро < вечера — перекинулось через полночь
                        diff = (w_min - b_min) if w_min > b_min else (w_min + 24 * 60 - b_min)
                        total_hours += diff / 60
                        counted += 1
                    except Exception:
                        pass
                if r.quality:
                    quality_counts[r.quality] = quality_counts.get(r.quality, 0) + 1
            avg_hours = round(total_hours / counted, 1) if counted else None
            return {
                "member": member,
                "days": days,
                "records_count": len(rows),
                "avg_hours": avg_hours,
                "quality_breakdown": quality_counts,
                "last_records": [
                    {"date": r.date, "bedtime": r.bedtime, "wake_time": r.wake_time, "quality": r.quality}
                    for r in rows[:7]
                ],
            }
        except Exception as e:
            log.exception("altron_sleep_stats_failed")
            return {"error": str(e)[:200]}

    async def _tool_get_system_status(self) -> dict:
        """Здоровье Family HQ — каналы, посты, тревоги, интеграции, модель."""
        try:
            from sqlalchemy import select
            from src.db.models import ActiveAlert, NewsChannel, NewsPost
            from src.utils.time import now_kyiv
            from datetime import datetime as _dt

            async with self._memory._engine.connect() as conn:
                channels = list(await conn.execute(select(NewsChannel)))
                alerts = list(await conn.execute(select(ActiveAlert)))
                last_post = (await conn.execute(
                    select(NewsPost.date).order_by(NewsPost.date.desc()).limit(1)
                )).first()

            ch_by_cat: dict[str, int] = {}
            inactive = 0
            for c in channels:
                ch_by_cat[c.category] = ch_by_cat.get(c.category, 0) + 1
                if not c.active:
                    inactive += 1

            last_post_iso = last_post[0] if last_post else None
            last_post_lag_min = None
            if last_post_iso:
                try:
                    lag = now_kyiv() - _dt.fromisoformat(last_post_iso)
                    last_post_lag_min = int(lag.total_seconds() / 60)
                except Exception:
                    pass

            s = self._settings
            return {
                "news_channels": {
                    "total": len(channels),
                    "by_category": ch_by_cat,
                    "inactive": inactive,
                },
                "news_posts": {
                    "last_saved_at": last_post_iso,
                    "minutes_ago": last_post_lag_min,
                    "stale": (last_post_lag_min or 0) > 120 if last_post_lag_min is not None else None,
                },
                "active_alerts": [
                    {"region": a.region, "started": a.started_at, "last_update": a.last_update_at}
                    for a in alerts
                ],
                "integrations": {
                    "google_sheets": bool(getattr(s, "sheet_baby_id", "") and getattr(s, "google_service_account_b64", "")),
                    "google_calendar": bool(getattr(s, "calendar_id", "") and getattr(s, "google_service_account_b64", "")),
                    "github": bool(getattr(s, "github_token", "")),
                    "railway": bool(getattr(s, "railway_api_token", "") and getattr(s, "railway_project_id", "")),
                    "tuya": bool(getattr(s, "tuya_access_id", "")),
                    "nova_poshta": bool(getattr(s, "nova_poshta_api_key", "")),
                },
                "model": {
                    "main": getattr(s, "model_main", ""),
                    "gemini_configured": bool(getattr(s, "gemini_api_key", "")),
                },
            }
        except Exception as e:
            log.exception("altron_system_status_failed")
            return {"error": str(e)[:200]}

    async def _tool_list_open_prs(self) -> dict:
        """Открытые PR-ы на GitHub."""
        try:
            token = getattr(self._settings, "github_token", "")
            repo = getattr(self._settings, "github_repo", "")
            if not token or not repo:
                return {"error": "GitHub не настроен (нет token или repo)"}
            from src.integrations.github_api import GitHubClient
            gh = GitHubClient(token=token, repo=repo)
            prs = await gh.list_open_prs()
            return {
                "count": len(prs),
                "prs": [
                    {
                        "number": p.number,
                        "title": p.title,
                        "branch": p.branch,
                        "url": p.html_url,
                    }
                    for p in prs
                ],
            }
        except Exception as e:
            log.exception("altron_list_prs_failed")
            return {"error": str(e)[:200]}

    async def _tool_get_railway_status(self) -> dict:
        """Статус сервисов на Railway."""
        try:
            token = getattr(self._settings, "railway_api_token", "")
            project_id = getattr(self._settings, "railway_project_id", "")
            if not token or not project_id:
                return {"error": "Railway не настроен"}
            from src.integrations.railway_api import RailwayClient
            rw = RailwayClient(api_token=token, project_id=project_id)
            services = await rw.get_project_services()
            return {
                "services": [
                    {
                        "name": s.get("name", ""),
                        "status": s.get("status", "UNKNOWN"),
                    }
                    for s in services
                ],
            }
        except Exception as e:
            log.exception("altron_railway_status_failed")
            return {"error": str(e)[:200]}

    async def _tool_get_home_map(self, room: str = "") -> dict:
        """Устройства + сцены Tuya сгруппированные по комнатам."""
        try:
            from src.integrations.tuya import TuyaClient
            tuya = TuyaClient.from_settings(self._settings)
            if not tuya:
                return {"error": "Tuya не настроен"}

            room_keywords = {
                "спальня": ("спальн", "bedroom"),
                "детская": ("детск", "малыш", "кроватк", "матве"),
                "кухня": ("кухн", "kitchen"),
                "гостиная": ("гостин", "зал", "living"),
                "ванная": ("ванн", "душ", "bathroom"),
                "туалет": ("туалет", "wc"),
                "коридор": ("коридор", "прихож", "hall"),
                "балкон": ("балкон", "лоджи", "balcony"),
                "офис": ("офис", "кабинет", "office"),
            }

            def _room_of(name: str) -> str:
                n = (name or "").lower()
                for r, kws in room_keywords.items():
                    if any(k in n for k in kws):
                        return r
                return "другое"

            devices = await tuya.list_devices()
            scenes = await tuya.list_scenes()

            rooms: dict[str, dict[str, list]] = {}
            for d in devices:
                r = _room_of(d.get("name", ""))
                rooms.setdefault(r, {"devices": [], "scenes": []})
                rooms[r]["devices"].append({
                    "name": d.get("name", ""),
                    "category": d.get("category", ""),
                    "online": d.get("online", False),
                })
            for s in scenes:
                if s.get("is_automation"):
                    continue
                sname = s.get("name") or ""
                r = _room_of(sname)
                rooms.setdefault(r, {"devices": [], "scenes": []})
                rooms[r]["scenes"].append(sname)

            if room:
                needle = room.lower().strip()
                matched = None
                for r in rooms:
                    if needle in r or any(needle in k for k in room_keywords.get(r, ())):
                        matched = r
                        break
                if matched:
                    return {"room": matched, **rooms[matched]}
                return {"error": f"Не нашёл комнату «{room}»", "rooms_available": list(rooms.keys())}

            summary = {
                r: {
                    "devices_count": len(v["devices"]),
                    "online_count": sum(1 for x in v["devices"] if x["online"]),
                    "scenes_count": len(v["scenes"]),
                    "devices": [x["name"] for x in v["devices"]],
                    "scenes": v["scenes"],
                }
                for r, v in sorted(rooms.items())
            }
            return {
                "rooms": summary,
                "total_devices": len(devices),
                "total_scenes": sum(len(v["scenes"]) for v in rooms.values()),
            }
        except Exception as e:
            log.exception("altron_home_map_failed")
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

    async def handle(
        self, text: str, user_name: str = "Пользователь", chat_id: int = 0,
        on_partial=None,
    ) -> str:
        """Обработать входящее сообщение и вернуть ответ.

        Использует историю сообщений (по chat_id), защита от цикла tool-loop.

        on_partial(text) — необязательный async callback. Если передан, финальный
        текстовый ответ идёт стримом через Gemini, callback вызывается по мере
        накопления. Возвращаемое значение всё равно — финальная строка.
        """
        if not text or not text.strip():
            return "Слушаю?"

        # Ленивая подгрузка истории из БД после рестарта
        await self.load_history_from_db(chat_id)

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
        MAX_ITER = 4  # 3 → 4: чтобы сложные вопросы могли собрать 2-3 тула + ответ

        for iteration in range(MAX_ITER):
            # На последней итерации выключаем tools и заставляем ответить текстом
            force_final = iteration == MAX_ITER - 1
            # Стриминг только на форсированной финальной итерации (сложные
            # compound-ответы). Простые «привет» на iter=0 отвечают как раньше.
            if force_final and on_partial is not None and hasattr(self._gemini, "complete_stream"):
                acc = ""
                try:
                    import time as _time
                    last_edit_ts = _time.time()
                    async for chunk in self._gemini.complete_stream(
                        system=_SYSTEM_PROMPT,
                        messages=messages,
                        max_tokens=500,
                    ):
                        acc += chunk
                        if _time.time() - last_edit_ts > 0.9:
                            try:
                                await on_partial(acc)
                            except Exception:
                                pass
                            last_edit_ts = _time.time()
                    text_out = acc.strip() or self._synth_from_tool_results(messages) or "Готово."
                    self._append_history(chat_id, user_msg["role"], user_msg["content"])
                    self._append_history(chat_id, "assistant", text_out)
                    return text_out
                except Exception:
                    log.exception("altron_stream_failed_fallback_nostream")
            try:
                resp = await self._gemini.complete_with_tools(
                    system=_SYSTEM_PROMPT,
                    messages=messages,
                    tools=[] if force_final else tools,
                    max_tokens=500,
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
                # Пустой ответ на force_final — синтезируем из последних
                # tool_results вместо унылого «не смог сформулировать».
                if not text_out:
                    text_out = self._synth_from_tool_results(messages)
                self._append_history(chat_id, user_msg["role"], user_msg["content"])
                self._append_history(chat_id, "assistant", text_out or "…")
                return text_out or "Готово."

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
                synth = self._synth_from_tool_results(messages)
                if synth:
                    self._append_history(chat_id, user_msg["role"], user_msg["content"])
                    self._append_history(chat_id, "assistant", synth)
                    return synth
                return "Что-то залип. Спроси иначе?"

            # Выполняем новые вызовы параллельно — если Gemini вернул сразу
            # несколько tools, ждём их одновременно.
            messages.append({"role": "assistant", "content": content_blocks})

            async def _run_one(tc):
                sig = f"{tc.name}:{json.dumps(tc.input or {}, sort_keys=True)}"
                if sig in called_signatures and tc in duplicate_calls:
                    return tc, {"note": "already called this tool, use previous result"}
                res = await self._exec_tool(tc.name, tc.input or {})
                log.info("altron_tool_ran", name=tc.name, keys=list(res.keys())[:5])
                return tc, res

            paired = await asyncio.gather(*[_run_one(tc) for tc in tool_calls])
            tool_results = [
                {
                    "type": "tool_result",
                    "tool_use_id": tc.id,
                    "content": json.dumps(res, ensure_ascii=False, default=str),
                }
                for tc, res in paired
            ]
            messages.append({"role": "user", "content": tool_results})

            # FAST PATH: если ВСЕ вызовы были write/action-tools И все успешны
            # (или все явно неуспешны с понятным reason) — отвечаем сразу
            # из результатов, не гоняя ещё один turn через Gemini. Пользователь
            # видит команду выполненной И ответ одновременно.
            if paired and all(tc.name in _FAST_PATH_TOOLS for tc, _ in paired):
                synth = self._synth_from_results([res for _, res in paired])
                if synth:
                    self._append_history(chat_id, user_msg["role"], user_msg["content"])
                    self._append_history(chat_id, "assistant", synth)
                    return synth

        return "Слишком долго думаю. Попробуй перефразировать?"
