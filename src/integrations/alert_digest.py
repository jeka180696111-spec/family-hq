"""Дозорный digest — структурированные тревоги вместо потока постов.

Как работает:
- При alert_start отправляем скелет-карточку в чат и запоминаем tg_message_id
- Каждый alert_update пост — сохраняем в alert_posts (буфер сырых постов)
- Debounce-таймер (60с) → LLM анализирует все посты активной тревоги
- Формируем структурированный текст → editMessageText той же карточки
- При alert_clear — финальный digest в новом сообщении

LLM: сначала Claude Haiku, при пустом ключе — Gemini Flash (free tier ~1500/день).
"""
from __future__ import annotations

import asyncio
import json
import re
from typing import Any

import structlog
from sqlalchemy import select, update, insert, delete

from src.db.models import ActiveAlert, AlertPost
from src.utils.time import iso_now, now_kyiv

log = structlog.get_logger()


# ─── Промпт для LLM ─────────────────────────────────────────────────

_DIGEST_PROMPT = """Ты военный аналитик мониторинга воздушной обстановки над Украиной.
Тебе дан список постов из Telegram-каналов о ТЕКУЩЕЙ ВОЗДУШНОЙ ТРЕВОГЕ.

ГЛАВНОЕ ПРАВИЛО: агрегируй одно и то же оружие в ОДИН элемент weapons.
Не создавай отдельные entries для того же типа. Считай общее количество.

СЛОВАРЬ (обязательно применяй):
• «бандероль», «бандероли», «бандер» = КАБ (одно и то же!)
  Если посты пишут «летят 3 бандероли» → weapons: [{{"type":"КАБ","count":3}}].
  НЕ создавай отдельно "КАБ" и "бандероли" — это одно оружие.
• «шахед», «шахи», «шахеди», «герань», «geran», «дрон-камикадзе», «мопед» = Шахед
• «калібр», «калибр» = Калибр
• «Х-101», «Х-59», «Х-22», «Х-32», «Х-555», «Х-31» = соответствующий Х-ракеты
• «крылатая ракета», «крилата ракета», «КР» (без уточнения типа) = "Крылатая ракета"
• «баллистика», «балістика», «баллистическая» (без имени) = "Баллистика"
• «Іскандер», «Искандер» = Искандер
• «Кинжал», «Кинджал» = Кинжал
• «КАБ», «ФАБ», «УМПБ», «управляемая авиабомба» = соответствующая КАБ/ФАБ/УМПБ

ПРАВИЛА ПОДСЧЁТА:
1. Если один пост говорит «3 бандероли», а другой «летит бандероль» — берешь БОЛЬШЕЕ (3).
2. Не суммируй по разным постам. Один канал видит один рой — не удваивай в двух каналах.
3. «~20», потом «уточнили: 15» → бери 15 (свежее уточнение).
4. Если count не указан явно нигде → count: null (не 1).

ПРИЛЁТЫ (hits) — ловим АКТИВНО:
Ищи в постах любое из: «прилёт», «прилет», «удар по», «попадання», «попадание»,
«вибух чути», «взрыв слышен», «уражено», «поражено», «загорілось», «загорелось»,
«детонація», «детонация», «дим над», «дым над», «пожежа», «пожар» —
всё это = ПРИЛЁТ, добавляй в hits.
Даже одно упоминание = добавляй с confirmed: false.
Если явное подтверждение от 2+ каналов или официалов → confirmed: true.

Верни СТРОГО валидный JSON без markdown-обрамления по схеме:
{{
  "primary_region": "Одесская обл",
  "weapons": [
    {{"type": "Шахед", "count": 20, "origin": "море, Крым"}},
    {{"type": "КАБ", "count": 3, "origin": "с моря"}},
    {{"type": "Крылатая ракета", "count": 2, "origin": null}}
  ],
  "targets": ["Юг Одесской обл", "Овидиополь", "порт Одессы"],
  "eta": [
    {{"weapon": "Шахед", "arrival_time": "~21:47"}},
    {{"weapon": "КАБ", "arrival_time": "~09:00"}}
  ],
  "hits": [
    {{"location": "жилой дом Таирова", "detail": "2 раненых", "confirmed": false}},
    {{"location": "порт Одессы", "detail": "пожар", "confirmed": true}}
  ],
  "other_regions": [
    {{"region": "Николаевская обл", "weapons": [{{"type": "Шахед", "count": 3}}], "target": "Первомайск"}}
  ]
}}

Регион по умолчанию — Одесская обл. Параллельная тревога в другом регионе → other_regions.
ETA пиши как «~HH:MM» местного времени Одессы, только если явно есть в постах.

ВСЕГДА возвращай валидный JSON. НИКАКОГО дополнительного текста, markdown, комментариев.
"""


def _extract_json(text: str) -> dict | None:
    """LLM иногда обёртывает JSON в markdown. Вырезаем."""
    if not text:
        return None
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        text = m.group(1)
    else:
        m2 = re.search(r"(\{.*\})", text, re.DOTALL)
        if m2:
            text = m2.group(1)
    try:
        return json.loads(text)
    except Exception:
        log.warning("digest_json_parse_failed", preview=text[:200])
        return None


async def _call_llm(prompt: str, posts_text: str, *, claude_client: Any, gemini_client: Any, model_cheap: str) -> str | None:
    """Пробуем Claude, при неудаче — Gemini. Возвращаем raw text ответа."""
    full = prompt + "\n\n=== ПОСТЫ ИЗ КАНАЛОВ ===\n" + posts_text
    # Claude первым
    if claude_client:
        try:
            resp = await claude_client.complete(
                model=model_cheap,
                system="Ты military OSINT-аналитик. Отвечаешь строго JSON, без текста вокруг.",
                messages=[{"role": "user", "content": full}],
                max_tokens=800,
                temperature=0.0,
            )
            text = ""
            if hasattr(resp, "content") and resp.content:
                text = resp.content[0].text if hasattr(resp.content[0], "text") else str(resp.content[0])
            elif isinstance(resp, str):
                text = resp
            if text:
                return text
        except Exception as e:
            log.info("digest_claude_fallback_gemini", err=str(e)[:150])
    # Gemini fallback (тот же интерфейс что Claude)
    if gemini_client:
        try:
            return await gemini_client.complete(
                system="Ты military OSINT-аналитик. Отвечаешь строго JSON, без текста вокруг.",
                messages=[{"role": "user", "content": full}],
                max_tokens=800,
            )
        except Exception as e:
            log.warning("digest_gemini_failed", err=str(e)[:150])
    return None


# ─── Форматирование digest → Telegram HTML ─────────────────────────

def format_digest(digest: dict, region: str, started_at: str, sources_count: int) -> str:
    """Из JSON digest'a собираем красивое сообщение с иконками."""
    try:
        from datetime import datetime
        started = datetime.fromisoformat(started_at)
        duration_min = int((now_kyiv() - started).total_seconds() / 60)
        started_hm = started.strftime("%H:%M")
    except Exception:
        duration_min = 0
        started_hm = "?"

    lines = [f"🚨 <b>ТРЕВОГА · {region}</b> · с {started_hm} ({duration_min} мин)"]
    lines.append("─" * 20)

    weapons = digest.get("weapons") or []
    if weapons:
        lines.append("\n✈ <b>ЛЕТИТ:</b>")
        for w in weapons:
            wtype = w.get("type", "?")
            wcount = w.get("count")
            worigin = w.get("origin", "")
            row = f"• {wtype}"
            if wcount is not None:
                row += f" × {wcount}"
            if worigin:
                row += f"  ({worigin})"
            lines.append(row)

    targets = digest.get("targets") or []
    if targets:
        lines.append("\n🎯 <b>КУРС:</b>")
        for t in targets:
            lines.append(f"• {t}")

    eta = digest.get("eta") or []
    if eta:
        lines.append("\n⏱ <b>ETA:</b>")
        for e in eta:
            w = e.get("weapon", "?")
            t = e.get("arrival_time", "?")
            lines.append(f"• {w}  {t}")

    hits = digest.get("hits") or []
    if hits:
        lines.append("\n💥 <b>ПРИЛЁТЫ:</b>")
        for h in hits:
            loc = h.get("location", "?")
            detail = h.get("detail", "")
            confirmed = h.get("confirmed", False)
            marker = "" if confirmed else "  <i>(не подтверждено)</i>"
            row = f"• {loc}"
            if detail:
                row += f" — {detail}"
            row += marker
            lines.append(row)
    else:
        lines.append("\n💥 <b>ПРИЛЁТЫ:</b> пока нет")

    others = digest.get("other_regions") or []
    if others:
        lines.append("\n⚠ <b>ДРУГИЕ РЕГИОНЫ:</b>")
        for o in others:
            reg = o.get("region", "?")
            tgt = o.get("target", "")
            ws = o.get("weapons") or []
            ws_txt = ", ".join(f"{w.get('type','?')} × {w.get('count','?')}" for w in ws)
            row = f"• {reg}"
            if ws_txt:
                row += f" — {ws_txt}"
            if tgt:
                row += f" → {tgt}"
            lines.append(row)

    lines.append("─" * 20)
    lines.append(f"📡 {sources_count} источник(ов)")
    return "\n".join(lines)


def format_final_digest(digest: dict, region: str, started_at: str, duration_min: int, sources_count: int) -> str:
    """Финальное сообщение при отбое — итог тревоги."""
    lines = [f"✅ <b>ОТБОЙ · {region}</b> · длилось {duration_min} мин"]
    lines.append("─" * 20)
    lines.append("<b>Итог:</b>")

    hits = digest.get("hits") or []
    if hits:
        lines.append("\n💥 Прилёты:")
        for h in hits:
            loc = h.get("location", "?")
            detail = h.get("detail", "")
            row = f"• {loc}"
            if detail:
                row += f" — {detail}"
            lines.append(row)
    else:
        lines.append("• Прилётов не зафиксировано")

    weapons = digest.get("weapons") or []
    if weapons:
        total_shahed = sum(w.get("count", 0) for w in weapons if "шахед" in w.get("type", "").lower())
        total_missile = sum(w.get("count", 0) for w in weapons if any(k in w.get("type", "").lower() for k in ("х-", "калибр", "кинжал", "искандер", "точка")))
        if total_shahed:
            lines.append(f"• Всего шахедов: ~{total_shahed}")
        if total_missile:
            lines.append(f"• Всего ракет: ~{total_missile}")

    lines.append(f"\n📡 Проанализировано {sources_count} источник(ов)")
    return "\n".join(lines)


# ─── Основной класс, живущий рядом с NewsIngestor ──────────────────

class AlertDigestManager:
    """Управляет буфером постов и периодическим обновлением сообщения-карточки.

    Раньше был чистый debounce — обновляем только когда прилетает пост. Проблема:
    если каналы затихли, длительность не тикала. Теперь пока тревога активна
    крутится фоновый таск, который дёргает refresh_digest раз в TICK_SEC.
    """

    TICK_SEC = 60          # heartbeat пока тревога активна (тикает длительность)
    COALESCE_SEC = 3       # окно склейки: несколько постов подряд — один refresh
    _last_text: dict[str, str] = {}  # чтобы не спамить "message not modified"

    def __init__(
        self,
        memory: Any,
        bot_manager: Any,
        chat_id: int,
        claude_client: Any = None,
        gemini_client: Any = None,
        model_cheap: str = "claude-haiku-4-5-20251001",
    ) -> None:
        self._memory = memory
        self._bots = bot_manager
        self._chat_id = chat_id
        self._claude = claude_client
        self._gemini = gemini_client
        self._model = model_cheap
        # Фоновые тикеры — по региону
        self._tick_tasks: dict[str, asyncio.Task] = {}
        # Задачи-коалесеры на «свежий пост» — по региону
        self._coalesce_tasks: dict[str, asyncio.Task] = {}
        # Флаг «есть непереваренные посты» — не гоняем LLM впустую
        self._dirty: dict[str, bool] = {}

    async def add_post(self, region: str, channel_id: int, channel_title: str | None, text: str) -> None:
        """Сохранить пост в буфер. Тикер сам подхватит на ближайшем такте."""
        try:
            async with self._memory._engine.begin() as conn:
                await conn.execute(insert(AlertPost).values(
                    region=region,
                    channel_id=channel_id,
                    channel_title=channel_title,
                    text=text[:4000],
                    received_at=iso_now(),
                ))
        except Exception:
            log.exception("alert_post_save_failed", region=region)
        self._dirty[region] = True
        # Если тикер по каким-то причинам не запущен (напр. перезапуск процесса
        # с уже активной тревогой) — стартуем.
        self.start_ticker(region)
        # Немедленный refresh с коротким окном склейки: если несколько каналов
        # прислали одно и то же событие в течение 3с, дёрнем LLM один раз.
        existing = self._coalesce_tasks.get(region)
        if existing and not existing.done():
            return
        self._coalesce_tasks[region] = asyncio.create_task(self._coalesce_refresh(region))

    async def _coalesce_refresh(self, region: str) -> None:
        try:
            await asyncio.sleep(self.COALESCE_SEC)
            await self.refresh_digest(region)
        except Exception:
            log.exception("digest_coalesce_refresh_failed", region=region)
        finally:
            self._coalesce_tasks.pop(region, None)

    def start_ticker(self, region: str) -> None:
        """Запустить фоновый цикл обновления карточки. Идемпотентно."""
        existing = self._tick_tasks.get(region)
        if existing and not existing.done():
            return
        self._tick_tasks[region] = asyncio.create_task(self._tick_loop(region))
        log.info("digest_ticker_started", region=region)

    def stop_ticker(self, region: str) -> None:
        t = self._tick_tasks.pop(region, None)
        if t and not t.done():
            t.cancel()
        c = self._coalesce_tasks.pop(region, None)
        if c and not c.done():
            c.cancel()
        self._dirty.pop(region, None)
        self._last_text.pop(region, None)

    async def _tick_loop(self, region: str) -> None:
        try:
            while True:
                await asyncio.sleep(self.TICK_SEC)
                # Проверяем, не закрылась ли тревога
                async with self._memory._engine.connect() as conn:
                    aa = (await conn.execute(
                        select(ActiveAlert).where(ActiveAlert.region == region)
                    )).first()
                if not aa:
                    log.info("digest_ticker_alert_gone", region=region)
                    break
                try:
                    await self.refresh_digest(region)
                except Exception:
                    log.exception("digest_tick_refresh_failed", region=region)
        except asyncio.CancelledError:
            pass
        finally:
            self._tick_tasks.pop(region, None)

    async def refresh_digest(self, region: str) -> None:
        """Собрать посты, дёрнуть LLM, отредактировать сообщение-карточку."""
        # 1. Получить ActiveAlert (там tg_message_id)
        async with self._memory._engine.connect() as conn:
            aa = (await conn.execute(
                select(ActiveAlert).where(ActiveAlert.region == region)
            )).first()
        if not aa:
            return
        if not aa.tg_message_id:
            return

        # 2. Собрать все посты по этому региону
        async with self._memory._engine.connect() as conn:
            posts = list(await conn.execute(
                select(AlertPost).where(AlertPost.region == region)
                .order_by(AlertPost.received_at.desc()).limit(80)
            ))
        if not posts:
            return

        # 3. Сформировать текст для LLM
        posts_lines = []
        for p in posts:
            title = p.channel_title or f"channel_{p.channel_id}"
            posts_lines.append(f"[{p.received_at}] {title}: {p.text[:500]}")
        posts_text = "\n\n".join(posts_lines[:40])  # последние 40, старше — не отдаём

        # 4. LLM
        raw = await _call_llm(
            _DIGEST_PROMPT, posts_text,
            claude_client=self._claude, gemini_client=self._gemini,
            model_cheap=self._model,
        )
        if not raw:
            log.warning("digest_llm_no_response", region=region)
            return
        digest = _extract_json(raw)
        if not digest:
            log.warning("digest_json_invalid", region=region, raw_preview=raw[:200])
            return

        # 5. Отформатировать
        primary_region = digest.get("primary_region") or region
        text = format_digest(digest, primary_region, aa.started_at, len(posts))

        # 6. Обновить БД
        try:
            async with self._memory._engine.begin() as conn:
                await conn.execute(
                    update(ActiveAlert).where(ActiveAlert.region == region).values(
                        digest_json=json.dumps(digest, ensure_ascii=False),
                        last_update_at=iso_now(),
                    )
                )
        except Exception:
            log.exception("digest_save_failed", region=region)

        # 7. Редактируем сообщение — но пропускаем, если контент идентичен
        prev = self._last_text.get(region)
        if prev == text:
            log.debug("digest_skip_same_text", region=region)
            self._dirty[region] = False
            return
        try:
            ok = await self._bots.edit_message(
                agent_id="news", chat_id=self._chat_id,
                message_id=aa.tg_message_id, text=text,
            )
            self._last_text[region] = text
            self._dirty[region] = False
            log.info("digest_refreshed", region=region, sources=len(posts), edit_ok=ok)
        except Exception:
            log.exception("digest_edit_failed", region=region)

    async def send_final(self, region: str, duration_min: int) -> None:
        """Финальное сообщение при отбое."""
        async with self._memory._engine.connect() as conn:
            aa = (await conn.execute(
                select(ActiveAlert).where(ActiveAlert.region == region)
            )).first()
        digest = {}
        if aa and aa.digest_json:
            try:
                digest = json.loads(aa.digest_json)
            except Exception:
                digest = {}

        async with self._memory._engine.connect() as conn:
            posts_count = len(list(await conn.execute(
                select(AlertPost.id).where(AlertPost.region == region)
            )))

        text = format_final_digest(digest, region, aa.started_at if aa else "", duration_min, posts_count)
        try:
            await self._bots.send_message(agent_id="news", chat_id=self._chat_id, text=text)
        except Exception:
            log.exception("digest_final_failed", region=region)

    async def cleanup_after_alert(self, region: str) -> None:
        """Удалить буфер постов после отбоя (чтоб не рос бесконечно)."""
        try:
            async with self._memory._engine.begin() as conn:
                await conn.execute(delete(AlertPost).where(AlertPost.region == region))
        except Exception:
            log.exception("alert_posts_cleanup_failed", region=region)
        self.stop_ticker(region)

    def initial_skeleton(self, region: str) -> str:
        """Скелет-карточка отправляется первой при alert_start."""
        started_hm = now_kyiv().strftime("%H:%M")
        return (
            f"🚨 <b>ТРЕВОГА · {region}</b> · с {started_hm}\n"
            + "─" * 20
            + "\n⏳ Собираю данные из каналов…\n"
            + "─" * 20
            + "\n📡 Первое обновление через ~1 мин"
        )
