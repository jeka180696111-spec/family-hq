// ═══════════════════════════════════════════════════════════════
// MAIN — точка входу, Firebase ініціалізація
// ═══════════════════════════════════════════════════════════════

import { state, FAMILY_MEMBERS, APP_CONFIG, FIREBASE_CONFIG } from './config.js';
import { showOnboarding } from './onboarding.js';
import { log, showToast, setText, esc } from './utils.js';
import {
  getFamilyName, getFamilyAvatar, getAvatar, getProfiles, getTheme,
  getExpCats, getIncCats, getCards, getWalletTypes,
  setExpCats, setIncCats, setCards, setWalletTypes, setProfiles, setFamilyName,
  isDirty, clearDirty,
  getViewAsMember, setViewAsMember,
} from './storage.js';
import { initTheme, toggleTheme } from './theme.js';
import { initAuth, signInWithGoogle, signOut, whoAmI } from './auth.js';
import { checkAndLock, startActivityTracking } from './lock-screen.js';
import { initFirestore, apiGet, syncSettingsToSheet, loadSettingsFromFirestore, loadFamilyData } from './api.js';
import { initFAB } from './fab.js';
import { renderDashboard, loadDashboard } from './dashboard.js';
import { renderWalletsPage } from './wallets.js';
import { renderOperationsPage, loadOperations } from './operations-list.js';
import { renderAnalyticsPage, loadAnalytics } from './analytics.js';
import { renderReservePage, loadReserve } from './reserve.js';
import { renderGoalsPage, loadGoals } from './goals.js';
import { renderSettingsPage, resetSettingsPage } from './settings-ui.js';
// ── НОВІ МОДУЛІ ─────────────────────────────────────────────
import { renderRecurringPage, loadRecurringPayments } from './recurring-payments.js';
import { renderAIChatPage } from './ai-chat.js';
import { renderChallengesPage, loadChallenges } from './challenges.js';
import { initEdgeSwipe } from './gestures.js';

const PAGE_TITLES = {
  dashboard: 'Головна',
  wallets: 'Кошельки',
  operations: 'Операції',
  analytics: 'Аналіз',
  reserve: 'Накопичення',
  goals: 'Цілі',
  recurring: 'Платежі',
  'ai-chat': 'AI · Фінн',
  challenges: 'Гра та досягнення',
  settings: 'Налаштування',
};

// ── Навігація ───────────────────────────────────────────────
export function navigateTo(page) {
  if (!PAGE_TITLES[page]) page = 'dashboard';
  // Reset settings nav when leaving settings
  if (state.currentPage === 'settings' && page !== 'settings') resetSettingsPage();
  state.currentPage = page;

  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  const pageEl = document.getElementById('page-' + page);
  if (pageEl) pageEl.classList.add('active');

  document.title = PAGE_TITLES[page] + ' · Сімейний бюджет';
  setText('topbar-title', PAGE_TITLES[page]);

  document.querySelectorAll('.sb-item[data-nav-page]').forEach(a => {
    a.classList.toggle('active', a.dataset.navPage === page);
  });
  document.querySelectorAll('.bn-item[data-nav-page]').forEach(a => {
    a.classList.toggle('active', a.dataset.navPage === page);
  });

  // Закрити sidebar на мобільному
  closeSidebar();

  // Рендеримо сторінку
  switch (page) {
    case 'dashboard':   renderDashboard(); break;
    case 'wallets':     renderWalletsPage(); break;
    case 'operations':  renderOperationsPage(); break;
    case 'analytics':   renderAnalyticsPage(); break;
    case 'reserve':     renderReservePage(); break;
    case 'goals':       renderGoalsPage(); break;
    case 'recurring':   renderRecurringPage(); break;
    case 'ai-chat':     renderAIChatPage(); break;
    case 'challenges':  renderChallengesPage(); break;
    case 'settings':    renderSettingsPage(); break;
  }
  loadPageData(page);
}

function loadPageData(page) {
  switch (page) {
    case 'dashboard':
      loadDashboard();
      break;
    case 'operations':
      loadOperations();
      break;
    case 'analytics':
      loadAnalytics();
      break;
    case 'reserve':
      if (!state.reserve) loadReserve();
      break;
    case 'goals':
      if (!state.goals.length) loadGoals();
      break;
    case 'recurring':
      if (!state.recurringPayments) loadRecurringPayments().then(() => renderRecurringPage());
      break;
    case 'challenges':
      loadChallenges();
      break;
  }
}

// ── Повний синк (з Firestore) ───────────────────────────────
async function fullSync() {
  try {
    // 1. Курси валют (потрібні для конвертації)
    await refreshFx();

    // 2. Налаштування з Firestore → localStorage
    await loadSettingsFromFirestore();

    // 3. Дашборд і операції паралельно
    await Promise.all([
      loadDashboard(),
      loadOperations(),
    ]);

    // 4. Обов'язкові платежі (для дашборду)
    loadRecurringPayments();

    log('full sync OK');
  } catch (e) {
    log('full sync error:', e.message);
  }
}

window.fullSync = fullSync;

// ── Курси валют ─────────────────────────────────────────────
async function refreshFx() {
  try {
    const fx = await apiGet('fx');
    state.fx = fx;
    // Показуємо курси в статус барі
    const fxEl = document.getElementById('fx-bar');
    if (fxEl && fx.USD && fx.EUR) {
      fxEl.textContent = `us ${fx.USD.mid?.toFixed(2) || '?'} ₴ · eu ${fx.EUR.mid?.toFixed(2) || '?'} ₴`;
    }
  } catch (e) {
    log('fx error:', e.message);
  }
}

// ═══════════════════════════════════════════════════════════════
// SIDEBAR + TOPBAR + BOTTOM NAV
// ═══════════════════════════════════════════════════════════════

// Exposed so settings can trigger sidebar/topbar/dashboard refresh
window.renderSidebarPublic = () => renderSidebar();
window.renderTopbarPublic = () => renderTopbar();
window.renderDashboardPublic = () => import('./dashboard.js').then(m => m.renderDashboard());

function renderSidebar() {
  const sb = document.getElementById('sidebar');
  if (!sb) return;
  const profiles = getProfiles();
  const me = whoAmI() || FAMILY_MEMBERS[0];
  const myProfile = profiles[me] || {};

  const familyAvatar = getFamilyAvatar();
  const familyName = getFamilyName() || 'Моя родина';
  const userAvatarStored = getAvatar();
  const userPhotoUrl = state.user?.avatar || '';
  const userAvatarSrc = userAvatarStored || userPhotoUrl;
  const familyLogoHtml = familyAvatar && familyAvatar.startsWith('data:')
    ? `<img src="${familyAvatar}" style="width:36px;height:36px;border-radius:10px;object-fit:cover">`
    : familyAvatar
      ? `<span style="font-size:22px;line-height:1">${familyAvatar}</span>`
      : `<i class="ti ti-home-2"></i>`;
  const userAvatarHtml = userAvatarSrc && userAvatarSrc.length > 2
    ? `<img src="${userAvatarSrc}" style="width:36px;height:36px;border-radius:50%;object-fit:cover">`
    : `<span style="font-weight:700">${(myProfile.name || me)[0]}</span>`;

  sb.innerHTML = `
    <div class="sb-header">
      <div class="sb-logo">
        <div class="sb-logo-icon" style="display:flex;align-items:center;justify-content:center">${familyLogoHtml}</div>
        <div class="sb-logo-info">
          <div class="sb-logo-name">${esc(familyName)}</div>
          <div class="sb-logo-sub">Сімейний бюджет</div>
        </div>
      </div>
      <div class="sb-user">
        <div class="sb-user-avatar" style="background:var(--c-accent-soft);color:var(--c-accent);overflow:hidden;padding:0">${userAvatarHtml}</div>
        <div>
          <div class="sb-user-name">${esc(myProfile.name || me)}</div>
          <div class="sb-user-role">Активний</div>
        </div>
      </div>
    </div>
    <nav class="sb-nav">
      <div class="sb-section-label">Головне</div>
      <a class="sb-item active" data-nav-page="dashboard"><i class="ti ti-layout-dashboard"></i> Дашборд</a>
      <a class="sb-item" data-nav-page="wallets"><i class="ti ti-wallet"></i> Кошельки</a>
      <a class="sb-item" data-nav-page="operations"><i class="ti ti-list"></i> Операції</a>
      <a class="sb-item" data-nav-page="analytics"><i class="ti ti-chart-bar"></i> Аналіз</a>
      <div class="sb-section-label">Фінанси</div>
      <a class="sb-item" data-nav-page="reserve"><i class="ti ti-coins"></i> Накопичення</a>
      <a class="sb-item" data-nav-page="goals"><i class="ti ti-target"></i> Цілі</a>
      <a class="sb-item" data-nav-page="recurring"><i class="ti ti-calendar-repeat"></i> Платежі</a>
      <div class="sb-section-label">Система</div>
      <a class="sb-item" data-nav-page="ai-chat"><i class="ti ti-sparkles"></i> AI · Фінн</a>
      <a class="sb-item" data-nav-page="challenges"><i class="ti ti-trophy"></i> Гра</a>
      <a class="sb-item" data-nav-page="settings"><i class="ti ti-settings"></i> Налаштування</a>
    </nav>
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
  const activeView = viewAs || me;
  const activeProf = profiles[activeView] || { name: activeView };

  tb.innerHTML = `
    <button class="topbar-menu" id="topbar-menu"><i class="ti ti-menu-2"></i></button>
    <div class="topbar-title" id="topbar-title">Головна</div>

    <button class="topbar-viewas-btn" id="topbar-viewas">
      ${(() => {
        const isMine = activeView === me;
        const src = isMine ? (getAvatar() || state.user?.avatar || '') : '';
        return src && src.length > 2
          ? `<img src="${src}" style="width:28px;height:28px;border-radius:50%;object-fit:cover;flex-shrink:0">`
          : `<div class="topbar-viewas-avatar">${(activeProf.name || activeView)[0]}</div>`;
      })()}
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

  const rect = anchor.getBoundingClientRect();
  menu.style.position = 'fixed';
  menu.style.top = (rect.bottom + 8) + 'px';
  menu.style.right = (window.innerWidth - rect.right) + 'px';
  menu.style.zIndex = '999';

  menu.querySelectorAll('[data-viewas]').forEach(b => {
    b.addEventListener('click', () => {
      const val = b.dataset.viewas;
      setViewAsMember(val === 'all' ? null : val);
      menu.remove();
      renderTopbar();
      navigateTo(state.currentPage);
    });
  });

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

function renderBottomNav() {
  const bn = document.getElementById('bottom-nav');
  if (!bn) return;
  bn.innerHTML = `
    <a class="bn-item ${state.currentPage==='dashboard'?'active':''}" data-nav-page="dashboard"><i class="ti ti-layout-dashboard"></i><span>Дашборд</span></a>
    <a class="bn-item ${state.currentPage==='wallets'?'active':''}" data-nav-page="wallets"><i class="ti ti-wallet"></i><span>Кошельки</span></a>
    <button class="bn-fab" id="bn-fab-btn"><i class="ti ti-plus"></i></button>
    <a class="bn-item ${state.currentPage==='operations'?'active':''}" data-nav-page="operations"><i class="ti ti-list"></i><span>Операції</span></a>
    <a class="bn-item ${state.currentPage==='settings'?'active':''}" data-nav-page="settings"><i class="ti ti-settings"></i><span>Ще</span></a>
  `;
  bn.querySelectorAll('[data-nav-page]').forEach(a => {
    a.addEventListener('click', (e) => {
      e.preventDefault();
      navigateTo(a.dataset.navPage);
    });
  });
}

// ── Sidebar mobile ──────────────────────────────────────────
function openSidebar() {
  document.body.classList.add('sidebar-open');
}
function closeSidebar() {
  document.body.classList.remove('sidebar-open');
}

// ═══════════════════════════════════════════════════════════════
// ІНІЦІАЛІЗАЦІЯ
// ═══════════════════════════════════════════════════════════════

function initAIFab() {
  const btn = document.getElementById('ai-fab-btn');
  if (!btn) return;
  btn.addEventListener('click', () => openAIBubble(btn));
}

function openAIBubble(triggerBtn) {
  if (document.getElementById('ai-bubble-dialog')) return;
  const btnRect = triggerBtn.getBoundingClientRect();

  const overlay = document.createElement('div');
  overlay.id = 'ai-bubble-overlay';
  overlay.style.cssText = 'position:fixed;inset:0;z-index:199;';

  const dialog = document.createElement('div');
  dialog.id = 'ai-bubble-dialog';
  dialog.style.cssText = `
    position:fixed;
    bottom:${window.innerHeight - btnRect.top + 8}px;
    right:${window.innerWidth - btnRect.right}px;
    width:min(360px, calc(100vw - 24px));
    height:min(480px, calc(100vh - ${window.innerHeight - btnRect.top + 24}px));
    background:var(--c-card);
    border-radius:20px;
    box-shadow:0 8px 40px rgba(0,0,0,0.22);
    border:1px solid var(--c-border);
    display:flex;
    flex-direction:column;
    overflow:hidden;
    z-index:200;
    transform:scale(0.1);
    transform-origin:bottom right;
    opacity:0;
    transition:transform 0.28s cubic-bezier(0.34,1.56,0.64,1),opacity 0.2s ease;
  `;

  let bubbleHistory = [];

  dialog.innerHTML = `
    <div style="display:flex;align-items:center;justify-content:space-between;padding:14px 16px;border-bottom:1px solid var(--c-border);flex-shrink:0">
      <div style="display:flex;align-items:center;gap:10px">
        <div style="width:32px;height:32px;border-radius:50%;background:var(--c-accent);color:#fff;display:flex;align-items:center;justify-content:center;font-size:16px">🤖</div>
        <div>
          <div style="font-size:14px;font-weight:700">Фінн</div>
          <div style="font-size:11px;color:var(--c-text-3)">AI помічник</div>
        </div>
      </div>
      <button id="ai-bubble-close" style="width:30px;height:30px;border-radius:50%;background:var(--c-bg-3);border:none;cursor:pointer;display:flex;align-items:center;justify-content:center;color:var(--c-text-2)">
        <i class="ti ti-x" style="font-size:14px"></i>
      </button>
    </div>
    <div id="ai-bubble-messages" style="flex:1;overflow-y:auto;padding:12px 16px;display:flex;flex-direction:column;gap:10px">
      <div class="ai-msg ai-msg-bot">
        <div class="ai-msg-bubble">Привіт! Я Фінн — ваш AI фінансовий помічник 👋 Чим можу допомогти?</div>
      </div>
    </div>
    <div style="padding:10px 12px;border-top:1px solid var(--c-border);display:flex;gap:8px;flex-shrink:0">
      <input id="ai-bubble-input" type="text" placeholder="Запитай мене..." style="flex:1;padding:9px 14px;border-radius:20px;border:1.5px solid var(--c-border);background:var(--c-bg-2);color:var(--c-text);font-size:14px;outline:none">
      <button id="ai-bubble-send" style="width:38px;height:38px;border-radius:50%;background:var(--c-accent);color:#fff;border:none;cursor:pointer;display:flex;align-items:center;justify-content:center;flex-shrink:0">
        <i class="ti ti-send" style="font-size:16px"></i>
      </button>
    </div>
  `;

  document.body.appendChild(overlay);
  document.body.appendChild(dialog);

  requestAnimationFrame(() => {
    dialog.style.transform = 'scale(1)';
    dialog.style.opacity = '1';
  });

  function closeAIBubble() {
    dialog.style.transform = 'scale(0.1)';
    dialog.style.opacity = '0';
    overlay.style.opacity = '0';
    setTimeout(() => { dialog.remove(); overlay.remove(); }, 280);
  }

  overlay.addEventListener('click', closeAIBubble);
  dialog.querySelector('#ai-bubble-close').addEventListener('click', closeAIBubble);

  const input = dialog.querySelector('#ai-bubble-input');
  const messagesEl = dialog.querySelector('#ai-bubble-messages');
  const sendBtn = dialog.querySelector('#ai-bubble-send');

  function addMessage(text, role) {
    const div = document.createElement('div');
    div.className = `ai-msg ai-msg-${role === 'user' ? 'user' : 'bot'}`;
    div.innerHTML = `<div class="ai-msg-bubble">${text.replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/\n/g,'<br>')}</div>`;
    messagesEl.appendChild(div);
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  async function sendBubbleMessage() {
    const text = input.value.trim();
    if (!text) return;
    input.value = '';
    addMessage(text, 'user');
    bubbleHistory.push({ role: 'user', content: text });

    const typingDiv = document.createElement('div');
    typingDiv.className = 'ai-msg ai-msg-bot';
    typingDiv.innerHTML = '<div class="ai-msg-bubble" style="color:var(--c-text-3)">...</div>';
    messagesEl.appendChild(typingDiv);
    messagesEl.scrollTop = messagesEl.scrollHeight;

    try {
      const { askAI } = await import('./ai-chat.js');
      const reply = await askAI(text, bubbleHistory.slice(-10));
      typingDiv.remove();
      addMessage(reply, 'bot');
      bubbleHistory.push({ role: 'assistant', content: reply });
      if (bubbleHistory.length > 20) bubbleHistory = bubbleHistory.slice(-20);
    } catch {
      typingDiv.remove();
      addMessage('Помилка відповіді. Спробуй ще раз.', 'bot');
    }
  }

  sendBtn.addEventListener('click', sendBubbleMessage);
  input.addEventListener('keydown', e => { if (e.key === 'Enter') sendBubbleMessage(); });
  input.focus();
}

async function bootApp() {
  renderSidebar();
  renderTopbar();
  renderBottomNav();
  initFAB();
  initAIFab();

  const overlay = document.getElementById('sidebar-overlay');
  if (overlay) overlay.addEventListener('click', closeSidebar);

  navigateTo('dashboard');

  // Handle PWA shortcuts
  const urlAction = new URLSearchParams(location.search).get('action');
  if (urlAction === 'add-expense') {
    setTimeout(() => import('./operations.js').then(m => m.openOperationDialog({ type: 'Витрата' })), 500);
  } else if (urlAction === 'add-income') {
    setTimeout(() => import('./operations.js').then(m => m.openOperationDialog({ type: 'Дохід' })), 500);
  }

  initEdgeSwipe(openSidebar);

  refreshFx();

  // Початковий синк
  setTimeout(() => fullSync(), 200);

  // Авто-синк раз на 2 хвилини
  setInterval(() => {
    if (document.hidden) return;
    if (state.currentPage !== 'dashboard') return;
    log('auto-sync tick');
    loadDashboard();
  }, 120000);
}

document.addEventListener('DOMContentLoaded', () => {
  initTheme();

  // Ініціалізуємо Firebase
  firebase.initializeApp(FIREBASE_CONFIG);
  initFirestore();

  // Register service worker for offline support
  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/sw.js').catch(() => {});
  }

  // Firebase Auth — слухаємо стан входу
  initAuth(async (user) => {
    // Завантажуємо членів родини з Firestore перед запуском
    if (state.familyId) {
      try { await loadFamilyData(state.familyId); } catch(e) { log('loadFamilyData error:', e.message); }
    }
    const loginScreen = document.getElementById('login-screen');
    const onboardingScreen = document.getElementById('onboarding-screen');
    const appRoot = document.getElementById('app-root');
    if (loginScreen) loginScreen.style.display = 'none';
    if (onboardingScreen) onboardingScreen.style.display = 'none';
    if (appRoot) appRoot.style.display = '';

    const locked = checkAndLock(() => {
      startActivityTracking();
      bootApp();
    });
    if (!locked) {
      startActivityTracking();
      bootApp();
    }
  });

  const signInBtn = document.getElementById('google-signin-btn');
  if (signInBtn) {
    signInBtn.addEventListener('click', () => signInWithGoogle());
  }
});
