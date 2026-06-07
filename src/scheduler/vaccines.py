"""Seed Ukrainian vaccination schedule into Google Calendar for the baby.

Idempotent: marks each seeded event with `#vacc-seed:<id>` in description
and skips on re-run. Schedule per Наказ МОЗ України.

Baby Матвей DOB: 02.12.2025 — past vaccines (0-6 мес) assumed already done;
we seed only future ones.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

import structlog

from src.utils.time import KYIV_TZ

log = structlog.get_logger()

BABY_DOB = datetime(2025, 12, 2, 10, 0, tzinfo=KYIV_TZ)


@dataclass
class VaccineItem:
    seed_id: str          # stable identifier embedded in description
    age_months: int       # age of baby on vaccination day
    title: str
    notes: str


# Future-only items (baby already 6 months on 07.06.2026)
SCHEDULE: list[VaccineItem] = [
    VaccineItem("checkup-9mo", 9, "👶 Профосмотр педиатра (9 мес)",
                "Плановый осмотр. Вес, рост, развитие."),
    VaccineItem("vacc-12mo", 12, "💉 Прививка КПК-1 + PCV-3 (12 мес)",
                "Корь-Паротит-Краснуха (1-я) + Пневмококк (3-я). Запиши в поликлинике."),
    VaccineItem("checkup-12mo", 12, "👶 Профосмотр педиатра (12 мес)",
                "Год — большой осмотр, плюс ОАК/ОАМ."),
    VaccineItem("vacc-18mo", 18, "💉 АКДС-4 + Hib-4 + ОПВ-2 (18 мес)",
                "Ревакцинация АКДС, Hib и оральная полио."),
    VaccineItem("checkup-18mo", 18, "👶 Профосмотр педиатра (18 мес)",
                "Осмотр, оценка речи и моторики."),
    VaccineItem("vacc-6yr", 72, "💉 АДС + КПК-2 + ОПВ-3 (6 лет)",
                "Перед школой: АДС, корь-паротит-краснуха (2-я), ОПВ."),
    VaccineItem("vacc-14yr", 168, "💉 ОПВ-4 (14 лет)",
                "Ревакцинация ОПВ."),
    VaccineItem("vacc-16yr", 192, "💉 АДС-М (16 лет)",
                "Взрослая доза дифтерия-столбняк."),
]


def _add_months(base: datetime, months: int) -> datetime:
    y = base.year + (base.month - 1 + months) // 12
    m = (base.month - 1 + months) % 12 + 1
    # Clamp day if target month is shorter
    d = min(base.day, [31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1])
    return base.replace(year=y, month=m, day=d)


async def seed_baby_vaccines(calendar_client, force: bool = False) -> dict:
    """Seed missing vaccine events. Returns {created, skipped}."""
    if not calendar_client:
        return {"error": "no_calendar"}
    # Look forward 16 years to cover the whole schedule
    try:
        existing = await calendar_client.list_upcoming(days=365 * 16)
    except Exception:
        log.exception("vaccines_list_upcoming_failed")
        existing = []
    existing_ids = set()
    for ev in existing:
        desc = (getattr(ev, "description", "") or "")
        for it in SCHEDULE:
            if f"#vacc-seed:{it.seed_id}" in desc:
                existing_ids.add(it.seed_id)

    created = 0
    skipped = 0
    for it in SCHEDULE:
        if it.seed_id in existing_ids and not force:
            skipped += 1
            continue
        start = _add_months(BABY_DOB, it.age_months)
        # Past dates — skip silently
        if start < datetime.now(KYIV_TZ):
            skipped += 1
            continue
        end = start + timedelta(hours=1)
        try:
            await calendar_client.create_event(
                title=it.title,
                start=start,
                end=end,
                description=f"{it.notes}\n\n#vacc-seed:{it.seed_id}",
                color_id="10" if it.seed_id.startswith("vacc") else "2",
            )
            created += 1
            log.info("vaccine_seeded", seed_id=it.seed_id, start=start.isoformat())
        except Exception:
            log.exception("vaccine_seed_failed", seed_id=it.seed_id)
    return {"created": created, "skipped": skipped, "total": len(SCHEDULE)}


async def register_vaccine_seed_once(calendar_client, memory) -> None:
    """Run seeder once on startup (idempotent — safe to re-run)."""
    try:
        result = await seed_baby_vaccines(calendar_client)
        log.info("vaccine_seed_done", **result)
        result2 = await seed_family_health(calendar_client)
        log.info("family_health_seed_done", **result2)
    except Exception:
        log.exception("vaccine_seed_startup_failed")


# ─── Family health checkups (not baby vaccines) ─────────────────────

@dataclass
class HealthCheckup:
    seed_id: str
    when: datetime
    title: str
    notes: str


def _ua_dt(y: int, m: int, d: int, hh: int = 10) -> datetime:
    return datetime(y, m, d, hh, 0, tzinfo=KYIV_TZ)


FAMILY_HEALTH: list[HealthCheckup] = [
    HealthCheckup(
        seed_id="eugene-phthisiologist-2026-06-18",
        when=_ua_dt(2026, 6, 18, 10),
        title="🫁 Евгений — фтизиатр, плановый осмотр",
        notes=(
            "3 месяца после окончания курса. Что взять: выписку, последние "
            "снимки, журнал самочувствия. Айболит подготовит чек-лист за день."
        ),
    ),
    # follow-ups every 3 months for the first year off-meds
    HealthCheckup(
        seed_id="eugene-phthisiologist-2026-09-18",
        when=_ua_dt(2026, 9, 18, 10),
        title="🫁 Евгений — фтизиатр, контроль (6 мес off-meds)",
        notes="Полугодовой контроль после курса.",
    ),
    HealthCheckup(
        seed_id="eugene-phthisiologist-2026-12-18",
        when=_ua_dt(2026, 12, 18, 10),
        title="🫁 Евгений — фтизиатр, годовой осмотр",
        notes="Год после окончания курса.",
    ),
]


async def seed_family_health(calendar_client) -> dict:
    if not calendar_client:
        return {"error": "no_calendar"}
    try:
        existing = await calendar_client.list_upcoming(days=365 * 3)
    except Exception:
        existing = []
    seeded = set()
    for ev in existing:
        desc = getattr(ev, "description", "") or ""
        for it in FAMILY_HEALTH:
            if f"#health-seed:{it.seed_id}" in desc:
                seeded.add(it.seed_id)
    created = 0
    skipped = 0
    for it in FAMILY_HEALTH:
        if it.seed_id in seeded:
            skipped += 1
            continue
        if it.when < datetime.now(KYIV_TZ):
            skipped += 1
            continue
        try:
            await calendar_client.create_event(
                title=it.title,
                start=it.when,
                end=it.when + timedelta(hours=1),
                description=f"{it.notes}\n\n#health-seed:{it.seed_id}",
                color_id="4",  # Flamingo / red — medical
            )
            created += 1
            log.info("family_health_seeded", seed_id=it.seed_id)
        except Exception:
            log.exception("family_health_seed_failed", seed_id=it.seed_id)
    return {"created": created, "skipped": skipped, "total": len(FAMILY_HEALTH)}
