"""Render emoji as inline PNG images for reportlab Paragraph.

ReportLab can't display color emoji fonts (NotoColorEmoji is CBDT, not
TTF outline). Monochrome alternatives like Symbola cover old emoji but
miss newer ones the user types (🥵 🩺 🥲 …). Twemoji has PNGs for
every emoji and we inline them via <img> tags inside Paragraph markup.

PNGs are cached at /tmp/emoji_cache/<codepoint>.png so we only fetch
each emoji once.
"""
from __future__ import annotations

import os
import re
import urllib.request
from pathlib import Path

import structlog

log = structlog.get_logger()


CACHE_DIR = Path("/tmp/emoji_cache")
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Match emoji-presentation scalar values. Covers:
#   miscellaneous symbols, dingbats, emoticons, transport, supplemental
#   symbols (incl. Unicode 13/14 newer ones like 🥵 🩺), regional flags.
# Variation selector U+FE0F is matched + consumed as part of the cluster.
_EMOJI_RE = re.compile(
    "([☝⚠⚡⛄✊-✍❌❎✨"
    "\U0001F300-\U0001F64F"
    "\U0001F680-\U0001F6FF"
    "\U0001F900-\U0001F9FF"
    "\U0001FA00-\U0001FAFF"
    "][️‍\U0001F3FB-\U0001F3FF]*"
    "(?:‍[\U0001F300-\U0001F9FF][️]?)*)"
)


def _codepoint_name(cluster: str) -> str:
    """Twemoji's filename convention: hex codepoints joined by '-'.
    Variation selector U+FE0F is usually OMITTED in twemoji filenames."""
    parts = [f"{ord(c):x}" for c in cluster if c != "️"]
    return "-".join(parts)


def _fetch_png(codepoint: str) -> str | None:
    path = CACHE_DIR / f"{codepoint}.png"
    if path.exists() and path.stat().st_size > 0:
        return str(path)
    # jsdelivr mirrors the official twemoji assets and is fast.
    sources = (
        f"https://cdn.jsdelivr.net/gh/jdecked/twemoji@latest/assets/72x72/{codepoint}.png",
        f"https://cdn.jsdelivr.net/gh/twitter/twemoji@latest/assets/72x72/{codepoint}.png",
    )
    for url in sources:
        try:
            urllib.request.urlretrieve(url, str(path))
            if path.exists() and path.stat().st_size > 100:
                return str(path)
        except Exception:
            continue
    if path.exists():
        try:
            path.unlink()
        except Exception:
            pass
    log.warning("emoji_fetch_failed", codepoint=codepoint)
    return None


def inline_emojis(text: str, size_pt: float = 12.0) -> str:
    """Walk the string, replace each emoji cluster with an inline <img>
    tag pointing at a cached twemoji PNG. Non-emoji text is left alone.
    """
    if not text or "<img" in text:
        # Avoid double-processing already-inlined output
        return text

    def _replace(match: re.Match) -> str:
        cluster = match.group(1)
        cp = _codepoint_name(cluster)
        if not cp:
            return cluster
        png = _fetch_png(cp)
        if not png:
            # Fall back to original character — squares are still better
            # than empty captions for the user's flow
            return cluster
        # valign='middle' keeps the emoji baseline-aligned with text
        return (f'<img src="{png}" valign="middle" '
                f'width="{size_pt}" height="{size_pt}"/>')

    return _EMOJI_RE.sub(_replace, text)
