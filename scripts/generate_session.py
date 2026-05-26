"""
Run this LOCALLY (not on Railway) to generate a Telethon session file.
Then upload the .session file to Railway Volume at /data/.

Usage:
    python scripts/generate_session.py
"""
import asyncio
import os
from telethon import TelegramClient
from dotenv import load_dotenv

load_dotenv()

API_ID = int(os.environ["TG_API_ID"])
API_HASH = os.environ["TG_API_HASH"]
PHONE = os.environ["TG_PHONE"]
SESSION_NAME = os.environ.get("TG_SESSION_NAME", "family_hq_user")


async def main() -> None:
    client = TelegramClient(SESSION_NAME, API_ID, API_HASH)
    await client.start(phone=PHONE)
    me = await client.get_me()
    print(f"Logged in as: {me.first_name} (@{me.username})")
    print(f"Session file saved: {SESSION_NAME}.session")
    print("Upload this file to Railway Volume at /data/")
    await client.disconnect()


asyncio.run(main())
