// ═══════════════════════════════════════════════════════════════
// SETTINGS UI — сторінка налаштувань (iOS-style sub-pages)
// ═══════════════════════════════════════════════════════════════

import { FAMILY_MEMBERS, state, getFamilyMembers, setFamilyMembers } from './config.js';
import {
  getExpCats, setExpCats, getIncCats, setIncCats,
  getWalletTypes, setWalletTypes,
  getFamilyName, setFamilyName,
  getProfiles, setProfiles,
  getCards,
  getTheme,
  getCategoryLimits, setCategoryLimits,
  getSpendingPlan, setSpendingPlan,
  getDefaultWallet, setDefaultWallet,
  getTelegramPrefs, setTelegramPrefs,
  getPalette, setPalette,
  getAvatar, setAvatar,
  getFamilyAvatar, setFamilyAvatar,
  getDashWidgets, setDashWidgets,
} from './storage.js';
import { syncSettingsToSheet, pingBackend, generateInviteCode } from './api.js';
import { applyTheme, toggleTheme, applyPalette } from './theme.js';
import { esc, showToast, uid } from './utils.js';
import { openIconPicker } from './icon-picker.js';
import { openBottomSheet, closeModal, confirmModal, promptModal } from './modals.js';
import { signOut } from './auth.js';
import { isLockEnabled, isBiometricAvailable, setupLock, disableLock } from './lock-screen.js';

// ── Sub-page state ───────────────────────────────────────────
let settingsSubPage = null;

// ── Helper functions ─────────────────────────────────────────
function getCatMeta(key) {
  const cat = getExpCats().find(c => (c.id || c) === key);
  return cat || { icon: 'ti-dots', bg: '#f0f0f0', color: '#888' };
}

function renderBudgetGrid(type) {
  const data = type === 'plan' ? getSpendingPlan() : getCategoryLimits();
  const entries = Object.entries(data);
  const noun = type === 'plan' ? 'план' : 'ліміт';

  const cards = entries.map(([key, amount]) => {
    const m = getCatMeta(key);
    return `
      <div class="limits-card">
        <button class="limits-card-del" data-budget-del="${type}" data-key="${esc(key)}" title="Видалити">
          <i class="ti ti-x"></i>
        </button>
        <div class="limits-card-icon" style="background:${m.bg}">
          <i class="ti ${m.icon}" style="color:${m.color}"></i>
        </div>
        <div class="limits-card-name">${esc(key)}</div>
        <button class="limits-card-amount-btn" data-budget-edit="${type}" data-key="${esc(key)}" data-amount="${amount}">
          ${Math.round(amount).toLocaleString('uk-UA')} ₴
        </button>
      </div>
    `;
  }).join('');

  return `
    <div class="limits-grid" id="${type}-grid">
      ${cards || `<div class="settings-hint" style="grid-column:1/-1">Не встановлено. Натисни «Додати ${noun}».</div>`}
    </div>
    <button class="settings-add-btn" id="add-${type}-btn">
      <i class="ti ti-plus"></i> Додати ${noun}
    </button>
  `;
}

function openPinSetupSheet(onDone, changeOnly = false) {
  let step = 'enter'; // 'enter' | 'confirm'
  let pin1 = '';

  function buildContent() {
    return `
      <div style="display:flex;flex-direction:column;align-items:center;gap:14px;padding:16px 0 8px">
        <div class="lock-icon" style="width:48px;height:48px;font-size:22px;background:var(--c-accent-soft);color:var(--c-accent);border-radius:50%;display:flex;align-items:center;justify-content:center">
          <i class="ti ti-keyframe"></i>
        </div>
        <div style="font-size:16px;font-weight:600;color:var(--c-text)" id="pin-setup-title">
          ${step === 'enter' ? 'Введіть новий PIN' : 'Повторіть PIN'}
        </div>
        <div class="lock-dots" id="pin-setup-dots">
          <span></span><span></span><span></span><span></span>
        </div>
        <div class="lock-error" id="pin-setup-error" style="height:14px;opacity:0"></div>
        <div class="lock-pad" style="width:260px">
          ${[1,2,3,4,5,6,7,8,9,'',0,'⌫'].map(k => `
            <button class="lock-key${k===''?' lock-key-empty':''}" data-pin-key="${k}" style="height:52px;font-size:20px">${k}</button>
          `).join('')}
        </div>
      </div>
    `;
  }

  let modalId;
  modalId = openBottomSheet({
    title: changeOnly ? 'Змінити PIN' : 'Встановити PIN',
    content: buildContent(),
    onOpen(modal) {
      let cur = '';

      function updateDots() {
        modal.querySelectorAll('#pin-setup-dots span').forEach((d, i) => {
          d.classList.toggle('filled', i < cur.length);
        });
      }

      function showErr(msg) {
        const e = modal.querySelector('#pin-setup-error');
        if (e) { e.textContent = msg; e.style.opacity = '1'; }
        const dots = modal.querySelector('#pin-setup-dots');
        if (dots) { dots.classList.add('shake'); setTimeout(() => dots.classList.remove('shake'), 400); }
        setTimeout(() => { if (e) e.style.opacity = '0'; }, 1200);
        cur = '';
        updateDots();
      }

      modal.querySelectorAll('[data-pin-key]').forEach(btn => {
        btn.addEventListener('click', () => {
          const k = btn.dataset.pinKey;
          if (k === '⌫') { cur = cur.slice(0, -1); updateDots(); return; }
          if (k === '' || cur.length >= 4) return;
          cur += k;
          updateDots();
          if (cur.length === 4) {
            setTimeout(async () => {
              if (step === 'enter') {
                pin1 = cur; cur = ''; step = 'confirm';
                modal.querySelector('#pin-setup-title').textContent = 'Повторіть PIN';
                updateDots();
              } else {
                if (cur !== pin1) { showErr('PIN не збігається'); step = 'enter'; pin1 = ''; return; }
                try {
                  await setupLock({ pin: cur, timeout: 5 });
                  closeModal(modalId);
                  showToast('✅ PIN встановлено');
                  if (onDone) onDone();
                } catch (e) { showErr('Помилка: ' + e.message); }
              }
            }, 80);
          }
        });
      });
    },
  });
}

function openAddBudgetItem(type) {
  const data = type === 'plan' ? getSpendingPlan() : getCategoryLimits();
  const cats = getExpCats();
  const noun = type === 'plan' ? 'план' : 'ліміт';

  const catsHtml = cats.map(c => {
    const key = c.id || c;
    const already = !!data[key];
    return `
      <button class="limits-card add-budget-pick ${already ? 'already' : ''}" data-pick="${esc(key)}" ${already ? 'disabled' : ''}>
        <div class="limits-card-icon" style="background:${c.bg}">
          <i class="ti ${c.icon}" style="color:${c.color}"></i>
        </div>
        <div class="limits-card-name">${esc(key)}</div>
        ${already ? '<div class="limits-card-name" style="font-size:9px;color:var(--c-text-3)">вже є</div>' : ''}
      </button>
    `;
  }).join('') + `
    <button class="limits-card add-budget-pick" data-pick="__custom__">
      <div class="limits-card-icon" style="background:#f0f0f0"><i class="ti ti-pencil" style="color:#888"></i></div>
      <div class="limits-card-name">Своя</div>
    </button>
  `;

  let selectedKey = null;
  let modalId;

  modalId = openBottomSheet({
    title: `Додати ${noun}`,
    content: `
      <div style="margin-bottom:12px;font-size:13px;color:var(--c-text-2)">Виберіть категорію та вкажіть суму</div>
      <div class="limits-grid">${catsHtml}</div>
      <div id="add-budget-amount-row" style="display:none;margin-top:14px;align-items:center;gap:10px">
        <div id="add-budget-selected-name" style="font-weight:700;font-size:14px;flex:1"></div>
        <input id="add-budget-amount" class="settings-row-input" type="number" min="0" step="100" placeholder="Сума (₴)" style="max-width:130px">
      </div>
    `,
    footer: `
      <button class="btn-ghost flex-1" data-modal-close>Скасувати</button>
      <button class="btn-primary flex-1" id="confirm-add-budget" disabled>Додати ${noun}</button>
    `,
    onOpen: (modal) => {
      modal.querySelectorAll('.add-budget-pick:not([disabled])').forEach(btn => {
        btn.addEventListener('click', async () => {
          if (btn.dataset.pick === '__custom__') {
            const name = await promptModal('Назва категорії', '', { placeholder: 'Наприклад: Кафе', okText: 'Далі' });
            if (!name) return;
            selectedKey = name.trim();
          } else {
            selectedKey = btn.dataset.pick;
          }
          modal.querySelectorAll('.add-budget-pick').forEach(b => b.classList.remove('selected'));
          btn.classList.add('selected');
          modal.querySelector('#add-budget-selected-name').textContent = selectedKey;
          modal.querySelector('#add-budget-amount-row').style.display = 'flex';
          modal.querySelector('#add-budget-amount').focus();
          modal.querySelector('#confirm-add-budget').disabled = false;
        });
      });

      modal.querySelector('#confirm-add-budget').addEventListener('click', () => {
        const amt = parseFloat(modal.querySelector('#add-budget-amount').value);
        if (!selectedKey || !(amt > 0)) { showToast('Вкажіть суму', 'error'); return; }
        const d = type === 'plan' ? getSpendingPlan() : getCategoryLimits();
        d[selectedKey] = amt;
        if (type === 'plan') setSpendingPlan(d); else setCategoryLimits(d);
        closeModal(modalId);
        renderSettingsPage();
        showToast('✅ Додано');
      });
    },
  });
}

function openEditBudgetItem(type, key, currentAmount) {
  const noun = type === 'plan' ? 'план' : 'ліміт';
  promptModal(`${noun === 'план' ? 'План' : 'Ліміт'} для «${key}» (₴)`, String(currentAmount), {
    placeholder: 'Сума ₴',
    okText: 'Зберегти',
  }).then(val => {
    if (val === null) return;
    const amt = parseFloat(val);
    if (!(amt > 0)) return;
    const d = type === 'plan' ? getSpendingPlan() : getCategoryLimits();
    d[key] = amt;
    if (type === 'plan') setSpendingPlan(d); else setCategoryLimits(d);
    renderSettingsPage();
    showToast('✅ Збережено');
  });
}

function renderDefaultWalletRows() {
  const dw = getDefaultWallet();
  const profiles = getProfiles();
  return FAMILY_MEMBERS.map(m => {
    const cards = getCards(m);
    const selected = dw.member === m ? dw.cardId : '';
    return `
      <div class="settings-row">
        <div class="settings-row-icon" style="background:var(--c-accent-soft);color:var(--c-accent)"><b>${(profiles[m]?.name || m)[0]}</b></div>
        <div class="settings-row-info"><div class="settings-row-name">${esc(profiles[m]?.name || m)}</div></div>
        <select class="settings-row-input dw-select" data-dw-member="${esc(m)}" style="max-width:160px">
          <option value="">— не обрано —</option>
          ${cards.map(c => `<option value="${esc(c.id)}" ${c.id === selected ? 'selected' : ''}>${esc(c.id)}${c.currency && c.currency !== 'UAH' ? ' ('+c.currency+')' : ''}</option>`).join('')}
        </select>
      </div>
    `;
  }).join('');
}

function renderTelegramPrefs() {
  const p = getTelegramPrefs();
  return `
    <div class="settings-row">
      <div class="settings-row-info"><div class="settings-row-name"><i class="ti ti-calendar-due"></i> Нагадування про платежі</div></div>
      <label class="settings-toggle"><input type="checkbox" id="tg-payments" ${p.paymentReminders ? 'checked' : ''}><span></span></label>
    </div>
    <div class="settings-row">
      <div class="settings-row-info"><div class="settings-row-name"><i class="ti ti-alert-triangle"></i> Попередження про ліміти</div></div>
      <label class="settings-toggle"><input type="checkbox" id="tg-limits" ${p.limitAlerts ? 'checked' : ''}><span></span></label>
    </div>
    <div class="settings-row">
      <div class="settings-row-info"><div class="settings-row-name"><i class="ti ti-chart-bar"></i> Щоденний підсумок</div></div>
      <label class="settings-toggle"><input type="checkbox" id="tg-daily" ${p.dailySummary ? 'checked' : ''}><span></span></label>
    </div>
    <div class="settings-row">
      <div class="settings-row-info"><div class="settings-row-name">Час підсумку</div></div>
      <select class="settings-row-input" id="tg-hour" style="max-width:120px">
        ${[8,9,10,12,18,19,20,21,22].map(h => `<option value="${h}" ${p.summaryHour === h ? 'selected' : ''}>${h}:00</option>`).join('')}
      </select>
    </div>
    <button class="btn-primary" style="width:100%;margin-top:8px" id="save-tg-prefs-btn">Зберегти налаштування</button>
  `;
}

function renderLockSection() {
  const enabled = isLockEnabled();
  return `
    <div class="settings-row">
      <div class="settings-row-icon"><i class="ti ti-lock"></i></div>
      <div class="settings-row-info">
        <div class="settings-row-name">Блокування додатку</div>
        <div class="settings-row-sub">${enabled ? 'Увімкнено (PIN / біометрія)' : 'Вимкнено'}</div>
      </div>
      <label class="settings-toggle">
        <input type="checkbox" id="lock-toggle" ${enabled ? 'checked' : ''}>
        <span></span>
      </label>
    </div>
    ${enabled ? `
    <div class="settings-row" id="lock-change-pin-row">
      <div class="settings-row-icon"><i class="ti ti-keyframe"></i></div>
      <div class="settings-row-info">
        <div class="settings-row-name">Змінити PIN</div>
        <div class="settings-row-sub">4-значний код</div>
      </div>
      <button class="btn-ghost-sm" id="lock-change-pin-btn">Змінити</button>
    </div>
    <div class="settings-row" id="lock-biom-row">
      <div class="settings-row-icon"><i class="ti ti-fingerprint"></i></div>
      <div class="settings-row-info">
        <div class="settings-row-name">Face ID / відбиток</div>
        <div class="settings-row-sub" id="lock-biom-status">Перевірка...</div>
      </div>
      <button class="btn-ghost-sm" id="lock-biom-btn">Налаштувати</button>
    </div>
    ` : ''}
  `;
}

// ── Main menu ─────────────────────────────────────────────────
function renderMainMenu() {
  const userAv = getAvatar() || state.user?.avatar || '';
  const avatarHtml = userAv && userAv.length > 2
    ? `<img src="${esc(userAv)}" style="width:46px;height:46px;border-radius:50%;object-fit:cover;border:2px solid rgba(255,255,255,0.4)">`
    : `<div style="width:46px;height:46px;border-radius:50%;background:rgba(255,255,255,0.25);color:#fff;font-size:20px;font-weight:700;display:flex;align-items:center;justify-content:center;border:2px solid rgba(255,255,255,0.4)">${(state.user?.name || state.member || '?')[0].toUpperCase()}</div>`;

  return `
    <div class="page-inner">
      <div class="page-head">
        <h1 class="page-title">Налаштування</h1>
      </div>

      <!-- Profile Card -->
      <button class="settings-profile-card" data-sub="profile-group">
        <div style="display:flex;align-items:center;gap:14px">
          ${avatarHtml}
          <div style="text-align:left">
            <div style="font-size:16px;font-weight:700;color:#fff">${esc(state.user?.name || state.member || 'Профіль')}</div>
            <div style="font-size:12px;color:rgba(255,255,255,0.72)">${esc(state.user?.email || 'Профіль · Вигляд · Родина · Безпека')}</div>
          </div>
        </div>
        <i class="ti ti-chevron-right" style="color:rgba(255,255,255,0.6);font-size:18px;flex-shrink:0"></i>
      </button>

      <!-- PRO Card -->
      <button class="settings-pro-card" data-sub="subscription">
        <div style="display:flex;align-items:center;gap:12px">
          <div style="width:42px;height:42px;border-radius:12px;background:rgba(255,255,255,0.18);display:flex;align-items:center;justify-content:center;font-size:22px">✨</div>
          <div style="text-align:left">
            <div style="font-size:15px;font-weight:800;color:#fff;letter-spacing:-0.01em">Money Budget Pro</div>
            <div style="font-size:12px;color:rgba(255,255,255,0.78)">AI · Родина · Telegram · Сканер</div>
          </div>
        </div>
        <div style="display:flex;align-items:center;gap:8px;flex-shrink:0">
          <span style="background:rgba(255,255,255,0.2);color:#fff;font-size:10px;font-weight:700;padding:3px 10px;border-radius:20px">FREE</span>
          <i class="ti ti-chevron-right" style="color:rgba(255,255,255,0.6);font-size:18px"></i>
        </div>
      </button>

      <!-- СЕРВІСИ -->
      <div class="settings-section-header">СЕРВІСИ</div>
      <div class="settings-menu-group">
        <button class="settings-menu-item" data-sub="telegram">
          <div class="settings-menu-icon" style="background:#E0F2FE;color:#0284C7"><i class="ti ti-brand-telegram"></i></div>
          <div class="settings-menu-label">Telegram бот</div>
          <i class="ti ti-chevron-right settings-menu-arrow"></i>
        </button>
        <button class="settings-menu-item" data-sub="sync">
          <div class="settings-menu-icon" style="background:#F0FDF4;color:#15803D"><i class="ti ti-refresh"></i></div>
          <div class="settings-menu-label">Синхронізація та Backup</div>
          <i class="ti ti-chevron-right settings-menu-arrow"></i>
        </button>
      </div>

      <!-- НАЛАШТУВАННЯ -->
      <div class="settings-section-header">НАЛАШТУВАННЯ</div>
      <div class="settings-menu-group">
        <button class="settings-menu-item" data-sub="default-wallet">
          <div class="settings-menu-icon" style="background:#DCFCE7;color:#16A34A"><i class="ti ti-wallet"></i></div>
          <div class="settings-menu-label">Кошельок за замовчуванням</div>
          <i class="ti ti-chevron-right settings-menu-arrow"></i>
        </button>
        <button class="settings-menu-item" data-sub="dashboard-widgets">
          <div class="settings-menu-icon" style="background:#EEF2FF;color:#4F46E5"><i class="ti ti-layout-dashboard"></i></div>
          <div class="settings-menu-label">Блоки дашборду</div>
          <i class="ti ti-chevron-right settings-menu-arrow"></i>
        </button>
        <button class="settings-menu-item" data-sub="exp-cats">
          <div class="settings-menu-icon" style="background:#FEF3C7;color:#B45309"><i class="ti ti-arrow-up-circle"></i></div>
          <div class="settings-menu-label">Категорії витрат</div>
          <i class="ti ti-chevron-right settings-menu-arrow"></i>
        </button>
        <button class="settings-menu-item" data-sub="inc-cats">
          <div class="settings-menu-icon" style="background:#DCFCE7;color:#16A34A"><i class="ti ti-arrow-down-circle"></i></div>
          <div class="settings-menu-label">Категорії доходів</div>
          <i class="ti ti-chevron-right settings-menu-arrow"></i>
        </button>
        <button class="settings-menu-item" data-sub="limits">
          <div class="settings-menu-icon" style="background:#FEE2E2;color:#DC2626"><i class="ti ti-gauge"></i></div>
          <div class="settings-menu-label">Ліміти та план витрат</div>
          <i class="ti ti-chevron-right settings-menu-arrow"></i>
        </button>
        <button class="settings-menu-item" data-sub="wallets">
          <div class="settings-menu-icon" style="background:#DBEAFE;color:#1D4ED8"><i class="ti ti-building-bank"></i></div>
          <div class="settings-menu-label">Кошельки та рахунки</div>
          <i class="ti ti-chevron-right settings-menu-arrow"></i>
        </button>
      </div>

      <!-- ІНФОРМАЦІЯ -->
      <div class="settings-section-header">ІНФОРМАЦІЯ</div>
      <div class="settings-menu-group">
        <button class="settings-menu-item" data-sub="about">
          <div class="settings-menu-icon" style="background:#EEF2FF;color:#4F46E5"><i class="ti ti-info-circle"></i></div>
          <div class="settings-menu-label">Про додаток</div>
          <i class="ti ti-chevron-right settings-menu-arrow"></i>
        </button>
        <button class="settings-menu-item" data-sub="privacy">
          <div class="settings-menu-icon" style="background:#E0F2FE;color:#0369A1"><i class="ti ti-shield"></i></div>
          <div class="settings-menu-label">Конфіденційність</div>
          <i class="ti ti-chevron-right settings-menu-arrow"></i>
        </button>
        <button class="settings-menu-item" data-sub="terms">
          <div class="settings-menu-icon" style="background:#F0FDF4;color:#15803D"><i class="ti ti-file-text"></i></div>
          <div class="settings-menu-label">Умови використання</div>
          <i class="ti ti-chevron-right settings-menu-arrow"></i>
        </button>
      </div>

      <div class="settings-footer">Money Budget · v3.0</div>
    </div>
  `;
}

// ── Sub-page content builders ─────────────────────────────────
const SUB_PAGE_TITLES = {
  'profile-group':     'Профіль',
  'dashboard-widgets': 'Блоки дашборду',
  profile:        'Профіль',
  family:         'Родина',
  appearance:     'Зовнішній вигляд',
  security:       'Безпека',
  'default-wallet': 'Кошельок за замовчуванням',
  telegram:       'Telegram сповіщення',
  sync:           'Синхронізація',
  plan:           'План витрат',
  limits:         'Ліміти витрат',
  'exp-cats':     'Категорії витрат',
  'inc-cats':     'Категорії доходів',
  'wallet-types': 'Типи рахунків',
  wallets:        'Кошельки',
  subscription:   'Підписка',
  privacy:        'Політика конфіденційності',
  terms:          'Угода користувача',
  about:          'Про додаток',
};

function renderSubPageBody(key) {
  const theme = getTheme();
  const family = getFamilyName();
  const profiles = getProfiles();
  const lastSync = localStorage.getItem('budget_last_sync');

  switch (key) {
    case 'profile-group': {
      return `
        <div class="settings-menu-group" style="margin-bottom:12px">
          <button class="settings-menu-item" data-sub="profile">
            <div class="settings-menu-icon" style="background:#DCFCE7;color:#16A34A"><i class="ti ti-user"></i></div>
            <div class="settings-menu-label">Профіль</div>
            <i class="ti ti-chevron-right settings-menu-arrow"></i>
          </button>
          <button class="settings-menu-item" data-sub="appearance">
            <div class="settings-menu-icon" style="background:#EEF2FF;color:#4F46E5"><i class="ti ti-palette"></i></div>
            <div class="settings-menu-label">Зовнішній вигляд</div>
            <i class="ti ti-chevron-right settings-menu-arrow"></i>
          </button>
          <button class="settings-menu-item" data-sub="family">
            <div class="settings-menu-icon" style="background:#FEF3C7;color:#D97706"><i class="ti ti-home-2"></i></div>
            <div class="settings-menu-label">Родина</div>
            <i class="ti ti-chevron-right settings-menu-arrow"></i>
          </button>
          <button class="settings-menu-item" data-sub="security">
            <div class="settings-menu-icon" style="background:#FEE2E2;color:#DC2626"><i class="ti ti-lock"></i></div>
            <div class="settings-menu-label">Безпека</div>
            <i class="ti ti-chevron-right settings-menu-arrow"></i>
          </button>
        </div>
      `;
    }

    case 'profile': {
      const userAv = getAvatar() || state.user?.avatar || '';
      const userAvatarHtml = userAv && userAv.length > 2
        ? `<img id="profile-avatar-img" src="${esc(userAv)}" style="width:80px;height:80px;border-radius:50%;object-fit:cover;border:3px solid var(--c-accent)">`
        : `<div id="profile-avatar-img" style="width:80px;height:80px;border-radius:50%;background:var(--c-accent-soft);color:var(--c-accent);font-size:32px;font-weight:700;display:flex;align-items:center;justify-content:center;border:3px solid var(--c-accent)">${(state.user?.name || '?')[0]}</div>`;
      return `
        <div class="settings-card" style="align-items:center;text-align:center;gap:12px;display:flex;flex-direction:column;padding:24px 16px">
          <div style="position:relative;display:inline-block">
            ${userAvatarHtml}
            <label for="profile-photo-input" style="position:absolute;bottom:0;right:0;width:26px;height:26px;border-radius:50%;background:var(--c-accent);color:#fff;display:flex;align-items:center;justify-content:center;cursor:pointer;box-shadow:0 2px 6px rgba(0,0,0,0.25)">
              <i class="ti ti-camera" style="font-size:13px"></i>
            </label>
            <input type="file" id="profile-photo-input" accept="image/*" style="display:none">
          </div>
          <div>
            <div style="font-size:17px;font-weight:700">${esc(state.user?.name || state.member || '')}</div>
            <div style="font-size:13px;color:var(--c-text-3)">${esc(state.user?.email || '')}</div>
          </div>
          <button class="btn-ghost-sm" id="remove-user-avatar-btn" style="font-size:12px;color:var(--c-text-3)">Скинути фото</button>
        </div>
        <div class="settings-card">
          <button class="settings-menu-item" id="signout-btn">
            <div class="settings-menu-icon" style="background:var(--c-red-soft);color:var(--c-red)"><i class="ti ti-logout"></i></div>
            <div class="settings-menu-label" style="color:var(--c-red)">Вийти з профілю</div>
            <i class="ti ti-chevron-right settings-menu-arrow"></i>
          </button>
          <button class="settings-menu-item" id="delete-account-btn">
            <div class="settings-menu-icon" style="background:var(--c-red-soft);color:var(--c-red)"><i class="ti ti-trash"></i></div>
            <div class="settings-menu-label" style="color:var(--c-red)">Видалити профіль і дані</div>
            <i class="ti ti-chevron-right settings-menu-arrow"></i>
          </button>
        </div>
      `;
    }

    case 'family': {
      const famAv = getFamilyAvatar();
      const famName = getFamilyName() || '';
      const famLogoHtml = famAv && famAv.startsWith('data:')
        ? `<img id="family-avatar-img" src="${esc(famAv)}" style="width:80px;height:80px;border-radius:20px;object-fit:cover;border:3px solid var(--c-accent)">`
        : famAv
          ? `<div id="family-avatar-img" style="width:80px;height:80px;border-radius:20px;background:var(--c-accent-soft);color:var(--c-accent);font-size:40px;display:flex;align-items:center;justify-content:center;border:3px solid var(--c-accent)">${famAv}</div>`
          : `<div id="family-avatar-img" style="width:80px;height:80px;border-radius:20px;background:var(--c-accent-soft);color:var(--c-accent);font-size:32px;display:flex;align-items:center;justify-content:center;border:3px solid var(--c-accent)"><i class="ti ti-home-2"></i></div>`;
      const FAMILY_EMOJIS = ['🏠','🏡','🏰','🌟','🌈','🌊','🌿','🦁','🐯','🦊','🐺','🦅','🌺','🍀','⭐','🎯','🚀','💎','🌙','🔥','🍁','🌻','🐉','🦋'];
      return `
        <div class="settings-card" style="text-align:center;display:flex;flex-direction:column;align-items:center;gap:12px;padding:24px 16px">
          <div style="position:relative;display:inline-block">
            ${famLogoHtml}
            <label for="family-photo-input" style="position:absolute;bottom:0;right:0;width:26px;height:26px;border-radius:50%;background:var(--c-accent);color:#fff;display:flex;align-items:center;justify-content:center;cursor:pointer;box-shadow:0 2px 6px rgba(0,0,0,0.25)">
              <i class="ti ti-camera" style="font-size:13px"></i>
            </label>
            <input type="file" id="family-photo-input" accept="image/*" style="display:none">
          </div>
          <div style="display:flex;align-items:center;gap:8px">
            <input id="family-name-input" value="${esc(famName)}" placeholder="Назва родини" style="font-size:16px;font-weight:700;text-align:center;border-bottom:1.5px solid var(--c-border);padding:4px 8px;background:transparent;width:180px">
            <button class="btn-ghost-sm" id="save-family-btn">✓</button>
          </div>
          <button class="btn-ghost-sm" id="remove-family-avatar-btn" style="font-size:12px;color:var(--c-text-3)">Скинути фото</button>
        </div>
        <div class="settings-card" style="padding:16px">
          <div style="font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:0.06em;color:var(--c-text-3);margin-bottom:12px">Іконка родини</div>
          <div style="display:grid;grid-template-columns:repeat(6,1fr);gap:8px">
            ${FAMILY_EMOJIS.map(em => `<button data-fam-emoji="${em}" style="font-size:24px;padding:6px;border-radius:10px;background:${famAv===em?'var(--c-accent-soft)':'var(--c-bg-3)'};border:2px solid ${famAv===em?'var(--c-accent)':'transparent'};cursor:pointer">${em}</button>`).join('')}
          </div>
        </div>
        <div class="settings-card">
          <div id="members-list">
            ${getFamilyMembers().map((m) => `
              <div class="settings-row">
                <div class="settings-row-icon" style="background:var(--c-accent-soft);color:var(--c-accent)"><b>${m[0]}</b></div>
                <div class="settings-row-info">
                  <div class="settings-row-name">${esc(m)}</div>
                  <div class="settings-row-sub">${esc(m) === esc(state.member) ? 'Це ви' : 'Учасник'}</div>
                </div>
              </div>
            `).join('')}
          </div>
          <button class="settings-add-btn" id="invite-btn"><i class="ti ti-user-plus"></i> Запросити члена родини</button>
        </div>
      `;
    }

    case 'appearance': {
      const curPalette = getPalette();
      const PALETTES_LIST = [
        { id: 'default',  label: 'Зелений',    bg: 'linear-gradient(135deg,#2E7D5F,#4CAF50)', emoji: '🌿' },
        { id: 'ocean',    label: 'Океан',       bg: 'linear-gradient(135deg,#1A6FBF,#4A9FEF)', emoji: '🌊' },
        { id: 'sunset',   label: 'Захід',       bg: 'linear-gradient(135deg,#E05A2B,#FF7D4D)', emoji: '🌅' },
        { id: 'midnight', label: 'Полудень',    bg: 'linear-gradient(135deg,#6C3FD4,#9B72FF)', emoji: '🌙' },
        { id: 'neon',     label: 'Неон',        bg: 'linear-gradient(135deg,#060811,#00FFB3)', emoji: '⚡' },
        { id: 'glass',    label: 'Скло',        bg: 'linear-gradient(135deg,#b8f5d8,#ece4ff)', emoji: '🪟' },
      ];
      return `
        <div class="settings-card">
          <div class="settings-row">
            <div class="settings-row-icon"><i class="ti ti-${theme === 'dark' ? 'moon' : 'sun'}"></i></div>
            <div class="settings-row-info">
              <div class="settings-row-name">Режим</div>
              <div class="settings-row-sub">${theme === 'dark' ? 'Темний' : 'Світлий'}</div>
            </div>
            <div class="theme-switch">
              <button class="theme-btn ${theme === 'light' ? 'active' : ''}" data-theme="light"><i class="ti ti-sun"></i></button>
              <button class="theme-btn ${theme === 'dark' ? 'active' : ''}" data-theme="dark"><i class="ti ti-moon"></i></button>
            </div>
          </div>
        </div>

        <div class="settings-card" style="padding:16px">
          <div style="font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:0.06em;color:var(--c-text-3);margin-bottom:12px;padding-left:2px">Стиль теми</div>
          <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:10px" id="palette-grid">
            ${PALETTES_LIST.map(p => `
              <button data-palette-id="${p.id}" style="display:flex;flex-direction:column;align-items:center;gap:6px;padding:10px 6px;border-radius:14px;border:2.5px solid ${p.id === curPalette ? 'var(--c-accent)' : 'transparent'};background:${p.id === curPalette ? 'var(--c-accent-soft)' : 'var(--c-bg-3)'};cursor:pointer;transition:all .15s">
                <div style="width:44px;height:44px;border-radius:12px;background:${p.bg};display:flex;align-items:center;justify-content:center;font-size:22px;box-shadow:0 3px 10px rgba(0,0,0,0.15)">${p.emoji}</div>
                <div style="font-size:11px;font-weight:600;color:var(--c-text)">${p.label}</div>
              </button>
            `).join('')}
          </div>
        </div>
      `;
    }

    case 'security':
      return `
        <div class="settings-card" id="lock-section-card">
          ${renderLockSection()}
        </div>
      `;

    case 'default-wallet':
      return `
        <div class="settings-card" id="default-wallet-card">
          ${renderDefaultWalletRows()}
        </div>
      `;

    case 'telegram':
      return `
        <div class="settings-card" style="margin-bottom:12px">
          <div style="display:flex;align-items:center;gap:14px;padding:4px 0 12px;border-bottom:1px solid var(--c-border);margin-bottom:12px">
            <div style="width:52px;height:52px;border-radius:14px;background:#E0F2FE;color:#0284C7;display:flex;align-items:center;justify-content:center;font-size:26px;flex-shrink:0">
              <i class="ti ti-brand-telegram"></i>
            </div>
            <div>
              <div style="font-size:16px;font-weight:700;margin-bottom:2px">Financial Family Assistant</div>
              <div style="font-size:13px;color:var(--c-text-3)">Ваш фінансовий асистент у Telegram</div>
            </div>
          </div>
          <a href="https://t.me/Financial_Family_Assistant_Bot" target="_blank" rel="noopener"
            style="display:flex;align-items:center;justify-content:center;gap:8px;width:100%;padding:12px;background:#0284C7;color:#fff;border-radius:var(--radius);font-size:14px;font-weight:700;text-decoration:none;margin-bottom:14px">
            <i class="ti ti-brand-telegram" style="font-size:18px"></i> Відкрити бота
          </a>
          <div style="font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:0.06em;color:var(--c-text-3);margin-bottom:8px">Що вміє бот</div>
          ${[
            ['ti-plus-circle','Додавати витрати та доходи','Надішліть боту суму і категорію — операція одразу з\'явиться в додатку'],
            ['ti-calendar-due','Нагадування про платежі','Бот нагадає про регулярні платежі та підписки вчасно'],
            ['ti-chart-bar','Щоденний підсумок','Отримуйте зведення витрат за день у зручний для вас час'],
            ['ti-alert-triangle','Попередження про ліміти','Сповіщення коли витрати наближаються до встановленого ліміту'],
            ['ti-camera','Сканування чеків','Надішліть фото чека — бот розпізнає суму і категорію автоматично'],
          ].map(([icon, name, desc], i, arr) => `
            <div style="display:flex;gap:12px;padding:10px 0;align-items:flex-start;${i < arr.length-1 ? 'border-bottom:0.5px solid var(--c-border)' : ''}">
              <div style="width:36px;height:36px;border-radius:10px;background:#E0F2FE;color:#0284C7;display:flex;align-items:center;justify-content:center;flex-shrink:0">
                <i class="ti ${icon}" style="font-size:16px"></i>
              </div>
              <div>
                <div style="font-size:13px;font-weight:600">${name}</div>
                <div style="font-size:12px;color:var(--c-text-3);margin-top:2px;line-height:1.4">${desc}</div>
              </div>
            </div>
          `).join('')}
        </div>
        <div class="settings-card">
          <div style="font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:0.06em;color:var(--c-text-3);margin-bottom:10px">Налаштування сповіщень</div>
          ${renderTelegramPrefs()}
        </div>
      `;

    case 'sync':
      return `
        <div class="settings-card">
          <div class="settings-row">
            <div class="settings-row-icon green"><i class="ti ti-brand-firebase"></i></div>
            <div class="settings-row-info">
              <div class="settings-row-name">Синхронізація</div>
              <div class="settings-row-sub" id="sync-status">${lastSync ? 'Остання: ' + new Date(lastSync).toLocaleString('uk-UA') : 'Не виконувалась'}</div>
            </div>
            <button class="btn-ghost-sm" id="sync-now-btn"><i class="ti ti-refresh"></i> Sync</button>
          </div>
          <div class="settings-row">
            <div class="settings-row-icon"><i class="ti ti-stethoscope"></i></div>
            <div class="settings-row-info">
              <div class="settings-row-name">Діагностика</div>
              <div class="settings-row-sub">Перевірити чи все працює</div>
            </div>
            <button class="btn-ghost-sm" id="diag-btn">Запустити</button>
          </div>
        </div>
      `;

    case 'plan':
      return `
        <div class="settings-card" id="plan-card">
          ${renderBudgetGrid('plan')}
        </div>
      `;

    case 'limits':
      return `
        <div class="settings-card" id="limits-card">
          ${renderBudgetGrid('limits')}
        </div>
      `;

    case 'exp-cats':
      return `
        <div class="settings-card">
          <div class="cat-grid" id="exp-cats-grid"></div>
          <button class="settings-add-btn" id="add-exp-cat-btn"><i class="ti ti-plus"></i> Додати категорію</button>
        </div>
      `;

    case 'inc-cats':
      return `
        <div class="settings-card">
          <div class="cat-grid" id="inc-cats-grid"></div>
          <button class="settings-add-btn" id="add-inc-cat-btn"><i class="ti ti-plus"></i> Додати категорію</button>
        </div>
      `;

    case 'wallet-types':
      return `
        <div class="settings-card">
          <div class="settings-hint">Свої категорії для кошельків. Наприклад: «Криптогаманець», «Депозит», «Валюта в євро». Клік для редагування.</div>
          <div class="cat-grid" id="wallet-types-grid"></div>
          <button class="settings-add-btn" id="add-wallet-type-btn"><i class="ti ti-plus"></i> Додати тип</button>
        </div>
      `;

    case 'wallets':
      return `
        <div class="settings-card">
          ${FAMILY_MEMBERS.map(m => {
            const cards = getCards(m);
            return `
              <div class="settings-wallet-owner-label">
                <div class="settings-wallet-owner-avatar">${(profiles[m]?.name || m)[0]}</div>
                ${esc(profiles[m]?.name || m)}
              </div>
              <div class="cat-grid">
                ${cards.map((c, idx) => `
                  <button class="cat-card" data-wallet-owner="${esc(m)}" data-wallet-idx="${idx}">
                    <div class="cat-card-icon" style="background:${c.bg}">
                      <i class="ti ${c.icon}" style="color:${c.color}"></i>
                    </div>
                    <div class="cat-card-name">${esc(c.id)}${c.currency && c.currency !== 'UAH' ? '<br><small style="opacity:.6">' + c.currency + '</small>' : ''}</div>
                  </button>
                `).join('')}
              </div>
            `;
          }).join('')}
          <button class="settings-add-btn" id="add-wallet-btn"><i class="ti ti-plus"></i> Додати кошельок</button>
        </div>
      `;

    case 'dashboard-widgets': {
      const widgets = JSON.parse(localStorage.getItem('budget_widgets') || '{}');
      const WIDGET_LIST = [
        { key: 'wallets',   label: 'Кошельки' },
        { key: 'chart',     label: 'Графіки витрат/доходів' },
        { key: 'donut',     label: 'Кругова діаграма категорій' },
        { key: 'limits',    label: 'Топ категорій з лімітами' },
        { key: 'credit',    label: 'Кредитні картки' },
        { key: 'recurring', label: 'Найближчі платежі' },
        { key: 'recent',    label: 'Останні операції' },
      ];
      return `
        <div class="settings-card" style="padding:16px">
          <div style="font-size:12px;color:var(--c-text-3);margin-bottom:14px;padding-left:2px">Вибери що показувати на головній</div>
          ${WIDGET_LIST.map(w => `
            <div class="settings-row" style="padding:10px 0;border-bottom:.5px solid var(--c-border)">
              <div class="settings-row-info"><div class="settings-row-name" style="font-size:14px">${w.label}</div></div>
              <label class="toggle-switch" style="flex-shrink:0">
                <input type="checkbox" class="widget-toggle" data-widget="${w.key}" ${widgets[w.key] !== false ? 'checked' : ''}>
                <span class="toggle-track"><span class="toggle-thumb"></span></span>
              </label>
            </div>
          `).join('')}
        </div>
      `;
    }

    case 'subscription':
      return `
        <div class="sub-page-hero">
          <div class="sub-page-hero-logo">✨</div>
          <div class="sub-page-hero-title">Money Budget Pro</div>
          <div class="sub-page-hero-sub">Усі можливості. Одна підписка.</div>
        </div>

        <div class="settings-card" style="margin-bottom:12px">
          <div style="font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:0.06em;color:var(--c-text-3);margin-bottom:10px;padding-left:4px">Оберіть план</div>

          <div class="sub-plan-card" data-plan="week">
            <div style="display:flex;justify-content:space-between;align-items:flex-start">
              <div>
                <div style="font-size:15px;font-weight:700">Тижневий</div>
                <div style="font-size:12px;color:var(--c-text-3);margin-top:2px">7 днів повного доступу</div>
              </div>
              <div style="text-align:right">
                <div style="font-size:20px;font-weight:800;color:var(--c-accent)">49 ₴</div>
                <div style="font-size:11px;color:var(--c-text-3)">~$1.2 · / 7 днів</div>
              </div>
            </div>
          </div>

          <div class="sub-plan-card sub-plan-featured" data-plan="month">
            <div style="display:flex;justify-content:space-between;align-items:flex-start">
              <div>
                <div style="display:flex;align-items:center;gap:8px">
                  <div style="font-size:15px;font-weight:700">Місячний</div>
                  <span style="background:var(--c-accent);color:#fff;font-size:10px;font-weight:700;padding:2px 8px;border-radius:20px">POPULAR</span>
                </div>
                <div style="font-size:12px;color:var(--c-text-3);margin-top:2px">30 днів повного доступу</div>
              </div>
              <div style="text-align:right">
                <div style="font-size:20px;font-weight:800;color:var(--c-accent)">149 ₴</div>
                <div style="font-size:11px;color:var(--c-text-3)">~$3.6 · / місяць</div>
              </div>
            </div>
          </div>

          <div class="sub-plan-card" data-plan="year">
            <div style="display:flex;justify-content:space-between;align-items:flex-start">
              <div>
                <div style="display:flex;align-items:center;gap:8px">
                  <div style="font-size:15px;font-weight:700">Річний</div>
                  <span style="background:#F59E0B;color:#fff;font-size:10px;font-weight:700;padding:2px 8px;border-radius:20px">ВИГІДНО</span>
                </div>
                <div style="font-size:12px;color:var(--c-text-3);margin-top:2px">365 днів · ~133 ₴/міс · ~$39/рік</div>
              </div>
              <div style="text-align:right">
                <div style="font-size:20px;font-weight:800;color:var(--c-accent)">1599 ₴</div>
                <div style="font-size:11px;color:var(--c-text-3)">~$39 · / рік</div>
              </div>
            </div>
          </div>
        </div>

        <div style="padding:0 0 8px">
          <button class="pw-btn-primary" id="sub-page-subscribe-btn">Підключити Pro</button>
          <button class="pw-btn-trial" id="sub-page-trial-btn">Спробувати 7 днів безкоштовно</button>
          <div class="pw-cancel-hint">Скасувати в будь-який час. Без прихованих платежів.</div>
        </div>
      `;

    case 'privacy':
      return `
        <div class="settings-card" style="margin-bottom:12px">
          <div style="display:flex;align-items:center;gap:12px;padding-bottom:14px;border-bottom:1px solid var(--c-border);margin-bottom:14px">
            <div style="width:44px;height:44px;border-radius:12px;background:#F0FDF4;color:#16A34A;display:flex;align-items:center;justify-content:center;font-size:22px;flex-shrink:0"><i class="ti ti-shield-check"></i></div>
            <div>
              <div style="font-size:15px;font-weight:700">Політика конфіденційності</div>
              <div style="font-size:12px;color:var(--c-text-3)">Редакція від 1 травня 2025 р.</div>
            </div>
          </div>
          ${[
            ['Які дані ми збираємо', 'Ми збираємо мінімум інформації: ім\'я та email вашого Google-акаунта для авторизації, а також фінансові операції, кошельки та цілі, які ви вводите вручну. Ми не збираємо геолокацію, контакти, або будь-які інші персональні дані.'],
            ['Де зберігаються дані', 'Усі дані зберігаються у хмарній базі Firebase (Google Cloud) із шифруванням у стані спокою (AES-256) та під час передачі (TLS). Сервери розташовані в Євросоюзі.'],
            ['Хто має доступ', 'Виключно ви та члени вашої родини, яких ви самостійно запросили до облікового запису. Ми — команда розробників — не переглядаємо ваші фінансові дані. Жодна третя сторона не має доступу.'],
            ['Продаж даних', 'Ми не продаємо, не передаємо і не обмінюємо ваші персональні або фінансові дані з рекламодавцями, партнерами або будь-якими іншими організаціями.'],
            ['Видалення даних', 'Ви можете видалити свій акаунт і всі пов\'язані дані в будь-який момент у розділі Налаштування → Акаунт → Видалити акаунт. Після видалення дані стираються повністю протягом 30 днів.'],
            ['Зміни в політиці', 'Ми повідомляємо про суттєві зміни в цій політиці через сповіщення в додатку не менше ніж за 7 днів до набрання чинності. Актуальна версія завжди доступна в налаштуваннях.'],
          ].map(([title, text], i, arr) => `
            <div style="margin-bottom:${i < arr.length-1 ? '14px' : '0'}">
              <div style="font-size:13px;font-weight:700;color:var(--c-text);margin-bottom:4px">${title}</div>
              <div style="font-size:13px;line-height:1.6;color:var(--c-text-2)">${text}</div>
            </div>
          `).join('')}
        </div>
        <div class="settings-card">
          <div style="display:flex;gap:12px;align-items:flex-start">
            <i class="ti ti-mail" style="font-size:18px;color:var(--c-text-3);margin-top:2px"></i>
            <div>
              <div style="font-size:13px;font-weight:600">Питання щодо конфіденційності</div>
              <div style="font-size:12px;color:var(--c-text-3);margin-top:2px">Напишіть нам: <a href="mailto:privacy@many.app" style="color:var(--c-accent)">privacy@many.app</a></div>
            </div>
          </div>
        </div>
      `;

    case 'terms':
      return `
        <div class="settings-card" style="margin-bottom:12px">
          <div style="display:flex;align-items:center;gap:12px;padding-bottom:14px;border-bottom:1px solid var(--c-border);margin-bottom:14px">
            <div style="width:44px;height:44px;border-radius:12px;background:#FFF7ED;color:#EA580C;display:flex;align-items:center;justify-content:center;font-size:22px;flex-shrink:0"><i class="ti ti-file-text"></i></div>
            <div>
              <div style="font-size:15px;font-weight:700">Угода користувача</div>
              <div style="font-size:12px;color:var(--c-text-3)">Редакція від 1 травня 2025 р.</div>
            </div>
          </div>
          ${[
            ['Прийняття умов', 'Використовуючи додаток Many Budget, ви підтверджуєте, що ознайомились із цією угодою та погоджуєтесь з її умовами. Якщо ви не згодні — будь ласка, припиніть використання додатку.'],
            ['Підписка та оплата', 'Доступ до повного функціоналу надається за платною підпискою. Підписка автоматично поновлюється. Ви можете скасувати її в будь-який момент у налаштуваннях App Store або Google Play. Повернення коштів здійснюється відповідно до правил магазину застосунків.'],
            ['Обмеження відповідальності', 'Many Budget є інструментом для особистого фінансового обліку. Додаток не є фінансовим радником. Ми не несемо відповідальності за фінансові рішення, прийняті на основі даних у додатку. Завжди консультуйтесь із кваліфікованим фінансистом у важливих питаннях.'],
            ['Права та обов\'язки', 'Ви зобов\'язуєтесь не використовувати додаток для незаконних цілей, не намагатися отримати несанкціонований доступ до чужих даних, не розповсюджувати шкідливий вміст через функції спільного доступу.'],
            ['Зміни у функціоналі', 'Ми залишаємо за собою право змінювати, оновлювати або припиняти окремі функції додатку. Про суттєві зміни ми повідомляємо заздалегідь. Ми прагнемо вдосконалювати продукт та цінуємо ваш зворотний зв\'язок.'],
            ['Припинення доступу', 'Ми залишаємо за собою право призупинити або припинити доступ до акаунта у разі порушення умов цієї угоди. Ви можете самостійно видалити акаунт у будь-який час.'],
          ].map(([title, text], i, arr) => `
            <div style="margin-bottom:${i < arr.length-1 ? '14px' : '0'}">
              <div style="font-size:13px;font-weight:700;color:var(--c-text);margin-bottom:4px">${title}</div>
              <div style="font-size:13px;line-height:1.6;color:var(--c-text-2)">${text}</div>
            </div>
          `).join('')}
        </div>
        <div class="settings-card">
          <div style="display:flex;gap:12px;align-items:flex-start">
            <i class="ti ti-mail" style="font-size:18px;color:var(--c-text-3);margin-top:2px"></i>
            <div>
              <div style="font-size:13px;font-weight:600">Запитання щодо угоди</div>
              <div style="font-size:12px;color:var(--c-text-3);margin-top:2px">Напишіть нам: <a href="mailto:support@many.app" style="color:var(--c-accent)">support@many.app</a></div>
            </div>
          </div>
        </div>
      `;

    case 'about':
      return `
        <div class="settings-card" style="margin-bottom:12px">
          <div style="display:flex;flex-direction:column;align-items:center;padding:24px 16px 20px;text-align:center">
            <div style="width:80px;height:80px;border-radius:22px;background:linear-gradient(135deg,#2E7D5F,#4CAF50);display:flex;align-items:center;justify-content:center;font-size:40px;margin-bottom:14px;box-shadow:0 8px 24px rgba(46,125,95,0.35)">
              💰
            </div>
            <div style="font-size:22px;font-weight:800;letter-spacing:-0.02em;margin-bottom:4px">Many Budget</div>
            <div style="font-size:13px;color:var(--c-text-3);margin-bottom:16px">Версія 2.0.0 · Травень 2025</div>
            <div style="font-size:14px;color:var(--c-text-2);line-height:1.7;max-width:300px">
              Розумний фінансовий менеджер для всієї родини з AI-аналітикою, синхронізацією та Telegram-ботом.
            </div>
          </div>
          <div style="border-top:1px solid var(--c-border);padding-top:16px;display:grid;grid-template-columns:repeat(3,1fr);gap:8px;text-align:center">
            ${[
              ['🤝','Сімейний','доступ'],
              ['🤖','AI','аналітика'],
              ['📱','Telegram','бот'],
            ].map(([em, t1, t2]) => `
              <div style="padding:10px 4px">
                <div style="font-size:22px;margin-bottom:4px">${em}</div>
                <div style="font-size:12px;font-weight:700;color:var(--c-text)">${t1}</div>
                <div style="font-size:11px;color:var(--c-text-3)">${t2}</div>
              </div>
            `).join('')}
          </div>
        </div>
        <div class="settings-card" style="margin-bottom:12px">
          <div style="font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:0.06em;color:var(--c-text-3);margin-bottom:10px">Можливості</div>
          ${[
            ['ti-wallet','Кілька кошельків','Готівка, банківські картки, валютні рахунки — все в одному місці'],
            ['ti-users','Спільний бюджет','Додайте членів родини та відстежуйте витрати разом'],
            ['ti-robot','AI · Фінн','Персональний фінансовий радник на базі Claude AI'],
            ['ti-brand-telegram','Telegram-бот','Додавайте операції голосом або текстом прямо з месенджера'],
            ['ti-target','Цілі та резерв','Накопичуйте на мрії та формуйте фінансову подушку'],
            ['ti-chart-bar','Аналітика','Детальна статистика витрат по категоріях і членах родини'],
            ['ti-repeat','Регулярні платежі','Автоматичний облік підписок та щомісячних витрат'],
            ['ti-scan','Сканер чеків','Фотографуйте чек — додаток розпізнає суму автоматично'],
          ].map(([icon, name, desc], i, arr) => `
            <div style="display:flex;gap:12px;padding:10px 0;align-items:flex-start;${i < arr.length-1 ? 'border-bottom:0.5px solid var(--c-border)' : ''}">
              <div style="width:36px;height:36px;border-radius:10px;background:var(--c-accent-soft);color:var(--c-accent);display:flex;align-items:center;justify-content:center;flex-shrink:0">
                <i class="ti ${icon}"></i>
              </div>
              <div>
                <div style="font-size:13px;font-weight:600">${name}</div>
                <div style="font-size:12px;color:var(--c-text-3);margin-top:2px;line-height:1.4">${desc}</div>
              </div>
            </div>
          `).join('')}
        </div>
        <div class="settings-card">
          <div class="settings-row" style="border-bottom:0.5px solid var(--c-border);padding-bottom:10px;margin-bottom:10px">
            <div class="settings-row-icon" style="background:#FEF3C7;color:#D97706"><i class="ti ti-star-filled"></i></div>
            <div class="settings-row-info">
              <div class="settings-row-name">Оцінити додаток</div>
              <div class="settings-row-sub">Допоможіть нам стати кращими</div>
            </div>
            <i class="ti ti-chevron-right" style="color:var(--c-text-3)"></i>
          </div>
          <div class="settings-row" style="border-bottom:0.5px solid var(--c-border);padding-bottom:10px;margin-bottom:10px">
            <div class="settings-row-icon" style="background:#EDE9FE;color:#7C3AED"><i class="ti ti-share"></i></div>
            <div class="settings-row-info">
              <div class="settings-row-name">Поділитися</div>
              <div class="settings-row-sub">Розкажіть друзям про Many Budget</div>
            </div>
            <i class="ti ti-chevron-right" style="color:var(--c-text-3)"></i>
          </div>
          <div class="settings-row">
            <div class="settings-row-icon" style="background:#FEE2E2;color:#DC2626"><i class="ti ti-heart-filled"></i></div>
            <div class="settings-row-info">
              <div class="settings-row-name">Many Budget © 2025</div>
              <div class="settings-row-sub">Зроблено з ❤️ для вашої родини</div>
            </div>
          </div>
        </div>
      `;

    default:
      return `<div class="settings-hint">Невідома секція: ${esc(key)}</div>`;
  }
}

function renderSubPage(key) {
  const title = SUB_PAGE_TITLES[key] || key;
  return `
    <div class="settings-subpage">
      <div class="settings-subpage-head">
        <button class="settings-back-btn" id="settings-back"><i class="ti ti-arrow-left"></i></button>
        <h2 class="settings-subpage-title">${esc(title)}</h2>
      </div>
      <div class="settings-subpage-body">
        ${renderSubPageBody(key)}
      </div>
    </div>
  `;
}

export function resetSettingsPage() { settingsSubPage = null; }

// ── Main render function ──────────────────────────────────────
export function renderSettingsPage() {
  const el = document.getElementById('page-settings');
  if (!el) return;

  el.innerHTML = settingsSubPage ? renderSubPage(settingsSubPage) : renderMainMenu();

  // Scroll content area to top when entering/changing sub-page
  const contentEl = document.querySelector('.content');
  if (contentEl) contentEl.scrollTop = 0;

  // Render dynamic grids after HTML is set
  if (settingsSubPage === 'exp-cats') {
    renderCatGrid('exp-cats-grid', getExpCats(), 'exp');
  } else if (settingsSubPage === 'inc-cats') {
    renderCatGrid('inc-cats-grid', getIncCats(), 'inc');
  } else if (settingsSubPage === 'wallet-types') {
    renderTypesGrid('wallet-types-grid', getWalletTypes());
  }

  bindSettingsHandlers(el);
}

// ── Cat / type grids ──────────────────────────────────────────
function renderCatGrid(containerId, cats, kind) {
  const el = document.getElementById(containerId);
  if (!el) return;
  el.innerHTML = cats.map((c, i) => `
    <button class="cat-card" data-kind="${kind}" data-idx="${i}">
      <div class="cat-card-icon" style="background:${c.bg}">
        <i class="ti ${c.icon}" style="color:${c.color}"></i>
      </div>
      <div class="cat-card-name">${esc(c.id)}</div>
    </button>
  `).join('');

  el.querySelectorAll('.cat-card').forEach(card => {
    card.addEventListener('click', () => {
      const idx = parseInt(card.dataset.idx);
      const k = card.dataset.kind;
      openCatEditor(k, idx);
    });
  });
}

function renderTypesGrid(containerId, types) {
  const el = document.getElementById(containerId);
  if (!el) return;
  el.innerHTML = types.map((t, i) => `
    <button class="cat-card" data-type-idx="${i}">
      <div class="cat-card-icon" style="background:${t.bg || '#F0F0F0'}">
        <i class="ti ${t.icon || 'ti-wallet'}" style="color:${t.color || '#555'}"></i>
      </div>
      <div class="cat-card-name">${esc(t.name)}</div>
    </button>
  `).join('');

  el.querySelectorAll('.cat-card').forEach(card => {
    card.addEventListener('click', () => {
      const idx = parseInt(card.dataset.typeIdx);
      openTypeEditor(idx);
    });
  });
}

// ── Cat editor ────────────────────────────────────────────────
function openCatEditor(kind, idx) {
  const isEdit = idx !== undefined && idx >= 0;
  const list = kind === 'exp' ? getExpCats() : getIncCats();
  const cat = isEdit ? list[idx] : null;

  openIconPicker({
    title: isEdit ? 'Редагувати категорію' : 'Нова категорія',
    nameLabel: 'Назва',
    nameValue: cat?.id || '',
    namePlaceholder: 'Наприклад: Продукти',
    showTypes: false,
    selectedIcon: cat?.icon || 'ti-dots',
    selectedColor: cat ? { bg: cat.bg, color: cat.color } : undefined,
    isEdit,
    onSave: ({ name, icon, color }) => {
      const item = { id: name, icon, bg: color.bg, color: color.color };
      if (isEdit) list[idx] = item;
      else list.push(item);
      if (kind === 'exp') setExpCats(list); else setIncCats(list);
      syncSettingsToSheet();
      showToast(isEdit ? '✅ Збережено' : '✅ Додано');
      renderSettingsPage();
    },
    onDelete: isEdit ? () => {
      list.splice(idx, 1);
      if (kind === 'exp') setExpCats(list); else setIncCats(list);
      syncSettingsToSheet();
      showToast('Видалено');
      renderSettingsPage();
    } : null,
  });
}

// ── Type editor ───────────────────────────────────────────────
function openTypeEditor(idx) {
  const types = getWalletTypes();
  const isEdit = idx !== undefined && idx >= 0;
  const t = isEdit ? types[idx] : null;

  openIconPicker({
    title: isEdit ? 'Редагувати тип' : 'Новий тип',
    nameLabel: 'Назва',
    nameValue: t?.name || '',
    namePlaceholder: 'Наприклад: Криптогаманець',
    showTypes: false,
    selectedIcon: t?.icon || 'ti-wallet',
    selectedColor: t ? { bg: t.bg, color: t.color } : undefined,
    isEdit,
    onSave: ({ name, icon, color }) => {
      const id = isEdit ? t.id : name.toLowerCase().replace(/\s+/g, '_').replace(/[^a-z0-9_а-яіїєґ]/gi, '').substring(0, 30) || ('type_' + Date.now());
      const item = { id, name, icon, bg: color.bg, color: color.color };
      if (isEdit) {
        types[idx] = item;
      } else {
        if (types.find(x => x.id === id)) item.id = id + '_' + Date.now();
        types.push(item);
      }
      setWalletTypes(types);
      syncSettingsToSheet();
      showToast(isEdit ? '✅ Збережено' : '✅ Додано');
      renderSettingsPage();
    },
    onDelete: isEdit ? () => {
      types.splice(idx, 1);
      setWalletTypes(types);
      syncSettingsToSheet();
      showToast('Видалено');
      renderSettingsPage();
    } : null,
  });
}

// ── Handlers ──────────────────────────────────────────────────
function bindSettingsHandlers(el) {
  // Back button
  el.querySelector('#settings-back')?.addEventListener('click', () => {
    settingsSubPage = null;
    renderSettingsPage();
  });

  // Menu items + profile/pro cards
  el.querySelectorAll('.settings-menu-item, .settings-profile-card, .settings-pro-card').forEach(b => {
    b.addEventListener('click', () => {
      settingsSubPage = b.dataset.sub;
      renderSettingsPage();
    });
  });

  // Theme
  el.querySelectorAll('[data-theme]').forEach(b => {
    b.addEventListener('click', () => {
      applyTheme(b.dataset.theme);
      renderSettingsPage();
    });
  });

  // Palette
  el.querySelectorAll('[data-palette-id]').forEach(b => {
    b.addEventListener('click', () => {
      setPalette(b.dataset.paletteId);
      applyPalette(b.dataset.paletteId);
      renderSettingsPage();
    });
  });

  // Widget toggles
  el.querySelectorAll('.widget-toggle').forEach(inp => {
    inp.addEventListener('change', () => {
      const widgets = getDashWidgets();
      widgets[inp.dataset.widget] = inp.checked;
      setDashWidgets(widgets);
    });
  });

  // Family emoji picker
  el.querySelectorAll('[data-fam-emoji]').forEach(btn => {
    btn.addEventListener('click', () => {
      const emoji = btn.dataset.famEmoji;
      setFamilyAvatar(emoji);
      el.querySelectorAll('[data-fam-emoji]').forEach(b => {
        const active = b.dataset.famEmoji === emoji;
        b.style.borderColor = active ? 'var(--c-accent)' : 'transparent';
        b.style.background  = active ? 'var(--c-accent-soft)' : 'var(--c-bg-3)';
      });
      const img = el.querySelector('#family-avatar-img');
      if (img) img.outerHTML = `<div id="family-avatar-img" style="width:80px;height:80px;border-radius:20px;background:var(--c-accent-soft);color:var(--c-accent);font-size:40px;display:flex;align-items:center;justify-content:center;border:3px solid var(--c-accent)">${emoji}</div>`;
      if (window.renderSidebarPublic) window.renderSidebarPublic();
      showToast('✅ Іконку змінено');
    });
  });

  // Family photo upload
  el.querySelector('#family-photo-input')?.addEventListener('change', async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    try {
      const dataUrl = await compressImage(file, 256);
      setFamilyAvatar(dataUrl);
      const img = el.querySelector('#family-avatar-img');
      if (img) img.outerHTML = `<img id="family-avatar-img" src="${dataUrl}" style="width:80px;height:80px;border-radius:20px;object-fit:cover;border:3px solid var(--c-accent)">`;
      if (window.renderSidebarPublic) window.renderSidebarPublic();
      showToast('✅ Фото родини збережено');
    } catch { showToast('Помилка завантаження', 'error'); }
  });

  // Remove family avatar
  el.querySelector('#remove-family-avatar-btn')?.addEventListener('click', () => {
    setFamilyAvatar('');
    if (window.renderSidebarPublic) window.renderSidebarPublic();
    renderSettingsPage();
    showToast('Іконку скинуто');
  });

  // User photo upload
  el.querySelector('#profile-photo-input')?.addEventListener('change', async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    try {
      const dataUrl = await compressImage(file, 256);
      setAvatar(dataUrl);
      const img = el.querySelector('#profile-avatar-img');
      if (img) img.outerHTML = `<img id="profile-avatar-img" src="${dataUrl}" style="width:80px;height:80px;border-radius:50%;object-fit:cover;border:3px solid var(--c-accent)">`;
      if (window.renderSidebarPublic) window.renderSidebarPublic();
      if (window.renderTopbarPublic) window.renderTopbarPublic();
      showToast('✅ Фото профілю збережено');
    } catch { showToast('Помилка завантаження', 'error'); }
  });

  // Remove user avatar
  el.querySelector('#remove-user-avatar-btn')?.addEventListener('click', () => {
    setAvatar('');
    if (window.renderSidebarPublic) window.renderSidebarPublic();
    if (window.renderTopbarPublic) window.renderTopbarPublic();
    renderSettingsPage();
    showToast('Фото скинуто');
  });

  // Subscription plan cards
  el.querySelectorAll('.sub-plan-card').forEach(card => {
    card.addEventListener('click', () => {
      el.querySelectorAll('.sub-plan-card').forEach(c => c.classList.remove('selected'));
      card.classList.add('selected');
    });
  });

  // Subscribe button
  el.querySelector('#sub-page-subscribe-btn')?.addEventListener('click', () => {
    import('./paywall.js').then(m => m.showPaywall());
  });
  el.querySelector('#sub-page-trial-btn')?.addEventListener('click', () => {
    import('./paywall.js').then(m => m.showPaywall());
  });

  // Family name
  el.querySelector('#save-family-btn')?.addEventListener('click', () => {
    const v = el.querySelector('#family-name-input').value.trim();
    if (!v) return;
    setFamilyName(v);
    syncSettingsToSheet();
    const sb = document.getElementById('sb-family-name');
    if (sb) sb.textContent = v;
    showToast('✅ Збережено');
  });

  // Sign out
  el.querySelector('#signout-btn')?.addEventListener('click', async () => {
    const ok = await confirmModal('Точно вийти?', { danger: true, okText: 'Вийти' });
    if (ok) signOut();
  });

  // Delete account
  el.querySelector('#delete-account-btn')?.addEventListener('click', async () => {
    const { confirmModal } = await import('./modals.js');
    const ok = await confirmModal(
      'Видалити профіль і всі дані? Цю дію неможливо скасувати.',
      { danger: true, okText: 'Видалити назавжди' }
    );
    if (!ok) return;
    try {
      // Clear all localStorage
      localStorage.clear();
      // Delete Firestore data if possible
      if (window.firebase && state.familyId) {
        // Note: full deletion requires backend, just sign out for now
      }
      const { signOut } = await import('./auth.js');
      showToast('Дані видалено');
      setTimeout(() => signOut(), 1000);
    } catch (e) {
      showToast('Помилка: ' + e.message, 'error');
    }
  });

  // Invite member
  el.querySelector('#invite-btn')?.addEventListener('click', async () => {
    const btn = el.querySelector('#invite-btn');
    btn.disabled = true;
    btn.textContent = '⏳ Генерую код...';
    try {
      const code = await generateInviteCode(state.familyId, state.user?.uid);
      openBottomSheet({
        title: '📨 Запрошення до родини',
        content: `
          <div style="text-align:center;padding:16px 0">
            <div style="font-size:13px;color:var(--c-text-2);margin-bottom:12px">Поділися цим кодом з тим, кого хочеш додати до родини</div>
            <div style="font-size:36px;font-weight:700;letter-spacing:8px;color:var(--c-accent);margin:16px 0;padding:16px;background:var(--c-accent-soft);border-radius:12px">${esc(code)}</div>
            <div style="font-size:12px;color:var(--c-text-3);margin-bottom:16px">Код дійсний 7 днів</div>
            <p style="font-size:13px;color:var(--c-text-2)">Людина вводить цей код під час реєстрації або в налаштуваннях → "Приєднатись до родини"</p>
          </div>
        `,
        footer: `
          <button class="btn-primary flex-1" onclick="navigator.clipboard?.writeText('${esc(code)}');this.textContent='✅ Скопійовано!'">
            <i class="ti ti-copy"></i> Скопіювати код
          </button>
        `,
      });
    } catch (e) {
      showToast('Помилка: ' + e.message, 'error');
    }
    btn.disabled = false;
    btn.innerHTML = '<i class="ti ti-user-plus"></i> Запросити члена родини';
  });

  // Sync
  el.querySelector('#sync-now-btn')?.addEventListener('click', async () => {
    showToast('🔄 Синхронізую з Firebase...');
    try {
      await import('./api.js').then(m => m.syncSettingsToSheet());
      if (window.fullSync) await window.fullSync();
      showToast('✅ Синхронізовано з Firebase!');
      renderSettingsPage();
    } catch (e) {
      showToast('Помилка: ' + e.message, 'error');
    }
  });

  // Diagnostics
  el.querySelector('#diag-btn')?.addEventListener('click', async () => {
    const { openBottomSheet } = await import('./modals.js');
    const { apiGet, pingBackend } = await import('./api.js');

    const results = [];

    const modalId = openBottomSheet({
      title: '🔍 Діагностика Firebase',
      content: `<div id="diag-content"><div class="diag-list"><div class="diag-item"><i class="ti ti-loader"></i> Запускаю...</div></div></div>`,
      footer: '<button class="btn-primary flex-1" data-modal-close>Закрити</button>',
    });

    function update(items) {
      const c = document.getElementById('diag-content');
      if (!c) return;
      c.innerHTML = `<div class="diag-list">${items.map(it => {
        const icon = it.status === 'ok' ? 'ti-check' : it.status === 'fail' ? 'ti-x' : 'ti-loader';
        const cls = it.status === 'ok' ? 'ok' : it.status === 'fail' ? 'fail' : 'pending';
        return `<div class="diag-item ${cls}">
          <i class="ti ${icon}"></i>
          <div>
            <div class="diag-item-name">${esc(it.name)}</div>
            ${it.detail ? `<div class="diag-item-detail">${esc(it.detail)}</div>` : ''}
          </div>
        </div>`;
      }).join('')}</div>`;
    }

    const fbOk = typeof firebase !== 'undefined' && firebase.app();
    results.push({ name: 'Firebase SDK', status: fbOk ? 'ok' : 'fail', detail: fbOk ? 'Ініціалізовано' : 'НЕ завантажено' });
    update(results);

    const user = firebase.auth().currentUser;
    results.push({ name: 'Авторизація', status: user ? 'ok' : 'fail', detail: user ? user.email : 'Не залогінений' });
    update(results);

    results.push({ name: 'Firestore', status: 'pending' });
    update(results);
    try {
      const ok = await pingBackend();
      results[results.length - 1].status = ok ? 'ok' : 'fail';
      results[results.length - 1].detail = ok ? 'Доступний' : 'Недоступний';
    } catch (e) {
      results[results.length - 1].status = 'fail';
      results[results.length - 1].detail = e.message;
    }
    update(results);

    results.push({ name: 'Налаштування', status: 'pending' });
    update(results);
    try {
      const s = await apiGet('settings');
      const cardsE = (s.cardsEvgen && Array.isArray(s.cardsEvgen)) ? s.cardsEvgen.length : 0;
      const cardsM = (s.cardsMarina && Array.isArray(s.cardsMarina)) ? s.cardsMarina.length : 0;
      results[results.length - 1].status = 'ok';
      results[results.length - 1].detail = `Євген: ${cardsE} карт, Марина: ${cardsM} карт`;
    } catch (e) {
      results[results.length - 1].status = 'fail';
      results[results.length - 1].detail = e.message;
    }
    update(results);

    results.push({ name: 'Запис в Firestore', status: 'pending' });
    update(results);
    try {
      const { syncSettingsToSheet } = await import('./api.js');
      await syncSettingsToSheet();
      results[results.length - 1].status = 'ok';
      results[results.length - 1].detail = 'Налаштування збережено';
    } catch (e) {
      results[results.length - 1].status = 'fail';
      results[results.length - 1].detail = e.message;
    }
    update(results);

    let lsSize = 0;
    try {
      for (let k in localStorage) {
        if (localStorage.hasOwnProperty(k)) lsSize += (localStorage[k].length + k.length) * 2;
      }
      results.push({ name: 'localStorage', status: 'ok', detail: `${(lsSize / 1024).toFixed(1)} KB` });
    } catch (e) {
      results.push({ name: 'localStorage', status: 'fail', detail: e.message });
    }
    update(results);
  });

  // Default wallet
  el.querySelectorAll('.dw-select').forEach(sel => {
    sel.addEventListener('change', () => {
      setDefaultWallet(sel.dataset.dwMember, sel.value || null);
      showToast('✅ Збережено');
    });
  });

  // Telegram prefs
  el.querySelector('#save-tg-prefs-btn')?.addEventListener('click', () => {
    setTelegramPrefs({
      paymentReminders: el.querySelector('#tg-payments')?.checked ?? true,
      limitAlerts:      el.querySelector('#tg-limits')?.checked  ?? true,
      dailySummary:     el.querySelector('#tg-daily')?.checked   ?? true,
      summaryHour:      parseInt(el.querySelector('#tg-hour')?.value || '19'),
    });
    showToast('✅ Telegram налаштування збережено');
  });

  // Lock toggle
  const lockToggle = el.querySelector('#lock-toggle');
  if (lockToggle) {
    lockToggle.addEventListener('change', async () => {
      if (lockToggle.checked) {
        openPinSetupSheet(() => renderSettingsPage());
      } else {
        const ok = await confirmModal('Вимкнути блокування?', { okText: 'Вимкнути', danger: true });
        if (ok) { disableLock(); renderSettingsPage(); }
        else lockToggle.checked = true;
      }
    });
  }

  el.querySelector('#lock-change-pin-btn')?.addEventListener('click', () => {
    openPinSetupSheet(() => renderSettingsPage(), true);
  });

  const biomBtn = el.querySelector('#lock-biom-btn');
  const biomStatus = el.querySelector('#lock-biom-status');
  if (biomBtn && biomStatus) {
    isBiometricAvailable().then(available => {
      biomStatus.textContent = available ? 'Доступна на цьому пристрої' : 'Недоступна на цьому пристрої';
      if (!available) biomBtn.disabled = true;
    });
    biomBtn.addEventListener('click', async () => {
      try {
        await setupLock({ useBiometric: true });
        showToast('✅ Біометрія налаштована');
        renderSettingsPage();
      } catch (e) {
        showToast('Помилка: ' + e.message, 'error');
      }
    });
  }

  // Budget delete/edit
  el.querySelectorAll('[data-budget-del]').forEach(btn => {
    btn.addEventListener('click', async () => {
      const type = btn.dataset.budgetDel;
      const key = btn.dataset.key;
      const ok = await confirmModal(`Видалити ${type === 'plan' ? 'план' : 'ліміт'} для «${key}»?`, { danger: true, okText: 'Видалити' });
      if (!ok) return;
      const d = type === 'plan' ? getSpendingPlan() : getCategoryLimits();
      delete d[key];
      if (type === 'plan') setSpendingPlan(d); else setCategoryLimits(d);
      renderSettingsPage();
    });
  });

  el.querySelectorAll('[data-budget-edit]').forEach(btn => {
    btn.addEventListener('click', () => {
      openEditBudgetItem(btn.dataset.budgetEdit, btn.dataset.key, parseFloat(btn.dataset.amount));
    });
  });

  el.querySelector('#add-plan-btn')?.addEventListener('click', () => openAddBudgetItem('plan'));
  el.querySelector('#add-limits-btn')?.addEventListener('click', () => openAddBudgetItem('limits'));

  // Category buttons
  el.querySelector('#add-exp-cat-btn')?.addEventListener('click', () => openCatEditor('exp'));
  el.querySelector('#add-inc-cat-btn')?.addEventListener('click', () => openCatEditor('inc'));
  el.querySelector('#add-wallet-type-btn')?.addEventListener('click', () => openTypeEditor());

  // Wallet edit
  el.querySelectorAll('[data-wallet-owner]').forEach(chip => {
    chip.addEventListener('click', () => {
      const owner = chip.dataset.walletOwner;
      const idx = parseInt(chip.dataset.walletIdx);
      import('./wallets.js').then(m => m.openEditWallet(owner, idx));
    });
  });

  el.querySelector('#add-wallet-btn')?.addEventListener('click', () => {
    import('./wallets.js').then(m => m.openCreateWallet());
  });

  // Navigation
  el.querySelectorAll('[data-go]').forEach(b => {
    b.addEventListener('click', () => {
      import('./main.js').then(m => m.navigateTo(b.dataset.go));
    });
  });
}

// ── Image compression helper ──────────────────────────────────
function compressImage(file, maxSize = 256) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = reject;
    reader.onload = e => {
      const img = new Image();
      img.onerror = reject;
      img.onload = () => {
        const canvas = document.createElement('canvas');
        const scale = Math.min(maxSize / img.width, maxSize / img.height, 1);
        canvas.width  = Math.round(img.width  * scale);
        canvas.height = Math.round(img.height * scale);
        canvas.getContext('2d').drawImage(img, 0, 0, canvas.width, canvas.height);
        resolve(canvas.toDataURL('image/jpeg', 0.82));
      };
      img.src = e.target.result;
    };
    reader.readAsDataURL(file);
  });
}
