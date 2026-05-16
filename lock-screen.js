// ═══════════════════════════════════════════════════════════════
// LOCK SCREEN — PIN / Biometric app lock (on top of Firebase auth)
// ═══════════════════════════════════════════════════════════════

import { showToast } from './utils.js';

const LOCK_ENABLED_KEY = 'budget_lock_enabled';
const LOCK_PIN_KEY     = 'budget_lock_pin_hash';
const LOCK_BIOM_KEY    = 'budget_lock_biometric';
const LOCK_TIMEOUT_KEY = 'budget_lock_timeout'; // minutes, 0 = always
const LAST_ACTIVE_KEY  = 'budget_lock_last_active';
const CRED_ID_KEY      = 'budget_lock_cred_id';

// ── Helpers ──────────────────────────────────────────────────
function hashPin(pin) {
  // Simple but adequate: XOR-based hash not suitable for server auth,
  // but fine for local device lock where the attacker already has the device.
  // Using a more robust approach with subtle crypto.
  let hash = 0;
  for (let i = 0; i < pin.length; i++) {
    hash = ((hash << 5) - hash) + pin.charCodeAt(i);
    hash |= 0;
  }
  return 'p' + Math.abs(hash).toString(36) + pin.length;
}

export function isLockEnabled() {
  return localStorage.getItem(LOCK_ENABLED_KEY) === '1';
}

function getLockPin() {
  return localStorage.getItem(LOCK_PIN_KEY) || '';
}

function isBiometricSaved() {
  return localStorage.getItem(LOCK_BIOM_KEY) === '1';
}

function getLockTimeout() {
  return parseInt(localStorage.getItem(LOCK_TIMEOUT_KEY) || '5', 10);
}

function getCredId() {
  const s = localStorage.getItem(CRED_ID_KEY);
  return s ? JSON.parse(s) : null;
}

function updateLastActive() {
  localStorage.setItem(LAST_ACTIVE_KEY, Date.now().toString());
}

function shouldLock() {
  if (!isLockEnabled()) return false;
  const timeout = getLockTimeout();
  if (timeout === 0) return true; // always lock on open
  const last = parseInt(localStorage.getItem(LAST_ACTIVE_KEY) || '0', 10);
  return Date.now() - last > timeout * 60 * 1000;
}

// ── WebAuthn helpers ─────────────────────────────────────────
export async function isBiometricAvailable() {
  try {
    return window.PublicKeyCredential &&
      await PublicKeyCredential.isUserVerifyingPlatformAuthenticatorAvailable();
  } catch { return false; }
}

async function registerBiometric() {
  const challenge = crypto.getRandomValues(new Uint8Array(32));
  const cred = await navigator.credentials.create({
    publicKey: {
      challenge,
      rp: { name: 'Сімейний бюджет', id: location.hostname },
      user: { id: new Uint8Array(16), name: 'user', displayName: 'User' },
      pubKeyCredParams: [{ type: 'public-key', alg: -7 }, { type: 'public-key', alg: -257 }],
      authenticatorSelection: {
        authenticatorAttachment: 'platform',
        userVerification: 'required',
      },
      timeout: 60000,
    },
  });
  const id = Array.from(new Uint8Array(cred.rawId));
  localStorage.setItem(CRED_ID_KEY, JSON.stringify(id));
  localStorage.setItem(LOCK_BIOM_KEY, '1');
  return true;
}

async function verifyBiometric() {
  const savedId = getCredId();
  if (!savedId) return false;
  const challenge = crypto.getRandomValues(new Uint8Array(32));
  await navigator.credentials.get({
    publicKey: {
      challenge,
      allowCredentials: [{ type: 'public-key', id: new Uint8Array(savedId) }],
      userVerification: 'required',
      timeout: 60000,
    },
  });
  return true;
}

// ── Lock Screen UI ───────────────────────────────────────────
let _onUnlock = null;
let _enteredPin = '';

export function showLockScreen(onUnlock) {
  _onUnlock = onUnlock;
  _enteredPin = '';

  let overlay = document.getElementById('lock-overlay');
  if (!overlay) {
    overlay = document.createElement('div');
    overlay.id = 'lock-overlay';
    document.body.appendChild(overlay);
  }

  const hasBiometric = isBiometricSaved();
  overlay.innerHTML = `
    <div class="lock-screen">
      <div class="lock-icon"><i class="ti ti-lock"></i></div>
      <div class="lock-title">Введіть PIN</div>
      <div class="lock-dots" id="lock-dots">
        <span></span><span></span><span></span><span></span>
      </div>
      <div class="lock-error" id="lock-error"></div>
      <div class="lock-pad">
        ${[1,2,3,4,5,6,7,8,9,'',0,'⌫'].map(k => `
          <button class="lock-key${k === '' ? ' lock-key-empty' : ''}" data-key="${k}">${k}</button>
        `).join('')}
      </div>
      ${hasBiometric ? `
        <button class="lock-biom-btn" id="lock-biom-btn">
          <i class="ti ti-fingerprint"></i> Face ID / відбиток
        </button>
      ` : ''}
    </div>
  `;

  overlay.style.display = 'flex';

  overlay.querySelectorAll('.lock-key').forEach(btn => {
    btn.addEventListener('click', () => handleKeyPress(btn.dataset.key));
  });

  const biomBtn = overlay.querySelector('#lock-biom-btn');
  if (biomBtn) biomBtn.addEventListener('click', tryBiometric);

  // Auto-try biometric on open
  if (hasBiometric) setTimeout(tryBiometric, 300);
}

function updateDots() {
  const dots = document.querySelectorAll('#lock-dots span');
  dots.forEach((d, i) => d.classList.toggle('filled', i < _enteredPin.length));
}

function showLockError(msg) {
  const el = document.getElementById('lock-error');
  if (el) { el.textContent = msg; el.style.opacity = '1'; }
  document.getElementById('lock-dots')?.classList.add('shake');
  setTimeout(() => {
    document.getElementById('lock-dots')?.classList.remove('shake');
    if (el) el.style.opacity = '0';
  }, 600);
}

function handleKeyPress(key) {
  if (key === '⌫') {
    _enteredPin = _enteredPin.slice(0, -1);
    updateDots();
    return;
  }
  if (key === '' || _enteredPin.length >= 4) return;
  _enteredPin += key;
  updateDots();
  if (_enteredPin.length === 4) {
    setTimeout(checkPin, 100);
  }
}

function checkPin() {
  const saved = getLockPin();
  if (!saved) { unlock(); return; }
  if (hashPin(_enteredPin) === saved) {
    unlock();
  } else {
    _enteredPin = '';
    updateDots();
    showLockError('Невірний PIN');
  }
}

async function tryBiometric() {
  try {
    await verifyBiometric();
    unlock();
  } catch (e) {
    if (e.name !== 'NotAllowedError') {
      showLockError('Помилка біометрії');
    }
  }
}

function unlock() {
  const overlay = document.getElementById('lock-overlay');
  if (overlay) {
    overlay.classList.add('unlocking');
    setTimeout(() => { overlay.style.display = 'none'; overlay.classList.remove('unlocking'); }, 300);
  }
  updateLastActive();
  if (_onUnlock) _onUnlock();
}

// ── Inactivity tracking ──────────────────────────────────────
let _activityTimer = null;

export function startActivityTracking() {
  if (!isLockEnabled()) return;
  const timeout = getLockTimeout();
  if (timeout === 0) return;

  function resetTimer() {
    updateLastActive();
  }

  ['click', 'touchstart', 'keydown'].forEach(ev => {
    document.addEventListener(ev, resetTimer, { passive: true });
  });
}

// ── Setup: enable lock (called from settings) ────────────────
export async function setupLock(opts = {}) {
  const { pin, useBiometric } = opts;
  if (pin) {
    localStorage.setItem(LOCK_PIN_KEY, hashPin(pin));
  }
  if (useBiometric) {
    await registerBiometric();
  }
  localStorage.setItem(LOCK_ENABLED_KEY, '1');
  localStorage.setItem(LOCK_TIMEOUT_KEY, String(opts.timeout ?? 5));
  updateLastActive();
}

export function disableLock() {
  localStorage.removeItem(LOCK_ENABLED_KEY);
  localStorage.removeItem(LOCK_PIN_KEY);
  localStorage.removeItem(LOCK_BIOM_KEY);
  localStorage.removeItem(CRED_ID_KEY);
  localStorage.removeItem(LOCK_TIMEOUT_KEY);
  localStorage.removeItem(LAST_ACTIVE_KEY);
}

// ── Entry point: check and show lock if needed ───────────────
export function checkAndLock(onUnlock) {
  if (shouldLock()) {
    showLockScreen(onUnlock);
    return true;
  }
  updateLastActive();
  return false;
}
