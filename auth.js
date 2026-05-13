// ═══════════════════════════════════════════════════════════════
// AUTH — авторизація через Google
// ═══════════════════════════════════════════════════════════════

import { APP_CONFIG, state } from './config.js';
import { getUsername, setUsername, getAvatar, setAvatar, getMyMember } from './storage.js';
import { log, logError } from './utils.js';

// ── Завантаження збереженого юзера з localStorage ───────────
export function restoreSession() {
  const userJson = localStorage.getItem(APP_CONFIG.USER_KEY);
  const token = localStorage.getItem(APP_CONFIG.TOKEN_KEY);
  if (userJson && token) {
    try {
      state.user = JSON.parse(userJson);
      state.token = token;
      log('session restored:', state.user.email);
      return true;
    } catch (e) {
      logError('restoreSession', e);
    }
  }
  return false;
}

// ── Google Sign-In Initialization ───────────────────────────
export function initGoogleAuth(onSignIn) {
  if (typeof google === 'undefined' || !google.accounts) {
    log('Google API not loaded yet, retrying...');
    setTimeout(() => initGoogleAuth(onSignIn), 500);
    return;
  }
  google.accounts.id.initialize({
    client_id: APP_CONFIG.GOOGLE_CLIENT_ID,
    callback: (response) => handleCredentialResponse(response, onSignIn),
    auto_select: false,
    cancel_on_tap_outside: true,
  });
  // Рендер кнопки
  const btn = document.getElementById('google-signin-btn');
  if (btn) {
    google.accounts.id.renderButton(btn, {
      theme: 'outline',
      size: 'large',
      type: 'standard',
      text: 'signin_with',
      shape: 'pill',
      locale: 'uk',
    });
  }
}

function handleCredentialResponse(response, onSignIn) {
  const token = response.credential;
  // Decode JWT payload
  try {
    const parts = token.split('.');
    if (parts.length !== 3) throw new Error('Invalid JWT');
    const payload = JSON.parse(atob(parts[1].replace(/-/g, '+').replace(/_/g, '/')));
    state.user = {
      email: payload.email,
      name: payload.given_name || payload.name || payload.email.split('@')[0],
      avatar: payload.picture || null,
      sub: payload.sub,
    };
    state.token = token;
    localStorage.setItem(APP_CONFIG.USER_KEY, JSON.stringify(state.user));
    localStorage.setItem(APP_CONFIG.TOKEN_KEY, token);

    // Якщо в localStorage немає кастомного імені — використовуємо з Google
    if (!getUsername()) setUsername(state.user.name);
    if (!getAvatar() && state.user.avatar) setAvatar(state.user.avatar);

    log('signed in:', state.user.email);
    if (onSignIn) onSignIn(state.user);
  } catch (e) {
    logError('handleCredentialResponse', e);
  }
}

// ── Вихід ───────────────────────────────────────────────────
export function signOut() {
  if (typeof google !== 'undefined' && google.accounts && google.accounts.id) {
    google.accounts.id.disableAutoSelect();
  }
  state.user = null;
  state.token = null;
  localStorage.removeItem(APP_CONFIG.USER_KEY);
  localStorage.removeItem(APP_CONFIG.TOKEN_KEY);
  location.reload();
}

// ── Який це юзер у нашій сім'ї ──────────────────────────────
export function whoAmI() {
  if (!state.user) return null;
  return getMyMember(state.user.email);
}
