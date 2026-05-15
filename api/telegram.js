// /api/telegram.js — Telegram Bot Webhook (Vercel Serverless Function)
// Обробляє повідомлення від Telegram і записує операції в Firestore

const admin = require('firebase-admin');

// ── Firebase Admin ініціалізація ────────────────────────────
if (!admin.apps.length) {
  admin.initializeApp({
    credential: admin.credential.cert({
      projectId: 'familybudget-aa238',
      clientEmail: process.env.FIREBASE_CLIENT_EMAIL,
      privateKey: (process.env.FIREBASE_PRIVATE_KEY || '').replace(/\\n/g, '\n'),
    }),
  });
}
const db = admin.firestore();

// ── Конфігурація ────────────────────────────────────────────
const BOT_TOKEN = process.env.TELEGRAM_BOT_TOKEN;
const FAMILY_ID = 'koval';

// Дозволені Telegram user ID (додай свій і Марини після першого /start)
const ALLOWED_USERS = process.env.TELEGRAM_ALLOWED_USERS
  ? process.env.TELEGRAM_ALLOWED_USERS.split(',').map(Number)
  : []; // Порожній = всі дозволені (для тестування)

// Маппінг Telegram user ID → ім'я в сім'ї
const USER_MAP = {
  // Заповниться автоматично після /start
};

// ── Категорії для автовизначення ────────────────────────────
const CATEGORY_KEYWORDS = {
  'Продукти': ['продукт', 'магазин', 'атб', 'сільпо', 'фора', 'рукавичка', 'ашан', 'metro', 'їж', 'молок', 'хліб', 'мясо', 'овоч', 'фрукт'],
  'Ресторани': ['кав', 'каф', 'ресторан', 'обід', 'вечер', 'піц', 'суш', 'бургер', 'фастфуд', 'їдальн', 'макдональдс', 'kfc'],
  'Транспорт': ['бензин', 'заправ', 'таксі', 'uber', 'bolt', 'парков', 'метро', 'автобус', 'проїзд', 'окко', 'wog'],
  'Комунальні': ['комунал', 'електр', 'газ', 'вода', 'інтернет', 'опалення', 'квартплат'],
  "Здоров'я": ['аптек', 'лік', 'лікар', 'стоматолог', 'клінік', 'медиц', 'здоров'],
  'Одяг': ['одяг', 'взуття', 'куртк', 'штани', 'сукн', 'футболк', 'zara', 'h&m'],
  'Розваги': ['кіно', 'театр', 'концерт', 'гра', 'steam', 'netflix', 'розваг', 'spotify'],
  'Дім': ['меблі', 'ремонт', 'будматеріал', 'ikea', 'порядок'],
  'Дитячі': ['дитяч', 'іграшк', 'памперс', 'дитсад', 'школ'],
};

const INCOME_KEYWORDS = {
  'Зарплата': ['зп', 'зарплат', 'зарплата', 'salary'],
  'Підробіток': ['підробіт', 'фріланс', 'халтур', 'freelance'],
  'Пенсія': ['пенсі'],
  'Виплата': ['виплат', 'допомог', 'повернен'],
};

// ── Парсинг повідомлення ────────────────────────────────────
function parseMessage(text) {
  if (!text) return null;
  text = text.trim();

  // Команди
  if (text.startsWith('/')) return { command: text.split(' ')[0].toLowerCase() };

  // Парсимо: "каву 85" або "85 каву" або "зп 40000" або "дохід 1000 зарплата"
  const lower = text.toLowerCase();

  // Визначаємо тип: дохід чи витрата
  let type = 'Витрата';
  if (/^(дохід|дохід|income|зп|зарплат|заробив|отримав|прихід|\+)/.test(lower)) {
    type = 'Дохід';
  }

  // Знаходимо суму (перше число в тексті)
  const amountMatch = text.match(/(\d[\d\s]*[\d.,]?\d*)/);
  if (!amountMatch) return null;
  const amount = parseFloat(amountMatch[1].replace(/\s/g, '').replace(',', '.'));
  if (!amount || amount <= 0) return null;

  // Визначаємо валюту
  let currency = 'UAH';
  if (/\$|usd|долар|бакс/.test(lower)) currency = 'USD';
  if (/€|eur|євро|евро/.test(lower)) currency = 'EUR';

  // Визначаємо кошельок
  let card = '';
  if (/готівк|нал|cash/.test(lower)) card = 'Готівка';
  else if (/моно|mono/.test(lower)) card = 'Моно';
  else if (/пумб/.test(lower)) card = 'ПУМБ';
  else if (/приват/.test(lower)) card = 'Приват';
  else if (/кредит/.test(lower)) card = 'Кредитна';
  else if (/долар|\$|usd/.test(lower)) card = 'Долар';
  else if (/євро|€|eur/.test(lower)) card = 'Євро';

  // Визначаємо категорію
  let category = type === 'Дохід' ? 'Інше' : 'Інше';

  if (type === 'Дохід') {
    for (const [cat, keywords] of Object.entries(INCOME_KEYWORDS)) {
      if (keywords.some(kw => lower.includes(kw))) {
        category = cat;
        break;
      }
    }
  } else {
    for (const [cat, keywords] of Object.entries(CATEGORY_KEYWORDS)) {
      if (keywords.some(kw => lower.includes(kw))) {
        category = cat;
        break;
      }
    }
  }

  // Опис — весь текст без числа
  let desc = text.replace(amountMatch[0], '').trim();
  desc = desc.replace(/^[\s,.\-:]+|[\s,.\-:]+$/g, '');
  if (desc.length > 100) desc = desc.substring(0, 100);

  return { type, amount, currency, category, card, desc };
}

// ── Надіслати повідомлення в Telegram ───────────────────────
async function sendMessage(chatId, text, options = {}) {
  const url = `https://api.telegram.org/bot${BOT_TOKEN}/sendMessage`;
  const body = {
    chat_id: chatId,
    text,
    parse_mode: 'HTML',
    ...options,
  };
  await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}

// ── Дата в Київському часовому поясі ────────────────────────
function todayKyiv() {
  return new Date().toLocaleDateString('sv-SE', { timeZone: 'Europe/Kyiv' }); // 'YYYY-MM-DD'
}

// ── Зберегти операцію в Firestore ───────────────────────────
async function saveOperation(op) {
  const ref = db.collection('families').doc(FAMILY_ID).collection('operations');
  await ref.add({
    date: todayKyiv(),
    type: op.type,
    category: op.category,
    amount: op.amount,
    currency: op.currency || 'UAH',
    amountUah: op.amountUah || op.amount,
    desc: op.desc || '',
    who: op.who || 'Євген',
    card: op.card || '',
    source: 'Telegram',
    createdAt: new Date().toISOString(),
  });
}

// ── Отримати баланс ─────────────────────────────────────────
async function getBalance(who) {
  const snapshot = await db.collection('families').doc(FAMILY_ID)
    .collection('operations')
    .get();

  let income = 0, expense = 0;
  snapshot.docs.forEach(doc => {
    const d = doc.data();
    if (d.category === 'Переказ') return;
    if (who && d.who !== who) return;
    const amt = d.amountUah || d.amount || 0;
    if (d.type === 'Дохід') income += amt;
    if (d.type === 'Витрата') expense += amt;
  });

  return { income: Math.round(income), expense: Math.round(expense), balance: Math.round(income - expense) };
}

// ── Форматування грошей ─────────────────────────────────────
function fmtMoney(amount) {
  return Math.round(Math.abs(amount)).toLocaleString('uk-UA') + ' ₴';
}

// ── Emoji для категорій ─────────────────────────────────────
const CAT_EMOJI = {
  'Продукти': '🛒', 'Ресторани': '☕', 'Транспорт': '🚗', 'Комунальні': '🏠',
  "Здоров'я": '💊', 'Одяг': '👕', 'Розваги': '🎮', 'Дім': '🛋', 'Дитячі': '👶',
  'Зарплата': '💰', 'Підробіток': '💵', 'Пенсія': '🏦', 'Виплата': '📋',
  'Інше': '📌',
};

// ── Обробка команд ──────────────────────────────────────────
async function handleCommand(cmd, chatId, userId, userName, who, res) {
  switch (cmd) {
    case '/start':
      await sendMessage(chatId,
        `👋 Привіт, ${userName}!\n\n` +
        `Я бот <b>Сімейного бюджету</b>.\n\n` +
        `📝 <b>Як додати витрату:</b>\n` +
        `<code>каву 85</code> — витрата 85₴ → Ресторани\n` +
        `<code>продукти 1200</code> — витрата 1200₴ → Продукти\n` +
        `<code>бензин 1500 моно</code> — витрата з Моно\n\n` +
        `💰 <b>Як додати дохід:</b>\n` +
        `<code>зп 40000</code> — дохід (Зарплата)\n\n` +
        `Або натисни кнопку нижче 👇`,
        {
          reply_markup: {
            keyboard: [
              [{ text: '💰 Баланс' }, { text: '📅 Сьогодні' }],
              [{ text: '➕ Витрата' }, { text: '💵 Дохід' }],
              [{ text: '❓ Допомога' }],
            ],
            resize_keyboard: true,
            is_persistent: true,
          }
        }
      );
      return res.status(200).json({ ok: true });

    case '/help':
      await sendMessage(chatId,
        `📝 Просто напиши що купив і суму:\n` +
        `<code>каву 85</code>\n` +
        `<code>продукти 500 моно</code>\n` +
        `<code>зп 40000</code>\n\n` +
        `💰 Баланс — /balance\n` +
        `📅 Сьогодні — /today`
      );
      return res.status(200).json({ ok: true });

    case '/balance': {
      const bal = await getBalance(who);
      await sendMessage(chatId,
        `📊 <b>Баланс ${who}:</b>\n\n` +
        `💰 Доходи: +${fmtMoney(bal.income)}\n` +
        `💸 Витрати: -${fmtMoney(bal.expense)}\n` +
        `━━━━━━━━━━━━━━━\n` +
        `💎 Баланс: <b>${fmtMoney(bal.balance)}</b>`
      );
      return res.status(200).json({ ok: true });
    }

    case '/today': {
      const today = todayKyiv();
      const snapshot = await db.collection('families').doc(FAMILY_ID)
        .collection('operations')
        .where('date', '==', today)
        .get();
      const ops = snapshot.docs.map(d => d.data()).filter(o => o.category !== 'Переказ');
      const totalExp = ops.filter(o => o.type === 'Витрата').reduce((s, o) => s + (o.amountUah || o.amount || 0), 0);
      const totalInc = ops.filter(o => o.type === 'Дохід').reduce((s, o) => s + (o.amountUah || o.amount || 0), 0);

      let txt = `📅 <b>Сьогодні (${today}):</b>\n\n`;
      if (!ops.length) {
        txt += `Ще жодної операції.`;
      } else {
        ops.forEach(o => {
          const emoji = CAT_EMOJI[o.category] || '📌';
          const sign = o.type === 'Витрата' ? '-' : '+';
          txt += `${emoji} ${sign}${fmtMoney(o.amount)} · ${o.category}${o.desc ? ' · ' + o.desc : ''}\n`;
        });
        txt += `\n💸 Витрати: ${fmtMoney(totalExp)}`;
        if (totalInc > 0) txt += `\n💰 Доходи: ${fmtMoney(totalInc)}`;
      }
      await sendMessage(chatId, txt);
      return res.status(200).json({ ok: true });
    }

    default:
      await sendMessage(chatId, `❓ Невідома команда. Натисни кнопку нижче або напиши витрату.`);
      return res.status(200).json({ ok: true });
  }
}

// ═══════════════════════════════════════════════════════════════
// WEBHOOK HANDLER
// ═══════════════════════════════════════════════════════════════

module.exports = async function handler(req, res) {
  if (req.method !== 'POST') {
    return res.status(200).json({ ok: true, message: 'Telegram webhook endpoint' });
  }

  try {
    const update = req.body;
    if (!update || !update.message) {
      return res.status(200).json({ ok: true });
    }

    const msg = update.message;
    const chatId = msg.chat.id;
    const userId = msg.from.id;
    const userName = msg.from.first_name || 'User';
    const text = msg.text || '';

    // Визначаємо хто пише (поки за замовчуванням Євген)
    // Потім можна додати маппінг Telegram ID → ім'я
    const who = USER_MAP[userId] || 'Євген';

    // ── Команди ──────────────────────────────────────────────
    if (text.startsWith('/')) {
      const cmd = text.split(' ')[0].toLowerCase();
      return handleCommand(cmd, chatId, userId, userName, who, res);
    }

    // ── Reply keyboard кнопки ────────────────────────────────
    const btnMap = {
      '💰 Баланс': '/balance',
      '📅 Сьогодні': '/today',
      '❓ Допомога': '/help',
      '➕ Витрата': null, // спеціальна обробка
      '💵 Дохід': null,   // спеціальна обробка
    };

    if (btnMap[text] !== undefined) {
      if (btnMap[text]) {
        return handleCommand(btnMap[text], chatId, userId, userName, who, res);
      }
      // Кнопки Витрата / Дохід — підказка
      const isIncome = text.includes('Дохід');
      await sendMessage(chatId,
        isIncome
          ? `💵 Напиши дохід, наприклад:\n<code>зп 40000</code>\n<code>дохід 5000 підробіток</code>`
          : `➕ Напиши витрату, наприклад:\n<code>каву 85</code>\n<code>продукти 500 моно</code>`
      );
      return res.status(200).json({ ok: true });
    }

    // ── Текстове повідомлення — парсимо операцію ─────────────
    const parsed = parseMessage(text);

    if (!parsed) {
      await sendMessage(chatId,
        `🤔 Не зрозумів. Напиши суму і опис:\n` +
        `<code>каву 85</code>\n` +
        `<code>зп 40000</code>\n` +
        `<code>продукти 500 моно</code>`
      );
      return res.status(200).json({ ok: true });
    }

    // Конвертуємо в UAH
    let amountUah = parsed.amount;
    if (parsed.currency !== 'UAH') {
      // Приблизні курси (можна потім тягнути з Firestore)
      const rates = { USD: 41.5, EUR: 45.0 };
      amountUah = Math.round(parsed.amount * (rates[parsed.currency] || 1));
    }

    // Зберігаємо
    await saveOperation({
      type: parsed.type,
      amount: parsed.amount,
      currency: parsed.currency,
      amountUah,
      category: parsed.category,
      card: parsed.card,
      desc: parsed.desc,
      who,
    });

    // Відповідаємо
    const emoji = parsed.type === 'Дохід' ? '💰' : CAT_EMOJI[parsed.category] || '💸';
    const sign = parsed.type === 'Дохід' ? '+' : '-';
    const currSym = { UAH: '₴', USD: '$', EUR: '€' }[parsed.currency] || '₴';
    let reply = `${emoji} <b>${parsed.type}</b> ${sign}${parsed.amount} ${currSym}`;
    if (parsed.currency !== 'UAH') reply += ` (≈ ${fmtMoney(amountUah)})`;
    reply += `\n📁 ${parsed.category}`;
    if (parsed.card) reply += ` · 💳 ${parsed.card}`;
    reply += ` · 👤 ${who}`;
    if (parsed.desc) reply += `\n📝 ${parsed.desc}`;
    reply += `\n\n✅ Збережено!`;

    await sendMessage(chatId, reply);
    return res.status(200).json({ ok: true });

  } catch (error) {
    console.error('Telegram webhook error:', error);
    return res.status(200).json({ ok: true, error: error.message });
  }
};
