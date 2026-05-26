"""
Запусти цей скрипт в Google Colab (colab.research.google.com):
1. Створи новий notebook
2. Встав цей код в клітинку
3. Запусти — введи API ID, API Hash, номер телефону, SMS-код
4. Скопіюй рядок SESSION_STRING
5. Додай його в Railway Variables як TG_SESSION_STRING
"""

# Клітинка 1: встановити бібліотеку
# !pip install telethon

# Клітинка 2: генерація
from telethon.sync import TelegramClient
from telethon.sessions import StringSession

api_id    = int(input("TG_API_ID: "))
api_hash  = input("TG_API_HASH: ")
phone     = input("TG_PHONE (+380...): ")

with TelegramClient(StringSession(), api_id, api_hash) as client:
    client.start(phone=phone)
    session_string = client.session.save()

print("\n✅ Готово! Скопіюй рядок нижче і встав у Railway Variables як TG_SESSION_STRING:\n")
print(session_string)
