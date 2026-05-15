// ═══════════════════════════════════════════════════════════════
// AUTH — Firebase Google Authentication
// ═══════════════════════════════════════════════════════════════

import { state, EMAIL_TO_MEMBER, ALLOWED_EMAILS, FAMILY_MEMBERS } from './config.js';
import { log, logError } from './utils.js';

let firebaseAuth = null;
let googleProvider = null;

// ── Ініціалізація Firebase Auth ─────────────────────────────
export function initAuth(onSignIn) {
  firebaseAuth = firebase.auth();
  googleProvider = new firebase.auth.GoogleAuthProvider();

  // Слухаємо зміну стану авторизації
  firebaseAuth.onAuthStateChanged((user) => {
    if (user) {
      // Перевіряємо чи дозволений email
      if (ALLOWED_EMAILS.length > 0 && !ALLOWED_EMAILS.includes(user.email)) {
        log('Unauthorized email:', user.email);
        firebaseAuth.signOut();
        showLoginError('Цей акаунт не має доступу. Зверніться до адміністратора.');
        return;
      }

      state.user = {
        uid: user.uid,
        email: user.email,
        name: user.displayName || user.email.split('@')[0],
        avatar: user.photoURL || null,
      };
      state.member = EMAIL_TO_MEMBER[user.email] || FAMILY_MEMBERS[0];

      log('Firebase auth:', state.user.email, '→', state.member);

      // Ховаємо екран логіну, показуємо додаток
      if (onSignIn) onSignIn(state.user);
    } else {
      // Не залогінений — показуємо екран логіну
      state.user = null;
      state.member = null;
      showLoginScreen();
    }
  });
}

// ── Відновлення сесії ────────────────────────────────────────
export function restoreSession() {
  // Firebase зберігає сесію автоматично (IndexedDB)
  // onAuthStateChanged спрацює сам
  return firebaseAuth && firebaseAuth.currentUser !== null;
}

// ── Google Sign-In ──────────────────────────────────────────
export async function signInWithGoogle() {
  try {
    await firebaseAuth.signInWithPopup(googleProvider);
  } catch (e) {
    if (e.code === 'auth/popup-closed-by-user') return;
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
  location.reload();
}

// ── Хто я в сім'ї ───────────────────────────────────────────
export function whoAmI() {
  if (!state.user) return null;
  return state.member || EMAIL_TO_MEMBER[state.user.email] || FAMILY_MEMBERS[0];
}

// ── Показати екран логіну ───────────────────────────────────
function showLoginScreen() {
  const app = document.getElementById('app-root');
  const login = document.getElementById('login-screen');
  if (app) app.style.display = 'none';
  if (login) login.style.display = 'flex';
}

function showLoginError(msg) {
  const errEl = document.getElementById('login-error');
  if (errEl) {
    errEl.textContent = msg;
    errEl.style.display = 'block';
  }
}

// ── Ініціалізація Google Sign-In кнопки ─────────────────────
// Для сумісності зі старим initGoogleAuth
export function initGoogleAuth(onSignIn) {
  initAuth(onSignIn);
}
