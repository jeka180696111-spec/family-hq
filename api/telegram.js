// /api/telegram.js — Telegram Bot Webhook (Vercel Serverless Function)

const admin = require('firebase-admin');

if (!admin.apps.length) {
  admin.initializeApp({
    credential: admin.credential.cert({
      projectId: process.env.FIREBASE_PROJECT_ID || 'familybudget-aa238',
      clientEmail: process.env.FIREBASE_CLIENT_EMAIL,
      privateKey: (process.env.FIREBASE_PRIVATE_KEY || '').replace(/\\n/g, '\n'),
    }),
  });
}
const db = admin.firestore();

const BOT_TOKEN = process.env.TELEGRAM_BOT_TOKEN;
const FAMILY_ID = process.env.FAMILY_ID || 'koval';

// Дозволені Telegram user ID: "123456,789012" в env
const ALLOWED_USERS = process.env.TELEGRAM_ALLOWED_USERS
  ? process.env.TELEGRAM_ALLOWED_USERS.split(',').map(Number)
  : [];

// Fallback маппінг ID → ім'я: "123456:Євген,789012:Марина" в env
const USER_MAP = {};
if (process.env.TELEGRAM_USER_MAP) {
  for (const pair of process.env.TELEGRAM_USER_MAP.split(',')) {
    const [id, name] = pair.split(':');
    if (id && name) USER_MAP[Number(id.trim())] = name.trim();
  }
}

// ── Категорії ────────────────────────────────────────────────
const EXPENSE_CATS = ['Продукти', 'Ресторани', 'Транспорт', 'Комунальні', "Здоров'я", 'Одяг', 'Розваги', 'Дім', 'Дитячі', 'Інше'];
const INCOME_CATS  = ['Зарплата', 'Підробіток', 'Пенсія', 'Виплата', 'Інше'];

const CATEGORY_KEYWORDS = {
  'Продукти':   ['продукт', 'магазин', 'атб', 'сільпо', 'фора', 'рукавичка', 'ашан', 'metro', 'їж', 'молок', 'хліб', 'мясо', 'овоч', 'фрукт'],
  'Ресторани':  ['кав', 'каф', 'ресторан', 'обід', 'вечер', 'піц', 'суш', 'бургер', 'фастфуд', 'їдальн', 'макдональдс', 'kfc'],
  'Транспорт':  ['бензин', 'заправ', 'таксі', 'uber', 'bolt', 'парков', 'метро', 'автобус', 'проїзд', 'окко', 'wog'],
  'Комунальні': ['комунал', 'електр', 'газ', 'вода', 'інтернет', 'опалення', 'квартплат'],
  "Здоров'я":   ['аптек', 'лік', 'лікар', 'стоматолог', 'клінік', 'медиц', 'здоров'],
  'Одяг':       ['одяг', 'взуття', 'куртк', 'штани', 'сукн', 'футболк', 'zara', 'h&m'],
  'Розваги':    ['кіно', 'театр', 'концерт', 'гра', 'steam', 'netflix', 'розваг', 'spotify'],
  'Дім':        ['меблі', 'ремонт', 'будматеріал', 'ikea', 'порядок'],
  'Дитячі':     ['дитяч', 'іграшк', 'памперс', 'дитсад', 'школ'],
};

const INCOME_KEYWORDS = {
  'Зарплата':   ['зп', 'зарплат', 'зарплата', 'salary'],
  'Підробіток': ['підробіт', 'фріланс', 'халтур', 'freelance'],
  'Пенсія':     ['пенсі'],
  'Виплата':    ['виплат', 'допомог', 'повернен'],
};

const CAT_EMOJI = {
  'Продукти': '🛒', 'Ресторани': '☕', 'Транспорт': '🚗', 'Комунальні': '🏠',
  "Здоров'я": '💊', 'Одяг': '👕', 'Розваги': '🎮', 'Дім': '🛋', 'Дитячі': '👶',
  'Зарплата': '💰', 'Підробіток': '💵', 'Пенсія': '🏦', 'Виплата': '📋',
  'Інше': '📌',
};

// ── Telegram API ─────────────────────────────────────────────
async function tgPost(method, body) {
  await fetch(`https://api.telegram.org/bot${BOT_TOKEN}/${method}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}

async function sendMessage(chatId, text, options = {}) {
  await tgPost('sendMessage', { chat_id: chatId, text, parse_mode: 'HTML', ...options });
}

async function editMessage(chatId, messageId, text, options = {}) {
  await tgPost('editMessageText', { chat_id: chatId, message_id: messageId, text, parse_mode: 'HTML', ...options });
}

async function answerCallback(callbackId, text = '') {
  await tgPost('answerCallbackQuery', { callback_query_id: callbackId, text });
}

// ── Helpers ──────────────────────────────────────────────────
function todayKyiv() {
  return new Date().toLocaleDateString('sv-SE', { timeZone: 'Europe/Kyiv' });
}

function fmtMoney(amount) {
  return Math.round(Math.abs(amount)).toLocaleString('uk-UA') + ' ₴';
}

function buildBar(value, max, len = 8) {
  const filled = max > 0 ? Math.round((value / max) * len) : 0;
  return '█'.repeat(filled) + '░'.repeat(len - filled);
}

function currentMonthRange() {
  const kyiv = new Date().toLocaleDateString('sv-SE', { timeZone: 'Europe/Kyiv' });
  const [year, month] = kyiv.split('-');
  return { from: `${year}-${month}-01`, to: `${year}-${month}-31`, label: `${month}.${year}` };
}

function weekRange() {
  const now = new Date();
  const to = now.toLocaleDateString('sv-SE', { timeZone: 'Europe/Kyiv' });
  const from = new Date(now - 6 * 86400000).toLocaleDateString('sv-SE', { timeZone: 'Europe/Kyiv' });
  return { from, to };
}

// ── User management ──────────────────────────────────────────
async function getWho(userId, fallbackName) {
  if (USER_MAP[userId]) return USER_MAP[userId];
  try {
    const doc = await db.collection('families').doc(FAMILY_ID)
      .collection('telegramUsers').doc(String(userId)).get();
    if (doc.exists) return doc.data().name;
  } catch (e) {}
  return fallbackName || 'Невідомий';
}

async function registerUser(userId, name) {
  await db.collection('families').doc(FAMILY_ID)
    .collection('telegramUsers').doc(String(userId)).set({ name, updatedAt: new Date().toISOString() });
}

async function setPendingReg(userId) {
  await db.collection('families').doc(FAMILY_ID)
    .collection('pendingReg').doc(String(userId)).set({ createdAt: new Date().toISOString() });
}

async function checkPendingReg(userId) {
  const doc = await db.collection('families').doc(FAMILY_ID)
    .collection('pendingReg').doc(String(userId)).get();
  return doc.exists;
}

async function clearPendingReg(userId) {
  await db.collection('families').doc(FAMILY_ID)
    .collection('pendingReg').doc(String(userId)).delete();
}

// ── Pending operations ───────────────────────────────────────
async function savePending(op, userId) {
  const ref = db.collection('families').doc(FAMILY_ID).collection('pendingOps');
  const doc = await ref.add({ ...op, userId: String(userId), createdAt: new Date().toISOString() });
  return doc.id;
}

async function getPending(id) {
  const doc = await db.collection('families').doc(FAMILY_ID)
    .collection('pendingOps').doc(id).get();
  return doc.exists ? doc.data() : null;
}

async function updatePending(id, data) {
  await db.collection('families').doc(FAMILY_ID)
    .collection('pendingOps').doc(id).update(data);
}

async function deletePending(id) {
  await db.collection('families').doc(FAMILY_ID)
    .collection('pendingOps').doc(id).delete();
}

// ── Firestore queries ────────────────────────────────────────

// Курси валют з meta/fx (як у головному додатку)
async function getExchangeRates() {
  try {
    const doc = await db.collection('meta').doc('fx').get();
    if (doc.exists) {
      const d = doc.data();
      return {
        USD: d.USD?.mid || d.USD?.buy || 41.5,
        EUR: d.EUR?.mid || d.EUR?.buy || 45.0,
      };
    }
  } catch (e) {}
  return { USD: 41.5, EUR: 45.0 };
}

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

// Баланс по кошельках з урахуванням валюти
async function getWalletBalances() {
  const [snapshot, rates] = await Promise.all([
    db.collection('families').doc(FAMILY_ID).collection('operations').get(),
    getExchangeRates(),
  ]);

  const wallets = {};
  snapshot.docs.forEach(doc => {
    const d = doc.data();
    if (d.category === 'Переказ') return;
    const card = d.card || 'Без рахунку';
    if (!wallets[card]) wallets[card] = { currencies: {} };

    const cur = d.currency || 'UAH';
    const amt = d.amount || 0;

    if (!wallets[card].currencies[cur]) wallets[card].currencies[cur] = { income: 0, expense: 0 };
    if (d.type === 'Дохід') wallets[card].currencies[cur].income += amt;
    if (d.type === 'Витрата') wallets[card].currencies[cur].expense += amt;
  });

  return Object.entries(wallets)
    .map(([name, v]) => {
      // Рідна валюта — перша не-UAH, або UAH
      const primaryCur = Object.keys(v.currencies).find(c => c !== 'UAH') || 'UAH';
      const curData = v.currencies[primaryCur] || { income: 0, expense: 0 };
      const balance = Math.round(curData.income - curData.expense);

      // UAH-еквівалент за ПОТОЧНИМ курсом (не за збереженим amountUah)
      let balanceUah;
      if (primaryCur === 'UAH') {
        balanceUah = balance;
      } else {
        const rate = rates[primaryCur] || 1;
        balanceUah = Math.round(balance * rate);
      }

      return { name, balance, primaryCur, balanceUah };
    })
    .filter(w => w.balance !== 0)
    .sort((a, b) => Math.abs(b.balanceUah) - Math.abs(a.balanceUah));
}

async function getPeriodOps(from, to) {
  const snapshot = await db.collection('families').doc(FAMILY_ID)
    .collection('operations')
    .where('date', '>=', from)
    .where('date', '<=', to)
    .orderBy('date', 'desc')
    .get();
  return snapshot.docs.map(d => d.data()).filter(o => o.category !== 'Переказ');
}

async function getLastOps(n = 5) {
  const snapshot = await db.collection('families').doc(FAMILY_ID)
    .collection('operations')
    .orderBy('createdAt', 'desc')
    .limit(n)
    .get();
  return snapshot.docs
    .map(d => ({ id: d.id, ...d.data() }))
    .filter(o => o.category !== 'Переказ');
}

async function deleteOperation(id) {
  await db.collection('families').doc(FAMILY_ID)
    .collection('operations').doc(id).delete();
}

// ── Keyboards ────────────────────────────────────────────────
const MAIN_KEYBOARD = {
  keyboard: [
    [{ text: '💰 Баланс' },     { text: '📅 Сьогодні' }],
    [{ text: '📆 Місяць' },     { text: '⏱ Тиждень' }],
    [{ text: '📊 Статистика' }, { text: '📋 Останні' }],
    [{ text: '➕ Витрата' },    { text: '💵 Дохід' }],
    [{ text: '❓ Допомога' }],
  ],
  resize_keyboard: true,
  is_persistent: true,
};

function buildConfirmKeyboard(pendingId, type) {
  const cats = type === 'Дохід' ? INCOME_CATS : EXPENSE_CATS;
  const catRows = [];
  for (let i = 0; i < cats.length; i += 2) {
    catRows.push(cats.slice(i, i + 2).map(cat => ({
      text: `${CAT_EMOJI[cat] || '📌'} ${cat}`,
      callback_data: `ct:${pendingId}:${cat}`,
    })));
  }
  return {
    inline_keyboard: [
      [
        { text: '✅ Зберегти',   callback_data: `sv:${pendingId}` },
        { text: '❌ Скасувати', callback_data: `cl:${pendingId}` },
      ],
      ...catRows,
    ],
  };
}

function pendingPreviewText(op) {
  const currSym = { UAH: '₴', USD: '$', EUR: '€' }[op.currency] || '₴';
  const sign = op.type === 'Дохід' ? '+' : '-';
  const emoji = op.type === 'Дохід' ? '💰' : (CAT_EMOJI[op.category] || '💸');
  let txt = `${emoji} <b>${op.type}</b> ${sign}${op.amount} ${currSym}`;
  if (op.currency !== 'UAH') txt += ` (≈ ${fmtMoney(op.amountUah)})`;
  txt += `\n📁 ${op.category}`;
  if (op.card) txt += ` · 💳 ${op.card}`;
  txt += ` · 👤 ${op.who}`;
  if (op.desc) txt += `\n📝 ${op.desc}`;
  txt += `\n\n<i>Перевір або вибери іншу категорію:</i>`;
  return txt;
}

// ── Formatters ───────────────────────────────────────────────
function formatPeriodStats(ops, label) {
  const expenses = ops.filter(o => o.type === 'Витрата');
  const incomes  = ops.filter(o => o.type === 'Дохід');
  const totalExp = expenses.reduce((s, o) => s + (o.amountUah || o.amount || 0), 0);
  const totalInc = incomes.reduce((s, o) => s + (o.amountUah || o.amount || 0), 0);

  const byCat = {};
  expenses.forEach(o => {
    const cat = o.category || 'Інше';
    byCat[cat] = (byCat[cat] || 0) + (o.amountUah || o.amount || 0);
  });

  let txt = `📆 <b>${label}:</b>\n\n`;
  if (!ops.length) return txt + 'Ще жодної операції.';

  if (Object.keys(byCat).length) {
    txt += `💸 <b>Витрати: ${fmtMoney(totalExp)}</b>\n`;
    Object.entries(byCat).sort((a, b) => b[1] - a[1]).forEach(([cat, amt]) => {
      txt += `${CAT_EMOJI[cat] || '📌'} ${cat}: ${fmtMoney(amt)}\n`;
    });
  }
  if (totalInc > 0) txt += `\n💰 <b>Доходи: ${fmtMoney(totalInc)}</b>`;
  return txt;
}

function formatStats(ops, label) {
  const expenses = ops.filter(o => o.type === 'Витрата');
  const byCat = {};
  expenses.forEach(o => {
    const cat = o.category || 'Інше';
    byCat[cat] = (byCat[cat] || 0) + (o.amountUah || o.amount || 0);
  });

  const sorted = Object.entries(byCat).sort((a, b) => b[1] - a[1]);
  const maxAmt = sorted[0]?.[1] || 0;
  const total = sorted.reduce((s, [, v]) => s + v, 0);

  let txt = `📊 <b>Статистика ${label}:</b>\n\n`;
  if (!sorted.length) return txt + 'Ще жодних витрат.';

  sorted.forEach(([cat, amt]) => {
    const pct = total > 0 ? Math.round((amt / total) * 100) : 0;
    txt += `${CAT_EMOJI[cat] || '📌'} ${buildBar(amt, maxAmt)} ${fmtMoney(amt)} <i>${pct}%</i>\n`;
    txt += `<code>   ${cat}</code>\n`;
  });

  txt += `\n💸 Разом: <b>${fmtMoney(total)}</b>`;
  return txt;
}

// ── parseMessage ─────────────────────────────────────────────
function parseMessage(text) {
  if (!text) return null;
  text = text.trim();
  if (text.startsWith('/')) return { command: text.split(' ')[0].toLowerCase() };

  const lower = text.toLowerCase();
  let type = 'Витрата';
  if (/^(дохід|income|зп|зарплат|заробив|отримав|прихід|\+)/.test(lower)) type = 'Дохід';

  const amountMatch = text.match(/(\d[\d\s]*[\d.,]?\d*)/);
  if (!amountMatch) return null;
  const amount = parseFloat(amountMatch[1].replace(/\s/g, '').replace(',', '.'));
  if (!amount || amount <= 0) return null;

  let currency = 'UAH';
  if (/\$|usd|долар|бакс/.test(lower)) currency = 'USD';
  if (/€|eur|євро|евро/.test(lower)) currency = 'EUR';

  let card = '';
  if (/готівк|нал|cash/.test(lower))   card = 'Готівка';
  else if (/моно|mono/.test(lower))    card = 'Моно';
  else if (/пумб/.test(lower))         card = 'ПУМБ';
  else if (/приват/.test(lower))       card = 'Приват';
  else if (/кредит/.test(lower))       card = 'Кредитна';
  else if (/долар|\$|usd/.test(lower)) card = 'Долар';
  else if (/євро|€|eur/.test(lower))   card = 'Євро';

  let category = 'Інше';
  if (type === 'Дохід') {
    for (const [cat, kws] of Object.entries(INCOME_KEYWORDS)) {
      if (kws.some(kw => lower.includes(kw))) { category = cat; break; }
    }
  } else {
    for (const [cat, kws] of Object.entries(CATEGORY_KEYWORDS)) {
      if (kws.some(kw => lower.includes(kw))) { category = cat; break; }
    }
  }

  let desc = text.replace(amountMatch[0], '').trim().replace(/^[\s,.\-:]+|[\s,.\-:]+$/g, '');
  if (desc.length > 100) desc = desc.substring(0, 100);

  return { type, amount, currency, category, card, desc };
}

// ── Callback handler ─────────────────────────────────────────
async function handleCallback(cb, res) {
  const data = cb.data || '';
  const chatId = cb.message.chat.id;
  const messageId = cb.message.message_id;
  const [action, id, ...rest] = data.split(':');
  const newCat = rest.join(':'); // category names don't contain ':' but safe regardless

  if (action === 'sv') {
    const op = await getPending(id);
    if (!op) {
      await answerCallback(cb.id, '⚠️ Операція застаріла');
      await editMessage(chatId, messageId, '⚠️ Операція застаріла. Введи знову.');
      return res.status(200).json({ ok: true });
    }
    await saveOperation(op);
    await deletePending(id);

    const emoji = op.type === 'Дохід' ? '💰' : (CAT_EMOJI[op.category] || '💸');
    const sign = op.type === 'Дохід' ? '+' : '-';
    const currSym = { UAH: '₴', USD: '$', EUR: '€' }[op.currency] || '₴';
    let txt = `${emoji} <b>${op.type}</b> ${sign}${op.amount} ${currSym}`;
    if (op.currency !== 'UAH') txt += ` (≈ ${fmtMoney(op.amountUah)})`;
    txt += `\n📁 ${op.category}`;
    if (op.card) txt += ` · 💳 ${op.card}`;
    txt += ` · 👤 ${op.who}`;
    if (op.desc) txt += `\n📝 ${op.desc}`;
    txt += `\n\n✅ Збережено!`;
    await editMessage(chatId, messageId, txt);
    await answerCallback(cb.id, '✅ Збережено!');
    return res.status(200).json({ ok: true });
  }

  if (action === 'cl') {
    await deletePending(id).catch(() => {});
    await editMessage(chatId, messageId, '❌ Скасовано.');
    await answerCallback(cb.id, 'Скасовано');
    return res.status(200).json({ ok: true });
  }

  if (action === 'ct') {
    const op = await getPending(id);
    if (!op) {
      await answerCallback(cb.id, '⚠️ Операція застаріла');
      return res.status(200).json({ ok: true });
    }
    await updatePending(id, { category: newCat });
    const updated = { ...op, category: newCat };
    await editMessage(chatId, messageId, pendingPreviewText(updated), {
      reply_markup: buildConfirmKeyboard(id, op.type),
    });
    await answerCallback(cb.id, `📁 ${newCat}`);
    return res.status(200).json({ ok: true });
  }

  if (action === 'dl') {
    await deleteOperation(id);
    await editMessage(chatId, messageId, '🗑 Операцію видалено.');
    await answerCallback(cb.id, 'Видалено');
    return res.status(200).json({ ok: true });
  }

  await answerCallback(cb.id);
  return res.status(200).json({ ok: true });
}

// ── Command handler ──────────────────────────────────────────
async function handleCommand(cmd, chatId, userId, userName, who, res) {
  switch (cmd) {
    case '/start': {
      const existing = await getWho(userId, null);
      const isNew = !existing || existing === 'Невідомий';
      if (isNew) {
        await setPendingReg(userId);
        await sendMessage(chatId, `👋 Привіт! Я бот <b>Сімейного бюджету</b>.\n\nЯк тебе звати?`);
      } else {
        await sendMessage(chatId,
          `👋 Привіт, <b>${existing}</b>!\n\n` +
          `Надсилай витрати або доходи, або натисни кнопку:`,
          { reply_markup: MAIN_KEYBOARD }
        );
      }
      return res.status(200).json({ ok: true });
    }

    case '/help':
      await sendMessage(chatId,
        `📝 Просто напиши що купив і суму:\n` +
        `<code>каву 85</code>\n` +
        `<code>продукти 500 моно</code>\n` +
        `<code>зп 40000</code>\n\n` +
        `📋 <b>Команди:</b>\n` +
        `/balance — баланс по рахунках\n` +
        `/today — сьогодні\n` +
        `/month — місяць\n` +
        `/week — тиждень\n` +
        `/stats — статистика\n` +
        `/last — останні операції`,
        { reply_markup: MAIN_KEYBOARD }
      );
      return res.status(200).json({ ok: true });

    case '/balance': {
      const wallets = await getWalletBalances();
      if (!wallets.length) {
        await sendMessage(chatId, '💳 Ще жодних операцій.');
        return res.status(200).json({ ok: true });
      }
      let txt = `💳 <b>Баланс по рахунках:</b>\n\n`;
      let totalUah = 0;
      const SYM = { USD: '$', EUR: '€' };
      wallets.forEach(w => {
        const sign = w.balance >= 0 ? '+' : '';
        if (w.primaryCur !== 'UAH') {
          const sym = SYM[w.primaryCur] || w.primaryCur;
          txt += `💳 <b>${w.name}</b>: ${sign}${w.balance} ${sym} (≈ ${fmtMoney(Math.abs(w.balanceUah))})\n`;
        } else {
          txt += `💳 <b>${w.name}</b>: ${sign}${fmtMoney(w.balance)}\n`;
        }
        totalUah += w.balanceUah;
      });
      txt += `━━━━━━━━━━━━━━━\n💎 Разом: <b>${totalUah >= 0 ? '+' : ''}${fmtMoney(totalUah)}</b>`;
      await sendMessage(chatId, txt);
      return res.status(200).json({ ok: true });
    }

    case '/today': {
      const today = todayKyiv();
      const ops = await getPeriodOps(today, today);
      const totalExp = ops.filter(o => o.type === 'Витрата').reduce((s, o) => s + (o.amountUah || o.amount || 0), 0);
      const totalInc = ops.filter(o => o.type === 'Дохід').reduce((s, o) => s + (o.amountUah || o.amount || 0), 0);

      let txt = `📅 <b>Сьогодні (${today}):</b>\n\n`;
      if (!ops.length) {
        txt += 'Ще жодної операції.';
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

    case '/month': {
      const { from, to, label } = currentMonthRange();
      const ops = await getPeriodOps(from, to);
      await sendMessage(chatId, formatPeriodStats(ops, `місяць ${label}`));
      return res.status(200).json({ ok: true });
    }

    case '/week': {
      const { from, to } = weekRange();
      const ops = await getPeriodOps(from, to);
      await sendMessage(chatId, formatPeriodStats(ops, 'тиждень'));
      return res.status(200).json({ ok: true });
    }

    case '/stats': {
      const { from, to, label } = currentMonthRange();
      const ops = await getPeriodOps(from, to);
      await sendMessage(chatId, formatStats(ops, label));
      return res.status(200).json({ ok: true });
    }

    case '/last': {
      const ops = await getLastOps(5);
      if (!ops.length) {
        await sendMessage(chatId, '📋 Ще жодних операцій.');
        return res.status(200).json({ ok: true });
      }
      let txt = `📋 <b>Останні операції:</b>\n\n`;
      const buttons = ops.map((o, i) => {
        const emoji = CAT_EMOJI[o.category] || '📌';
        const sign = o.type === 'Витрата' ? '-' : '+';
        txt += `${i + 1}. ${emoji} ${sign}${fmtMoney(o.amount)} · ${o.category}${o.desc ? ' · ' + o.desc : ''} · <i>${o.date}</i>\n`;
        return [{ text: `🗑 Видалити #${i + 1}`, callback_data: `dl:${o.id}` }];
      });
      await sendMessage(chatId, txt, { reply_markup: { inline_keyboard: buttons } });
      return res.status(200).json({ ok: true });
    }

    default:
      await sendMessage(chatId, `❓ Невідома команда. Натисни кнопку нижче або напиши витрату.`, { reply_markup: MAIN_KEYBOARD });
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
    if (!update) return res.status(200).json({ ok: true });

    // Callback від inline кнопок
    if (update.callback_query) {
      return handleCallback(update.callback_query, res);
    }

    if (!update.message) return res.status(200).json({ ok: true });

    const msg = update.message;
    const chatId = msg.chat.id;
    const userId = msg.from.id;
    const userName = msg.from.first_name || 'User';
    const text = msg.text || '';

    // Перевірка доступу
    if (ALLOWED_USERS.length > 0 && !ALLOWED_USERS.includes(userId)) {
      await sendMessage(chatId, '⛔ У вас немає доступу до цього бота.');
      return res.status(200).json({ ok: true });
    }

    // Реєстрація імені (якщо чекаємо відповіді після /start)
    if (!text.startsWith('/') && await checkPendingReg(userId)) {
      const name = text.trim().substring(0, 30);
      await registerUser(userId, name);
      await clearPendingReg(userId);
      await sendMessage(chatId,
        `✅ Відмінно, <b>${name}</b>! Тепер ти зареєстрований.\n\nНадсилай витрати або доходи:`,
        { reply_markup: MAIN_KEYBOARD }
      );
      return res.status(200).json({ ok: true });
    }

    const who = await getWho(userId, userName);

    // Команди
    if (text.startsWith('/')) {
      return handleCommand(text.split(' ')[0].toLowerCase(), chatId, userId, userName, who, res);
    }

    // Reply keyboard кнопки
    const BTN_MAP = {
      '💰 Баланс':     '/balance',
      '📅 Сьогодні':   '/today',
      '📆 Місяць':     '/month',
      '⏱ Тиждень':    '/week',
      '📊 Статистика': '/stats',
      '📋 Останні':    '/last',
      '❓ Допомога':   '/help',
    };

    if (BTN_MAP[text]) {
      return handleCommand(BTN_MAP[text], chatId, userId, userName, who, res);
    }

    if (text === '➕ Витрата') {
      await sendMessage(chatId, `➕ Напиши витрату:\n<code>каву 85</code>\n<code>продукти 500 моно</code>`);
      return res.status(200).json({ ok: true });
    }
    if (text === '💵 Дохід') {
      await sendMessage(chatId, `💵 Напиши дохід:\n<code>зп 40000</code>\n<code>дохід 5000 підробіток</code>`);
      return res.status(200).json({ ok: true });
    }

    // Парсимо операцію і показуємо для підтвердження
    const parsed = parseMessage(text);
    if (!parsed) {
      await sendMessage(chatId,
        `🤔 Не зрозумів. Напиши суму і опис:\n<code>каву 85</code>\n<code>зп 40000</code>`
      );
      return res.status(200).json({ ok: true });
    }

    const rates = await getExchangeRates();
    const amountUah = parsed.currency !== 'UAH'
      ? Math.round(parsed.amount * (rates[parsed.currency] || 1))
      : parsed.amount;

    const opData = { type: parsed.type, amount: parsed.amount, currency: parsed.currency, amountUah, category: parsed.category, card: parsed.card, desc: parsed.desc, who };
    const pendingId = await savePending(opData, userId);

    await sendMessage(chatId, pendingPreviewText(opData), {
      reply_markup: buildConfirmKeyboard(pendingId, opData.type),
    });

    return res.status(200).json({ ok: true });

  } catch (error) {
    console.error('Telegram webhook error:', error);
    return res.status(200).json({ ok: true, error: error.message });
  }
};
