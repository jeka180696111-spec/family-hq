// ═══════════════════════════════════════════════════════════════
// API — Firestore (замість Google Apps Script)
// ═══════════════════════════════════════════════════════════════

import { state, syncState, APP_CONFIG,
         getFamilyMembers, setFamilyMembers, FAMILY_MEMBERS,
         DEFAULT_EXP_CATS, DEFAULT_INC_CATS, DEFAULT_WALLET_TYPES, DEFAULT_CARDS,
} from './config.js';
import {
  getExpCats, getIncCats, getCards, getProfiles,
  getWalletTypes, getFamilyName,
} from './storage.js';
import { log, logError } from './utils.js';

let db = null;

// Дата в Київському часовому поясі
function todayKyiv() {
  return new Date().toLocaleDateString('sv-SE', { timeZone: 'Europe/Kyiv' });
}

// ── Ініціалізація Firestore ─────────────────────────────────
export function initFirestore() {
  db = firebase.firestore();
  log('Firestore initialized');
}

// ── Хелпер: колекція родини ──────────────────────────────────
function familyRef() {
  return db.collection('families').doc(state.familyId);
}

// ═══════════════════════════════════════════════════════════════
// ЧИТАННЯ
// ═══════════════════════════════════════════════════════════════

// ── Dashboard (агрегація операцій за період) ─────────────────
export async function apiGet(action, params) {
  if (!db) throw new Error('Firestore not initialized');

  switch (action) {
    case 'ping':
      return { ok: true, version: 'firebase-1.0', features: ['walletTypes', 'familyName', 'periodFilter'] };

    case 'dashboard':
      return getDashboard(params?.period || 'month');

    case 'operations':
      return getOperations(params);

    case 'settings':
      return getSettings();

    case 'reserve':
      return getReserve();

    case 'goals':
      return getGoals();

    case 'fx':
      return getFxRates();

    case 'trend':
      return getTrend();

    case 'transfers':
      return getTransfers();

    default:
      throw new Error('Unknown action: ' + action);
  }
}

// ── Дашборд ──────────────────────────────────────────────────
async function getDashboard(period) {
  // Використовуємо Київський часовий пояс для дат (не UTC)
  const kyivNow = new Date().toLocaleDateString('sv-SE', { timeZone: 'Europe/Kyiv' });
  const [kyivYear, kyivMonth] = kyivNow.split('-').map(Number);
  let startDateStr;

  if (period === 'year') {
    startDateStr = `${kyivYear}-01-01`;
  } else if (period === 'quarter') {
    const q = Math.floor((kyivMonth - 1) / 3);
    startDateStr = `${kyivYear}-${String(q * 3 + 1).padStart(2, '0')}-01`;
  } else {
    startDateStr = `${kyivYear}-${String(kyivMonth).padStart(2, '0')}-01`;
  }

  const snapshot = await familyRef().collection('operations')
    .where('date', '>=', startDateStr)
    .orderBy('date', 'desc')
    .get();

  const ops = snapshot.docs.map(doc => ({ id: doc.id, ...doc.data() }));
  const realOps = ops.filter(o => o.category !== 'Переказ');

  const totalIncome = realOps.filter(o => o.type === 'Дохід').reduce((s, o) => s + (o.amountUah || o.amount || 0), 0);
  const totalExpense = realOps.filter(o => o.type === 'Витрата').reduce((s, o) => s + (o.amountUah || o.amount || 0), 0);

  // По членах
  const byMember = {};
  realOps.forEach(o => {
    const who = o.who || 'Інше';
    if (!byMember[who]) byMember[who] = { income: 0, expense: 0 };
    if (o.type === 'Дохід') byMember[who].income += (o.amountUah || o.amount || 0);
    if (o.type === 'Витрата') byMember[who].expense += (o.amountUah || o.amount || 0);
  });
  // Додаємо balance і byCard
  ops.forEach(o => {
    const who = o.who || 'Інше';
    const card = o.card || '';
    if (!byMember[who]) byMember[who] = { income: 0, expense: 0 };
    if (!byMember[who].byCard) byMember[who].byCard = {};
    if (!card) return;
    if (!byMember[who].byCard[card]) byMember[who].byCard[card] = { income: 0, expense: 0, balance: 0 };
    if (o.type === 'Дохід') byMember[who].byCard[card].income += (o.amountUah || o.amount || 0);
    if (o.type === 'Витрата') byMember[who].byCard[card].expense += (o.amountUah || o.amount || 0);
  });
  Object.values(byMember).forEach(m => {
    m.balance = (m.income || 0) - (m.expense || 0);
    if (m.byCard) Object.values(m.byCard).forEach(c => c.balance = c.income - c.expense);
  });

  // По категоріях (загальне + по членах)
  const byCategory = {};
  const byCategoryMember = {};
  realOps.filter(o => o.type === 'Витрата').forEach(o => {
    const cat = o.category || 'Інше';
    const who = o.who || 'Інше';
    byCategory[cat] = (byCategory[cat] || 0) + (o.amountUah || o.amount || 0);
    if (!byCategoryMember[who]) byCategoryMember[who] = {};
    byCategoryMember[who][cat] = (byCategoryMember[who][cat] || 0) + (o.amountUah || o.amount || 0);
  });

  // По днях (загальне + по членах)
  const byDay = {};
  const byDayIncome = {};
  const byDayMember = {};
  const byDayIncomeMember = {};
  realOps.forEach(o => {
    const day = parseInt((o.date || '').split('-')[2] || '0', 10);
    if (!day) return;
    const who = o.who || 'Інше';
    if (o.type === 'Витрата') {
      byDay[day] = (byDay[day] || 0) + (o.amountUah || o.amount || 0);
      if (!byDayMember[who]) byDayMember[who] = {};
      byDayMember[who][day] = (byDayMember[who][day] || 0) + (o.amountUah || o.amount || 0);
    }
    if (o.type === 'Дохід') {
      byDayIncome[day] = (byDayIncome[day] || 0) + (o.amountUah || o.amount || 0);
      if (!byDayIncomeMember[who]) byDayIncomeMember[who] = {};
      byDayIncomeMember[who][day] = (byDayIncomeMember[who][day] || 0) + (o.amountUah || o.amount || 0);
    }
  });

  // Останні 8 + всі операції по картках (для реального залишку кредиток)
  const [recentSnap, allCardSnap] = await Promise.all([
    familyRef().collection('operations').orderBy('date', 'desc').limit(8).get(),
    familyRef().collection('operations').get(),
  ]);
  const recent = recentSnap.docs.map(doc => ({ id: doc.id, row: doc.id, ...doc.data() }));

  const cardBalances = {};
  allCardSnap.docs.forEach(doc => {
    const o = doc.data();
    if (o.category === 'Переказ' || !o.card) return;
    const key = `${o.who || ''}:${o.card}`;
    if (!cardBalances[key]) cardBalances[key] = { income: 0, expense: 0 };
    const amt = o.amountUah || o.amount || 0;
    if (o.type === 'Дохід') cardBalances[key].income += amt;
    if (o.type === 'Витрата') cardBalances[key].expense += amt;
  });

  const month = `${kyivYear}-${String(kyivMonth).padStart(2, '0')}`;

  return {
    month, period,
    totalIncome: Math.round(totalIncome),
    totalExpense: Math.round(totalExpense),
    balance: Math.round(totalIncome - totalExpense),
    savingsRate: totalIncome > 0 ? (totalIncome - totalExpense) / totalIncome * 100 : 0,
    byMember, byCategory, byCategoryMember, byDay, byDayIncome, byDayMember, byDayIncomeMember, recent, cardBalances,
    fx: state.fx || {},
  };
}

// ── Операції ─────────────────────────────────────────────────
async function getOperations(params) {
  let q = familyRef().collection('operations').orderBy('date', 'desc');

  if (params?.month) {
    // Одна нерівність — не потребує composite index
    q = q.where('date', '>=', `${params.month}-01`);
  }

  q = q.limit(Number(params?.limit) || 500);

  const snapshot = await q.get();
  let ops = snapshot.docs.map(doc => ({ id: doc.id, row: doc.id, ...doc.data() }));

  // Точна фільтрація по місяцю на клієнті
  if (params?.month) {
    ops = ops.filter(o => o.date?.startsWith(params.month));
  }

  return { operations: ops };
}

// ── Налаштування ─────────────────────────────────────────────
async function getSettings() {
  const doc = await familyRef().get();
  if (!doc.exists) return {};
  return doc.data() || {};
}

// ── Резерв ───────────────────────────────────────────────────
async function getReserve() {
  const doc = await familyRef().collection('meta').doc('reserve').get();
  if (!doc.exists) return { totalUah: 0, balances: {}, transactions: [] };
  return doc.data();
}

// ── Цілі ─────────────────────────────────────────────────────
async function getGoals() {
  const snapshot = await familyRef().collection('goals').get();
  const goals = snapshot.docs.map(doc => ({ id: doc.id, row: doc.id, ...doc.data() }));
  return { goals };
}

// ── Тренд по місяцях (останні 6 місяців) ────────────────────
async function getTrend() {
  const kyivNow = new Date().toLocaleDateString('sv-SE', { timeZone: 'Europe/Kyiv' });
  const [year, month] = kyivNow.split('-').map(Number);

  // Build array of last 6 months
  const months = [];
  for (let i = 5; i >= 0; i--) {
    let m = month - i, y = year;
    while (m <= 0) { m += 12; y--; }
    months.push({ year: y, month: m, key: `${y}-${String(m).padStart(2,'0')}` });
  }
  const startDate = months[0].key + '-01';

  const snapshot = await familyRef().collection('operations')
    .where('date', '>=', startDate)
    .get();

  const byMonth = {};
  months.forEach(({ key }) => { byMonth[key] = { month: key, income: 0, expense: 0 }; });

  snapshot.docs.forEach(doc => {
    const o = doc.data();
    if (o.category === 'Переказ') return;
    const key = (o.date || '').substring(0, 7);
    if (!byMonth[key]) return;
    const amt = o.amountUah || o.amount || 0;
    if (o.type === 'Дохід')    byMonth[key].income  += amt;
    if (o.type === 'Витрата')  byMonth[key].expense += amt;
  });

  return { trend: Object.values(byMonth) };
}

// ── Перекази ─────────────────────────────────────────────────
async function getTransfers() {
  const snapshot = await familyRef().collection('operations')
    .where('category', '==', 'Переказ')
    .orderBy('date', 'desc')
    .limit(50)
    .get();
  return snapshot.docs.map(doc => ({ id: doc.id, ...doc.data() }));
}

// ── Курси валют (з Firestore або fallback) ───────────────────
async function getFxRates() {
  try {
    const doc = await db.collection('meta').doc('fx').get();
    if (doc.exists) {
      const data = doc.data();
      state.fx = data;
      return data;
    }
  } catch (e) {
    logError('getFxRates firestore', e.message);
  }
  // Fallback: НБУ API (публічний)
  try {
    const resp = await fetch('https://bank.gov.ua/NBUStatService/v1/statdirectory/exchange?json');
    const rates = await resp.json();
    const fx = {};
    rates.forEach(r => {
      if (r.cc === 'USD') fx.USD = { buy: r.rate, sale: r.rate, mid: r.rate };
      if (r.cc === 'EUR') fx.EUR = { buy: r.rate, sale: r.rate, mid: r.rate };
    });
    state.fx = fx;
    // Зберігаємо в Firestore для кешування
    try { await db.collection('meta').doc('fx').set({ ...fx, updatedAt: new Date().toISOString() }); } catch (e) {}
    return fx;
  } catch (e) {
    logError('getFxRates nbu', e.message);
    return {};
  }
}

// ═══════════════════════════════════════════════════════════════
// ЗАПИС
// ═══════════════════════════════════════════════════════════════

export async function apiPost(body) {
  if (!db) throw new Error('Firestore not initialized');

  switch (body.action) {
    case 'addOp':           return addOperation(body);
    case 'addOperation':    return addOperation(body);
    case 'updateOperation': return updateOperation(body);
    case 'deleteOperation': return deleteOperation(body);
    case 'addTransfer':     return addTransfer(body);
    case 'addReserve':      return addReserveOp(body);
    case 'updateSettings':  return updateSettings(body);
    case 'addGoal':         return addGoal(body);
    case 'updateGoal':      return updateGoal(body);
    case 'deleteGoal':      return deleteGoal(body);
    default:
      throw new Error('Unknown action: ' + body.action);
  }
}

// ── Додати операцію ──────────────────────────────────────────
async function addOperation(body) {
  const amount = Number(body.amount) || 0;
  const currency = body.currency || 'UAH';

  // Конвертуємо в UAH
  let amountUah = amount;
  if (currency !== 'UAH' && state.fx && state.fx[currency]) {
    const rate = state.fx[currency].mid || state.fx[currency].buy || state.fx[currency].sale || 1;
    amountUah = Math.round(amount * rate);
  }
  // Якщо фронт передав amountUah — використовуємо його
  if (body.amountUah && Number(body.amountUah) > 0) {
    amountUah = Number(body.amountUah);
  }

  const op = {
    date: body.date || todayKyiv(),
    type: body.type,
    category: body.category,
    amount,
    currency,
    amountUah,
    desc: body.desc || '',
    who: body.who || state.member || FAMILY_MEMBERS[0],
    card: body.card || '',
    createdAt: new Date().toISOString(),
  };

  const ref = await familyRef().collection('operations').add(op);
  log('operation added:', ref.id, currency, amount, '→', amountUah, 'UAH');
  return { ok: true, id: ref.id };
}

// ── Оновити операцію ─────────────────────────────────────────
async function updateOperation(body) {
  const id = body.row || body.id;
  if (!id) throw new Error('Operation id required');
  const updates = {};
  if (body.date !== undefined) updates.date = body.date;
  if (body.type !== undefined) updates.type = body.type;
  if (body.category !== undefined) updates.category = body.category;
  if (body.amount !== undefined) updates.amount = Number(body.amount);
  if (body.currency !== undefined) updates.currency = body.currency;
  if (body.amountUah !== undefined) updates.amountUah = Number(body.amountUah);
  if (body.desc !== undefined) updates.desc = body.desc;
  if (body.who !== undefined) updates.who = body.who;
  if (body.card !== undefined) updates.card = body.card;
  updates.updatedAt = new Date().toISOString();

  await familyRef().collection('operations').doc(id).update(updates);
  log('operation updated:', id);
  return { ok: true };
}

// ── Видалити операцію ────────────────────────────────────────
async function deleteOperation(body) {
  const id = body.row || body.id;
  if (!id) throw new Error('Operation id required');
  await familyRef().collection('operations').doc(id).delete();
  log('operation deleted:', id);
  return { ok: true };
}

// ── Переказ ──────────────────────────────────────────────────
async function addTransfer(body) {
  const batch = db.batch();
  const opsRef = familyRef().collection('operations');
  const now = todayKyiv();

  // Витрата з відправника
  const fromOp = {
    date: now,
    type: 'Витрата',
    category: 'Переказ',
    amount: Number(body.amount),
    currency: body.currency || 'UAH',
    amountUah: Number(body.amountUah) || Number(body.amount),
    desc: `→ ${body.toWho || ''}/${body.toCard || ''} ${body.desc || ''}`.trim(),
    who: body.fromWho,
    card: body.fromCard,
    createdAt: new Date().toISOString(),
  };
  batch.set(opsRef.doc(), fromOp);

  // Дохід у отримувача
  const toOp = {
    date: now,
    type: 'Дохід',
    category: 'Переказ',
    amount: Number(body.amount),
    currency: body.currency || 'UAH',
    amountUah: Number(body.amountUah) || Number(body.amount),
    desc: `← ${body.fromWho || ''}/${body.fromCard || ''} ${body.desc || ''}`.trim(),
    who: body.toWho || body.fromWho,
    card: body.toCard || '',
    createdAt: new Date().toISOString(),
  };
  batch.set(opsRef.doc(), toOp);

  await batch.commit();
  log('transfer added');
  return { ok: true };
}

// ── Резерв ───────────────────────────────────────────────────
async function addReserveOp(body) {
  const ref = familyRef().collection('meta').doc('reserve');
  const doc = await ref.get();
  const data = doc.exists ? doc.data() : { totalUah: 0, balances: {}, transactions: [] };

  const amt = Number(body.amount);
  const cur = body.currency || 'UAH';
  const sign = body.type === 'Поповнення' ? 1 : -1;

  if (!data.balances) data.balances = {};
  data.balances[cur] = (data.balances[cur] || 0) + amt * sign;

  // Конвертуємо в UAH для загальної суми
  let uahAmt = amt;
  if (cur !== 'UAH' && state.fx && state.fx[cur]) {
    uahAmt = amt * (state.fx[cur].mid || 1);
  }
  data.totalUah = (data.totalUah || 0) + uahAmt * sign;

  if (!data.transactions) data.transactions = [];
  data.transactions.unshift({
    date: todayKyiv(),
    type: body.type,
    amount: amt,
    currency: cur,
    comment: body.comment || '',
    who: state.member || FAMILY_MEMBERS[0],
  });

  // Обрізаємо до 100 транзакцій
  if (data.transactions.length > 100) data.transactions = data.transactions.slice(0, 100);

  await ref.set(data);
  return { ok: true };
}

// ── Зберегти налаштування ────────────────────────────────────
async function updateSettings(body) {
  const data = {};
  if (body.familyName !== undefined) data.familyName = body.familyName;
  if (body.expCats !== undefined) data.expCats = body.expCats;
  if (body.incCats !== undefined) data.incCats = body.incCats;
  if (body.cardsEvgen !== undefined) data.cardsEvgen = body.cardsEvgen;
  if (body.cardsMarina !== undefined) data.cardsMarina = body.cardsMarina;
  if (body.walletTypes !== undefined) data.walletTypes = body.walletTypes;
  if (body.profiles !== undefined) data.profiles = body.profiles;
  data.updatedAt = new Date().toISOString();

  await familyRef().set(data, { merge: true });
  log('settings saved to Firestore');
  return { ok: true };
}

// ── Цілі ─────────────────────────────────────────────────────
async function addGoal(body) {
  const goal = {
    name: body.name,
    target: Number(body.target),
    saved: Number(body.saved) || 0,
    deadline: body.deadline || '',
    icon: body.icon || 'ti-target',
    createdAt: new Date().toISOString(),
  };
  const ref = await familyRef().collection('goals').add(goal);
  return { ok: true, id: ref.id };
}

async function updateGoal(body) {
  const id = body.row || body.id;
  if (!id) throw new Error('Goal id required');
  const updates = {};
  if (body.name !== undefined) updates.name = body.name;
  if (body.target !== undefined) updates.target = Number(body.target);
  if (body.saved !== undefined) updates.saved = Number(body.saved);
  if (body.deadline !== undefined) updates.deadline = body.deadline;
  updates.updatedAt = new Date().toISOString();

  await familyRef().collection('goals').doc(id).update(updates);
  return { ok: true };
}

async function deleteGoal(body) {
  const id = body.row || body.id;
  if (!id) throw new Error('Goal id required');
  await familyRef().collection('goals').doc(id).delete();
  log('goal deleted:', id);
  return { ok: true };
}

// ═══════════════════════════════════════════════════════════════
// СИНХРОНІЗАЦІЯ НАЛАШТУВАНЬ
// ═══════════════════════════════════════════════════════════════

let syncInFlight = null;
export async function syncSettingsToSheet() {
  if (syncInFlight) return syncInFlight;
  if (!db) {
    syncState.pendingSettings = true;
    return;
  }

  syncInFlight = (async () => {
    try {
      await updateSettings({
        action: 'updateSettings',
        familyName: getFamilyName(),
        expCats: getExpCats(),
        incCats: getIncCats(),
        cardsEvgen: getCards('Євген'),
        cardsMarina: getCards('Марина'),
        walletTypes: getWalletTypes(),
        profiles: getProfiles(),
      });
      syncState.pendingSettings = false;
      log('settings synced to Firestore');
    } catch (e) {
      syncState.pendingSettings = true;
      logError('syncSettings', e.message);
      throw e;
    } finally {
      syncInFlight = null;
    }
  })();

  return syncInFlight;
}

// ── Ping ────────────────────────────────────────────────────
export async function pingBackend() {
  try {
    if (!db) return false;
    // Просто перевіряємо що Firestore доступний
    await db.collection('meta').doc('ping').set({ t: Date.now() });
    return true;
  } catch (e) {
    return false;
  }
}

// ── Завантаження налаштувань з Firestore → localStorage ──────
export async function loadSettingsFromFirestore() {
  try {
    const data = await getSettings();
    if (!data) return;

    const { setExpCats, setIncCats, setCards, setWalletTypes,
            setProfiles, setFamilyName } = await import('./storage.js');

    if (data.expCats && Array.isArray(data.expCats)) setExpCats(data.expCats);
    if (data.incCats && Array.isArray(data.incCats)) setIncCats(data.incCats);
    if (data.cardsEvgen && Array.isArray(data.cardsEvgen)) setCards(data.cardsEvgen, 'Євген');
    if (data.cardsMarina && Array.isArray(data.cardsMarina)) setCards(data.cardsMarina, 'Марина');
    if (data.walletTypes && Array.isArray(data.walletTypes)) setWalletTypes(data.walletTypes);
    if (data.profiles) setProfiles(data.profiles);
    if (data.familyName) setFamilyName(data.familyName);

    log('settings loaded from Firestore');
  } catch (e) {
    logError('loadSettingsFromFirestore', e.message);
  }
}

// ═══════════════════════════════════════════════════════════════
// КОРИСТУВАЧ І РОДИНА
// ═══════════════════════════════════════════════════════════════

// ── Читання документа користувача ───────────────────────────
export async function getUserDoc(uid) {
  if (!db) throw new Error('Firestore not initialized');
  const doc = await db.collection('users').doc(uid).get();
  return doc.exists ? doc.data() : null;
}

// ── Міграція існуючих користувачів ──────────────────────────
// Для користувачів які вже мали дані до переходу на multi-family
export async function migrateExistingUser(uid, { name, familyId, familyName }) {
  if (!db) throw new Error('Firestore not initialized');
  const now = new Date().toISOString();

  // Створюємо users/{uid} — якщо вже є, не перезаписуємо
  await db.collection('users').doc(uid).set({
    name,
    familyId,
    role: 'owner',
    migratedAt: now,
  }, { merge: true });

  // Оновлюємо families/{familyId} новими полями, не чіпаючи існуючі дані
  await db.collection('families').doc(familyId).set({
    name: familyName,
    ownerId: uid,
    members: [{ uid, name, joinedAt: now }],
    migratedAt: now,
  }, { merge: true });

  state.familyId = familyId;
  state.member = name;
  setFamilyMembers([name]);

  log('migrated existing user:', name, '→ family:', familyId);
  return { familyId, name };
}

// ── Генератор випадкового рядка ──────────────────────────────
function randomAlphanumeric(length) {
  const chars = 'abcdefghijklmnopqrstuvwxyz0123456789';
  let result = '';
  while (result.length < length) {
    result += Math.random().toString(36).slice(2);
  }
  return result.slice(0, length);
}

// ── Створити користувача і нову родину ───────────────────────
export async function createUserAndFamily(uid, { userName, userAvatar, familyName, familyAvatar }) {
  if (!db) throw new Error('Firestore not initialized');

  const familyId = randomAlphanumeric(8);
  const now = new Date().toISOString();

  // Документ користувача
  await db.collection('users').doc(uid).set({
    name: userName,
    avatar: userAvatar,
    familyId,
    role: 'owner',
    createdAt: now,
  });

  // Документ родини
  await db.collection('families').doc(familyId).set({
    name: familyName,
    avatar: familyAvatar,
    ownerId: uid,
    members: [{ uid, name: userName, avatar: userAvatar, joinedAt: now }],
    expCats: DEFAULT_EXP_CATS,
    incCats: DEFAULT_INC_CATS,
    walletTypes: DEFAULT_WALLET_TYPES,
    cards: { [uid]: DEFAULT_CARDS },
    createdAt: now,
  });

  state.familyId = familyId;
  state.member = userName;
  setFamilyMembers([userName]);

  log('family created:', familyId, 'owner:', userName);
  return { familyId, userName };
}

// ── Приєднатися до родини за кодом запрошення ────────────────
export async function joinFamilyWithCode(uid, { userName, userAvatar, code }) {
  if (!db) throw new Error('Firestore not initialized');

  const inviteRef = db.collection('invites').doc(code.toUpperCase());
  const inviteDoc = await inviteRef.get();

  if (!inviteDoc.exists) {
    throw new Error('Невірний або застарілий код запрошення');
  }

  const invite = inviteDoc.data();
  const now = new Date().toISOString();

  if (invite.used || (invite.expiresAt && invite.expiresAt < now)) {
    throw new Error('Невірний або застарілий код запрошення');
  }

  const { familyId } = invite;

  // Читаємо родину
  const familyDoc = await db.collection('families').doc(familyId).get();
  if (!familyDoc.exists) throw new Error('Родину не знайдено');

  const familyData = familyDoc.data();
  const members = Array.isArray(familyData.members) ? familyData.members : [];
  const newMember = { uid, name: userName, avatar: userAvatar, joinedAt: now };

  // Оновлюємо родину — додаємо нового члена
  await db.collection('families').doc(familyId).update({
    members: [...members, newMember],
  });

  // Документ користувача
  await db.collection('users').doc(uid).set({
    name: userName,
    avatar: userAvatar,
    familyId,
    role: 'member',
    createdAt: now,
  });

  // Позначаємо запрошення як використане
  await inviteRef.update({ used: true, usedBy: uid, usedAt: now });

  const memberNames = [...members.map(m => m.name), userName];
  state.familyId = familyId;
  state.member = userName;
  setFamilyMembers(memberNames);

  log('joined family:', familyId, 'as:', userName);
  return { familyId, userName };
}

// ── Генерувати код запрошення ────────────────────────────────
export async function generateInviteCode(familyId, createdByUid) {
  if (!db) throw new Error('Firestore not initialized');

  const code = randomAlphanumeric(6).toUpperCase();
  const now = new Date().toISOString();
  const expiresAt = new Date(Date.now() + 7 * 24 * 60 * 60 * 1000).toISOString();

  const inviteData = {
    familyId,
    createdBy: createdByUid,
    createdAt: now,
    expiresAt,
    used: false,
  };

  // Зберігаємо в колекції верхнього рівня для пошуку при join
  await db.collection('invites').doc(code).set(inviteData);

  // Зберігаємо також у підколекції родини для довідки
  await db.collection('families').doc(familyId).collection('invites').doc(code).set(inviteData);

  log('invite code generated:', code, 'for family:', familyId);
  return code;
}

// ── Завантажити дані родини ──────────────────────────────────
export async function loadFamilyData(familyId) {
  if (!db) throw new Error('Firestore not initialized');

  const doc = await db.collection('families').doc(familyId).get();
  if (!doc.exists) throw new Error('Родину не знайдено: ' + familyId);

  const data = doc.data();
  const memberNames = Array.isArray(data.members) ? data.members.map(m => m.name) : [];

  state.familyMembers = memberNames;
  setFamilyMembers(memberNames);

  log('family data loaded:', familyId, 'members:', memberNames);
  return data;
}
