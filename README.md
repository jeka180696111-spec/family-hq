# Сімейний бюджет — Веб-додаток PWA

## Файли
- index.html  — основна розмітка (6 сторінок, 2 модальних вікна)
- style.css   — стилі (теми: light / dark / sand)
- app.js      — логіка, API, рендеринг
- manifest.json — PWA маніфест

## Налаштування

### 1. Google OAuth
В app.js рядок 2:
  GOOGLE_CLIENT_ID: "YOUR_GOOGLE_CLIENT_ID.apps.googleusercontent.com"

Отримай Client ID:
  Google Cloud Console → APIs & Services → Credentials → Create OAuth 2.0 Client
  Application type: Web application
  Authorized JavaScript origins: https://твій-домен.vercel.app

### 2. Apps Script URL
Після деплою Code.gs: Розгортання → Нове розгортання → Веб-додаток
Скопіюй URL і встав в додатку: Налаштування → URL скрипта → Змінити

### 3. Деплой на Vercel
  npx vercel --prod
або перетягни папку на vercel.com

### 4. Monobank webhook
  curl -X POST https://api.monobank.ua/personal/webhook
    -H "X-Token: ТВІЙ_ТОКЕН"
    -d '{"webHookUrl":"SCRIPT_URL"}'

### 5. Telegram webhook
  curl "https://api.telegram.org/botТОКЕН/setWebhook?url=SCRIPT_URL"

## Функції додатку
- Дашборд: KPI картки, операції, категорії
- Операції: список з фільтрами (тип, бюджет)
- Аналіз: категорії та бюджети
- Резерв: подушка безпеки з динамікою
- Цілі: прогрес по цілях
- Налаштування: тема, масштаб, профіль

## Демо-режим
Якщо URL скрипта не налаштовано — додаток показує демо-дані.
Всі функції доступні без бекенду.