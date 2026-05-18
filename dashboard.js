// ═══════════════════════════════════════════════════════════════
// DASHBOARD — головна сторінка з графіками
// ═══════════════════════════════════════════════════════════════

import { FAMILY_MEMBERS, state } from './config.js';
import { getCards, getProfiles, getWalletTypeById, getFamilyName, getVisibleWallets, setVisibleWallets, getViewAsMember, getCategoryLimits, getSpendingPlan, getDashWidgets, getDashCardOrder, setDashCardOrder } from './storage.js';
import { apiGet } from './api.js';
import { esc, fmtMoney, fmtMoneyShort, fmtMoneyWithUah, setText, fmtDate, log, showToast } from './utils.js';
import { openOperationDialog } from './operations.js';
import { t } from './i18n.js';
import { whoAmI } from './auth.js';
// ── НОВІ ІМПОРТИ ────────────────────────────────────────────
import { renderCreditCardsBlock, getCreditAlerts } from './credit-cards.js';
import { renderUpcomingPaymentsBlock } from './recurring-payments.js';

export async function loadDashboard() {
  const period = 'month';
  const cacheKey = `budget_dash_cache_${state.familyId}_${period}`;
  const cached = (() => { try { return JSON.parse(localStorage.getItem(cacheKey)); } catch { return null; } })();
  if (cached && Date.now() - cached.ts < 5 * 60 * 1000) {
    state.dashboard = cached.data;
    renderDashboard();
  }
  try {
    const data = await apiGet('dashboard', { period });
    state.dashboard = data;
    localStorage.setItem('budget_last_sync', new Date().toISOString());
    localStorage.setItem(cacheKey, JSON.stringify({ data, ts: Date.now() }));
    renderDashboard();
    checkAndShowPaymentReminders();
  } catch (e) {
    log('loadDashboard error:', e.message);
    if (!cached) renderDashboard();
  }
}

export function checkAndShowPaymentReminders() {
  const payments = state.recurringPayments || [];
  const today = new Date().getDate();
  const dueToday = payments.filter(p => p.active !== false && p.dayOfMonth === today);
  const dueTomorrow = payments.filter(p => p.active !== false && p.dayOfMonth === today + 1);
  if (dueToday.length) {
    showToast(`🔴 Сьогодні: ${dueToday.map(p => p.name).join(', ')}`, 'warn');
  } else if (dueTomorrow.length) {
    showToast(`🟡 Завтра: ${dueTomorrow.map(p => p.name).join(', ')}`, 'warn');
  }
}

window.refreshDashboard = loadDashboard;

export function renderDashboard() {
  const el = document.getElementById('page-dashboard');
  if (!el) return;

  if (!state.dashboard) {
    el.innerHTML = `<div class="page-inner"><div class="dash-hero-v2" style="min-height:120px">
      <div class="skeleton skeleton-line w-40" style="margin-bottom:12px"></div>
      <div class="skeleton skeleton-line w-60" style="height:32px;margin-bottom:16px"></div>
      <div class="skeleton skeleton-line w-80"></div>
    </div></div>`;
    return;
  }

  const d = state.dashboard || { totalIncome: 0, totalExpense: 0, balance: 0, byMember: {}, byCategory: {}, byDay: {}, byDayIncome: {}, recent: [] };
  const profiles = getProfiles();
  const viewAs = getViewAsMember();

  const hour = new Date().getHours();
  const greet = hour < 6 ? t('Доброї ночі') : hour < 12 ? t('Доброго ранку') : hour < 18 ? t('Доброго дня') : t('Доброго вечора');
  const me = whoAmI() || FAMILY_MEMBERS[0];
  const myName = profiles[me]?.name || me;
  const isPro = state.isPro === true;

  const now = new Date();
  const periodLabel = now.toLocaleDateString('uk-UA', { month: 'long', year: 'numeric' });

  let totalIncome = d.totalIncome || 0;
  let totalExpense = d.totalExpense || 0;
  let byCategoryView = d.byCategory || {};
  let byDayView = d.byDay || {};
  let byDayIncomeView = d.byDayIncome || {};

  if (viewAs) {
    totalIncome = d.byMember?.[viewAs]?.income || 0;
    totalExpense = d.byMember?.[viewAs]?.expense || 0;
    byCategoryView = d.byCategoryMember?.[viewAs] || {};
    byDayView = d.byDayMember?.[viewAs] || {};
    byDayIncomeView = d.byDayIncomeMember?.[viewAs] || {};
  }

  const { freeBalance, savingsBalance } = calcBalanceSplit(viewAs);
  const creditAvail = calcCreditAvailable(viewAs);
  const savRate = totalIncome > 0 ? Math.round((totalIncome - totalExpense) / totalIncome * 100) : 0;
  const recurringTotal = (state.recurringPayments || [])
    .filter(p => p.active !== false && (!viewAs || p.who === viewAs || p.who === 'Загальний'))
    .reduce((s, p) => s + (p.amount || 0), 0);

  const w = getDashWidgets();

  el.innerHTML = `
    <div class="dashboard">
      <!-- HERO -->
      <div class="dash-hero-v2">
        <div class="dash-hero-left">
          <div class="dash-greet">${greet}, ${esc(myName)}! 👋${isPro ? '<span class="pro-badge">PRO</span>' : ''}${viewAs ? ` <span class="dash-viewas-tag">${t('дивлюсь як')} ${esc(profiles[viewAs]?.name || viewAs)}</span>` : ''}</div>
          <div class="dash-hero-label">${t('Можна витратити')}</div>
          <div class="dash-hero-balance" data-balance-target="${freeBalance + creditAvail}">
            ${fmtMoney(freeBalance + creditAvail, 'UAH')}
          </div>
          <div class="dash-hero-meta">
            ${savingsBalance > 0 ? `<span class="dash-hero-pill pos"><i class="ti ti-coins"></i> ${t('Накопичення')}: ${fmtMoney(savingsBalance, 'UAH')}</span>` : ''}
            <span class="dash-hero-pill">
              <i class="ti ti-cash"></i> ${t('Готівка')}: ${fmtMoney(freeBalance, 'UAH')}
            </span>
            ${creditAvail > 0 ? `<span class="dash-hero-pill"><i class="ti ti-credit-card"></i> ${t('Кредит вільно')}: ${fmtMoney(creditAvail, 'UAH')}</span>` : ''}
            ${recurringTotal > 0 ? `<span class="dash-hero-pill warn" data-go="recurring"><i class="ti ti-calendar-repeat"></i> ${t('Платежі')}: ${fmtMoney(recurringTotal, 'UAH')}</span>` : ''}
            <span class="dash-hero-pill ${savRate >= 0 ? 'pos' : 'neg'}">
              <i class="ti ${savRate >= 0 ? 'ti-trending-up' : 'ti-trending-down'}"></i>
              ${savRate}% ${t('накопичено')}
            </span>
            <span class="dash-hero-month">${esc(periodLabel)}</span>
          </div>
        </div>
      </div>

      <!-- Spend per day -->
      ${renderSpendPerDayCard(freeBalance, viewAs, recurringTotal)}

      <!-- Швидкі дії -->
      <div class="dash-quick-actions">
        <button class="quick-action" data-quick="income"><div class="qa-icon"><i class="ti ti-arrow-down-circle"></i></div><span>${t('Дохід')}</span></button>
        <button class="quick-action" data-quick="expense"><div class="qa-icon"><i class="ti ti-arrow-up-circle"></i></div><span>${t('Витрата')}</span></button>
        <button class="quick-action" data-quick="transfer"><div class="qa-icon"><i class="ti ti-arrows-exchange"></i></div><span>${t('Переказ')}</span></button>
        <button class="quick-action" data-quick="exchange"><div class="qa-icon"><i class="ti ti-currency-dollar"></i></div><span>${t('Обмін')}</span></button>
        <button class="quick-action" data-quick="scanner"><div class="qa-icon"><i class="ti ti-scan"></i></div><span>${t('Сканер')}</span></button>
      </div>

      <!-- Грід -->
      <div class="dash-grid" id="dash-sortable-grid">
        ${buildDashGrid(w, periodLabel, totalExpense, totalIncome, byCategoryView, byDayView, byDayIncomeView, d, viewAs, profiles)}
      </div>
    </div>
  `;

  bindHandlers(el);
  initDashSortable(el);

  // Анімація балансу — лічильник від 0 до реального значення
  requestAnimationFrame(() => {
    const balEl = el.querySelector('.dash-hero-balance');
    if (!balEl) return;
    const target = parseFloat(balEl.dataset.balanceTarget) || 0;
    const duration = 700;
    const start = performance.now();
    const prefix = target < 0 ? '−' : '';
    const absTarget = Math.abs(target);
    function tick(now) {
      const elapsed = now - start;
      const progress = Math.min(elapsed / duration, 1);
      // easeOutExpo
      const ease = progress === 1 ? 1 : 1 - Math.pow(2, -10 * progress);
      const current = Math.round(absTarget * ease);
      balEl.textContent = prefix + current.toLocaleString('uk-UA') + ' ₴';
      if (progress < 1) requestAnimationFrame(tick);
      else balEl.textContent = fmtMoney(target, 'UAH');
    }
    requestAnimationFrame(tick);
  });

  // Алерт по кредитках (один раз при завантаженні)
  const alerts = getCreditAlerts();
  if (alerts.length && !state._creditAlertShown) {
    state._creditAlertShown = true;
    setTimeout(() => showToast(alerts[0].message, 'error'), 1000);
  }
}

// ── Spend per day ────────────────────────────────────────────
function calcSpendPerDay(freeBalance, viewAs) {
  const now = new Date();
  const daysInMonth = new Date(now.getFullYear(), now.getMonth() + 1, 0).getDate();
  const today = now.getDate();
  const daysLeft = Math.max(1, daysInMonth - today + 1);

  // Upcoming recurring payments: dayOfMonth >= today
  const upcoming = (state.recurringPayments || [])
    .filter(p => p.active !== false && p.dayOfMonth >= today &&
      (!viewAs || p.who === viewAs || p.who === 'Загальний'))
    .reduce((s, p) => s + (p.amount || 0), 0);

  // Goals monthly reserve: (target - saved) / months_to_deadline or flat 0 if no deadline
  const goalsReserve = (state.goals || [])
    .filter(g => g.status !== 'done' && g.deadline)
    .reduce((s, g) => {
      const deadline = new Date(g.deadline);
      const monthsLeft = Math.max(1,
        (deadline.getFullYear() - now.getFullYear()) * 12 +
        (deadline.getMonth() - now.getMonth()));
      const remaining = Math.max(0, (g.target || 0) - (g.saved || 0));
      return s + remaining / monthsLeft;
    }, 0);

  const available = Math.max(0, freeBalance - upcoming - goalsReserve);
  const perDay = Math.round(available / daysLeft);

  return { perDay, daysLeft, upcoming, goalsReserve: Math.round(goalsReserve) };
}

function renderSpendPerDayCard(freeBalance, viewAs, recurringTotal) {
  const { perDay, daysLeft, upcoming, goalsReserve } = calcSpendPerDay(freeBalance, viewAs);
  if (perDay <= 0 && freeBalance <= 0) return '';

  const good = perDay >= 200;
  const warn = perDay > 0 && perDay < 200;

  return `
    <div class="spd-card">
      <div class="spd-left">
        <div class="spd-label">${t('Можна витрачати на день')}</div>
        <div class="spd-amount ${good ? 'good' : warn ? 'warn' : 'bad'}">${fmtMoney(perDay, 'UAH')}</div>
        <div class="spd-meta">${t('Залишилось')} ${daysLeft} ${daysLeft === 1 ? t('день') : daysLeft < 5 ? t('дні') : t('днів')} ${t('у місяці')}</div>
      </div>
      <div class="spd-right">
        ${upcoming > 0 ? `<div class="spd-item"><i class="ti ti-calendar-repeat"></i><span>${t('Платежі')}: −${fmtMoney(upcoming, 'UAH')}</span></div>` : ''}
        ${goalsReserve > 0 ? `<div class="spd-item"><i class="ti ti-target"></i><span>${t('Цілі')}: −${fmtMoney(goalsReserve, 'UAH')}</span></div>` : ''}
        <div class="spd-item"><i class="ti ti-calendar-month"></i><span>${t('Баланс')}: ${fmtMoney(freeBalance, 'UAH')}</span></div>
      </div>
    </div>
  `;
}

// ── Баланс з розділенням: вільні vs накопичення ──────────────
function calcBalanceSplit(viewAs) {
  let freeBalance = 0;
  let savingsBalance = 0;

  FAMILY_MEMBERS.forEach(m => {
    if (viewAs && m !== viewAs) return;
    getCards(m).forEach(c => {
      const wt = getWalletTypeById(c.walletType);
      const isSavings = wt && wt.id === 'savings';
      const isCredit = Number(c.creditLimit) > 0;
      if (isCredit) return; // кредитки рахуємо окремо через calcCreditAvailable

      // Рахуємо баланс картки так само як renderWalletsBlock
      let bal = 0;
      const cardCur = c.currency || 'UAH';
      (state.operations || []).forEach(o => {
        if (o.category === 'Переказ') return;
        if (o.who !== m || o.card !== c.id) return;
        const opCur = o.currency || 'UAH';
        let val = opCur === cardCur ? (o.amount || 0) : (o.amountUah || o.amount || 0);
        if (opCur !== cardCur && cardCur !== 'UAH' && state.fx?.[cardCur]) {
          val = val / (state.fx[cardCur].mid || 1);
        }
        if (o.type === 'Дохід') bal += val;
        if (o.type === 'Витрата') bal -= val;
      });

      const balUah = cardCur === 'UAH' ? bal : bal * (state.fx?.[cardCur]?.mid || 1);
      if (isSavings) savingsBalance += balUah;
      else freeBalance += balUah;
    });
  });

  return { freeBalance: Math.round(freeBalance), savingsBalance: Math.round(savingsBalance) };
}

// ── Доступний кредитний ліміт по всіх кредитних картках ──────
function calcCreditAvailable(viewAs) {
  let total = 0;
  FAMILY_MEMBERS.forEach(m => {
    if (viewAs && m !== viewAs) return;
    getCards(m).forEach(c => {
      const limit = Number(c.creditLimit) || 0;
      if (!limit) return;
      const key = `${m}:${c.id}`;
      const b = state.dashboard?.cardBalances?.[key];
      const balance = b ? Math.round(b.income - b.expense) : 0;
      const used = Math.max(0, -balance);
      total += Math.max(0, limit - used);
    });
  });
  return total;
}

// ── Sparkline ───────────────────────────────────────────────
function renderSparkline(byDay, color) {
  const days = Object.keys(byDay).map(Number).sort((a, b) => a - b);
  if (!days.length) return `<div class="sparkline-empty">${t("Немає даних")}</div>`;
  const w = 280, h = 60;
  const max = Math.max(...days.map(d => byDay[d]), 1);
  const minDay = days[0], maxDay = days[days.length - 1];
  const range = Math.max(1, maxDay - minDay);

  const points = days.map(d => {
    const x = ((d - minDay) / range) * w;
    const y = h - (byDay[d] / max) * h * 0.85 - 5;
    return [x, y];
  });

  let path = `M ${points[0][0]} ${points[0][1]}`;
  for (let i = 1; i < points.length; i++) {
    const [x1, y1] = points[i - 1];
    const [x2, y2] = points[i];
    path += ` Q ${(x1 + x2) / 2} ${y1}, ${x2} ${y2}`;
  }

  const areaPath = path + ` L ${points[points.length - 1][0]} ${h} L ${points[0][0]} ${h} Z`;
  const lineColor = color === 'green' ? 'var(--c-green)' : color === 'red' ? 'var(--c-red)' : 'var(--c-accent)';
  const fillColor = color === 'green' ? 'var(--c-green-soft)' : color === 'red' ? 'var(--c-red-soft)' : 'var(--c-accent-soft)';

  return `
    <div class="sparkline">
      <svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" width="100%" height="${h}">
        <path d="${areaPath}" fill="${fillColor}" opacity="0.6"/>
        <path d="${path}" fill="none" stroke="${lineColor}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
        ${points.map(([x, y]) => `<circle cx="${x}" cy="${y}" r="2" fill="${lineColor}"/>`).join('')}
      </svg>
    </div>
  `;
}

// ── Drag handle HTML ───────────────────────────────────────
const DRAG_HANDLE = '<span class="dash-drag-handle"><i class="ti ti-grip-vertical"></i></span>';

// ── Build sortable grid ────────────────────────────────────
function buildDashGrid(w, periodLabel, totalExpense, totalIncome, byCategoryView, byDayView, byDayIncomeView, d, viewAs, profiles) {
  const widgets = {};

  if (w.chart) {
    widgets.expenses = `
      <div class="dash-card dash-stat-card" data-widget="expenses" draggable="true">
        <div class="dash-card-head">
          <span class="dash-card-title">${t("Витрати")} · ${esc(periodLabel)}</span>
          <span class="dash-card-amount c-red">${fmtMoney(totalExpense, 'UAH')}</span>
          ${DRAG_HANDLE}
        </div>
        ${renderSparkline(byDayView, 'red')}
      </div>`;
    widgets.income = `
      <div class="dash-card dash-stat-card" data-widget="income" draggable="true">
        <div class="dash-card-head">
          <span class="dash-card-title">${t("Доходи")} · ${esc(periodLabel)}</span>
          <span class="dash-card-amount c-green">${fmtMoney(totalIncome, 'UAH')}</span>
          ${DRAG_HANDLE}
        </div>
        ${renderSparkline(byDayIncomeView, 'green')}
      </div>`;
  }

  const donutHtml = w.donut ? renderDonutCard(byCategoryView, totalExpense, periodLabel) : '';
  if (donutHtml) widgets.donut = donutHtml.replace(/^<div /, '<div data-widget="donut" draggable="true" ').replace(/<div class="dash-card-head">/, `<div class="dash-card-head">${DRAG_HANDLE}`);

  const fxHtml = renderFxCard();
  if (fxHtml) widgets.fx = fxHtml.replace(/^<div /, '<div data-widget="fx" draggable="true" ').replace(/<div class="dash-card-head">/, `<div class="dash-card-head">${DRAG_HANDLE}`);

  const forecastHtml = renderForecastCard(totalExpense, totalIncome);
  if (forecastHtml) widgets.forecast = forecastHtml.replace(/^<div /, '<div data-widget="forecast" draggable="true" ').replace(/<div class="dash-card-head">/, `<div class="dash-card-head">${DRAG_HANDLE}`);

  const limitsHtml = w.limits ? renderCategoriesBlock(d, byCategoryView, totalExpense) : '';
  if (limitsHtml) widgets.limits = limitsHtml.replace(/^<div /, '<div data-widget="limits" draggable="true" ').replace(/<div class="dash-card-head">/, `<div class="dash-card-head">${DRAG_HANDLE}`);

  if (w.wallets) {
    widgets.wallets = `
      <div class="dash-card dash-wallets-card" data-widget="wallets" draggable="true">
        <div class="dash-card-head">
          ${DRAG_HANDLE}
          <span class="dash-card-title">${t("Гаманці")}${viewAs ? ' · ' + esc(profiles[viewAs]?.name || viewAs) : ''}</span>
          <div class="dash-card-actions">
            <button class="dash-card-icon-btn" data-config="wallets" title="${t("Налаштувати")}"><i class="ti ti-adjustments"></i></button>
            <a href="#" class="dash-card-action" data-go="wallets">${t("Усі →")}</a>
          </div>
        </div>
        ${renderWalletsBlock(viewAs)}
      </div>`;
  }

  const creditHtml = w.credit ? renderCreditCardsBlock(viewAs) : '';
  if (creditHtml) widgets.credit = creditHtml.replace(/^<div /, '<div data-widget="credit" draggable="true" ').replace(/<div class="dash-card-head">/, `<div class="dash-card-head">${DRAG_HANDLE}`);

  const recurringHtml = w.recurring ? renderUpcomingPaymentsBlock(viewAs) : '';
  if (recurringHtml) widgets.recurring = recurringHtml.replace(/^<div /, '<div data-widget="recurring" draggable="true" ').replace(/<div class="dash-card-head">/, `<div class="dash-card-head">${DRAG_HANDLE}`);

  const recentHtml = w.recent ? renderRecentBlock(d.recent || [], viewAs) : '';
  if (recentHtml) widgets.recent = recentHtml.replace(/^<div /, '<div data-widget="recent" draggable="true" ').replace(/<div class="dash-card-head">/, `<div class="dash-card-head">${DRAG_HANDLE}`);

  const order = getDashCardOrder();
  const allIds = ['expenses','income','donut','fx','forecast','limits','wallets','credit','recurring','recent'];
  const sortedIds = [...order, ...allIds.filter(id => !order.includes(id))];
  return sortedIds.map(id => widgets[id] || '').join('');
}

// ── Drag-and-drop сортування ───────────────────────────────
export function initDashSortable(el) {
  const grid = el.querySelector('#dash-sortable-grid');
  if (!grid) return;

  let dragSrc = null;

  function cards() { return [...grid.querySelectorAll('[data-widget]')]; }
  function saveOrder() { setDashCardOrder(cards().map(c => c.dataset.widget)); }
  function getCard(target) { return target?.closest('[data-widget]'); }
  function swap(src, tgt) {
    if (!src || !tgt || src === tgt) return;
    const all = cards();
    const si = all.indexOf(src), ti = all.indexOf(tgt);
    if (si < ti) grid.insertBefore(src, tgt.nextSibling);
    else grid.insertBefore(src, tgt);
  }

  // Desktop HTML5 drag
  grid.addEventListener('dragstart', e => {
    const c = getCard(e.target);
    if (!c) return;
    // Only allow drag from handle
    if (!e.target.closest('.dash-drag-handle')) { e.preventDefault(); return; }
    dragSrc = c;
    c.classList.add('dash-dragging');
    e.dataTransfer.effectAllowed = 'move';
  });
  grid.addEventListener('dragover', e => {
    e.preventDefault();
    const c = getCard(e.target);
    if (c && dragSrc) swap(dragSrc, c);
  });
  grid.addEventListener('dragend', () => {
    dragSrc?.classList.remove('dash-dragging');
    dragSrc = null;
    saveOrder();
  });

  // Mobile touch drag
  let touchCard = null, holdTimer = null, touchActive = false;
  let startX = 0, startY = 0;

  grid.addEventListener('touchstart', e => {
    const handle = e.target.closest('.dash-drag-handle');
    const card = getCard(e.target);
    if (!card) return;
    startX = e.touches[0].clientX;
    startY = e.touches[0].clientY;
    if (handle) {
      touchCard = card;
      touchActive = true;
      card.classList.add('dash-dragging');
      navigator.vibrate?.(40);
    } else {
      holdTimer = setTimeout(() => {
        touchCard = card;
        touchActive = true;
        card.classList.add('dash-dragging');
        navigator.vibrate?.(40);
      }, 500);
    }
  }, { passive: true });

  grid.addEventListener('touchmove', e => {
    if (!touchActive) {
      if (Math.abs(e.touches[0].clientX - startX) > 8 || Math.abs(e.touches[0].clientY - startY) > 8) {
        clearTimeout(holdTimer); holdTimer = null;
      }
      return;
    }
    e.preventDefault();
    const el2 = document.elementFromPoint(e.touches[0].clientX, e.touches[0].clientY);
    const tgt = getCard(el2);
    if (tgt && touchCard) swap(touchCard, tgt);
  }, { passive: false });

  grid.addEventListener('touchend', () => {
    clearTimeout(holdTimer); holdTimer = null;
    if (!touchActive) return;
    touchCard?.classList.remove('dash-dragging');
    touchCard = null;
    touchActive = false;
    saveOrder();
  });
}

// ── Блок гаманців ──────────────────────────────────────────
function renderWalletsBlock(viewAs) {
  const allCards = [];
  FAMILY_MEMBERS.forEach(m => {
    if (viewAs && m !== viewAs) return;
    getCards(m).forEach((c, idx) => allCards.push({ ...c, owner: m, ownerIdx: idx }));
  });

  function cardBal(c) {
    // Для кредитних карток — all-time баланс
    const limit = Number(c.creditLimit) || 0;
    if (limit > 0 && state.dashboard?.cardBalances) {
      const key = `${c.owner}:${c.id}`;
      const b = state.dashboard.cardBalances[key];
      if (b) return Math.round(b.income - b.expense);
    }
    let bal = 0;
    const cardCur = c.currency || 'UAH';
    (state.operations || []).forEach(o => {
      if (o.who === c.owner && o.card === c.id) {
        const opCur = o.currency || 'UAH';
        let val = opCur === cardCur ? (o.amount || 0) : (o.amountUah || o.amount || 0);
        if (opCur !== cardCur && cardCur !== 'UAH' && state.fx?.[cardCur]) {
          val = val / (state.fx[cardCur].mid || 1);
        }
        if (o.type === 'Дохід') bal += val;
        if (o.type === 'Витрата') bal -= val;
      }
    });
    return bal;
  }

  const visible = getVisibleWallets();
  let filtered = allCards;
  if (visible !== null) filtered = allCards.filter(c => visible.includes(`${c.owner}::${c.id}`));

  const cardsWithBal = filtered.map(c => {
    const balance = cardBal(c);
    const limit = Number(c.creditLimit) || 0;
    let credit = null;
    if (limit > 0) {
      const creditUsed = Math.max(0, -balance);
      credit = {
        limit,
        creditUsed,
        creditAvail: Math.max(0, limit - creditUsed),
        pct: Math.min(100, Math.round((creditUsed / limit) * 100)),
        status: creditUsed / limit >= 0.9 ? 'danger' : creditUsed / limit >= 0.6 ? 'warning' : '',
      };
    }
    return { ...c, balance, credit };
  })
    .sort((a, b) => Math.abs(b.balance) - Math.abs(a.balance));

  if (!cardsWithBal.length) {
    return visible !== null && visible.length === 0
      ? '<div class="empty-mini">Усі гаманці приховано. Натисни ⚙ щоб налаштувати.</div>'
      : '<div class="empty-mini">Жодного гаманця. Додай на сторінці Гаманці.</div>';
  }

  return `
    <div class="dash-wallets-list">
      ${cardsWithBal.map(c => `
        <div class="dash-wallet-item" data-owner="${esc(c.owner)}" data-card="${esc(c.id)}">
          <div class="dash-wallet-icon" style="background:${c.bg}">
            <i class="ti ${c.icon}" style="color:${c.color}"></i>
          </div>
          <div class="dash-wallet-info">
            <div class="dash-wallet-name">${esc(c.id)}</div>
            <div class="dash-wallet-owner">${esc(c.owner)}${c.currency && c.currency !== 'UAH' ? ' · ' + c.currency : ''}</div>
            ${c.credit ? `
              <div class="dash-wallet-credit">
                <div class="wallet-credit-track">
                  <div class="wallet-credit-fill ${c.credit.status}" style="width:${c.credit.pct}%"></div>
                </div>
                <span class="wallet-credit-label ${c.credit.creditUsed > 0 ? 'used' : ''}">
                  використано ${fmtMoney(c.credit.creditUsed)} з ${fmtMoney(c.credit.limit)}
                </span>
              </div>
            ` : ''}
          </div>
          <div class="dash-wallet-balance ${c.credit ? 'pos' : (c.balance >= 0 ? 'pos' : 'neg')}">
            ${c.credit
              ? `${fmtMoney(c.credit.creditAvail)} <span style="font-size:11px;font-weight:500;opacity:.7">вільно</span>`
              : fmtMoneyWithUah(c.balance, c.currency || 'UAH', state.fx)
            }
          </div>
        </div>
      `).join('')}
    </div>
  `;
}

// ── Donut chart категорій ────────────────────────────────────
const DONUT_COLORS = [
  '#2E7D5F','#4A7BB7','#D9A13E','#C85450','#7F77DD',
  '#E05A2B','#1A9E8A','#B85C9A','#5E8F3E','#8C6A2F',
];

function renderDonutCard(byCat, total, periodLabel) {
  const entries = Object.entries(byCat || {}).sort((a, b) => b[1] - a[1]).slice(0, 8);
  if (!entries.length || !total) return '';

  const R = 54, cx = 70, cy = 70, strokeW = 22;
  const circ = 2 * Math.PI * R;
  let offset = 0;
  const segments = entries.map(([cat, val], i) => {
    const pct = val / total;
    const dash = pct * circ;
    const seg = { cat, val, pct, dash, offset, color: DONUT_COLORS[i % DONUT_COLORS.length] };
    offset += dash;
    return seg;
  });

  const svgSegments = segments.map(s => `
    <circle
      cx="${cx}" cy="${cy}" r="${R}"
      fill="none"
      stroke="${s.color}"
      stroke-width="${strokeW}"
      stroke-dasharray="${s.dash.toFixed(2)} ${(circ - s.dash).toFixed(2)}"
      stroke-dashoffset="${(-s.offset + circ / 4).toFixed(2)}"
      stroke-linecap="butt"
    />
  `).join('');

  return `
    <div class="dash-card">
      <div class="dash-card-head">
        <span class="dash-card-title">Категорії · ${esc(periodLabel)}</span>
        <a href="#" class="dash-card-action" data-go="analytics">Аналіз →</a>
      </div>
      <div style="display:flex;gap:16px;align-items:center;flex-wrap:wrap">
        <div style="flex-shrink:0">
          <svg width="140" height="140" viewBox="0 0 140 140">
            <circle cx="${cx}" cy="${cy}" r="${R}" fill="none" stroke="var(--c-bg-3)" stroke-width="${strokeW}"/>
            ${svgSegments}
            <text x="${cx}" y="${cy - 6}" text-anchor="middle" font-size="11" fill="var(--c-text-3)" font-family="inherit" font-weight="600">Витрати</text>
            <text x="${cx}" y="${cy + 12}" text-anchor="middle" font-size="13" fill="var(--c-text)" font-family="inherit" font-weight="800">${fmtMoneyShort(total)}</text>
          </svg>
        </div>
        <div style="flex:1;min-width:0;display:flex;flex-direction:column;gap:6px">
          ${segments.map(s => `
            <div style="display:flex;align-items:center;gap:8px">
              <div style="width:10px;height:10px;border-radius:3px;background:${s.color};flex-shrink:0"></div>
              <div style="flex:1;font-size:12px;font-weight:500;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(s.cat)}</div>
              <div style="font-size:12px;font-weight:700;flex-shrink:0">${Math.round(s.pct * 100)}%</div>
            </div>
          `).join('')}
        </div>
      </div>
    </div>
  `;
}

// ── FX Rate card ────────────────────────────────────────────
function renderFxCard() {
  const fx = state.fx || {};
  const usd = fx.USD || {};
  const eur = fx.EUR || {};
  if (!usd.buy && !usd.mid) return '';

  const usdRate = (usd.mid || usd.buy || 0).toFixed(2);
  const eurRate = (eur.mid || eur.buy || 0).toFixed(2);
  const updTime = fx._updated ? new Date(fx._updated).toLocaleTimeString('uk-UA', { hour: '2-digit', minute: '2-digit' }) : '';

  return `
    <div class="dash-card dash-fx-card">
      <div class="dash-card-head">
        <span class="dash-card-title">💱 Курси НБУ</span>
        ${updTime ? `<span style="font-size:11px;color:var(--c-text-3)">оновлено ${updTime}</span>` : ''}
      </div>
      <div class="dash-fx-row">
        <div class="dash-fx-item">
          <span class="dash-fx-name">USD</span>
          <span class="dash-fx-buy">${usdRate}</span>
          <span class="dash-fx-unit">₴</span>
        </div>
        <div class="dash-fx-item">
          <span class="dash-fx-name">EUR</span>
          <span class="dash-fx-buy">${eurRate}</span>
          <span class="dash-fx-unit">₴</span>
        </div>
      </div>
      <div style="font-size:11px;color:var(--c-text-3);margin-top:4px">офіційний курс НБУ</div>
    </div>
  `;
}

function renderForecastCard(totalExpense, totalIncome) {
  const now = new Date();
  const day = now.getDate();
  const daysInMonth = new Date(now.getFullYear(), now.getMonth() + 1, 0).getDate();
  const daysLeft = daysInMonth - day;
  if (day < 3) return ''; // not enough data

  const dailyRate = totalExpense / day;
  const projected = Math.round(dailyRate * daysInMonth);
  const projectedBalance = Math.round(totalIncome - projected);
  const pct = Math.min(100, Math.round((day / daysInMonth) * 100));
  const overBudget = projected > totalIncome && totalIncome > 0;

  return `
    <div class="dash-card">
      <div class="dash-card-head">
        <span class="dash-card-title">📈 Прогноз на місяць</span>
        <span style="font-size:12px;color:var(--c-text-2)">${day} з ${daysInMonth} днів</span>
      </div>
      <div style="height:6px;border-radius:3px;background:var(--c-border);margin:8px 0 4px;overflow:hidden">
        <div style="height:100%;width:${pct}%;background:var(--c-accent);border-radius:3px"></div>
      </div>
      <div class="dash-forecast-row">
        <div class="dash-forecast-item">
          <div class="dash-forecast-label">Витрачено</div>
          <div class="dash-forecast-val c-red">${fmtMoney(totalExpense, 'UAH')}</div>
        </div>
        <div class="dash-forecast-item">
          <div class="dash-forecast-label">Прогноз витрат</div>
          <div class="dash-forecast-val ${overBudget ? 'c-red' : ''}">${fmtMoney(projected, 'UAH')}</div>
        </div>
        <div class="dash-forecast-item">
          <div class="dash-forecast-label">Залишок</div>
          <div class="dash-forecast-val ${projectedBalance >= 0 ? 'c-green' : 'c-red'}">${projectedBalance >= 0 ? '+' : ''}${fmtMoney(projectedBalance, 'UAH')}</div>
        </div>
      </div>
      ${overBudget ? `<div style="font-size:12px;color:var(--c-red);margin-top:6px">⚠️ При такому темпі витрати перевищать доходи на ${fmtMoney(projected - totalIncome, 'UAH')}</div>` : `<div style="font-size:12px;color:var(--c-text-3);margin-top:6px">Залишилось ${daysLeft} днів · в середньому ${fmtMoney(Math.round(dailyRate), 'UAH')}/день</div>`}
    </div>
  `;
}

// ── Блок категорій ──────────────────────────────────────────
function renderCategoriesBlock(d, byCat, total) {
  byCat = byCat || d.byCategory || {};
  const entries = Object.entries(byCat).sort((a, b) => b[1] - a[1]).slice(0, 5);
  total = total || d.totalExpense || entries.reduce((s, [, v]) => s + v, 0) || 1;
  if (!entries.length) return '';
  const limits = getCategoryLimits();
  const plan = getSpendingPlan();

  return `
    <div class="dash-card">
      <div class="dash-card-head">
        <span class="dash-card-title">Топ категорій</span>
        <a href="#" class="dash-card-action" data-go="analytics">Аналіз →</a>
      </div>
      <div class="dash-cats-list">
        ${entries.map(([cat, val]) => {
          const pct = (val / total * 100).toFixed(0);
          const limit = limits[cat];
          const planned = plan[cat];
          const ref = limit || planned;
          const refPct = ref ? Math.min(100, Math.round((val / ref) * 100)) : null;
          const overLimit = limit && val > limit;
          const overPlan = !overLimit && planned && val > planned;
          const barClass = overLimit ? 'over-limit' : (overPlan ? 'over-plan' : '');
          const badge = limit
            ? `<span class="dash-cat-limit-badge ${overLimit ? 'over' : ''}">${refPct}% ліміт</span>`
            : planned
              ? `<span class="dash-cat-limit-badge ${overPlan ? 'over' : 'plan'}">${refPct}% план</span>`
              : '';
          return `
            <div class="dash-cat-row">
              <div class="dash-cat-name">${esc(cat)}${overLimit ? ' ⚠️' : overPlan ? ' 📋' : ''}</div>
              <div class="dash-cat-bar">
                <div class="dash-cat-bar-fill ${barClass}" style="width:${pct}%"></div>
                ${limit ? `<div class="dash-cat-limit-line" style="left:${Math.min(100,(limit/total*100)).toFixed(0)}%" title="Ліміт: ${fmtMoneyShort(limit)}"></div>` : ''}
                ${planned && !limit ? `<div class="dash-cat-plan-line" style="left:${Math.min(100,(planned/total*100)).toFixed(0)}%" title="План: ${fmtMoneyShort(planned)}"></div>` : ''}
              </div>
              <div class="dash-cat-amount">${fmtMoney(val, 'UAH')}${badge}</div>
            </div>
          `;
        }).join('')}
      </div>
    </div>
  `;
}

function renderRecentBlock(recent, viewAs) {
  if (!recent?.length) return '';
  let filtered = viewAs ? recent.filter(o => o.who === viewAs) : recent;
  if (!filtered.length) return '';

  return `
    <div class="dash-card">
      <div class="dash-card-head">
        <span class="dash-card-title">Останні операції</span>
        <a href="#" class="dash-card-action" data-go="operations">Усі →</a>
      </div>
      <div class="dash-recent-list">
        ${filtered.slice(0, 5).map(op => {
          const isExp = op.type === 'Витрата';
          return `
            <div class="dash-recent-item" data-op-row="${op.row}">
              <div class="dash-recent-icon" style="background:${isExp ? 'var(--c-red-soft)' : 'var(--c-green-soft)'};color:${isExp ? 'var(--c-red)' : 'var(--c-green)'}">
                <i class="ti ${isExp ? 'ti-arrow-up' : 'ti-arrow-down'}"></i>
              </div>
              <div class="dash-recent-info">
                <div class="dash-recent-name">${esc(op.category || '—')}${op.desc ? ` · ${esc(op.desc)}` : ''}</div>
                <div class="dash-recent-meta">${esc(op.who || '')} · ${fmtDate(op.date)}</div>
              </div>
              <div class="dash-recent-amount ${isExp ? 'neg' : 'pos'}">${isExp ? '−' : '+'}${fmtMoney(op.amount, op.currency)}</div>
            </div>
          `;
        }).join('')}
      </div>
    </div>
  `;
}

function bindHandlers(el) {
  el.querySelectorAll('[data-quick]').forEach(b => {
    b.addEventListener('click', () => {
      const act = b.dataset.quick;
      if (act === 'income')   openOperationDialog({ type: 'Дохід' });
      else if (act === 'expense')  openOperationDialog({ type: 'Витрата' });
      else if (act === 'transfer') import('./transfer.js').then(t => t.openTransferDialog());
      else if (act === 'exchange') import('./transfer.js').then(t => t.openTransferDialog({ exchange: true }));
      else if (act === 'scanner') import('./receipt-scanner.js').then(s => s.openScannerChoice());
    });
  });

  el.querySelectorAll('[data-go]').forEach(a => {
    a.addEventListener('click', (e) => {
      e.preventDefault();
      import('./main.js').then(m => m.navigateTo(a.dataset.go));
    });
  });

  el.querySelectorAll('[data-config="wallets"]').forEach(b => {
    b.addEventListener('click', () => openWalletsVisibilityDialog());
  });

  el.querySelectorAll('.dash-wallet-item').forEach(item => {
    item.addEventListener('click', () => {
      import('./main.js').then(m => m.navigateTo('wallets'));
    });
  });

  el.querySelectorAll('.dash-recent-item').forEach(item => {
    item.addEventListener('click', () => {
      const row = parseInt(item.dataset.opRow);
      const op = (state.dashboard?.recent || []).find(o => o.row === row);
      if (op) openOperationDialog({ type: op.type, editing: op });
    });
  });
}

// ── Діалог налаштування видимих гаманців ───────────────────
function openWalletsVisibilityDialog() {
  import('./modals.js').then(({ openBottomSheet, closeModal }) => {
    const allCards = [];
    FAMILY_MEMBERS.forEach(m => {
      getCards(m).forEach(c => allCards.push({ ...c, owner: m, key: `${m}::${c.id}` }));
    });

    const visible = getVisibleWallets();
    const selectedSet = new Set(visible || allCards.map(c => c.key));
    let modalId;

    function renderGrid() {
      const profiles = getProfiles();
      return allCards.map(c => {
        const sel = selectedSet.has(c.key);
        return `
          <button class="vis-card ${sel ? 'selected' : ''}" data-key="${esc(c.key)}">
            <div class="vis-card-icon" style="background:${c.bg}"><i class="ti ${c.icon}" style="color:${c.color}"></i></div>
            <div class="vis-card-name">${esc(c.id)}</div>
            <div class="vis-card-owner">${esc(profiles[c.owner]?.name || c.owner)}</div>
            ${sel ? '<i class="ti ti-check vis-card-check"></i>' : ''}
          </button>
        `;
      }).join('');
    }

    function bodyHtml() {
      return `
        <div style="margin-bottom:10px;display:flex;gap:8px;justify-content:flex-end">
          <button class="btn-ghost-sm" data-act="all">Обрати всі</button>
          <button class="btn-ghost-sm" data-act="none">Зняти всі</button>
        </div>
        <div class="vis-grid" id="vis-list">${renderGrid()}</div>
        <button class="btn-primary" style="width:100%;margin-top:14px" data-act="save">Зберегти</button>
      `;
    }

    modalId = openBottomSheet({
      title: 'Гаманці на дашборді',
      content: bodyHtml(),
      onOpen: (modal) => {
        function rerender() {
          const listEl = modal.querySelector('#vis-list');
          if (listEl) { listEl.innerHTML = renderGrid(); bindGrid(modal); }
        }
        function bindGrid(root) {
          root.querySelectorAll('.vis-card').forEach(btn => {
            btn.addEventListener('click', () => {
              if (selectedSet.has(btn.dataset.key)) selectedSet.delete(btn.dataset.key);
              else selectedSet.add(btn.dataset.key);
              rerender();
            });
          });
        }
        bindGrid(modal);
        modal.querySelector('[data-act="all"]').addEventListener('click', () => {
          allCards.forEach(c => selectedSet.add(c.key)); rerender();
        });
        modal.querySelector('[data-act="none"]').addEventListener('click', () => {
          selectedSet.clear(); rerender();
        });
        modal.querySelector('[data-act="save"]').addEventListener('click', () => {
          if (selectedSet.size === allCards.length) setVisibleWallets(null);
          else setVisibleWallets(Array.from(selectedSet));
          closeModal(modalId);
          renderDashboard();
          import('./utils.js').then(u => u.showToast('✅ Налаштовано'));
        });
      },
    });
  });
}
