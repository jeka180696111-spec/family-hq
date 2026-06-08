"""Food delivery deeplinks for Glovo / Bolt Food.

Neither service has a public ordering API, so we generate the
universal-link URLs that open the user's app in the right place
(restaurant/category in Odesa). The user finishes the order in the app.
"""
from __future__ import annotations

import urllib.parse
from typing import Any


DEFAULT_CITY = "Odesa"
DEFAULT_COORDS = (46.4825, 30.7233)  # Odesa centre


def glovo_search_url(query: str, city: str = DEFAULT_CITY) -> str:
    q = urllib.parse.quote(query)
    return f"https://glovoapp.com/ua/uk/{city.lower()}/?content=restaurants&search={q}"


def bolt_food_url(city: str = DEFAULT_CITY) -> str:
    lat, lng = DEFAULT_COORDS
    return f"https://food.bolt.eu/en-US/{city.lower()}?lat={lat}&lng={lng}"


def build_deeplinks(query: str, city: str = DEFAULT_CITY) -> dict:
    return {
        "query": query,
        "city": city,
        "glovo": glovo_search_url(query, city),
        "bolt": bolt_food_url(city),
        "rocket": f"https://rocket.delivery/{city.lower()}/search?q={urllib.parse.quote(query)}",
        "instruction": (
            "Открой одну из ссылок в браузере (она перейдёт в приложение если установлено), "
            "выбери ресторан и оформи заказ. Мы можем только подобрать — оформить через API "
            "сервисы не дают."
        ),
    }
