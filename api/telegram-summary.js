// /api/telegram-summary.js — Щоденний підсумок о 22:00 Kyiv
// Cron: "0 19 * * *" (19:00 UTC = 22:00 Kyiv влітку)

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
const CHAT_ID   = process.env.TELEGRAM_CHAT_ID;
const FAMILY_ID = process.env.FAMILY_ID || 'koval';

const CAT_EMOJI = {
  'Продукти': '🛒', 'Ресторани': '☕', 'Транспорт': '🚗', 'Комунальні': '🏠',
  "Здоров'я": '💊', 'Одяг': '👕', 'Розваги': '🎮', 'Дім': '🛋', 'Дитячі': '👶',
  'Зарплата': '💰', 'Підробіток': '💵', 'Пенсія': '🏦', 'Виплата': '📋',
  'Інше': '📌',
};

function fmtMoney(amount) {
  return Math.round(Math.abs(amount)).toLocaleString('uk-UA') + ' ₴';
}

function todayKyiv() {
  return new Date().toLocaleDateString('sv-SE', { timeZone: 'Europe/Kyiv' });
}

module.exports = async function handler(req, res) {
  if (!BOT_TOKEN || !CHAT_ID) {
    return res.status(500).json({ error: 'Missing TELEGRAM env vars' });
  }

  try {
    const today = todayKyiv();
    const snapshot = await db.collection('families').doc(FAMILY_ID)
      .collection('operations')
      .where('date', '==', today)
      .get();

    const ops = snapshot.docs.map(d => d.data()).filter(o => o.category !== 'Переказ');

    if (!ops.length) {
      return res.status(200).json({ ok: true, note: 'no ops today, skipping' });
    }

    const expenses = ops.filter(o => o.type === 'Витрата');
    const incomes  = ops.filter(o => o.type === 'Дохід');
    const totalExp = expenses.reduce((s, o) => s + (o.amountUah || o.amount || 0), 0);
    const totalInc = incomes.reduce((s, o) => s + (o.amountUah || o.amount || 0), 0);

    const byCat = {};
    expenses.forEach(o => {
      const cat = o.category || 'Інше';
      byCat[cat] = (byCat[cat] || 0) + (o.amountUah || o.amount || 0);
    });

    let txt = `🌙 <b>Підсумок дня ${today}</b>\n\n`;

    if (expenses.length) {
      txt += `💸 <b>Витрати: ${fmtMoney(totalExp)}</b>\n`;
      Object.entries(byCat).sort((a, b) => b[1] - a[1]).forEach(([cat, amt]) => {
        txt += `${CAT_EMOJI[cat] || '📌'} ${cat}: ${fmtMoney(amt)}\n`;
      });
    }

    if (incomes.length) {
      txt += `\n💰 <b>Доходи: ${fmtMoney(totalInc)}</b>\n`;
      incomes.forEach(o => {
        txt += `${CAT_EMOJI[o.category] || '📌'} ${o.category}: +${fmtMoney(o.amount)}\n`;
      });
    }

    const net = totalInc - totalExp;
    txt += `\n${net >= 0 ? '✅' : '⚠️'} Підсумок дня: <b>${net >= 0 ? '+' : ''}${fmtMoney(net)}</b>`;

    await fetch(`https://api.telegram.org/bot${BOT_TOKEN}/sendMessage`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ chat_id: CHAT_ID, text: txt, parse_mode: 'HTML' }),
    });

    return res.status(200).json({ ok: true, ops: ops.length });
  } catch (e) {
    console.error('telegram-summary error:', e);
    return res.status(500).json({ error: e.message });
  }
};
