"""Telethon user-bot for reading all messages in the Family HQ group."""
from __future__ import annotations

from typing import Callable, Awaitable, Any

from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.errors import ChannelPrivateError, UsernameInvalidError, UsernameNotOccupiedError
from telethon.tl.types import Message
import structlog

log = structlog.get_logger()

MessageHandler = Callable[[Message], Awaitable[None]]


class UserBot:
    """
    Telethon client for reading all messages in the HQ group.

    Only the user-bot can read ALL messages including those sent by bots,
    which is why we use a full user account here instead of a bot token.
    """

    def __init__(
        self,
        api_id: int,
        api_hash: str,
        session_name: str,
        phone: str,
        chat_id: int,
        session_string: str = "",
    ) -> None:
        session = StringSession(session_string) if session_string else f"/data/{session_name}"
        self._client = TelegramClient(session, api_id, api_hash)
        self._phone = phone
        self._chat_id = chat_id
        self._handlers: list[MessageHandler] = []
        self._news_handlers: list[MessageHandler] = []
        self._sidebar_handlers: list[MessageHandler] = []  # NP bot etc.

    def add_message_handler(self, handler: MessageHandler) -> None:
        """Register a callable to be invoked for each new HQ-group message."""
        self._handlers.append(handler)
        log.debug("message_handler_registered", total_handlers=len(self._handlers))

    def add_news_handler(self, handler: MessageHandler) -> None:
        """Register a callable to be invoked for each new post from a tracked news channel."""
        self._news_handlers.append(handler)
        log.debug("news_handler_registered", total_handlers=len(self._news_handlers))

    def add_sidebar_handler(self, handler: MessageHandler) -> None:
        """Register a callable for non-HQ private chats (e.g. NP Telegram bot)."""
        self._sidebar_handlers.append(handler)
        log.debug("sidebar_handler_registered", total_handlers=len(self._sidebar_handlers))

    async def start(self) -> None:
        """Connect to Telegram and start listening for new messages."""
        await self._client.start(phone=self._phone)

        hq_chat_id = self._chat_id

        # Реакции на сообщения в HQ-группе — Telethon ловит через
        # raw update UpdateMessageReactions / UpdateBotMessageReactions.
        from telethon.tl.types import UpdateMessageReactions, UpdateBotMessageReactions
        @self._client.on(events.Raw([UpdateMessageReactions, UpdateBotMessageReactions]))
        async def on_reaction(update: Any) -> None:
            try:
                peer = getattr(update, "peer", None)
                channel_id = getattr(peer, "channel_id", None) or getattr(peer, "chat_id", None)
                if channel_id and -(1000000000000 + (channel_id or 0)) != hq_chat_id and channel_id != hq_chat_id:
                    return  # not our chat
                msg_id = getattr(update, "msg_id", None)
                reactions_obj = getattr(update, "reactions", None)
                if not reactions_obj or msg_id is None:
                    return
                # Извлечь сами эмодзи / custom reactions
                results = getattr(reactions_obj, "results", []) or []
                emojis = []
                for r in results:
                    reaction = getattr(r, "reaction", None)
                    emoji = getattr(reaction, "emoticon", None)
                    if emoji:
                        emojis.append(emoji)
                # Сохранить в event_log
                try:
                    from src.db.memory import _get_engine
                    from src.db.models import EventLog
                    from src.utils.time import iso_now
                    from sqlalchemy import insert
                    import json as _json
                    engine = _get_engine()
                    if engine is not None:
                        async with engine.begin() as conn:
                            await conn.execute(insert(EventLog).values(
                                created_at=iso_now(),
                                level="INFO",
                                component="reaction",
                                message=f"reaction_on_msg:{msg_id}",
                                payload=_json.dumps({
                                    "msg_id": msg_id,
                                    "emojis": emojis,
                                }, ensure_ascii=False),
                            ))
                            log.info("reaction_recorded", msg_id=msg_id, emojis=emojis)
                except Exception:
                    log.exception("reaction_save_failed")
            except Exception:
                log.exception("reaction_handler_failed")

        @self._client.on(events.NewMessage())
        async def on_new_message(event: events.NewMessage.Event) -> None:
            chat = event.chat_id
            if chat == hq_chat_id:
                for handler in self._handlers:
                    try:
                        await handler(event.message)
                    except Exception:
                        log.exception("message_handler_error")
            else:
                # First — let sidebar handlers (NP bot DMs etc.) try
                handled = False
                for handler in self._sidebar_handlers:
                    try:
                        res = await handler(event.message)
                        if res:
                            handled = True
                    except Exception:
                        log.exception("sidebar_handler_error")
                if handled:
                    return
                # Otherwise — likely a tracked news channel
                for handler in self._news_handlers:
                    try:
                        await handler(event.message)
                    except Exception:
                        log.exception("news_handler_error")

        log.info("userbot_started", chat_id=self._chat_id)

    async def stop(self) -> None:
        """Disconnect from Telegram gracefully."""
        await self._client.disconnect()
        log.info("userbot_stopped")

    async def subscribe_to_channel(self, channel_username: str) -> int | None:
        """
        Join a public channel by username and return its numeric ID.

        Used for news-feed monitoring. Returns ``None`` if the channel
        cannot be found or joined.
        """
        try:
            entity = await self._client.get_entity(channel_username)
            # JoinChannelRequest is only needed for channels the user hasn't joined;
            # get_entity resolves it, but we explicitly join to ensure membership.
            from telethon.tl.functions.channels import JoinChannelRequest  # local import to keep top-level clean

            await self._client(JoinChannelRequest(entity))
            channel_id: int = entity.id
            log.info(
                "channel_subscribed",
                username=channel_username,
                channel_id=channel_id,
            )
            return channel_id
        except (UsernameInvalidError, UsernameNotOccupiedError):
            log.warning("channel_username_does_not_exist", username=channel_username)
            return None
        except ChannelPrivateError:
            log.error("channel_private", username=channel_username)
            return None
        except Exception:
            log.exception("channel_subscribe_error", username=channel_username)
            return None

    async def get_channel_messages(
        self, channel_id: int, limit: int = 10
    ) -> list[Message]:
        """Fetch the *limit* most recent messages from *channel_id*."""
        try:
            messages: list[Message] = await self._client.get_messages(
                channel_id, limit=limit
            )
            log.debug(
                "channel_messages_fetched",
                channel_id=channel_id,
                count=len(messages),
            )
            return messages
        except Exception:
            log.exception("get_channel_messages_error", channel_id=channel_id)
            return []
