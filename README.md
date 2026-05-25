# Family HQ

Мульти-агентна Telegram-система для сім'ї.

7 ІІ-агентів в одній групі: щоденник малюка, новини/тривоги, фінанси, календар, рецепти, здоров'я, DevOps.

## Документація

- [SPEC.md](SPEC.md) — повна специфікація проекту
- [SETUP.md](SETUP.md) — покрокова інструкція налаштування

## Швидкий старт

```bash
cp .env.example .env
# заповнити .env
pip install -e .
python -m src.main --init-db
python -m src.main
```
