"""Telegram-channel archive: send a copy of a media file to a private
channel/chat as a backup. Works around the Google Drive 'service
account has no storage quota' limitation on personal Gmail accounts.

Setup (one-time):
  1. In Telegram: create a private channel «Family HQ · Archive».
  2. Add Прораб (or any of the family bots) as Admin → 'Post Messages'.
  3. Channel ID (starts with -100...) goes into env BABY_PHOTO_ARCHIVE_CHANNEL_ID.

Photos forwarded there keep full quality and live forever.
"""
from __future__ import annotations

from typing import Any

import structlog

log = structlog.get_logger()


async def archive_to_telegram(
    bot_manager: Any,
    agent_id: str,
    channel_id: int,
    local_path: str,
    caption: str | None,
) -> dict:
    """Send a copy of the local file to the archive channel.

    Returns {message_id} on success or {error} on failure.
    """
    if not channel_id:
        return {"error": "no_archive_channel"}
    try:
        from telegram import Bot
        token = bot_manager._bots[agent_id].token  # private attr — small dependency
        bot = Bot(token=token)
        with open(local_path, "rb") as f:
            msg = await bot.send_photo(
                chat_id=channel_id, photo=f,
                caption=(caption or "")[:1024] or None,
            )
        return {"message_id": msg.message_id, "channel_id": channel_id}
    except Exception as e:
        log.exception("telegram_archive_failed")
        return {"error": str(e)[:300]}
