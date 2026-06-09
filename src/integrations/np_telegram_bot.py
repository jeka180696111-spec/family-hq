"""Detect Nova Poshta Telegram-bot DMs and surface them in the HQ chat.

Setup (one-time per family member):
  1. Open Telegram → search @NovaPoshtaUaBot (or @NovaPoshta_bot).
  2. /start, authenticate with phone — NP will send shipment events to
     this DM from now on.

Our Telethon user-bot is already logged into the family member's
Telegram account, so it sees every message in every chat. We add a
sidebar handler: if a message arrives in the DM with the NP bot,
forward the text to the HQ group as if the user pasted it. The
existing 14-digit TTN regex picks up the number; devops._parcel_track
saves and announces it.

Phone-independent: when the user changes device but keeps the same
Telegram account, this keeps working with no reconfiguration.
"""
from __future__ import annotations

import re
from typing import Any, Callable

import structlog

log = structlog.get_logger()


_NP_BOT_USERNAMES = {
    "novaposhtauabot", "novaposhta_bot", "novaposhtaofficialbot",
    "novapostbot", "np_official_bot",
}

_TTN_RE = re.compile(r"\b(\d{14})\b")


def make_handler(
    bot_manager: Any, hq_chat_id: int, devops_agent: Any,
    member_phones: dict[str, str] | None = None,
) -> Callable:
    """Build a sidebar handler that forwards NP-bot messages."""
    member_phones = member_phones or {}

    async def handle(message: Any) -> bool:
        try:
            sender = await message.get_sender()
        except Exception:
            sender = None
        username = (getattr(sender, "username", "") or "").lower()
        if username not in _NP_BOT_USERNAMES:
            return False
        text = getattr(message, "text", "") or getattr(message, "message", "") or ""
        ttns = _TTN_RE.findall(text)
        if not ttns:
            log.info("np_bot_no_ttn_in_message", preview=text[:80])
            return False
        # Determine recipient: which Telegram account did this arrive on?
        # Telethon doesn't directly expose that; we tag as 'family' and let
        # the user disambiguate if needed.
        member = "family"
        for ttn in set(ttns):
            try:
                if devops_agent:
                    await devops_agent._parcel_track(
                        ttn=ttn, title="", member=member,
                    )
                    log.info("np_bot_tracked", ttn=ttn)
            except Exception:
                log.exception("np_bot_track_failed", ttn=ttn)
        # Also forward the raw NP message to HQ chat for visibility
        try:
            if bot_manager and hq_chat_id:
                await bot_manager.send_message(
                    agent_id="devops",
                    chat_id=hq_chat_id,
                    text=f"📨 <b>Nova Poshta бот:</b>\n{text[:600]}",
                )
        except Exception:
            log.exception("np_bot_forward_failed")
        return True

    return handle
