// ═══════════════════════════════════════════════════════════════
// SETTINGS UI — сторінка налаштувань
// ═══════════════════════════════════════════════════════════════

import { FAMILY_MEMBERS, state } from './config.js';
import {
  getExpCats, setExpCats, getIncCats, setIncCats,
  getWalletTypes, setWalletTypes,
  getFamilyName, setFamilyName,
  getProfiles, setProfiles,
  getTheme, getScriptUrl, setScriptUrl,
} from './storage.js';
import { syncSettingsToSheet, pingBackend } from './api.js';
import { applyTheme, toggleTheme } from './theme.js';
import { esc, showToast, uid } from './utils.js';
import { openIconPicker } from './icon-picker.js';
import { openBottomSheet, closeModal, confirmModal, promptModal } from './modals.js';
import { signOut } from './auth.js';

export function renderSettingsPage() {
  const el = document.getElementById('page-settings');
  if (!el) return;

  const theme = getTheme();
  const family = getFamilyName();
  const profiles = getProfiles();
  const url = getScriptUrl();
  const lastSync = localStorage.getItem('budget_last_sync');

  el.innerHTML = `
    <div class="page-inner">
      <div class="page-head">
        <h1 class="page-title">Налаштування</h1>
      </div>

      <!-- Профіль -->
      <div class="settings-section">
        <div class="settings-label">Профіль</div>
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
      </div>

      <!-- Тема -->
      <div class="settings-section">
        <div class="settings-label">Зовнішній вигляд</div>
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
      </div>

      <!-- Sync -->
      <div class="settings-section">
        <div class="settings-label">Google Sheets</div>
        <div class="settings-card">
          <div class="settings-row">
            <div class="settings-row-icon green"><i class="ti ti-brand-google"></i></div>
            <div class="settings-row-info">
              <div class="settings-row-name">Синхронізація</div>
              <div class="settings-row-sub" id="sync-status">${lastSync ? 'Остання: ' + new Date(lastSync).toLocaleString('uk-UA') : 'Не виконувалась'}</div>
            </div>
            <button class="btn-ghost-sm" id="sync-now-btn"><i class="ti ti-refresh"></i> Sync</button>
          </div>
          <div class="settings-row">
            <div class="settings-row-icon"><i class="ti ti-link"></i></div>
            <div class="settings-row-info">
              <div class="settings-row-name">URL скрипта</div>
              <div class="settings-row-sub url-preview">${url ? esc(url.substring(0, 60)) + '...' : 'Не налаштовано'}</div>
            </div>
            <button class="btn-ghost-sm" id="change-url-btn">Змінити</button>
          </div>
        </div>
      </div>

      <!-- Категорії витрат -->
      <div class="settings-section">
        <div class="settings-label">Категорії витрат</div>
        <div class="settings-card">
          <div class="cat-grid" id="exp-cats-grid"></div>
          <button class="settings-add-btn" id="add-exp-cat-btn"><i class="ti ti-plus"></i> Додати категорію</button>
        </div>
      </div>

      <!-- Категорії доходів -->
      <div class="settings-section">
        <div class="settings-label">Категорії доходів</div>
        <div class="settings-card">
          <div class="cat-grid" id="inc-cats-grid"></div>
          <button class="settings-add-btn" id="add-inc-cat-btn"><i class="ti ti-plus"></i> Додати категорію</button>
        </div>
      </div>

      <!-- Типи рахунків -->
      <div class="settings-section">
        <div class="settings-label">Типи рахунків</div>
        <div class="settings-card">
          <div class="settings-hint">Свої категорії для кошельків. Наприклад: «Криптогаманець», «Депозит», «Валюта в євро». Клік для редагування.</div>
          <div class="cat-grid" id="wallet-types-grid"></div>
          <button class="settings-add-btn" id="add-wallet-type-btn"><i class="ti ti-plus"></i> Додати тип</button>
        </div>
      </div>

      <!-- Кошельки -->
      <div class="settings-section">
        <div class="settings-label">Кошельки</div>
        <div class="settings-card">
          <div class="settings-hint">Усі кошельки можна переглянути та керувати на сторінці «Кошельки».</div>
          <button class="settings-add-btn" data-go="wallets"><i class="ti ti-wallet"></i> Перейти до кошельків</button>
        </div>
      </div>

      <!-- Інфо -->
      <div class="settings-footer">
        <div>Сімейний бюджет v3.0</div>
      </div>
    </div>
  `;

  renderCatGrid('exp-cats-grid', getExpCats(), 'exp');
  renderCatGrid('inc-cats-grid', getIncCats(), 'inc');
  renderTypesGrid('wallet-types-grid', getWalletTypes());

  bindHandlers(el);
}

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

// ── Редактор категорії ──────────────────────────────────────
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

// ── Редактор типу рахунку ───────────────────────────────────
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
        // Унікальність
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

// ── Слухачі ─────────────────────────────────────────────────
function bindHandlers(el) {
  // Тема
  el.querySelectorAll('[data-theme]').forEach(b => {
    b.addEventListener('click', () => {
      applyTheme(b.dataset.theme);
      renderSettingsPage();
    });
  });

  // Сім'я
  el.querySelector('#save-family-btn')?.addEventListener('click', () => {
    const v = el.querySelector('#family-name-input').value.trim();
    if (!v) return;
    setFamilyName(v);
    syncSettingsToSheet();
    const sb = document.getElementById('sb-family-name');
    if (sb) sb.textContent = v;
    showToast('✅ Збережено');
  });

  // Вихід
  el.querySelector('#signout-btn')?.addEventListener('click', async () => {
    const ok = await confirmModal('Точно вийти?', { danger: true, okText: 'Вийти' });
    if (ok) signOut();
  });

  // Sync
  el.querySelector('#sync-now-btn')?.addEventListener('click', async () => {
    showToast('🔄 Перевіряю...');
    const ok = await pingBackend();
    if (!ok) { showToast('Сервер не відповідає', 'error'); return; }
    if (window.fullSync) await window.fullSync();
    showToast('✅ Синхронізовано');
    renderSettingsPage();
  });

  // URL
  el.querySelector('#change-url-btn')?.addEventListener('click', async () => {
    const newUrl = await promptModal('URL скрипта', getScriptUrl(), { placeholder: 'https://script.google.com/...' });
    if (newUrl) {
      setScriptUrl(newUrl);
      state.scriptUrl = newUrl;
      showToast('✅ URL змінено');
      renderSettingsPage();
    }
  });

  // Додати
  el.querySelector('#add-exp-cat-btn')?.addEventListener('click', () => openCatEditor('exp'));
  el.querySelector('#add-inc-cat-btn')?.addEventListener('click', () => openCatEditor('inc'));
  el.querySelector('#add-wallet-type-btn')?.addEventListener('click', () => openTypeEditor());

  // Навігація
  el.querySelectorAll('[data-go]').forEach(b => {
    b.addEventListener('click', () => {
      import('./main.js').then(m => m.navigateTo(b.dataset.go));
    });
  });
}
