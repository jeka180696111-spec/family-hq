"""Medical photo memory: archive medical document photos (УЗИ, анализы,
эпикризы, рецепты) to Google Drive into per-person folders + run vision
OCR so Айболит/Няня can comment on the results.

Folder layout in Drive:
    🏥 Здоровье/
        👨 Евгений · Здоровье / 2026-06 / *.jpg
        👩 Марина · Здоровье / 2026-06 / *.jpg
        👶 Матвей · Здоровье / 2026-06 / *.jpg

Vision OCR is best-effort: if it fails or LLM is offline, the file is still
saved and the user gets a clear ack.
"""
from __future__ import annotations

import os
import re
from datetime import datetime
from typing import Any

import structlog

from src.utils.time import now_kyiv

log = structlog.get_logger()


# ─── Detection ──────────────────────────────────────────────────────

_MEDICAL_KEYWORDS = (
    "узи", "узд", "узд органов", "узд серця", "ехо", "эхо",
    "анализ", "аналіз", "анализы", "аналізи",
    "кровь", "кров", "моча", "сеча", "биохимия", "біохімія",
    "гормон", "гормони",
    "кардиограмм", "екг", "экг",
    "рентген", "флюрограф", "флг", "флюорограф",
    "мрт", "кт", "томограф",
    "эпикриз", "епікриз", "выписка", "виписка",
    "заключение", "висновок",
    "диагноз", "діагноз",
    "осмотр", "огляд",
    "направление", "направлення",
    "рецепт",
    "приём", "прийом",
    "педиатр", "терапевт", "невролог", "ортопед", "офтальмолог",
    "невропатолог", "хирург", "фтизиатр", "лор",
    "доктор", "лікар", "врач",
    "больниц", "поліклін", "клінік", "клиник",
    "консультация", "консультація",
    "медкарт", "карточк",
)

# Person → display name + drive folder name
_PERSON_FOLDERS = {
    "eugene": "👨 Евгений · Здоровье",
    "marina": "👩 Марина · Здоровье",
    "matvey": "👶 Матвей · Здоровье",
}

_PERSON_KEYWORDS = {
    "eugene": (
        "евген", "женя", "жени", "жене", "жень", "женю",
        "муж", "мужа", "мужу", "отец", "отца", "мой ", "моих ",
        "мои анализ", "мне ", "мой узи", "мой осмотр", "мой эпикриз",
    ),
    "marina": (
        "марин", "марины", "марине", "жена", "жены", "жене",
        "мать", "мам",
    ),
    "matvey": (
        "матвей", "матве", "малыш", "малыша", "малышу",
        "сын", "сына", "сыну", "ребёнк", "ребенк",
    ),
}


def is_medical_photo(caption: str) -> bool:
    text = (caption or "").lower()
    if not text:
        return False
    for kw in _MEDICAL_KEYWORDS:
        if kw in text:
            return True
    return False


def detect_person(caption: str, default: str = "matvey") -> str:
    """Decide who the medical document belongs to based on caption.
    Default = matvey (most common case in this family)."""
    text = (caption or "").lower()
    for person, kws in _PERSON_KEYWORDS.items():
        for kw in kws:
            if kw in text:
                return person
    return default


# ─── Vision OCR + medical interpretation ────────────────────────────

_VISION_SYSTEM = (
    "Ты — медицинский ассистент семьи. Тебе показывают фото медицинского "
    "документа (УЗИ, анализы, эпикриз, рецепт, заключение врача). "
    "Твоя задача:\n"
    "1) Прочитай документ и извлеки ключевые факты: дата, кто пациент, "
    "что за исследование/анализ, основные показатели и их значения, "
    "выводы врача.\n"
    "2) Кратко (4-8 строк) перескажи человеку на русском что в документе. "
    "Используй структуру:\n"
    "   📄 Что: <тип документа>\n"
    "   📅 Дата: <если видна>\n"
    "   🔍 Ключевые показатели: <с цифрами>\n"
    "   📝 Вывод: <словами врача или «без патологий», если так указано>\n"
    "   ⚠️ Тревожные моменты: <если есть отклонения — назови>\n"
    "3) НЕ ставь диагнозов, не назначай лечение. Если что-то выходит за "
    "пределы нормы — прямо скажи «обсудить с лечащим врачом».\n"
    "4) Если фото нечёткое или это не медицинский документ — честно скажи "
    "«не могу прочитать» и опиши что видишь."
)


async def interpret_medical_photo(image_path: str, caption: str) -> str:
    """Vision OCR + structured interpretation. Returns text ready for chat."""
    from src.config import get_settings
    from src.integrations.gemini_client import GeminiClient

    settings = get_settings()
    gemini = GeminiClient.from_settings(settings)
    if not gemini:
        return "⚠️ Vision-модель не настроена (нет Gemini-ключей)."
    prompt = (
        f"Подпись пользователя: «{caption or '—'}»\n\n"
        "Прочитай этот медицинский документ по инструкции."
    )
    try:
        return await gemini.vision_complete(
            image_path=image_path,
            prompt=prompt,
            system=_VISION_SYSTEM,
            max_tokens=900,
        )
    except Exception as e:
        log.exception("medical_vision_failed")
        return f"⚠️ Не удалось распознать документ: {str(e)[:200]}"


# ─── Drive upload ───────────────────────────────────────────────────

async def archive_medical_photo(
    local_path: str,
    caption: str,
    person: str,
    interpretation: str,
    drive_client: Any,
) -> dict:
    """Upload photo to per-person Drive folder, embedding the vision
    interpretation as the file description. Each photo gets a unique
    suffix so album members don't collide on identical filenames."""
    import uuid
    when = now_kyiv()
    safe_caption = (caption or "").strip()[:100]
    ext = os.path.splitext(local_path)[1] or ".jpg"
    person_folder = _PERSON_FOLDERS.get(person, _PERSON_FOLDERS["matvey"])
    # uuid suffix (8 chars) guarantees uniqueness even when the whole
    # album has the same caption — all 3 photos save side by side instead
    # of colliding into one row.
    unique = uuid.uuid4().hex[:8]
    drive_name = (
        f"{when.strftime('%Y-%m-%d_%H%M%S')}_{person}"
        f"_{re.sub(r'[^A-Za-zА-Яа-я0-9._-]+', '_', safe_caption)[:40] or 'med'}"
        f"_{unique}{ext}"
    )

    drive_file_id = None
    drive_url = None
    upload_error = None
    if drive_client:
        try:
            folder_id = await drive_client.ensure_path([
                "🏥 Здоровье",
                person_folder,
                when.strftime("%Y-%m"),
            ])
            result = await drive_client.upload(
                local_path, drive_name, folder_id,
                description=(
                    f"Пациент: {person_folder}\n"
                    f"Подпись: {safe_caption}\n\n"
                    f"--- Распознанное содержимое ---\n{interpretation[:4000]}"
                ),
            )
            drive_file_id = result.get("id")
            drive_url = result.get("url")
            log.info("medical_photo_uploaded", file_id=drive_file_id, person=person)
        except Exception as e:
            log.exception("medical_photo_upload_failed")
            upload_error = str(e)[:200]
    else:
        upload_error = "drive_not_configured"

    return {
        "person": person,
        "person_label": person_folder,
        "drive_id": drive_file_id,
        "drive_url": drive_url,
        "drive_name": drive_name,
        "error": upload_error,
    }
