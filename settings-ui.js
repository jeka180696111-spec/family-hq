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
} from './storage.js';
import { syncSettingsToSheet, pingBackend, generateInviteCode } from './api.js';
import { applyTheme, toggleTheme } from './theme.js';
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
  return `
    <div class="page-inner">
      <div class="page-head">
        <h1 class="page-title">Налаштування</h1>
      </div>

      <!-- Group 1: Personal -->
      <div class="settings-menu-group">
        <button class="settings-menu-item" data-sub="profile">
          <div class="settings-menu-icon"><i class="ti ti-user"></i></div>
          <div class="settings-menu-label">Профіль</div>
          <i class="ti ti-chevron-right settings-menu-arrow"></i>
        </button>
        <button class="settings-menu-item" data-sub="family">
          <div class="settings-menu-icon"><i class="ti ti-users"></i></div>
          <div class="settings-menu-label">Родина</div>
          <i class="ti ti-chevron-right settings-menu-arrow"></i>
        </button>
        <button class="settings-menu-item" data-sub="appearance">
          <div class="settings-menu-icon"><i class="ti ti-palette"></i></div>
          <div class="settings-menu-label">Зовнішній вигляд</div>
          <i class="ti ti-chevron-right settings-menu-arrow"></i>
        </button>
        <button class="settings-menu-item" data-sub="security">
          <div class="settings-menu-icon"><i class="ti ti-lock"></i></div>
          <div class="settings-menu-label">Безпека</div>
          <i class="ti ti-chevron-right settings-menu-arrow"></i>
        </button>
      </div>

      <!-- Group 2: Finance -->
      <div class="settings-menu-group">
        <button class="settings-menu-item" data-sub="default-wallet">
          <div class="settings-menu-icon"><i class="ti ti-wallet"></i></div>
          <div class="settings-menu-label">Кошельок за замовчуванням</div>
          <i class="ti ti-chevron-right settings-menu-arrow"></i>
        </button>
        <button class="settings-menu-item" data-sub="telegram">
          <div class="settings-menu-icon"><i class="ti ti-brand-telegram"></i></div>
          <div class="settings-menu-label">Telegram сповіщення</div>
          <i class="ti ti-chevron-right settings-menu-arrow"></i>
        </button>
        <button class="settings-menu-item" data-sub="sync">
          <div class="settings-menu-icon"><i class="ti ti-refresh"></i></div>
          <div class="settings-menu-label">Синхронізація</div>
          <i class="ti ti-chevron-right settings-menu-arrow"></i>
        </button>
      </div>

      <!-- Group 3: Data -->
      <div class="settings-menu-group">
        <button class="settings-menu-item" data-sub="plan">
          <div class="settings-menu-icon"><i class="ti ti-list-check"></i></div>
          <div class="settings-menu-label">План витрат</div>
          <i class="ti ti-chevron-right settings-menu-arrow"></i>
        </button>
        <button class="settings-menu-item" data-sub="limits">
          <div class="settings-menu-icon"><i class="ti ti-gauge"></i></div>
          <div class="settings-menu-label">Ліміти витрат</div>
          <i class="ti ti-chevron-right settings-menu-arrow"></i>
        </button>
        <button class="settings-menu-item" data-sub="exp-cats">
          <div class="settings-menu-icon"><i class="ti ti-arrow-up-circle"></i></div>
          <div class="settings-menu-label">Категорії витрат</div>
          <i class="ti ti-chevron-right settings-menu-arrow"></i>
        </button>
        <button class="settings-menu-item" data-sub="inc-cats">
          <div class="settings-menu-icon"><i class="ti ti-arrow-down-circle"></i></div>
          <div class="settings-menu-label">Категорії доходів</div>
          <i class="ti ti-chevron-right settings-menu-arrow"></i>
        </button>
        <button class="settings-menu-item" data-sub="wallet-types">
          <div class="settings-menu-icon"><i class="ti ti-credit-card"></i></div>
          <div class="settings-menu-label">Типи рахунків</div>
          <i class="ti ti-chevron-right settings-menu-arrow"></i>
        </button>
        <button class="settings-menu-item" data-sub="wallets">
          <div class="settings-menu-icon"><i class="ti ti-building-bank"></i></div>
          <div class="settings-menu-label">Кошельки</div>
          <i class="ti ti-chevron-right settings-menu-arrow"></i>
        </button>
      </div>

      <!-- Divider -->
      <div style="height:4px"></div>

      <!-- Group 4: Legal -->
      <div class="settings-menu-group">
        <button class="settings-menu-item" data-sub="privacy">
          <div class="settings-menu-icon"><i class="ti ti-shield"></i></div>
          <div class="settings-menu-label">Політика конфіденційності</div>
          <i class="ti ti-chevron-right settings-menu-arrow"></i>
        </button>
        <button class="settings-menu-item" data-sub="terms">
          <div class="settings-menu-icon"><i class="ti ti-file-text"></i></div>
          <div class="settings-menu-label">Угода користувача</div>
          <i class="ti ti-chevron-right settings-menu-arrow"></i>
        </button>
      </div>

      <div class="settings-footer">
        <div>Сімейний бюджет v3.0</div>
      </div>
    </div>
  `;
}

// ── Sub-page content builders ─────────────────────────────────
const SUB_PAGE_TITLES = {
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
  privacy:        'Політика конфіденційності',
  terms:          'Угода користувача',
};

function renderSubPageBody(key) {
  const theme = getTheme();
  const family = getFamilyName();
  const profiles = getProfiles();
  const lastSync = localStorage.getItem('budget_last_sync');

  switch (key) {
    case 'profile':
      return `
        <div class="settings-card">
          ${state.user ? `
            <div class="settings-row">
              <div class="settings-row-icon"><i class="ti ti-user"></i></div>
              <div class="settings-row-info">
                <div class="settings-row-name">${esc(state.user.name)}</div>
                <div class="settings-row-sub">${esc(state.user.email)}</div>
              </div>
              <button class="btn-ghost-sm" id="signout-btn">Вихід</button>
            </div>
          ` : ''}
          <div class="settings-row">
            <div class="settings-row-icon"><i class="ti ti-home"></i></div>
            <div class="settings-row-info">
              <div class="settings-row-name">Назва родини</div>
              <input class="settings-row-input" id="family-name-input" value="${esc(family)}" placeholder="Родина...">
            </div>
            <button class="btn-ghost-sm" id="save-family-btn">Зберегти</button>
          </div>
        </div>
      `;

    case 'family':
      return `
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

    case 'appearance':
      return `
        <div class="settings-card">
          <div class="settings-row">
            <div class="settings-row-icon"><i class="ti ti-${theme === 'dark' ? 'moon' : 'sun'}"></i></div>
            <div class="settings-row-info">
              <div class="settings-row-name">Тема</div>
              <div class="settings-row-sub">${theme === 'dark' ? 'Темна' : 'Світла'}</div>
            </div>
            <div class="theme-switch">
              <button class="theme-btn ${theme === 'light' ? 'active' : ''}" data-theme="light"><i class="ti ti-sun"></i></button>
              <button class="theme-btn ${theme === 'dark' ? 'active' : ''}" data-theme="dark"><i class="ti ti-moon"></i></button>
            </div>
          </div>
        </div>
      `;

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
        <div class="settings-card">
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

    case 'privacy':
      return `
        <div class="settings-card">
          <div style="font-size:14px;line-height:1.6;color:var(--c-text-2);padding:4px 0">
            Ми збираємо мінімум даних необхідних для роботи додатку: Google акаунт (ім'я, email), фінансові операції що ви вводите вручну. Дані зберігаються у Firebase (Google) і доступні тільки вам і членам вашої родини. Ми не продаємо і не передаємо ваші дані третім особам. Ви можете видалити свій акаунт і всі пов'язані дані у будь-який час через підтримку.
          </div>
        </div>
      `;

    case 'terms':
      return `
        <div class="settings-card">
          <div style="font-size:14px;line-height:1.6;color:var(--c-text-2);padding:4px 0">
            Використовуючи додаток ви погоджуєтесь з умовами використання. Додаток надається «як є». Ми не несемо відповідальності за фінансові рішення прийняті на основі даних в додатку. Заборонено використовувати додаток для незаконних цілей. Ми залишаємо за собою право змінювати функціонал додатку.
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

// ── Main render function ──────────────────────────────────────
export function renderSettingsPage() {
  const el = document.getElementById('page-settings');
  if (!el) return;

  el.innerHTML = settingsSubPage ? renderSubPage(settingsSubPage) : renderMainMenu();

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

  // Menu items
  el.querySelectorAll('.settings-menu-item').forEach(b => {
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
