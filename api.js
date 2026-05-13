// ═══════════════════════════════════════════════════════════════
// API — спілкування з Google Apps Script
// ═══════════════════════════════════════════════════════════════

import { APP_CONFIG, state, syncState } from './config.js';
import { getScriptUrl, getExpCats, getIncCats, getCards, getProfiles, getWalletTypes, getFamilyName } from './storage.js';
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

// ── POST через GET payload (обхід CORS Apps Script) ─────────
export async function apiPost(body) {
  const url = getScriptUrl() || state.scriptUrl;
  if (!url) throw new Error('No script URL configured');

  const payload = { ...body, key: APP_CONFIG.SECRET_KEY };
  if (state.token) payload.token = state.token;

  const q = new URLSearchParams();
  q.set('payload', JSON.stringify(payload));
  q.set('key', APP_CONFIG.SECRET_KEY);

  const fullUrl = url + '?' + q.toString();
  try {
    const resp = await fetch(fullUrl, { method: 'GET', redirect: 'follow' });
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
export async function syncSettingsToSheet() {
  if (!state.scriptUrl || !state.token) {
    syncState.pendingSettings = true;
    return;
  }
  try {
    await apiPost({
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
    log('settings synced');
  } catch (e) {
    syncState.pendingSettings = true;
    logError('syncSettings', e.message);
  }
}

// ── Ping (для перевірки що бекенд живий) ────────────────────
export async function pingBackend() {
  try {
    const data = await apiGet('ping');
    return data && data.ok === true;
  } catch (e) {
    return false;
  }
}
