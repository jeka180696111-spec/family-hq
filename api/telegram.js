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

// ── User management (multi-family) ──────────────────────────
// Telegram user → {name, familyId} or null (if not registered)
async function getTelegramUser(telegramUserId) {
  try {
    const doc = await db.collection('telegramLinks').doc(String(telegramUserId)).get();
    if (doc.exists) return doc.data(); // {name, familyId, registeredAt}
  } catch (e) {}
  return null;
}

// Register after collecting name + invite code
async function registerTelegramUser(telegramUserId, { name, familyId }) {
  await db.collection('telegramLinks').doc(String(telegramUserId)).set({
    name, familyId, registeredAt: new Date().toISOString(),
  });
  // Add to family members list if not already there
  try {
    const familyRef = db.collection('families').doc(familyId);
    const familyDoc = await familyRef.get();
    if (familyDoc.exists) {
      const members = familyDoc.data().members || [];
      if (!members.find(m => m.name === name)) {
        members.push({ name, source: 'telegram', joinedAt: new Date().toISOString() });
        await familyRef.update({ members });
      }
    }
  } catch (e) { console.error('registerTelegramUser family update error:', e); }
}

// Multi-step registration state: step='name' or step='code', pending name stored
async function setPendingReg(userId, data = {}) {
  await db.collection('telegramPending').doc(String(userId)).set({
    createdAt: new Date().toISOString(),
    step: 'name',
    ...data,
  });
}

async function getPendingReg(userId) {
  const doc = await db.collection('telegramPending').doc(String(userId)).get();
  return doc.exists ? doc.data() : null;
}

async function updatePendingReg(userId, data) {
  await db.collection('telegramPending').doc(String(userId)).update(data);
}

async function clearPendingReg(userId) {
  await db.collection('telegramPending').doc(String(userId)).delete();
}

// Validate invite code → returns familyId or null
async function validateInviteCode(code) {
  try {
    const doc = await db.collection('invites').doc(code.toUpperCase()).get();
    if (!doc.exists) return null;
    const d = doc.data();
    if (d.used) return null;
    if (d.expiresAt && new Date(d.expiresAt) < new Date()) return null;
    return d.familyId;
  } catch (e) { return null; }
}

// ── Pending operations ───────────────────────────────────────
async function savePending(op, userId) {
  const familyId = op.familyId;
  const ref = db.collection('families').doc(familyId).collection('pendingOps');
  const doc = await ref.add({ ...op, userId: String(userId), createdAt: new Date().toISOString() });
  return doc.id;
}

async function getPending(id, familyId) {
  const doc = await db.collection('families').doc(familyId)
    .collection('pendingOps').doc(id).get();
  return doc.exists ? { ...doc.data(), _docFamilyId: familyId } : null;
}

async function updatePending(id, familyId, data) {
  await db.collection('families').doc(familyId)
    .collection('pendingOps').doc(id).update(data);
}

async function deletePending(id, familyId) {
  await db.collection('families').doc(familyId)
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

// ── Claude vision — аналіз фото чека ───────────────────────
async function analyzeReceiptWithClaude(base64Image) {
  try {
    const response = await fetch('https://api.anthropic.com/v1/messages', {
      method: 'POST',
      headers: {
        'x-api-key': process.env.ANTHROPIC_API_KEY,
        'anthropic-version': '2023-06-01',
        'content-type': 'application/json',
      },
      body: JSON.stringify({
        model: 'claude-haiku-4-5-20251001',
        max_tokens: 256,
        system: 'Ти помічник для розпізнавання чеків. Повертай тільки валідний JSON без пояснень.',
        messages: [
          {
            role: 'user',
            content: [
              {
                type: 'image',
                source: {
                  type: 'base64',
                  media_type: 'image/jpeg',
                  data: base64Image,
                },
              },
              {
                type: 'text',
                text: 'Це фото чека або квитанції. Витягни дані та поверни ТІЛЬКИ JSON без пояснень:\n{"amount": <число без валюти>, "store": "<назва магазину>", "date": "<YYYY-MM-DD або null>", "category": "<одна з: Продукти, Ресторани, Транспорт, Комунальні, Здоров\'я, Одяг, Розваги, Дім, Дитячі, Інше>"}\nЯкщо не можеш прочитати - поверни {"error": "не вдалося розпізнати"}',
              },
            ],
          },
        ],
      }),
    });

    if (!response.ok) return null;

    const data = await response.json();
    const text = (data.content?.[0]?.text || '').trim();

    try {
      return JSON.parse(text);
    } catch {
      const match = text.match(/\{[\s\S]*\}/);
      if (match) return JSON.parse(match[0]);
      return null;
    }
  } catch (e) {
    console.error('analyzeReceiptWithClaude error:', e);
    return null;
  }
}

// ── Завантаження фото з Telegram ────────────────────────────
async function downloadTelegramPhoto(fileId) {
  const fileRes = await fetch(`https://api.telegram.org/bot${BOT_TOKEN}/getFile?file_id=${fileId}`);
  const fileData = await fileRes.json();
  const filePath = fileData.result?.file_path;
  if (!filePath) throw new Error('Cannot get file path');

  const imgRes = await fetch(`https://api.telegram.org/file/bot${BOT_TOKEN}/${filePath}`);
  const buffer = await imgRes.arrayBuffer();
  return {
    base64: Buffer.from(buffer).toString('base64'),
    mediaType: 'image/jpeg',
  };
}

// ── Обробка фото чека ────────────────────────────────────────
async function handleReceiptPhoto(chatId, who, familyId, msg, res) {
  try {
    // Беремо найбільше фото
    const photos = [...msg.photo].sort((a, b) => (b.file_size || 0) - (a.file_size || 0));
    const fileId = photos[0].file_id;

    await sendMessage(chatId, '🔍 Аналізую чек...');

    const { base64 } = await downloadTelegramPhoto(fileId);
    const result = await analyzeReceiptWithClaude(base64);

    if (!result || result.error) {
      await sendMessage(chatId, 'Не вдалося розпізнати чек 😕\nСпробуй зробити чіткіше фото.');
      return res.status(200).json({ ok: true });
    }

    const amount = parseFloat(result.amount) || 0;
    if (!amount) {
      await sendMessage(chatId, 'Не вдалося розпізнати суму чека 😕');
      return res.status(200).json({ ok: true });
    }

    const opData = {
      type: 'Витрата',
      amount,
      currency: 'UAH',
      amountUah: amount,
      category: result.category || 'Інше',
      desc: result.store || '',
      card: '',
      who,
      familyId,
      date: result.date || todayKyiv(),
    };

    const pendingId = await savePending(opData, msg.from.id);

    const emoji = CAT_EMOJI[opData.category] || '💸';
    let txt = `🧾 <b>Чек розпізнано:</b>\n\n`;
    txt += `${emoji} <b>${opData.category}</b>\n`;
    txt += `💰 Сума: <b>${fmtMoney(amount)}</b>\n`;
    if (opData.desc) txt += `🏪 Магазин: ${opData.desc}\n`;
    if (result.date) txt += `📅 Дата: ${result.date}\n`;
    txt += `👤 ${who}\n`;
    txt += `\n<i>Перевір та збережи операцію:</i>`;

    await sendMessage(chatId, txt, {
      reply_markup: {
        inline_keyboard: [
          [
            { text: '✅ Зберегти',   callback_data: `sv:${pendingId}` },
            { text: '❌ Скасувати', callback_data: `cl:${pendingId}` },
          ],
        ],
      },
    });

    return res.status(200).json({ ok: true });
  } catch (e) {
    console.error('handleReceiptPhoto error:', e);
    await sendMessage(chatId, 'Не вдалося розпізнати чек 😕');
    return res.status(200).json({ ok: true });
  }
}

async function saveOperation(op) {
  const familyId = op.familyId;
  const ref = db.collection('families').doc(familyId).collection('operations');
  await ref.add({
    date: op.date || todayKyiv(),
    type: op.type,
    category: op.category,
    amount: op.amount,
    currency: op.currency || 'UAH',
    amountUah: op.amountUah || op.amount,
    desc: op.desc || '',
    who: op.who || '',
    card: op.card || '',
    source: 'Telegram',
    createdAt: new Date().toISOString(),
  });
}

// Баланс по кошельках з урахуванням валюти та кредитних лімітів
async function getWalletBalances(familyId) {
  const [snapshot, rates, settingsDoc] = await Promise.all([
    db.collection('families').doc(familyId).collection('operations').get(),
    getExchangeRates(),
    db.collection('families').doc(familyId).get(),
  ]);

  const creditLimits = {};
  if (settingsDoc.exists) {
    const s = settingsDoc.data();
    const cards = s.cards || {};
    Object.values(cards).forEach(memberCards => {
      (Array.isArray(memberCards) ? memberCards : []).forEach(c => {
        if (c.creditLimit) creditLimits[c.id] = Number(c.creditLimit);
      });
    });
    // Backwards compat with old cardsEvgen/cardsMarina format
    ['cardsEvgen', 'cardsMarina'].forEach(key => {
      (s[key] || []).forEach(c => {
        if (c.creditLimit) creditLimits[c.id] = Number(c.creditLimit);
      });
    });
  }

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
      const primaryCur = Object.keys(v.currencies).find(c => c !== 'UAH') || 'UAH';
      const curData = v.currencies[primaryCur] || { income: 0, expense: 0 };
      const balance = Math.round(curData.income - curData.expense);

      let balanceUah;
      if (primaryCur === 'UAH') {
        balanceUah = balance;
      } else {
        const rate = rates[primaryCur] || 1;
        balanceUah = Math.round(balance * rate);
      }

      const creditLimit = creditLimits[name] || 0;
      const creditUsed = creditLimit > 0 ? Math.max(0, -balance) : 0;
      const creditAvail = creditLimit > 0 ? Math.max(0, creditLimit - creditUsed) : 0;

      return { name, balance, primaryCur, balanceUah, creditLimit, creditUsed, creditAvail };
    })
    .filter(w => w.balance !== 0 || w.creditLimit > 0)
    .sort((a, b) => Math.abs(b.balanceUah) - Math.abs(a.balanceUah));
}

async function getPeriodOps(familyId, from, to) {
  const snapshot = await db.collection('families').doc(familyId)
    .collection('operations')
    .where('date', '>=', from)
    .where('date', '<=', to)
    .orderBy('date', 'desc')
    .get();
  return snapshot.docs.map(d => d.data()).filter(o => o.category !== 'Переказ');
}

async function getLastOps(familyId, n = 5) {
  const snapshot = await db.collection('families').doc(familyId)
    .collection('operations')
    .orderBy('createdAt', 'desc')
    .limit(n)
    .get();
  return snapshot.docs
    .map(d => ({ id: d.id, ...d.data() }))
    .filter(o => o.category !== 'Переказ');
}

async function deleteOperation(familyId, id) {
  await db.collection('families').doc(familyId)
    .collection('operations').doc(id).delete();
}

async function getTodaySameCategoryOps(familyId, who, category) {
  const today = todayKyiv();
  const snapshot = await db.collection('families').doc(familyId)
    .collection('operations')
    .where('date', '==', today)
    .where('who', '==', who)
    .where('category', '==', category)
    .where('type', '==', 'Витрата')
    .get();
  return snapshot.docs.map(d => d.data());
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
  const userId = cb.from.id;
  const [action, id, ...rest] = data.split(':');
  const newCat = rest.join(':');

  // familyId stored in pending op
  const tgUser = await getTelegramUser(userId);
  const familyId = tgUser?.familyId;
  if (!familyId) {
    await answerCallback(cb.id, '⚠️ Спочатку зареєструйся');
    return res.status(200).json({ ok: true });
  }

  if (action === 'sv') {
    const op = await getPending(id, familyId);
    if (!op) {
      await answerCallback(cb.id, '⚠️ Операція застаріла');
      await editMessage(chatId, messageId, '⚠️ Операція застаріла. Введи знову.');
      return res.status(200).json({ ok: true });
    }
    await saveOperation(op);
    await deletePending(id, familyId);

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

    // Проактивний саркастичний коментар при дублікаті категорії за день
    if (op.type === 'Витрата') {
      try {
        const todayOps = await getTodaySameCategoryOps(familyId, op.who, op.category);
        if (todayOps.length >= 2) {
          const comment = await generateSarcasticComment(op, todayOps);
          if (comment) await sendMessage(chatId, comment);
        }
      } catch (e) {}
    }

    return res.status(200).json({ ok: true });
  }

  if (action === 'cl') {
    await deletePending(id, familyId).catch(() => {});
    await editMessage(chatId, messageId, '❌ Скасовано.');
    await answerCallback(cb.id, 'Скасовано');
    return res.status(200).json({ ok: true });
  }

  if (action === 'ct') {
    const op = await getPending(id, familyId);
    if (!op) {
      await answerCallback(cb.id, '⚠️ Операція застаріла');
      return res.status(200).json({ ok: true });
    }
    await updatePending(id, familyId, { category: newCat });
    const updated = { ...op, category: newCat };
    await editMessage(chatId, messageId, pendingPreviewText(updated), {
      reply_markup: buildConfirmKeyboard(id, op.type),
    });
    await answerCallback(cb.id, `📁 ${newCat}`);
    return res.status(200).json({ ok: true });
  }

  if (action === 'dl') {
    await deleteOperation(familyId, id);
    await editMessage(chatId, messageId, '🗑 Операцію видалено.');
    await answerCallback(cb.id, 'Видалено');
    return res.status(200).json({ ok: true });
  }

  await answerCallback(cb.id);
  return res.status(200).json({ ok: true });
}

// ── Command handler ──────────────────────────────────────────
async function handleCommand(cmd, chatId, userId, userName, who, familyId, res) {
  switch (cmd) {
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
      const wallets = await getWalletBalances(familyId);
      if (!wallets.length) {
        await sendMessage(chatId, '💳 Ще жодних операцій.');
        return res.status(200).json({ ok: true });
      }
      let txt = `💳 <b>Баланс по рахунках:</b>\n\n`;
      let totalUah = 0;
      const SYM = { USD: '$', EUR: '€' };
      wallets.forEach(w => {
        const pos = w.balance >= 0;
        const sign = pos ? '+' : '−';
        const absNative = Math.abs(w.balance);
        const absUah = Math.abs(w.balanceUah);
        if (w.primaryCur !== 'UAH') {
          const sym = SYM[w.primaryCur] || w.primaryCur;
          txt += `💳 <b>${w.name}</b>: ${sign}${absNative} ${sym} (≈ ${sign === '−' ? '−' : ''}${fmtMoney(absUah)})\n`;
        } else if (w.creditLimit > 0) {
          // Кредитна картка: показуємо власні кошти і кредит окремо
          const ownFunds = Math.max(0, w.balance);
          if (w.creditUsed > 0) {
            txt += `💳 <b>${w.name}</b>: −${fmtMoney(w.creditUsed)} <i>(кредит)</i>\n`;
            txt += `   └ вільно: ${fmtMoney(w.creditAvail)} / ${fmtMoney(w.creditLimit)}\n`;
          } else {
            txt += `💳 <b>${w.name}</b>: +${fmtMoney(ownFunds)}\n`;
            txt += `   └ кредит вільний · ліміт ${fmtMoney(w.creditLimit)}\n`;
          }
        } else {
          txt += `💳 <b>${w.name}</b>: ${sign}${fmtMoney(absNative)}\n`;
        }
        totalUah += w.balanceUah;
      });
      const totalSign = totalUah >= 0 ? '+' : '−';
      txt += `━━━━━━━━━━━━━━━\n💎 Разом: <b>${totalSign}${fmtMoney(Math.abs(totalUah))}</b>`;
      await sendMessage(chatId, txt);
      return res.status(200).json({ ok: true });
    }

    case '/today': {
      const today = todayKyiv();
      const ops = await getPeriodOps(familyId, today, today);
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
      const ops = await getPeriodOps(familyId, from, to);
      await sendMessage(chatId, formatPeriodStats(ops, `місяць ${label}`));
      return res.status(200).json({ ok: true });
    }

    case '/week': {
      const { from, to } = weekRange();
      const ops = await getPeriodOps(familyId, from, to);
      await sendMessage(chatId, formatPeriodStats(ops, 'тиждень'));
      return res.status(200).json({ ok: true });
    }

    case '/stats': {
      const { from, to, label } = currentMonthRange();
      const ops = await getPeriodOps(familyId, from, to);
      await sendMessage(chatId, formatStats(ops, label));
      return res.status(200).json({ ok: true });
    }

    case '/last': {
      const ops = await getLastOps(familyId, 5);
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

// ── Проактивні саркастичні коментарі ────────────────────────
async function generateSarcasticComment(op, todayOps) {
  const apiKey = process.env.ANTHROPIC_API_KEY;
  if (!apiKey) return null;

  const totalToday = todayOps.reduce((s, o) => s + (o.amountUah || o.amount || 0), 0);
  const count = todayOps.length;
  const stores = todayOps.map(o => o.desc).filter(Boolean).join(', ');
  const context = `${op.who} щойно зробив ${count}-у витрату сьогодні в категорії "${op.category}": ${op.amount} ₴${op.desc ? ` (${op.desc})` : ''}. Всього сьогодні в цій категорії: ${fmtMoney(totalToday)}${stores ? `. Місця: ${stores}` : ''}.`;

  try {
    const response = await fetch('https://api.anthropic.com/v1/messages', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'x-api-key': apiKey, 'anthropic-version': '2023-06-01' },
      body: JSON.stringify({
        model: 'claude-haiku-4-5-20251001',
        max_tokens: 120,
        system: `Ти — саркастичний фінансовий радник родини Кіосе. Стиль: їдкий гумор, але з теплотою.
Правила: УКРАЇНСЬКА, ДУЖЕ коротко (1-2 речення), один дотепний коментар про повторну витрату за день у тій самій категорії. 1-2 емодзі максимум. Не запитуй питань. Не повторюй факти дослівно.`,
        messages: [{ role: 'user', content: context }],
      }),
    });
    const data = await response.json();
    return data.content?.filter(c => c.type === 'text').map(c => c.text).join('') || null;
  } catch (e) {
    return null;
  }
}

// ── AI Чат ───────────────────────────────────────────────────
function isConversational(text) {
  if (text.length < 4) return false;
  if (text.includes('?') || text.includes('?')) return true;
  const triggers = ['як', 'що', 'де', 'чому', 'скільки', 'коли', 'чи', 'поради', 'порада', 'допоможи', 'розкажи', 'поясни', 'аналіз', 'звіт', 'прогноз', 'розбір', 'критикуй', 'оціни', 'думаєш'];
  const lower = text.toLowerCase();
  return triggers.some(t => lower.startsWith(t) || lower.includes(' ' + t));
}

async function handleAIChat(chatId, userText, who, familyId, res) {
  try {
    const [wallets, recentOps] = await Promise.all([
      getWalletBalances(familyId),
      getLastOps(familyId, 10),
    ]);
    const totalUah = wallets.reduce((s, w) => s + w.balanceUah, 0);
    const recentExp = recentOps.filter(o => o.type === 'Витрата').slice(0, 5)
      .map(o => `${o.desc || o.category} ${o.amount}₴`).join(', ');
    const context = `Користувач: ${who}. Загальний баланс: ${fmtMoney(totalUah)}. Останні витрати: ${recentExp || 'немає'}.`;

    const apiKey = process.env.ANTHROPIC_API_KEY;
    if (!apiKey) {
      await sendMessage(chatId, '❌ AI ключ не налаштований.');
      return res.status(200).json({ ok: true });
    }

    const systemPrompt = `Ти — саркастичний фінансовий радник родини Кіосе. Стиль: дотепний, їдкий, але з турботою.
Правила: відповідай УКРАЇНСЬКОЮ, коротко (2-4 речення), використовуй конкретні цифри якщо є, емодзі помірно.
${context}`;

    const response = await fetch('https://api.anthropic.com/v1/messages', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'x-api-key': apiKey, 'anthropic-version': '2023-06-01' },
      body: JSON.stringify({
        model: 'claude-haiku-4-5-20251001',
        max_tokens: 400,
        system: systemPrompt,
        messages: [{ role: 'user', content: userText }],
      }),
    });

    const data = await response.json();
    const reply = data.content?.filter(c => c.type === 'text').map(c => c.text).join('\n') || 'Щось пішло не так 🤷';
    await sendMessage(chatId, reply);
  } catch (e) {
    await sendMessage(chatId, '❌ Помилка AI: ' + e.message);
  }
  return res.status(200).json({ ok: true });
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

    // ── Багатокрокова реєстрація ─────────────────────────────
    const pending = !text.startsWith('/') ? await getPendingReg(userId) : null;
    if (pending) {
      if (pending.step === 'name') {
        const name = text.trim().substring(0, 30);
        if (name.length < 2) {
          await sendMessage(chatId, '❌ Ім\'я має бути щонайменше 2 символи. Спробуй ще раз:');
          return res.status(200).json({ ok: true });
        }
        await updatePendingReg(userId, { step: 'code', pendingName: name });
        await sendMessage(chatId,
          `👋 Привіт, <b>${name}</b>!\n\n` +
          `Тепер введи <b>код запрошення</b> від члена своєї родини (6 символів).\n\n` +
          `Якщо у тебе немає коду — попроси того, хто вже користується додатком, ` +
          `згенерувати його в Налаштуваннях → "Запросити члена родини".`
        );
        return res.status(200).json({ ok: true });
      }

      if (pending.step === 'code') {
        const code = text.trim().toUpperCase();
        const familyIdFromCode = await validateInviteCode(code);
        if (!familyIdFromCode) {
          await sendMessage(chatId, '❌ Невірний або застарілий код. Попроси новий і спробуй ще раз:');
          return res.status(200).json({ ok: true });
        }
        const name = pending.pendingName || userName;
        await registerTelegramUser(userId, { name, familyId: familyIdFromCode });
        await clearPendingReg(userId);
        await sendMessage(chatId,
          `✅ <b>Готово, ${name}!</b> Ти приєднався до родини.\n\nТепер можеш надсилати витрати та доходи:`,
          { reply_markup: MAIN_KEYBOARD }
        );
        return res.status(200).json({ ok: true });
      }
    }

    // ── Перевіряємо чи є зареєстрований Telegram-акаунт ─────
    const tgUser = await getTelegramUser(userId);

    // /start — завжди доступний, запускає реєстрацію якщо потрібно
    if (text === '/start') {
      if (tgUser) {
        await sendMessage(chatId,
          `👋 Привіт, <b>${tgUser.name}</b>! З поверненням 💪\n\nНадсилай витрати або доходи:`,
          { reply_markup: MAIN_KEYBOARD }
        );
      } else {
        await setPendingReg(userId, { step: 'name' });
        await sendMessage(chatId,
          `👋 Привіт! Я бот для сімейного бюджету.\n\n` +
          `Щоб почати, мені потрібно тебе зареєструвати.\n\n` +
          `<b>Як тебе звати?</b> (введи своє ім\'я)`
        );
      }
      return res.status(200).json({ ok: true });
    }

    // Незареєстрований — просимо пройти реєстрацію
    if (!tgUser) {
      await sendMessage(chatId,
        `⚠️ Ти ще не зареєстрований.\n\nНатисни /start щоб почати реєстрацію.`
      );
      return res.status(200).json({ ok: true });
    }

    const who = tgUser.name;
    const familyId = tgUser.familyId;

    // Фото чека
    if (msg.photo && msg.photo.length > 0) {
      return handleReceiptPhoto(chatId, who, familyId, msg, res);
    }

    // Фото чека
    if (msg.photo && msg.photo.length > 0) {
      return handleReceiptPhoto(chatId, who, msg, res);
    }

    // Команди
    if (text.startsWith('/')) {
      return handleCommand(text.split(' ')[0].toLowerCase(), chatId, userId, userName, who, familyId, res);
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
      return handleCommand(BTN_MAP[text], chatId, userId, userName, who, familyId, res);
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
      if (isConversational(text)) {
        return handleAIChat(chatId, text, who, familyId, res);
      }
      await sendMessage(chatId,
        `🤔 Не зрозумів. Напиши суму і опис:\n<code>каву 85</code>\n<code>зп 40000</code>\n\nАбо постав питання — я відповім 😏`
      );
      return res.status(200).json({ ok: true });
    }

    const rates = await getExchangeRates();
    const amountUah = parsed.currency !== 'UAH'
      ? Math.round(parsed.amount * (rates[parsed.currency] || 1))
      : parsed.amount;

    const opData = { type: parsed.type, amount: parsed.amount, currency: parsed.currency, amountUah, category: parsed.category, card: parsed.card, desc: parsed.desc, who, familyId };
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
