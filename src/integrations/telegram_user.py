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

    def add_message_handler(self, handler: MessageHandler) -> None:
        """Register a callable to be invoked for each new HQ-group message."""
        self._handlers.append(handler)
        log.debug("message_handler_registered", total_handlers=len(self._handlers))

    def add_news_handler(self, handler: MessageHandler) -> None:
        """Register a callable to be invoked for each new post from a tracked news channel."""
        self._news_handlers.append(handler)
        log.debug("news_handler_registered", total_handlers=len(self._news_handlers))

    async def start(self) -> None:
        """Connect to Telegram and start listening for new messages."""
        await self._client.start(phone=self._phone)

        hq_chat_id = self._chat_id

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
                # Likely a tracked news channel — let news handlers decide
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
