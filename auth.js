// ═══════════════════════════════════════════════════════════════
// AUTH — Firebase Google Authentication (multi-tenant)
// ═══════════════════════════════════════════════════════════════

import { state } from './config.js';
import { log, logError } from './utils.js';
import { getUserDoc, migrateExistingUser } from './api.js';
import { showOnboarding } from './onboarding.js';

// Відомі існуючі користувачі — автоматично мігруються без онбордингу
const MIGRATION_MAP = {
  'jeka180696111@gmail.com': { name: 'Євген', familyId: 'koval', familyName: 'Кіосе' },
};

let firebaseAuth = null;
let googleProvider = null;
let _onSignIn = null;

// ── Ініціалізація Firebase Auth ─────────────────────────────
export function initAuth(onSignIn) {
  _onSignIn = onSignIn;
  firebaseAuth = firebase.auth();
  googleProvider = new firebase.auth.GoogleAuthProvider();

  // Обробляємо результат redirect-логіну (якщо popup був заблокований)
  firebaseAuth.getRedirectResult().catch(e => {
    if (e.code && e.code !== 'auth/no-auth-event') {
      logError('getRedirectResult', e.message);
      showLoginError('Помилка входу: ' + e.message);
    }
  });

  firebaseAuth.onAuthStateChanged(async (user) => {
    if (user) {
      state.user = {
        uid: user.uid,
        email: user.email,
        name: user.displayName || user.email.split('@')[0],
        avatar: user.photoURL || null,
      };

      try {
        const userDoc = await getUserDoc(user.uid);

        if (userDoc) {
          state.member = userDoc.name;
          state.familyId = userDoc.familyId;
          log('Auth: existing user', state.member, 'family', state.familyId);
          if (_onSignIn) _onSignIn(state.user);
        } else if (MIGRATION_MAP[user.email]) {
          // Автоматична міграція існуючого користувача
          log('Auth: migrating existing user', user.email);
          const m = MIGRATION_MAP[user.email];
          await migrateExistingUser(user.uid, m);
          if (_onSignIn) _onSignIn(state.user);
        } else {
          log('Auth: new user, showing onboarding');
          showOnboarding(completeOnboarding);
        }
      } catch (e) {
        logError('initAuth: getUserDoc failed', e.message);
        showLoginError('Помилка завантаження профілю: ' + e.message);
      }
    } else {
      state.user = null;
      state.member = null;
      state.familyId = null;
      showLoginScreen();
    }
  });
}

// ── Завершення онбордингу ────────────────────────────────────
// Викликається з onboarding.js після успішного створення/приєднання родини
export function completeOnboarding() {
  log('Onboarding complete, booting app for', state.member);
  if (_onSignIn) _onSignIn(state.user);
}

// ── Відновлення сесії ────────────────────────────────────────
export function restoreSession() {
  return firebaseAuth && firebaseAuth.currentUser !== null;
}

// ── Google Sign-In ──────────────────────────────────────────
export async function signInWithGoogle() {
  try {
    await firebaseAuth.signInWithPopup(googleProvider);
  } catch (e) {
    if (e.code === 'auth/popup-closed-by-user' || e.code === 'auth/cancelled-popup-request') return;
    if (e.code === 'auth/popup-blocked') {
      // Popup заблоковано браузером — переходимо на redirect-flow
      firebaseAuth.signInWithRedirect(googleProvider);
      return;
    }
    logError('signInWithGoogle', e.message);
    showLoginError('Помилка входу: ' + e.message);
  }
}

// ── Вихід ───────────────────────────────────────────────────
export function signOut() {
  if (firebaseAuth) {
    firebaseAuth.signOut();
  }
  state.user = null;
  state.member = null;
  state.familyId = null;
  location.reload();
}

// ── Хто я в сім'ї ───────────────────────────────────────────
export function whoAmI() {
  return state.member || null;
}

// ── Показати екран логіну ───────────────────────────────────
function showLoginScreen() {
  const app = document.getElementById('app-root');
  const login = document.getElementById('login-screen');
  const onboarding = document.getElementById('onboarding-screen');
  if (app) app.style.display = 'none';
  if (onboarding) onboarding.style.display = 'none';
  if (login) login.style.display = 'flex';
}

function showLoginError(msg) {
  const errEl = document.getElementById('login-error');
  if (errEl) {
    errEl.textContent = msg;
    errEl.style.display = 'block';
  }
}

// ── Сумісність зі старим initGoogleAuth ─────────────────────
export function initGoogleAuth(onSignIn) {
  initAuth(onSignIn);
}
