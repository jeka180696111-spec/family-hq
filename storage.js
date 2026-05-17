// ═══════════════════════════════════════════════════════════════
// STORAGE — обгортки над localStorage + захист від перетирання
// ═══════════════════════════════════════════════════════════════

import { APP_CONFIG, DEFAULT_EXP_CATS, DEFAULT_INC_CATS, DEFAULT_CARDS, DEFAULT_WALLET_TYPES, FAMILY_MEMBERS } from './config.js';
import { logError } from './utils.js';

// ── Базові обгортки ─────────────────────────────────────────
function readJson(key, fallback) {
  try {
    const s = localStorage.getItem(key);
    if (!s) return fallback;
    return JSON.parse(s);
  } catch (e) {
    logError('readJson', key, e);
    return fallback;
  }
}

function writeJson(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
    markDirty(key);
    return true;
  } catch (e) {
    logError('writeJson', key, e);
    return false;
  }
}

// ── Dirty-tracking: захист від перезапису свіжих локальних даних ──
const DIRTY_KEY = 'budget_dirty_keys';
const DIRTY_TTL_MS = 60000;

function markDirty(key) {
  try {
    const dirty = JSON.parse(localStorage.getItem(DIRTY_KEY) || '{}');
    dirty[key] = Date.now();
    localStorage.setItem(DIRTY_KEY, JSON.stringify(dirty));
  } catch (e) {}
}

export function isDirty(key) {
  try {
    const dirty = JSON.parse(localStorage.getItem(DIRTY_KEY) || '{}');
    const t = dirty[key];
    if (!t) return false;
    if (Date.now() - t > DIRTY_TTL_MS) {
      delete dirty[key];
      localStorage.setItem(DIRTY_KEY, JSON.stringify(dirty));
      return false;
    }
    return true;
  } catch (e) { return false; }
}

export function clearDirty(key) {
  try {
    const dirty = JSON.parse(localStorage.getItem(DIRTY_KEY) || '{}');
    if (key) delete dirty[key];
    else Object.keys(dirty).forEach(k => delete dirty[k]);
    localStorage.setItem(DIRTY_KEY, JSON.stringify(dirty));
  } catch (e) {}
}

// ── Категорії витрат ────────────────────────────────────────
export function getExpCats() {
  const v = readJson(APP_CONFIG.EXP_CATS_KEY, null);
  return v === null ? DEFAULT_EXP_CATS : (Array.isArray(v) ? v : DEFAULT_EXP_CATS);
}
export function setExpCats(cats) {
  writeJson(APP_CONFIG.EXP_CATS_KEY, cats);
}

// ── Категорії доходів ───────────────────────────────────────
export function getIncCats() {
  const v = readJson(APP_CONFIG.INC_CATS_KEY, null);
  return v === null ? DEFAULT_INC_CATS : (Array.isArray(v) ? v : DEFAULT_INC_CATS);
}
export function setIncCats(cats) {
  writeJson(APP_CONFIG.INC_CATS_KEY, cats);
}

// ── Авто-визначення валюти за назвою кошелька ───────────────
function detectCurrency(name) {
  if (!name) return 'UAH';
  const n = String(name).toLowerCase();
  if (n.includes('долар') || n.includes('доллар') || n.includes('usd') || n.includes('$')) return 'USD';
  if (n.includes('євро') || n.includes('евро') || n.includes('eur') || n.includes('€')) return 'EUR';
  return 'UAH';
}

// ── Картки/кошельки по членах сім'ї ─────────────────────────
export function getCards(member) {
  if (!member) {
    const all = [];
    FAMILY_MEMBERS.forEach(m => {
      const cards = getCards(m);
      cards.forEach(c => all.push({ ...c, owner: m }));
    });
    return all;
  }
  const key = APP_CONFIG.CARDS_KEY + '_' + member;
  const v = readJson(key, null);
  const list = v === null ? DEFAULT_CARDS : (Array.isArray(v) ? v : DEFAULT_CARDS);
  // Авто-додаємо currency якщо відсутнє (для старих кошельків)
  return list.map(c => ({
    ...c,
    currency: c.currency || detectCurrency(c.id),
  }));
}

export function setCards(cards, member) {
  if (!member) {
    logError('setCards', 'member required');
    return;
  }
  const key = APP_CONFIG.CARDS_KEY + '_' + member;
  writeJson(key, cards);
}

// ── Профілі (ім'я, аватар) ──────────────────────────────────
export function getProfiles() {
  const v = readJson(APP_CONFIG.PROFILES_KEY, null);
  if (v && typeof v === 'object') return v;
  const def = {};
  FAMILY_MEMBERS.forEach(m => {
    def[m] = { name: m, avatar: null };
  });
  return def;
}

export function setProfiles(profiles) {
  writeJson(APP_CONFIG.PROFILES_KEY, profiles);
}

// ── Типи рахунків ───────────────────────────────────────────
export function getWalletTypes() {
  const v = readJson(APP_CONFIG.WALLET_TYPES_KEY, null);
  return v === null ? DEFAULT_WALLET_TYPES : (Array.isArray(v) && v.length ? v : DEFAULT_WALLET_TYPES);
}

export function setWalletTypes(types) {
  writeJson(APP_CONFIG.WALLET_TYPES_KEY, types);
}

export function getWalletTypeById(id) {
  if (!id) return null;
  return getWalletTypes().find(t => t.id === id) || null;
}

// ── Назва родини ────────────────────────────────────────────
export function getFamilyName() {
  return localStorage.getItem(APP_CONFIG.FAMILY_KEY) || 'Родина Коваль';
}
export function setFamilyName(name) {
  localStorage.setItem(APP_CONFIG.FAMILY_KEY, name);
  markDirty(APP_CONFIG.FAMILY_KEY);
}

// ── Тема ────────────────────────────────────────────────────
export function getTheme() {
  return localStorage.getItem(APP_CONFIG.THEME_KEY) || 'light';
}
export function setTheme(theme) {
  localStorage.setItem(APP_CONFIG.THEME_KEY, theme);
  document.documentElement.setAttribute('data-theme', theme);
}

// ── Ім'я користувача та аватар ──────────────────────────────
export function getUsername() {
  return localStorage.getItem(APP_CONFIG.USERNAME_KEY) || '';
}
export function setUsername(name) {
  localStorage.setItem(APP_CONFIG.USERNAME_KEY, name);
}

export function getAvatar() {
  return localStorage.getItem(APP_CONFIG.AVATAR_KEY) || '';
}
export function setAvatar(dataUrl) {
  localStorage.setItem(APP_CONFIG.AVATAR_KEY, dataUrl);
}

// ── Який це юзер у нашій сім'ї ──────────────────────────────
export function getMyMember(userEmail) {
  if (!userEmail) return FAMILY_MEMBERS[0];
  const email = userEmail.toLowerCase();
  if (email.includes('jeka') || email.includes('evgen') || email.includes('eugene') || email.includes('zhenya')) {
    return 'Євген';
  }
  if (email.includes('marina') || email.includes('maryna')) {
    return 'Марина';
  }
  const saved = localStorage.getItem('budget_my_member');
  if (saved && FAMILY_MEMBERS.includes(saved)) return saved;
  return FAMILY_MEMBERS[0];
}

export function setMyMember(member) {
  localStorage.setItem('budget_my_member', member);
}

// ── "Дивлюсь як" — перемикач у topbar ───────────────────────
// Це лише перегляд (filter в state), а не справжня зміна юзера
export function getViewAsMember() {
  const v = localStorage.getItem('budget_view_as');
  return v || null; // null = "усі" / за замовч. свій
}
export function setViewAsMember(member) {
  if (!member || member === 'all') {
    localStorage.removeItem('budget_view_as');
  } else {
    localStorage.setItem('budget_view_as', member);
  }
}

// ── Період для дашборда: month | quarter | year ─────────────
export function getDashPeriod() {
  return localStorage.getItem('budget_dash_period') || 'month';
}
export function setDashPeriod(p) {
  if (!['month','quarter','year'].includes(p)) p = 'month';
  localStorage.setItem('budget_dash_period', p);
}

// ── Які кошельки показувати на дашборді ─────────────────────
// Зберігаємо масив ID кошельків у форматі "owner::cardId"
// Якщо null/[] — показуємо всі (поведінка за замовчуванням)
export function getVisibleWallets() {
  try {
    const s = localStorage.getItem('budget_visible_wallets');
    if (!s) return null;
    const v = JSON.parse(s);
    return Array.isArray(v) ? v : null;
  } catch (e) { return null; }
}

export function setVisibleWallets(arr) {
  if (!arr || !arr.length) {
    localStorage.removeItem('budget_visible_wallets');
  } else {
    localStorage.setItem('budget_visible_wallets', JSON.stringify(arr));
  }
}

// ── Script URL ──────────────────────────────────────────────
export function getScriptUrl() {
  return APP_CONFIG.SCRIPT_URL || localStorage.getItem(APP_CONFIG.SCRIPT_URL_KEY) || '';
}

export function setScriptUrl(url) {
  localStorage.setItem(APP_CONFIG.SCRIPT_URL_KEY, url);
}

export function getCategoryLimits() {
  return readJson('budget_cat_limits', {});
}
export function setCategoryLimits(limits) {
  writeJson('budget_cat_limits', limits);
}

export function getSpendingPlan() {
  return readJson('budget_spending_plan', {});
}
export function setSpendingPlan(plan) {
  writeJson('budget_spending_plan', plan);
}

export function getDefaultWallet() {
  return readJson('budget_default_wallet', { member: null, cardId: null });
}
export function setDefaultWallet(member, cardId) {
  writeJson('budget_default_wallet', { member, cardId });
}

export function getTelegramPrefs() {
  return readJson('budget_tg_prefs', {
    paymentReminders: true,
    limitAlerts: true,
    dailySummary: true,
    summaryHour: 19,
  });
}
export function setTelegramPrefs(prefs) {
  writeJson('budget_tg_prefs', prefs);
}

export function getEarnedAchievements() {
  return readJson('budget_achievements_earned', {});
}
export function setEarnedAchievements(obj) {
  writeJson('budget_achievements_earned', obj);
}
export function getPalette() {
  return localStorage.getItem('budget_palette') || 'default';
}
export function setPalette(palette) {
  localStorage.setItem('budget_palette', palette);
}
