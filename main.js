// ═══════════════════════════════════════════════════════════════
// MAIN — точка входу, ініціалізація
// ═══════════════════════════════════════════════════════════════

import { state, FAMILY_MEMBERS, APP_CONFIG } from './config.js';
import { log, showToast, setText, esc } from './utils.js';
import {
  getFamilyName, getProfiles, getTheme, getScriptUrl,
  getExpCats, getIncCats, getCards, getWalletTypes,
  setExpCats, setIncCats, setCards, setWalletTypes, setProfiles, setFamilyName,
  isDirty, clearDirty,
  getViewAsMember, setViewAsMember,
} from './storage.js';
import { initTheme, toggleTheme } from './theme.js';
import { initGoogleAuth, restoreSession, whoAmI } from './auth.js';
import { apiGet, syncSettingsToSheet } from './api.js';
import { initFAB } from './fab.js';
import { renderDashboard, loadDashboard } from './dashboard.js';
import { renderWalletsPage } from './wallets.js';
import { renderOperationsPage, loadOperations } from './operations-list.js';
import { renderAnalyticsPage, loadAnalytics } from './analytics.js';
import { renderReservePage, loadReserve } from './reserve.js';
import { renderGoalsPage, loadGoals } from './goals.js';
import { renderSettingsPage } from './settings-ui.js';

const PAGE_TITLES = {
  dashboard: 'Головна',
  wallets: 'Кошельки',
  operations: 'Операції',
  analytics: 'Аналіз',
  reserve: 'Накопичення',
  goals: 'Цілі',
  settings: 'Налаштування',
};

// ── Навігація ───────────────────────────────────────────────
export function navigateTo(page) {
  if (!PAGE_TITLES[page]) page = 'dashboard';
  state.currentPage = page;

  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  const pageEl = document.getElementById('page-' + page);
  if (pageEl) pageEl.classList.add('active');

  document.title = PAGE_TITLES[page] + ' · Сімейний бюджет';
  setText('topbar-title', PAGE_TITLES[page]);

  document.querySelectorAll('[data-nav-page]').forEach(a => {
    a.classList.toggle('active', a.dataset.navPage === page);
  });

  switch (page) {
    case 'dashboard':  renderDashboard(); break;
    case 'wallets':    renderWalletsPage(); break;
    case 'operations': renderOperationsPage(); break;
    case 'analytics':  renderAnalyticsPage(); break;
    case 'reserve':    renderReservePage(); break;
    case 'goals':      renderGoalsPage(); break;
    case 'settings':   renderSettingsPage(); break;
  }

  closeSidebar();
  loadPageData(page);
}

function loadPageData(page) {
  switch (page) {
    case 'dashboard':
      if (!state.dashboard) loadDashboard();
      break;
    case 'operations':
      if (!state.operations.length) loadOperations();
      break;
    case 'analytics':
      loadAnalytics(); // завжди перезавантажуємо (з урахуванням обраного періоду)
      break;
    case 'reserve':
      if (!state.reserve) loadReserve();
      break;
    case 'goals':
      if (!state.goals.length) loadGoals();
      break;
  }
}

// ── Повна синхронізація ─────────────────────────────────────
async function fullSync() {
  try {
    // 1. Налаштування з сервера (з повагою до dirty-флагів)
    const settings = await apiGet('settings');
    applyServerSettings(settings);

    // 2. Дашборд і операції паралельно
    await Promise.all([
      loadDashboard(),
      loadOperations(),
    ]);

    log('full sync OK');
  } catch (e) {
    log('full sync error:', e.message);
  }
}

window.fullSync = fullSync;

// ── Застосовуємо налаштування з сервера ─────────────────────
// КРИТИЧНО: не перезаписуємо локальні зміни які ще не доїхали до сервера!
function applyServerSettings(s) {
  if (!s) return;

  // familyName
  if (s.familyName && !isDirty(APP_CONFIG.FAMILY_KEY)) {
    if (s.familyName !== getFamilyName()) {
      setFamilyName(s.familyName);
      clearDirty(APP_CONFIG.FAMILY_KEY); // тільки що ми ж і встановили
      setText('sb-family-name', s.familyName);
    }
  }

  // expCats
  if (Array.isArray(s.expCats) && !isDirty(APP_CONFIG.EXP_CATS_KEY)) {
    setExpCats(s.expCats);
    clearDirty(APP_CONFIG.EXP_CATS_KEY);
  }
  // incCats
  if (Array.isArray(s.incCats) && !isDirty(APP_CONFIG.INC_CATS_KEY)) {
    setIncCats(s.incCats);
    clearDirty(APP_CONFIG.INC_CATS_KEY);
  }
  // cardsEvgen
  const keyE = APP_CONFIG.CARDS_KEY + '_Євген';
  if (Array.isArray(s.cardsEvgen) && !isDirty(keyE)) {
    setCards(s.cardsEvgen, 'Євген');
    clearDirty(keyE);
  }
  // cardsMarina
  const keyM = APP_CONFIG.CARDS_KEY + '_Марина';
  if (Array.isArray(s.cardsMarina) && !isDirty(keyM)) {
    setCards(s.cardsMarina, 'Марина');
    clearDirty(keyM);
  }
  // walletTypes
  if (Array.isArray(s.walletTypes) && s.walletTypes.length && !isDirty(APP_CONFIG.WALLET_TYPES_KEY)) {
    setWalletTypes(s.walletTypes);
    clearDirty(APP_CONFIG.WALLET_TYPES_KEY);
  }
  // profiles
  if (s.profiles && typeof s.profiles === 'object' && !isDirty(APP_CONFIG.PROFILES_KEY)) {
    setProfiles(s.profiles);
    clearDirty(APP_CONFIG.PROFILES_KEY);
  }
}

// ── Sidebar (mobile) ────────────────────────────────────────
function openSidebar() {
  document.body.classList.add('sidebar-open');
}
function closeSidebar() {
  document.body.classList.remove('sidebar-open');
}

// ── Рендер sidebar ──────────────────────────────────────────
function renderSidebar() {
  const sb = document.getElementById('sidebar');
  if (!sb) return;

  const family = getFamilyName();
  const profiles = getProfiles();
  const me = whoAmI() || FAMILY_MEMBERS[0];
  const myProfile = profiles[me] || { name: me };

  sb.innerHTML = `
    <div class="sb-header">
      <div class="sb-logo">
        <div class="sb-logo-icon">
          <i class="ti ti-home-2"></i>
        </div>
        <div class="sb-logo-info">
          <div class="sb-logo-name" id="sb-family-name">${family}</div>
          <div class="sb-logo-sub">Сімейний бюджет</div>
        </div>
      </div>
      <div class="sb-user">
        <div class="sb-user-avatar" style="background:var(--c-accent-soft);color:var(--c-accent)">
          ${state.user?.avatar ? `<img src="${state.user.avatar}" alt="">` : (myProfile.name || me)[0]}
        </div>
        <div class="sb-user-info">
          <div class="sb-user-name">${myProfile.name || me}</div>
          <div class="sb-user-role">Активний</div>
        </div>
      </div>
    </div>

    <nav class="sb-nav">
      <div class="sb-section-label">Головне</div>
      <a class="sb-item" data-nav-page="dashboard"><i class="ti ti-layout-dashboard"></i><span>Дашборд</span></a>
      <a class="sb-item" data-nav-page="wallets"><i class="ti ti-wallet"></i><span>Кошельки</span></a>
      <a class="sb-item" data-nav-page="operations"><i class="ti ti-list"></i><span>Операції</span></a>
      <a class="sb-item" data-nav-page="analytics"><i class="ti ti-chart-pie"></i><span>Аналіз</span></a>

      <div class="sb-section-label">Фінанси</div>
      <a class="sb-item" data-nav-page="reserve"><i class="ti ti-coins"></i><span>Накопичення</span></a>
      <a class="sb-item" data-nav-page="goals"><i class="ti ti-target"></i><span>Цілі</span></a>

      <div class="sb-section-label">Система</div>
      <a class="sb-item" data-nav-page="settings"><i class="ti ti-settings"></i><span>Налаштування</span></a>
    </nav>

    <div class="sb-footer">
      <div class="sb-fx" id="sb-fx">us — · eu —</div>
    </div>
  `;

  sb.querySelectorAll('[data-nav-page]').forEach(a => {
    a.addEventListener('click', (e) => {
      e.preventDefault();
      navigateTo(a.dataset.navPage);
    });
  });
}

// ── Рендер topbar ───────────────────────────────────────────
function renderTopbar() {
  const tb = document.getElementById('topbar');
  if (!tb) return;

  const viewAs = getViewAsMember();
  const profiles = getProfiles();
  const me = whoAmI() || FAMILY_MEMBERS[0];
  const activeView = viewAs || me; // що зараз показуємо
  const activeProf = profiles[activeView] || { name: activeView };

  tb.innerHTML = `
    <button class="topbar-menu" id="topbar-menu"><i class="ti ti-menu-2"></i></button>
    <div class="topbar-title" id="topbar-title">Головна</div>

    <button class="topbar-viewas-btn" id="topbar-viewas">
      <div class="topbar-viewas-avatar">${(activeProf.name || activeView)[0]}</div>
      <span class="topbar-viewas-name">${esc(activeProf.name || activeView)}</span>
      <i class="ti ti-chevron-down"></i>
    </button>

    <button class="topbar-action" id="topbar-theme"><i class="ti ti-${getTheme() === 'dark' ? 'sun' : 'moon'}"></i></button>
  `;
  document.getElementById('topbar-menu').addEventListener('click', openSidebar);
  document.getElementById('topbar-theme').addEventListener('click', () => {
    toggleTheme();
    renderTopbar();
  });
  document.getElementById('topbar-viewas').addEventListener('click', (e) => {
    e.stopPropagation();
    openViewAsMenu(e.currentTarget);
  });
}

// ── Меню вибору "Дивлюсь як" ────────────────────────────────
function openViewAsMenu(anchor) {
  // Закриваємо попереднє якщо є
  const old = document.getElementById('viewas-menu');
  if (old) { old.remove(); return; }

  const profiles = getProfiles();
  const viewAs = getViewAsMember();
  const me = whoAmI() || FAMILY_MEMBERS[0];

  const menu = document.createElement('div');
  menu.id = 'viewas-menu';
  menu.className = 'viewas-menu';

  const items = [
    { key: 'all', name: 'Усі (загальний)', avatar: '👥', desc: 'Дані всієї родини' },
    ...FAMILY_MEMBERS.map(m => ({
      key: m,
      name: profiles[m]?.name || m,
      avatar: (profiles[m]?.name || m)[0],
      desc: m === me ? 'Я' : '',
    })),
  ];

  menu.innerHTML = items.map(it => {
    const active = (it.key === 'all' && !viewAs) || (it.key === viewAs);
    return `
      <button class="viewas-item ${active ? 'active' : ''}" data-viewas="${esc(it.key)}">
        <div class="viewas-avatar">${esc(it.avatar)}</div>
        <div class="viewas-info">
          <div class="viewas-name">${esc(it.name)}</div>
          ${it.desc ? `<div class="viewas-desc">${esc(it.desc)}</div>` : ''}
        </div>
        ${active ? '<i class="ti ti-check"></i>' : ''}
      </button>
    `;
  }).join('');

  document.body.appendChild(menu);

  // Позиціонуємо біля кнопки
  const rect = anchor.getBoundingClientRect();
  menu.style.position = 'fixed';
  menu.style.top = (rect.bottom + 8) + 'px';
  menu.style.right = (window.innerWidth - rect.right) + 'px';
  menu.style.zIndex = '999';

  // Слухачі
  menu.querySelectorAll('[data-viewas]').forEach(b => {
    b.addEventListener('click', () => {
      const val = b.dataset.viewas;
      setViewAsMember(val === 'all' ? null : val);
      menu.remove();
      renderTopbar();
      // Перерендер поточної сторінки
      navigateTo(state.currentPage);
    });
  });

  // Закриття по кліку поза
  setTimeout(() => {
    const onDoc = (e) => {
      if (!menu.contains(e.target)) {
        menu.remove();
        document.removeEventListener('click', onDoc);
      }
    };
    document.addEventListener('click', onDoc);
  }, 50);
}

// ── Рендер bottom-nav (mobile) ──────────────────────────────
function renderBottomNav() {
  const bn = document.getElementById('bottom-nav');
  if (!bn) return;
  bn.innerHTML = `
    <a class="bn-item" data-nav-page="dashboard"><i class="ti ti-layout-dashboard"></i><span>Дашборд</span></a>
    <a class="bn-item" data-nav-page="wallets"><i class="ti ti-wallet"></i><span>Кошельки</span></a>
    <button class="bn-fab" id="fab-main"><i class="ti ti-plus"></i></button>
    <a class="bn-item" data-nav-page="operations"><i class="ti ti-list"></i><span>Операції</span></a>
    <a class="bn-item" data-nav-page="settings"><i class="ti ti-settings"></i><span>Ще</span></a>
  `;
  bn.querySelectorAll('[data-nav-page]').forEach(a => {
    a.addEventListener('click', (e) => {
      e.preventDefault();
      navigateTo(a.dataset.navPage);
    });
  });
}

async function refreshFx() {
  try {
    const fx = await apiGet('fx');
    state.fx = fx;
    const el = document.getElementById('sb-fx');
    if (el && fx?.USD && fx?.EUR) {
      el.textContent = `us ${fx.USD.mid.toFixed(2)} ₴ · eu ${fx.EUR.mid.toFixed(2)} ₴`;
    }
  } catch (e) { /* ignore */ }
}

function showAuthScreen() {
  const auth = document.getElementById('auth-screen');
  const main = document.getElementById('app-main');
  if (auth) auth.style.display = 'flex';
  if (main) main.style.display = 'none';
  initGoogleAuth(() => {
    if (auth) auth.style.display = 'none';
    if (main) main.style.display = '';
    bootApp();
  });
}

async function bootApp() {
  state.scriptUrl = getScriptUrl();

  renderSidebar();
  renderTopbar();
  renderBottomNav();
  initFAB();

  const overlay = document.getElementById('sidebar-overlay');
  if (overlay) overlay.addEventListener('click', closeSidebar);

  navigateTo('dashboard');
  refreshFx();

  setTimeout(() => fullSync(), 100);

  setInterval(() => {
    if (state.currentPage === 'dashboard') loadDashboard();
  }, 30000);
}

document.addEventListener('DOMContentLoaded', () => {
  initTheme();
  if (restoreSession()) {
    bootApp();
  } else {
    showAuthScreen();
  }
});
