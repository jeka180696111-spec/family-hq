// ═══════════════════════════════════════════════════════════════
// ONBOARDING — New user setup: name, avatar, create/join family
// ═══════════════════════════════════════════════════════════════

import { state } from './config.js';
import { log, logError } from './utils.js';
import { createUserAndFamily, joinFamilyWithCode } from './api.js';

let _onComplete = null;

const USER_AVATARS = [
  '👤', '🧑', '👨', '👩', '🧔', '👱', '🧑‍💼', '👨‍💼',
  '👩‍💼', '🦸', '🧙', '🎅', '🤠', '🥷', '👮', '🧑‍🍳',
  '🧑‍🎨', '🧑‍🚀',
];

const FAMILY_AVATARS = [
  '🏠', '🏡', '🏘', '🏰', '🌟', '🌈', '🌊', '🌿',
  '🦁', '🐯', '🦊', '🐺', '🦅', '🌺', '🍀', '⭐',
];

// ── Локальний стан онбордингу ────────────────────────────────
const ob = {
  userName: '',
  userAvatar: USER_AVATARS[0],
  activeTab: 'create',   // 'create' | 'join'
};

// ── Публічна функція ─────────────────────────────────────────
export function showOnboarding(onComplete) {
  _onComplete = onComplete || null;
  const screen = document.getElementById('onboarding-screen');
  const login = document.getElementById('login-screen');
  const app = document.getElementById('app-root');
  if (login) login.style.display = 'none';
  if (app) app.style.display = 'none';
  if (screen) {
    screen.style.display = 'flex';
    renderStep1(screen);
  }
}

// ═══════════════════════════════════════════════════════════════
// КРОК 1 — Ім'я + аватар
// ═══════════════════════════════════════════════════════════════

function renderStep1(screen) {
  screen.innerHTML = `
    <div class="auth-card animate-fade-in" style="max-width:420px;text-align:left">

      <!-- Progress indicator -->
      <div class="ob-step-indicator">
        <div class="ob-step-dot active"></div>
        <div class="ob-step-dot"></div>
      </div>

      <!-- Логотип і заголовок -->
      <div style="text-align:center;margin-bottom:24px">
        <div class="auth-logo" style="margin:0 auto 14px">💰</div>
        <h1 style="font-size:22px;font-weight:800;color:var(--c-text);margin-bottom:4px;letter-spacing:-0.3px">Many Budget</h1>
        <p style="font-size:13px;color:var(--c-text-2);font-weight:500">Розумний фінансовий менеджер</p>
      </div>

      <!-- Ключові фічі -->
      <div class="ob-features">
        <div class="ob-feature-row">
          <div class="ob-feature-icon">🤖</div>
          <div class="ob-feature-text"><strong>AI-аналітика</strong> — фінансовий радник Фінн допоможе контролювати витрати</div>
        </div>
        <div class="ob-feature-row">
          <div class="ob-feature-icon">👨‍👩‍👧</div>
          <div class="ob-feature-text"><strong>Сімейний бюджет</strong> — спільний облік для всієї родини в реальному часі</div>
        </div>
        <div class="ob-feature-row">
          <div class="ob-feature-icon">📱</div>
          <div class="ob-feature-text"><strong>Telegram-бот</strong> — додавай витрати де завгодно за лічені секунди</div>
        </div>
      </div>

      <div style="margin-bottom:20px">
        <label style="display:block;font-size:13px;font-weight:600;color:var(--c-text-2);margin-bottom:6px">Твоє ім'я</label>
        <input
          id="ob-name"
          type="text"
          placeholder="Наприклад: Євген"
          maxlength="40"
          value="${escHtml(ob.userName)}"
          style="width:100%;box-sizing:border-box;padding:10px 14px;border:1.5px solid var(--c-border);border-radius:var(--radius);font-size:15px;font-family:inherit;background:var(--c-bg);color:var(--c-text);outline:none;transition:border-color 0.2s"
        />
        <div id="ob-name-err" style="display:none;color:var(--c-red,#d93025);font-size:12px;margin-top:4px">Ім'я має бути не менше 2 символів</div>
      </div>

      <div style="margin-bottom:28px">
        <label style="display:block;font-size:13px;font-weight:600;color:var(--c-text-2);margin-bottom:8px">Твій аватар</label>
        <div id="ob-user-avatars" style="display:flex;flex-wrap:wrap;gap:6px">
          ${USER_AVATARS.map(a => `
            <button
              class="ob-avatar-btn"
              data-avatar="${a}"
              style="width:40px;height:40px;border-radius:10px;border:2px solid ${a === ob.userAvatar ? 'var(--c-accent)' : 'transparent'};background:${a === ob.userAvatar ? 'var(--c-accent-soft)' : 'var(--c-border)'};font-size:22px;cursor:pointer;transition:border-color 0.15s,background 0.15s;line-height:1;display:flex;align-items:center;justify-content:center"
            >${a}</button>
          `).join('')}
        </div>
      </div>

      <button id="ob-step1-next" class="btn-primary" style="width:100%">Розпочати →</button>
    </div>
  `;

  // Фокус на поле
  const nameInput = screen.querySelector('#ob-name');
  setTimeout(() => nameInput && nameInput.focus(), 100);

  // Підсвічування поля при фокусі
  nameInput.addEventListener('focus', () => { nameInput.style.borderColor = 'var(--c-accent)'; });
  nameInput.addEventListener('blur', () => { nameInput.style.borderColor = 'var(--c-border)'; });

  // Вибір аватара
  screen.querySelectorAll('.ob-avatar-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      ob.userAvatar = btn.dataset.avatar;
      screen.querySelectorAll('.ob-avatar-btn').forEach(b => {
        const active = b.dataset.avatar === ob.userAvatar;
        b.style.borderColor = active ? 'var(--c-accent)' : 'transparent';
        b.style.background = active ? 'var(--c-accent-soft)' : 'var(--c-border)';
      });
    });
  });

  // Кнопка "Далі"
  screen.querySelector('#ob-step1-next').addEventListener('click', () => {
    const name = nameInput.value.trim();
    const errEl = screen.querySelector('#ob-name-err');
    if (name.length < 2) {
      errEl.style.display = 'block';
      nameInput.style.borderColor = 'var(--c-red,#d93025)';
      nameInput.focus();
      return;
    }
    errEl.style.display = 'none';
    ob.userName = name;
    renderStep2(screen);
  });
}

// ═══════════════════════════════════════════════════════════════
// КРОК 2 — Нова родина або запрошення
// ═══════════════════════════════════════════════════════════════

function renderStep2(screen) {
  const familyAvatar = FAMILY_AVATARS[0];
  let selectedFamilyAvatar = familyAvatar;

  screen.innerHTML = `
    <div class="auth-card animate-fade-in" style="max-width:420px;text-align:left">
      <!-- Progress indicator -->
      <div class="ob-step-indicator">
        <div class="ob-step-dot"></div>
        <div class="ob-step-dot active"></div>
      </div>

      <button id="ob-back" style="background:none;border:none;cursor:pointer;color:var(--c-text-2);font-size:13px;padding:0;margin-bottom:16px;display:flex;align-items:center;gap:4px">
        <i class="ti ti-arrow-left"></i> Назад
      </button>

      <div style="display:flex;align-items:center;gap:10px;margin-bottom:4px">
        <span style="font-size:28px">${ob.userAvatar}</span>
        <div>
          <h1 class="auth-title" style="margin-bottom:2px">${escHtml(ob.userName)}</h1>
          <p style="font-size:13px;color:var(--c-text-2);margin:0">Крок 2 з 2 — Твоя родина</p>
        </div>
      </div>
      <p class="auth-text" style="margin-top:12px">Створи нову родину або приєднайся до існуючої за кодом запрошення.</p>

      <!-- Вибір у вигляді карток -->
      <div class="ob-choice-cards">
        <button class="ob-choice-card${ob.activeTab === 'create' ? ' selected' : ''}" data-tab="create">
          <div class="ob-choice-card-icon">🏠</div>
          <div>
            <div class="ob-choice-card-title">Створити нову родину</div>
            <div class="ob-choice-card-desc">Ти станеш адміністратором і зможеш запросити інших</div>
          </div>
        </button>
        <button class="ob-choice-card${ob.activeTab === 'join' ? ' selected' : ''}" data-tab="join">
          <div class="ob-choice-card-icon">🔗</div>
          <div>
            <div class="ob-choice-card-title">Приєднатись до існуючої</div>
            <div class="ob-choice-card-desc">Потрібен 6-символьний invite-код від адміністратора родини</div>
          </div>
        </button>
      </div>

      <div id="ob-tab-content"></div>

      <div id="ob-error" style="display:none;color:var(--c-red,#d93025);font-size:13px;margin-top:12px;padding:8px 12px;background:rgba(217,48,37,0.08);border-radius:var(--radius)"></div>
    </div>
  `;

  renderTabContent(screen, selectedFamilyAvatar, (av) => { selectedFamilyAvatar = av; });

  // Переключення карток вибору
  screen.querySelectorAll('.ob-choice-card').forEach(card => {
    card.addEventListener('click', () => {
      ob.activeTab = card.dataset.tab;
      screen.querySelectorAll('.ob-choice-card').forEach(c => {
        c.classList.toggle('selected', c.dataset.tab === ob.activeTab);
      });
      screen.querySelector('#ob-error').style.display = 'none';
      renderTabContent(screen, selectedFamilyAvatar, (av) => { selectedFamilyAvatar = av; });
    });
  });

  screen.querySelector('#ob-back').addEventListener('click', () => renderStep1(screen));
}


function renderTabContent(screen, selectedFamilyAvatar, onFamilyAvatarChange) {
  const content = screen.querySelector('#ob-tab-content');
  content.classList.add('animate-fade-in');
  // Re-trigger animation on tab switch
  void content.offsetWidth;
  if (ob.activeTab === 'create') {
    renderCreateTab(screen, content, selectedFamilyAvatar, onFamilyAvatarChange);
  } else {
    renderJoinTab(screen, content);
  }
}

// ── Вкладка "Нова родина" ────────────────────────────────────
function renderCreateTab(screen, content, selectedFamilyAvatar, onFamilyAvatarChange) {
  content.innerHTML = `
    <div style="margin-bottom:20px">
      <label style="display:block;font-size:13px;font-weight:600;color:var(--c-text-2);margin-bottom:6px">Назва родини</label>
      <input
        id="ob-family-name"
        type="text"
        placeholder="Наприклад: Ковалі"
        maxlength="40"
        style="width:100%;box-sizing:border-box;padding:10px 14px;border:1.5px solid var(--c-border);border-radius:var(--radius);font-size:15px;font-family:inherit;background:var(--c-bg);color:var(--c-text);outline:none;transition:border-color 0.2s"
      />
      <div id="ob-family-name-err" style="display:none;color:var(--c-red,#d93025);font-size:12px;margin-top:4px">Введіть назву родини</div>
    </div>

    <div style="margin-bottom:28px">
      <label style="display:block;font-size:13px;font-weight:600;color:var(--c-text-2);margin-bottom:8px">Аватар родини</label>
      <div id="ob-family-avatars" style="display:flex;flex-wrap:wrap;gap:6px">
        ${FAMILY_AVATARS.map(a => `
          <button
            class="ob-family-avatar-btn"
            data-avatar="${a}"
            style="width:40px;height:40px;border-radius:10px;border:2px solid ${a === selectedFamilyAvatar ? 'var(--c-accent)' : 'transparent'};background:${a === selectedFamilyAvatar ? 'var(--c-accent-soft)' : 'var(--c-border)'};font-size:22px;cursor:pointer;transition:border-color 0.15s,background 0.15s;line-height:1;display:flex;align-items:center;justify-content:center"
          >${a}</button>
        `).join('')}
      </div>
    </div>

    <button id="ob-create-submit" class="btn-primary" style="width:100%">Створити родину</button>
  `;

  const nameInput = content.querySelector('#ob-family-name');
  nameInput.addEventListener('focus', () => { nameInput.style.borderColor = 'var(--c-accent)'; });
  nameInput.addEventListener('blur', () => { nameInput.style.borderColor = 'var(--c-border)'; });

  content.querySelectorAll('.ob-family-avatar-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      onFamilyAvatarChange(btn.dataset.avatar);
      content.querySelectorAll('.ob-family-avatar-btn').forEach(b => {
        const active = b.dataset.avatar === btn.dataset.avatar;
        b.style.borderColor = active ? 'var(--c-accent)' : 'transparent';
        b.style.background = active ? 'var(--c-accent-soft)' : 'var(--c-border)';
      });
    });
  });

  content.querySelector('#ob-create-submit').addEventListener('click', async () => {
    const familyName = nameInput.value.trim();
    const nameErrEl = content.querySelector('#ob-family-name-err');
    const errEl = screen.querySelector('#ob-error');

    if (familyName.length < 1) {
      nameErrEl.style.display = 'block';
      nameInput.style.borderColor = 'var(--c-red,#d93025)';
      nameInput.focus();
      return;
    }
    nameErrEl.style.display = 'none';
    errEl.style.display = 'none';

    const currentFamilyAvatar = content.querySelector('.ob-family-avatar-btn[style*="var(--c-accent-soft)"]')?.dataset.avatar || selectedFamilyAvatar;

    setLoading(screen, true);
    try {
      await createUserAndFamily(state.user.uid, {
        userName: ob.userName,
        userAvatar: ob.userAvatar,
        familyName,
        familyAvatar: currentFamilyAvatar,
      });
      log('Family created, completing onboarding');
      if (_onComplete) _onComplete();
    } catch (e) {
      logError('createUserAndFamily', e.message);
      errEl.textContent = 'Помилка: ' + e.message;
      errEl.style.display = 'block';
      setLoading(screen, false);
    }
  });
}

// ── Вкладка "Маю запрошення" ─────────────────────────────────
function renderJoinTab(screen, content) {
  content.innerHTML = `
    <div style="margin-bottom:20px">
      <label style="display:block;font-size:13px;font-weight:600;color:var(--c-text-2);margin-bottom:6px">Код запрошення</label>
      <input
        id="ob-invite-code"
        type="text"
        placeholder="XXXXXX"
        maxlength="6"
        autocomplete="off"
        style="width:100%;box-sizing:border-box;padding:10px 14px;border:1.5px solid var(--c-border);border-radius:var(--radius);font-size:20px;font-weight:600;letter-spacing:4px;text-transform:uppercase;text-align:center;font-family:inherit;background:var(--c-bg);color:var(--c-text);outline:none;transition:border-color 0.2s"
      />
      <div id="ob-code-err" style="display:none;color:var(--c-red,#d93025);font-size:12px;margin-top:4px">Введіть 6-символьний код</div>
      <p style="font-size:12px;color:var(--c-text-3);margin-top:8px">Попроси адміністратора родини надіслати тобі 6-символьний invite-код з розділу «Налаштування».</p>
    </div>

    <button id="ob-join-submit" class="btn-primary" style="width:100%">Приєднатись до родини</button>
  `;

  const codeInput = content.querySelector('#ob-invite-code');
  codeInput.addEventListener('input', () => {
    codeInput.value = codeInput.value.toUpperCase().replace(/[^A-Z0-9]/g, '');
  });
  codeInput.addEventListener('focus', () => { codeInput.style.borderColor = 'var(--c-accent)'; });
  codeInput.addEventListener('blur', () => { codeInput.style.borderColor = 'var(--c-border)'; });

  content.querySelector('#ob-join-submit').addEventListener('click', async () => {
    const code = codeInput.value.trim().toUpperCase();
    const codeErrEl = content.querySelector('#ob-code-err');
    const errEl = screen.querySelector('#ob-error');

    if (code.length !== 6) {
      codeErrEl.style.display = 'block';
      codeInput.style.borderColor = 'var(--c-red,#d93025)';
      codeInput.focus();
      return;
    }
    codeErrEl.style.display = 'none';
    errEl.style.display = 'none';

    setLoading(screen, true);
    try {
      await joinFamilyWithCode(state.user.uid, {
        userName: ob.userName,
        userAvatar: ob.userAvatar,
        code,
      });
      log('Joined family, completing onboarding');
      if (_onComplete) _onComplete();
    } catch (e) {
      logError('joinFamilyWithCode', e.message);
      errEl.textContent = 'Помилка: ' + e.message;
      errEl.style.display = 'block';
      setLoading(screen, false);
    }
  });
}

// ── Утиліти ─────────────────────────────────────────────────

function setLoading(screen, loading) {
  const btns = screen.querySelectorAll('button[id$="-submit"]');
  btns.forEach(btn => {
    btn.disabled = loading;
    btn.textContent = loading ? 'Зачекайте...' : btn.dataset.origText || btn.textContent;
    if (loading && !btn.dataset.origText) btn.dataset.origText = btn.textContent;
  });

  let spinner = screen.querySelector('#ob-spinner');
  if (loading && !spinner) {
    spinner = document.createElement('div');
    spinner.id = 'ob-spinner';
    spinner.style.cssText = 'position:absolute;inset:0;background:rgba(var(--c-bg-rgb,255,255,255),0.7);display:flex;align-items:center;justify-content:center;border-radius:inherit;z-index:10;font-size:24px';
    spinner.innerHTML = '<i class="ti ti-loader-2" style="animation:spin 0.8s linear infinite"></i>';

    const card = screen.querySelector('.auth-card');
    if (card) {
      card.style.position = 'relative';
      card.appendChild(spinner);

      // Ensure spin animation exists
      if (!document.getElementById('ob-spin-style')) {
        const style = document.createElement('style');
        style.id = 'ob-spin-style';
        style.textContent = '@keyframes spin{to{transform:rotate(360deg)}}';
        document.head.appendChild(style);
      }
    }
  } else if (!loading && spinner) {
    spinner.remove();
  }
}

function escHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}
