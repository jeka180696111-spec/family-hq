from __future__ import annotations
import re

# All characters that must be escaped in Telegram MarkdownV2
_SPECIAL_CHARS: str = r"\_*[]()~`>#+-=|{}.!"
_ESCAPE_RE = re.compile(r"([" + re.escape(_SPECIAL_CHARS) + r"])")


def escape_md(text: str) -> str:
    """Escape special characters for Telegram MarkdownV2."""
    return _ESCAPE_RE.sub(r"\\\1", text)


def bold(text: str) -> str:
    return f"*{escape_md(text)}*"


def italic(text: str) -> str:
    return f"_{escape_md(text)}_"


def code(text: str) -> str:
    return f"`{escape_md(text)}`"


def link(text: str, url: str) -> str:
    return f"[{escape_md(text)}]({url})"
