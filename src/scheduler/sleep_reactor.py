"""Reactive sleep watcher.

Every 2 minutes scans the Дневник for new sleep entries (start/end).
When a fresh row appears that we haven't seen before, Няня reacts in
chat: «уснул в 12:15, как планировали → проснётся около 13:30», etc.

Uses a small in-memory set of seen row signatures so we don't
double-comment on the same entry. On process restart the set is empty —
we backfill recent rows quietly without commenting (so a deploy doesn't
spam old entries).
"""
from __future__ import annotations

from datetime import timedelta
from typing import Any

import structlog

log = structlog.get_logger()


class SleepReactor:
    # How far back to scan for new entries on each tick.
    _LOOKBACK_MIN = 30

    def __init__(
        self,
        memory: Any,
        nanny_agent: Any,
        bot_manager: Any,
        chat_id: int,
    ) -> None:
        self._memory = memory
        self._nanny = nanny_agent
        self._bots = bot_manager
        self._chat_id = chat_id
        self._seen: set[str] = set()
        self._primed = False  # First tick after startup: backfill, don't comment

    def _sig(self, row_data: dict) -> str:
        return f"{row_data.get('date','')}|{row_data.get('time','')}|{(row_data.get('event','') or '').lower()[:40]}"

    async def tick(self) -> None:
        try:
            from src.utils.chat_activity import is_chat_active
            if is_chat_active(within_seconds=90):
                return
        except Exception:
            pass
        try:
            from src.integrations.sleep_coach import (
                _parse_entry_dt, _kind_clean, _is_start, _is_end,
                next_sleep_advice,
            )
            from src.utils.time import now_kyiv

            sheets = getattr(self._nanny, "_sheets", None)
            if not sheets:
                return
            rows = await sheets.get_baby_diary(days=1)
            now = now_kyiv()
            cutoff = now - timedelta(minutes=self._LOOKBACK_MIN)

            fresh: list[dict] = []
            for r in rows:
                d = r.data
                if _kind_clean(d.get("kind", "")) not in ("сон", "sleep"):
                    continue
                dt = _parse_entry_dt(d)
                if dt is None or dt < cutoff:
                    # Still mark as seen to avoid commenting if it's
                    # re-edited; but не считаем fresh.
                    self._seen.add(self._sig(d))
                    continue
                sig = self._sig(d)
                if sig in self._seen:
                    continue
                self._seen.add(sig)
                ev = (d.get("event") or "").strip()
                kind_evt = "start" if _is_start(ev) else "end" if _is_end(ev) else "ambiguous"
                fresh.append({"dt": dt, "event": ev, "kind": kind_evt})

            # First tick after startup: don't react to anything we just
            # saw — those entries existed BEFORE our process came up.
            if not self._primed:
                self._primed = True
                return
            if not fresh:
                return

            # Take the freshest event only — if Marina logged two within
            # the lookback window, the latest one drives the comment.
            fresh.sort(key=lambda x: x["dt"], reverse=True)
            ev = fresh[0]
            if ev["kind"] == "ambiguous":
                return

            advice = await next_sleep_advice(sheets)

            # Подмешиваем свежий контекст из advice_tracker: какие
            # советы давала Няня ранее и насколько они сбылись.
            try:
                from src.integrations.advice_tracker import recent_advice_summary
                adv_history = await recent_advice_summary(
                    self._memory, "nanny", days=2,
                )
            except Exception:
                adv_history = ""

            # Климат в детской + доступные сцены Tuya — Няня учитывает
            # при планировании и может попросить Дворецкого запустить
            # конкретную СУЩЕСТВУЮЩУЮ сцену (не выдумывать).
            climate_info = ""
            available_scenes: list[str] = []
            try:
                from src.config import get_settings
                from src.integrations.tuya import TuyaClient
                settings = get_settings()
                tuya = TuyaClient.from_settings(settings)
                if tuya:
                    sensor_name = settings.baby_room_sensor_name or "детская"
                    sensor = await tuya.read_sensor(sensor_name)
                    if isinstance(sensor, dict) and "readings" in sensor:
                        r = sensor.get("readings") or {}
                        climate_info = (
                            f"Датчик в детской: "
                            f"{r.get('temperature','?')}, "
                            f"{r.get('humidity','?')}, "
                            f"батарея {r.get('battery','?')}. "
                            f"Норма для сна: {settings.baby_room_temp_min}-"
                            f"{settings.baby_room_temp_max}°C, влажность "
                            f"{settings.baby_room_humidity_min}-"
                            f"{settings.baby_room_humidity_max}%."
                        )
                    # Собираем СЦЕНЫ (не автоматизации) для промпта
                    try:
                        all_scenes = await tuya.list_scenes()
                        available_scenes = [
                            s["name"] for s in all_scenes
                            if s.get("name") and not s.get("is_automation")
                        ]
                    except Exception:
                        pass
            except Exception:
                log.exception("sleep_reactor_climate_failed")

            if ev["kind"] == "start":
                base = f"Записал: уснул в {ev['dt'].strftime('%H:%M')}."
            else:
                base = f"Записал: проснулся в {ev['dt'].strftime('%H:%M')}."

            adv_text = (advice or {}).get("summary_for_agent", "")
            is_wake = ev["kind"] == "end"
            climate_block = f"\n\nКЛИМАТ В ДЕТСКОЙ (только что):\n{climate_info}\n" if climate_info else ""
            scenes_block = ""
            if available_scenes:
                scenes_block = (
                    "\n\nДОСТУПНЫЕ СЦЕНЫ TUYA (используй ТОЛЬКО эти имена ДОСЛОВНО):\n"
                    + "\n".join(f"  • {n}" for n in available_scenes)
                )
            climate_action_rule = ""
            if climate_info:
                if available_scenes:
                    climate_action_rule = (
                        "\n\nЕСЛИ КЛИМАТ ВНЕ НОРМЫ — в самом конце ответа добавь "
                        "ОТДЕЛЬНУЮ ПОСЛЕДНЮЮ СТРОКУ которая ОБЯЗАТЕЛЬНО начинается "
                        "со слова «Дворецкий» (иначе он не поймёт что это ему).\n"
                        "Формат: «Дворецкий, <причина> — запусти сцену «<точное имя>».»\n"
                        "Примеры (подставь СВОЁ имя сцены из списка):\n"
                        "  «Дворецкий, 26°C жарко — запусти сцену «Кондер 24 авто».»\n"
                        "  «Дворецкий, 17°C холодно — запусти сцену «Кондер 25 авто».»\n"
                        "Слово «Дворецкий» ОБЯЗАТЕЛЬНО в начале строки — без него "
                        "он проигнорирует.\n"
                        "НИКОГДА не выдумывай имена — если в списке нет подходящей сцены, "
                        "просто напиши «Марине: в детской жарко/холодно, подстрой вручную» "
                        "(без слова «Дворецкий»). Если климат в норме — эту строку "
                        "не добавляй вообще."
                    )
                else:
                    climate_action_rule = (
                        "\n\nЕСЛИ КЛИМАТ ВНЕ НОРМЫ — предупреди Марину "
                        "в конце ответа отдельной строкой («в детской "
                        "26°C — жарко, стоит проветрить или включить кондер»)."
                    )

            if is_wake:
                # При пробуждении — Няня даёт развёрнутый анализ как
                # опытный sleep coach (как ChatGPT). Не «отлично выспался»
                # шаблонно, а реальный разбор timeline и совет.
                prompt = (
                    f"Маринa только что внесла: «{ev['event']}» в "
                    f"{ev['dt'].strftime('%H:%M')}.\n\n"
                    f"СЫРЫЕ ДАННЫЕ ДЛЯ АНАЛИЗА:\n{adv_text}\n\n"
                    f"ТВОИ ПРОШЛЫЕ СОВЕТЫ И КАК ОНИ СБЫЛИСЬ:\n"
                    f"{adv_history or '(пока нет истории)'}"
                    f"{climate_block}{scenes_block}\n"
                    "Напиши Марине развёрнутый ответ как опытный sleep coach.\n\n"
                    "СТРУКТУРА (свободная, но всегда содержит):\n"
                    "• Факт: что именно получилось — длительность, как "
                    "соотносится с обычной для Матвея.\n"
                    "• ЧЕСТНОЕ сравнение с твоим прошлым советом: если "
                    "ты говорила «уложить в 13:00» а уложили в 14:00 — "
                    "это НЕ «идёт по плану», это сдвиг на час. Признай.\n"
                    "• Действие: следующий конкретный шаг — HH:MM "
                    "следующего сна, желаемая длительность.\n\n"
                    "ТОН: тёплый, опытный. Без сюсюканья, без 🤱 💕 🥰.\n"
                    "Длительности — в формате Хч YYм.\n"
                    "Длина: 4-8 строк."
                    f"{climate_action_rule}"
                )
            else:
                prompt = (
                    f"Маринa только что внесла: «{ev['event']}» в "
                    f"{ev['dt'].strftime('%H:%M')}.\n\n"
                    f"{base}\n\nКонтекст:\n{adv_text}\n\n"
                    f"Твои прошлые советы:\n{adv_history or '(нет)'}"
                    f"{climate_block}{scenes_block}\n"
                    "Напиши КОРОТКОЕ (1-2 строки) подтверждение. "
                    "Когда планируется пробуждение (HH:MM). "
                    "ВАЖНО: если ты ранее советовала уложить в одно "
                    "время, а уложили в другое — НЕ пиши «идёт по плану». "
                    "Честно: «сдвинули на N минут позже» / «как и собирались». "
                    "Длительности в формате Хч YYм."
                    f"{climate_action_rule}"
                )
            try:
                text = await self._nanny._claude.complete(
                    model=self._nanny._get_model(),
                    system="Ты — Няня. Реактивный комментарий после записи о сне.",
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=800 if is_wake else 250,
                )
            except Exception:
                log.exception("sleep_reactor_llm_failed")
                return
            text = (text or "").strip()
            if not text:
                return
            try:
                await self._bots.send_message(
                    agent_id="nanny", chat_id=self._chat_id, text=text,
                )
                log.info("sleep_reactor_commented", kind=ev["kind"], event=ev["event"][:40])
            except Exception:
                log.exception("sleep_reactor_send_failed")
                return

            # Если Няня в ответе просит Дворецкого что-то сделать
            # (строка начинается с «Дворецкий») — выполняем директиву
            # прямо здесь: находим сцену в тексте, запускаем через Tuya,
            # Дворецкий постит подтверждение.
            try:
                await self._maybe_execute_butler_directive(text)
            except Exception:
                log.exception("sleep_reactor_butler_directive_failed")

            # Если Матвей только что проснулся — следом шлём план
            # бодрствования (что делать в это окно). Только на «end»
            # событие, чтобы не дёргать после «уснул».
            if ev["kind"] == "end":
                await self._push_wake_plan()
                # Записать ожидание по следующему сну для tracking
                try:
                    from src.integrations.advice_tracker import record_advice
                    from datetime import datetime as _dt, timedelta as _td
                    nx = (advice or {}).get("next_sleep_at") if isinstance(advice, dict) else None
                    if nx:
                        # advice уже посчитан внутри _next_sleep_advice
                        # Сохраним target_at и duration (берём средний nap target)
                        target_dur = (advice or {}).get("target_min") or 0
                        # Парсим HH:MM в datetime сегодня (или завтра если HH:MM уже прошёл)
                        try:
                            h, m = nx.split(":")
                            now = ev["dt"]
                            t = now.replace(hour=int(h), minute=int(m), second=0, microsecond=0)
                            if t < now:
                                t = t + _td(days=1)
                            await record_advice(
                                self._memory, "nanny", "nap_target",
                                {
                                    "target_at": t.isoformat(),
                                    "target_duration_min": int(target_dur) if target_dur else None,
                                    "source_awake_since": ev["dt"].isoformat(),
                                },
                            )
                        except Exception:
                            log.exception("sleep_advice_record_failed")
                except Exception:
                    log.exception("sleep_advice_hook_failed")
        except Exception:
            log.exception("sleep_reactor_tick_failed")

    async def _maybe_execute_butler_directive(self, nanny_reply: str) -> None:
        """Если в ответе Няни есть строка «Дворецкий, ... запусти сцену «X»»
        — найти сцену в Tuya, запустить, отправить подтверждение как Дворецкий.
        """
        import re
        if "дворецкий" not in nanny_reply.lower():
            return
        # Извлекаем строку с обращением к Дворецкому
        butler_lines = [
            ln for ln in nanny_reply.splitlines()
            if ln.lower().lstrip().startswith("дворецкий")
        ]
        if not butler_lines:
            return
        for line in butler_lines:
            # Ищем имя сцены в кавычках «...»
            m = re.search(r"«([^»]+)»", line)
            scene_query = m.group(1) if m else line
            try:
                from src.config import get_settings
                from src.integrations.tuya import TuyaClient
                tuya = TuyaClient.from_settings(get_settings())
                if not tuya:
                    continue
                match = await tuya.find_scene(scene_query)
                if not match or match.get("ambiguous"):
                    await self._bots.send_message(
                        agent_id="butler", chat_id=self._chat_id,
                        text=f"🏠 Не нашёл сцену «{scene_query}» — не могу выполнить.",
                    )
                    continue
                result = await tuya.run_scene(match["id"])
                if result.get("success"):
                    await self._bots.send_message(
                        agent_id="butler", chat_id=self._chat_id,
                        text=f"🏠 ✅ Запустил сцену «{match['name']}» по просьбе Няни",
                    )
                    log.info("butler_directive_executed", scene=match["name"])
                else:
                    err = str(result.get("raw", ""))[:100]
                    await self._bots.send_message(
                        agent_id="butler", chat_id=self._chat_id,
                        text=f"🏠 ❌ Не смог запустить «{match['name']}»: {err}",
                    )
            except Exception:
                log.exception("butler_directive_error", line=line[:100])

    async def _push_wake_plan(self) -> None:
        try:
            plan = await self._nanny._wake_window_plan()
        except Exception:
            log.exception("wake_plan_compute_failed")
            return
        text = (plan or {}).get("plan_text", "").strip()
        if not text:
            return
        try:
            await self._bots.send_message(
                agent_id="nanny", chat_id=self._chat_id,
                text=f"🌞 <b>План на это бодрствование</b>\n{text}",
            )
            log.info("wake_plan_pushed")
        except Exception:
            log.exception("wake_plan_send_failed")


def register_sleep_reactor_job(scheduler, reactor: SleepReactor) -> None:
    scheduler.add_job(
        reactor.tick, "interval", minutes=2,
        id="sleep_reactor", replace_existing=True,
    )
    log.info("sleep_reactor_registered")
