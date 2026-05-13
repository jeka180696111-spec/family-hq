// ═══════════════════════════════════════════════════════════════
// MAIN — точка входу, ініціалізація
// ═══════════════════════════════════════════════════════════════

import { state, FAMILY_MEMBERS } from './config.js';
import { log, showToast, setText } from './utils.js';
import {
  getFamilyName, getProfiles, getTheme, getScriptUrl,
  getExpCats, getIncCats, getCards, getWalletTypes,
  setExpCats, setIncCats, setCards, setWalletTypes, setProfiles, setFamilyName,
} from './storage.js';
import { initTheme } from './theme.js';
import { initGoogleAuth, restoreSession, whoAmI } from './auth.js';
import { apiGet, syncSettingsToSheet } from './api.js';
import { initFAB } from './fab.js';
import { renderDashboard, loadDashboard } from './dashboard.js';
import { renderWalletsPage } from './wallets.js';
import { renderOperationsPage, loadOperations } from './operations-list.js';
import { renderAnalyticsPage } from './analytics.js';
import { renderReservePage, loadReserve } from './reserve.js';
import { renderGoalsPage, loadGoals } from './goals.js';
import { renderSettingsPage } from './settings-ui.js';

// ── Заголовки сторінок ──────────────────────────────────────
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

  // Перемикаємо .page видимість
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  const pageEl = document.getElementById('page-' + page);
  if (pageEl) pageEl.classList.add('active');

  // Title
  document.title = PAGE_TITLES[page] + ' · Сімейний бюджет';
  setText('topbar-title', PAGE_TITLES[page]);

  // Активний пункт в sidebar / bottom-nav
  document.querySelectorAll('[data-nav-page]').forEach(a => {
    a.classList.toggle('active', a.dataset.navPage === page);
  });

  // Рендер відповідної сторінки
  switch (page) {
    case 'dashboard':  renderDashboard(); break;
    case 'wallets':    renderWalletsPage(); break;
    case 'operations': renderOperationsPage(); break;
    case 'analytics':  renderAnalyticsPage(); break;
    case 'reserve':    renderReservePage(); break;
    case 'goals':      renderGoalsPage(); break;
    case 'settings':   renderSettingsPage(); break;
  }

  // Закрити sidebar на мобілці
  closeSidebar();

  // Завантажити дані для сторінки (якщо ще не маємо)
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
    // 1. Налаштування з сервера
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
function applyServerSettings(s) {
  if (!s) return;
  if (s.familyName && s.familyName !== getFamilyName()) {
    setFamilyName(s.familyName);
    setText('sb-family-name', s.familyName);
  }
  if (Array.isArray(s.expCats) && s.expCats.length) setExpCats(s.expCats);
  if (Array.isArray(s.incCats) && s.incCats.length) setIncCats(s.incCats);
  if (Array.isArray(s.cardsEvgen) && s.cardsEvgen.length) setCards(s.cardsEvgen, 'Євген');
  if (Array.isArray(s.cardsMarina) && s.cardsMarina.length) setCards(s.cardsMarina, 'Марина');
  if (Array.isArray(s.walletTypes) && s.walletTypes.length) setWalletTypes(s.walletTypes);
  if (s.profiles && typeof s.profiles === 'object') setProfiles(s.profiles);
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

  // Слухачі
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
  tb.innerHTML = `
    <button class="topbar-menu" id="topbar-menu"><i class="ti ti-menu-2"></i></button>
    <div class="topbar-title" id="topbar-title">Головна</div>
    <button class="topbar-action" id="topbar-theme"><i class="ti ti-${getTheme() === 'dark' ? 'sun' : 'moon'}"></i></button>
  `;
  document.getElementById('topbar-menu').addEventListener('click', openSidebar);
  document.getElementById('topbar-theme').addEventListener('click', () => {
    import('./theme.js').then(t => {
      t.toggleTheme();
      renderTopbar();
    });
  });
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

// ── Курси валют у sidebar/topbar ────────────────────────────
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

// ── Авторизація: показуємо логін якщо немає ─────────────────
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

// ── Запуск додатку ──────────────────────────────────────────
async function bootApp() {
  // URL з конфіга або localStorage
  state.scriptUrl = getScriptUrl();

  // Рендер UI каркасу
  renderSidebar();
  renderTopbar();
  renderBottomNav();
  initFAB();

  // Закриття sidebar по кліку на оверлей
  const overlay = document.getElementById('sidebar-overlay');
  if (overlay) overlay.addEventListener('click', closeSidebar);

  // Початкова сторінка
  navigateTo('dashboard');

  // Курси валют
  refreshFx();

  // Повний синк (з невеликою затримкою щоб не блокувати рендер)
  setTimeout(() => fullSync(), 100);

  // Автоматичний синк раз на 30 сек
  setInterval(() => {
    if (state.currentPage === 'dashboard') loadDashboard();
  }, 30000);
}

// ── DOMContentLoaded ────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  initTheme();
  if (restoreSession()) {
    bootApp();
  } else {
    showAuthScreen();
  }
});
