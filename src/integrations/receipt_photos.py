"""Receipt photo handling — Vision OCR for sum/store, archive to Drive.

Финансовый бот (Фінн) у нас внешний и сам видит чат, так что мы не
дублируем его работу — наша задача:
  1. Распознать что это чек (через classify_photo)
  2. Извлечь ключевые поля (сумма, магазин, дата) Vision-OCR'ом
  3. Сохранить файл на Drive в папку «🧾 Чеки / YYYY-MM/»
  4. Кинуть в чат короткую сводку, на которую Фінн (или сам юзер) среагирует
"""
from __future__ import annotations

import json
import os
import re
import uuid
from typing import Any

import structlog

from src.utils.time import now_kyiv

log = structlog.get_logger()


RECEIPT_FOLDER = "🧾 Чеки"


_VISION_SYSTEM = (
    "Ты — парсер чеков. Тебе показывают фото чека из магазина / квитанции / "
    "распечатки оплаты. Верни СТРОГО JSON со следующими полями (без markdown, "
    "без комментариев):\n"
    '{"sum": <число грн или null>, "currency": "UAH"|"USD"|"EUR"|null, '
    '"store": "<название магазина или null>", '
    '"date": "<YYYY-MM-DD или null>", '
    '"items": [<основные позиции>], '
    '"category": "<продукты|аптека|топливо|кафе|связь|услуги|другое>"}'
)


async def parse_receipt(image_path: str) -> dict:
    """Vision OCR → structured fields. Returns {} on parse failure."""
    from src.config import get_settings
    from src.integrations.gemini_client import GeminiClient
    gemini = GeminiClient.from_settings(get_settings())
    if not gemini:
        return {}
    try:
        raw = await gemini.vision_complete(
            image_path=image_path,
            system=_VISION_SYSTEM,
            prompt="Распарси чек и верни JSON по схеме.",
            max_tokens=500,
        )
    except Exception:
        log.exception("receipt_parse_failed")
        return {}
    raw = (raw or "").strip()
    # Strip markdown code fences if present
    fence_match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not fence_match:
        return {}
    try:
        return json.loads(fence_match.group(0))
    except json.JSONDecodeError:
        return {}


async def archive_receipt(
    local_path: str, parsed: dict, drive_client: Any,
) -> dict:
    """Upload to Drive «🧾 Чеки / YYYY-MM/»."""
    when = now_kyiv()
    ext = os.path.splitext(local_path)[1] or ".jpg"
    safe_store = re.sub(
        r"[^A-Za-zА-Яа-я0-9._-]+", "_",
        (parsed.get("store") or "")[:30],
    ).strip("_") or "shop"
    sum_part = f"{parsed['sum']:.0f}грн" if parsed.get("sum") else "??"
    unique = uuid.uuid4().hex[:6]
    drive_name = (
        f"{when.strftime('%Y-%m-%d_%H%M')}_{sum_part}_{safe_store}_{unique}{ext}"
    )

    drive_file_id = None
    drive_url = None
    upload_error = None
    if drive_client:
        try:
            folder_id = await drive_client.ensure_path([
                RECEIPT_FOLDER, when.strftime("%Y-%m"),
            ])
            result = await drive_client.upload(
                local_path, drive_name, folder_id,
                description=(
                    f"Сумма: {parsed.get('sum') or '?'} "
                    f"{parsed.get('currency') or 'UAH'}\n"
                    f"Магазин: {parsed.get('store') or '—'}\n"
                    f"Дата: {parsed.get('date') or '—'}\n"
                    f"Категория: {parsed.get('category') or '—'}\n"
                    f"Позиции: {', '.join(parsed.get('items') or [])[:300]}"
                ),
            )
            drive_file_id = result.get("id")
            drive_url = result.get("url")
        except Exception as e:
            log.exception("receipt_upload_failed")
            upload_error = str(e)[:200]
    else:
        upload_error = "drive_not_configured"

    return {
        "drive_id": drive_file_id,
        "drive_url": drive_url,
        "drive_name": drive_name,
        "error": upload_error,
    }


def format_summary(parsed: dict, drive_url: str | None) -> str:
    lines = ["🧾 <b>Чек сохранён</b>"]
    if parsed.get("sum") is not None:
        cur = parsed.get("currency") or "UAH"
        lines.append(f"💰 Сумма: <b>{parsed['sum']} {cur}</b>")
    if parsed.get("store"):
        lines.append(f"🏪 {parsed['store']}")
    if parsed.get("date"):
        lines.append(f"📅 {parsed['date']}")
    if parsed.get("category"):
        lines.append(f"📂 Категория: {parsed['category']}")
    items = parsed.get("items") or []
    if items:
        lines.append(f"📋 {', '.join(items[:6])}" + (" …" if len(items) > 6 else ""))
    if drive_url:
        lines.append(f'\n☁️ <a href="{drive_url}">Открыть на Drive</a>')
    return "\n".join(lines)
