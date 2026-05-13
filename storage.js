// ═══════════════════════════════════════════════════════════════
// STORAGE — обгортки над localStorage
// ═══════════════════════════════════════════════════════════════

import { APP_CONFIG, DEFAULT_EXP_CATS, DEFAULT_INC_CATS, DEFAULT_CARDS, DEFAULT_WALLET_TYPES, FAMILY_MEMBERS } from './config.js';
import { logError } from './utils.js';

// ── Базові обгортки ─────────────────────────────────────────
function readJson(key, fallback) {
  try {
    const s = localStorage.getItem(key);
    if (!s) return fallback;
    const v = JSON.parse(s);
    return v;
  } catch (e) {
    logError('readJson', key, e);
    return fallback;
  }
}

function writeJson(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
    return true;
  } catch (e) {
    logError('writeJson', key, e);
    return false;
  }
}

// ── Категорії витрат ────────────────────────────────────────
export function getExpCats() {
  const v = readJson(APP_CONFIG.EXP_CATS_KEY, null);
  return Array.isArray(v) && v.length ? v : DEFAULT_EXP_CATS;
}
export function setExpCats(cats) {
  writeJson(APP_CONFIG.EXP_CATS_KEY, cats);
}

// ── Категорії доходів ───────────────────────────────────────
export function getIncCats() {
  const v = readJson(APP_CONFIG.INC_CATS_KEY, null);
  return Array.isArray(v) && v.length ? v : DEFAULT_INC_CATS;
}
export function setIncCats(cats) {
  writeJson(APP_CONFIG.INC_CATS_KEY, cats);
}

// ── Картки/кошельки по членах сім'ї ─────────────────────────
export function getCards(member) {
  if (!member) {
    // Всі картки разом
    const all = [];
    FAMILY_MEMBERS.forEach(m => {
      const cards = getCards(m);
      cards.forEach(c => all.push({ ...c, owner: m }));
    });
    return all;
  }
  const key = APP_CONFIG.CARDS_KEY + '_' + member;
  const v = readJson(key, null);
  return Array.isArray(v) && v.length ? v : DEFAULT_CARDS;
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
  // Дефолт
  const def = {};
  FAMILY_MEMBERS.forEach(m => {
    def[m] = { name: m, avatar: null };
  });
  return def;
}

export function setProfiles(profiles) {
  writeJson(APP_CONFIG.PROFILES_KEY, profiles);
}

// ── Типи рахунків (юзер керує) ──────────────────────────────
export function getWalletTypes() {
  const v = readJson(APP_CONFIG.WALLET_TYPES_KEY, null);
  return Array.isArray(v) && v.length ? v : DEFAULT_WALLET_TYPES;
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

// ── Визначення "мого" члена сім'ї ───────────────────────────
// За email — для типового сценарію 2 людини
export function getMyMember(userEmail) {
  if (!userEmail) return FAMILY_MEMBERS[0];
  const email = userEmail.toLowerCase();
  // Простіша логіка: якщо email явно вказує — Євген, інакше Марина
  if (email.includes('jeka') || email.includes('evgen') || email.includes('eugene') || email.includes('zhenya')) {
    return 'Євген';
  }
  if (email.includes('marina') || email.includes('maryna')) {
    return 'Марина';
  }
  // Fallback на збережене
  const saved = localStorage.getItem('budget_my_member');
  if (saved && FAMILY_MEMBERS.includes(saved)) return saved;
  return FAMILY_MEMBERS[0];
}

export function setMyMember(member) {
  localStorage.setItem('budget_my_member', member);
}

// ── Script URL ──────────────────────────────────────────────
export function getScriptUrl() {
  return APP_CONFIG.SCRIPT_URL || localStorage.getItem(APP_CONFIG.SCRIPT_URL_KEY) || '';
}

export function setScriptUrl(url) {
  localStorage.setItem(APP_CONFIG.SCRIPT_URL_KEY, url);
}
