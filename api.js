// ═══════════════════════════════════════════════════════════════
// API — спілкування з Google Apps Script
// ═══════════════════════════════════════════════════════════════

import { APP_CONFIG, state, syncState } from './config.js';
import {
  getScriptUrl, getExpCats, getIncCats, getCards, getProfiles,
  getWalletTypes, getFamilyName, clearDirty,
} from './storage.js';
import { log, logError } from './utils.js';

// ── GET-запит ───────────────────────────────────────────────
export async function apiGet(action, params) {
  const url = getScriptUrl() || state.scriptUrl;
  if (!url) throw new Error('No script URL configured');

  const q = new URLSearchParams();
  q.set('action', action);
  q.set('key', APP_CONFIG.SECRET_KEY);
  if (state.token) q.set('token', state.token);
  if (params) {
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null) q.set(k, v);
    });
  }

  const fullUrl = url + '?' + q.toString();
  try {
    const resp = await fetch(fullUrl, { method: 'GET', redirect: 'follow' });
    const text = await resp.text();
    let data;
    try { data = JSON.parse(text); }
    catch (e) { throw new Error('Invalid JSON response: ' + text.substring(0, 200)); }
    if (data.error) throw new Error(data.error);
    return data;
  } catch (e) {
    logError('apiGet', action, e.message);
    throw e;
  }
}

// ── POST: справжній POST з text/plain (БЕЗ CORS preflight) ──
export async function apiPost(body) {
  const url = getScriptUrl() || state.scriptUrl;
  if (!url) throw new Error('No script URL configured');

  const payload = { ...body, key: APP_CONFIG.SECRET_KEY };
  if (state.token) payload.token = state.token;

  try {
    // ВАЖЛИВО: Content-Type 'text/plain' — НЕ викликає CORS preflight!
    // Apps Script читає e.postData.contents — JSON парситься на бекенді
    const resp = await fetch(url, {
      method: 'POST',
      mode: 'cors',
      redirect: 'follow',
      headers: { 'Content-Type': 'text/plain;charset=utf-8' },
      body: JSON.stringify(payload),
    });
    const text = await resp.text();
    let data;
    try { data = JSON.parse(text); }
    catch (e) { throw new Error('Invalid JSON: ' + text.substring(0, 200)); }
    if (data.error) throw new Error(data.error);
    return data;
  } catch (e) {
    logError('apiPost', body.action, e.message);
    throw e;
  }
}

// ── Сінк налаштувань на сервер ──────────────────────────────
let syncInFlight = null;
export async function syncSettingsToSheet() {
  // Запобігаємо паралельним sync (debounce)
  if (syncInFlight) return syncInFlight;

  if (!getScriptUrl() && !state.scriptUrl) {
    syncState.pendingSettings = true;
    return;
  }
  if (!state.token) {
    syncState.pendingSettings = true;
    return;
  }

  syncInFlight = (async () => {
    try {
      const payload = {
        action: 'updateSettings',
        familyName: getFamilyName(),
        expCats: getExpCats(),
        incCats: getIncCats(),
        cardsEvgen: getCards('Євген'),
        cardsMarina: getCards('Марина'),
        walletTypes: getWalletTypes(),
        profiles: getProfiles(),
      };
      await apiPost(payload);

      // При успіху — очищуємо ВСІ dirty-флаги пов'язані з налаштуваннями
      clearDirty(APP_CONFIG.FAMILY_KEY);
      clearDirty(APP_CONFIG.EXP_CATS_KEY);
      clearDirty(APP_CONFIG.INC_CATS_KEY);
      clearDirty(APP_CONFIG.CARDS_KEY + '_Євген');
      clearDirty(APP_CONFIG.CARDS_KEY + '_Марина');
      clearDirty(APP_CONFIG.WALLET_TYPES_KEY);
      clearDirty(APP_CONFIG.PROFILES_KEY);

      syncState.pendingSettings = false;
      log('settings synced');
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
    const data = await apiGet('ping');
    return data && data.ok === true;
  } catch (e) {
    return false;
  }
}
