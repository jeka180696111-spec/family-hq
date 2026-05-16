// ═══════════════════════════════════════════════════════════════
// DASHBOARD — головна сторінка з графіками
// ═══════════════════════════════════════════════════════════════

import { FAMILY_MEMBERS, state } from './config.js';
import { getCards, getProfiles, getWalletTypeById, getFamilyName, getVisibleWallets, setVisibleWallets, getViewAsMember, getCategoryLimits, getSpendingPlan } from './storage.js';
import { apiGet } from './api.js';
import { esc, fmtMoney, fmtMoneyShort, fmtMoneyWithUah, setText, fmtDate, log } from './utils.js';
import { openOperationDialog } from './operations.js';
import { whoAmI } from './auth.js';
// ── НОВІ ІМПОРТИ ────────────────────────────────────────────
import { renderCreditCardsBlock, getCreditAlerts } from './credit-cards.js';
import { renderUpcomingPaymentsBlock } from './recurring-payments.js';

export async function loadDashboard() {
  try {
    const data = await apiGet('dashboard', { period: 'month' });
    state.dashboard = data;
    localStorage.setItem('budget_last_sync', new Date().toISOString());
    renderDashboard();
  } catch (e) {
    log('loadDashboard error:', e.message);
    renderDashboard();
  }
}

window.refreshDashboard = loadDashboard;

export function renderDashboard() {
  const el = document.getElementById('page-dashboard');
  if (!el) return;

  const d = state.dashboard || { totalIncome: 0, totalExpense: 0, balance: 0, byMember: {}, byCategory: {}, byDay: {}, byDayIncome: {}, recent: [] };
  const profiles = getProfiles();
  const viewAs = getViewAsMember();

  const hour = new Date().getHours();
  const greet = hour < 6 ? 'Доброї ночі' : hour < 12 ? 'Доброго ранку' : hour < 18 ? 'Доброго дня' : 'Доброго вечора';
  const me = whoAmI() || FAMILY_MEMBERS[0];
  const myName = profiles[me]?.name || me;

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

  el.innerHTML = `
    <div class="dashboard">
      <!-- HERO -->
      <div class="dash-hero-v2">
        <div class="dash-hero-left">
          <div class="dash-greet">${greet}, ${esc(myName)}! 👋${viewAs ? ` <span class="dash-viewas-tag">дивлюсь як ${esc(profiles[viewAs]?.name || viewAs)}</span>` : ''}</div>
          <div class="dash-hero-label">Можна витратити</div>
          <div class="dash-hero-balance">${fmtMoney(freeBalance + creditAvail, 'UAH')}</div>
          <div class="dash-hero-meta">
            ${savingsBalance > 0 ? `<span class="dash-hero-pill pos"><i class="ti ti-coins"></i> Накопичення: ${fmtMoney(savingsBalance, 'UAH')}</span>` : ''}
            <span class="dash-hero-pill">
              <i class="ti ti-cash"></i> Готівка: ${fmtMoney(freeBalance, 'UAH')}
            </span>
            ${creditAvail > 0 ? `<span class="dash-hero-pill"><i class="ti ti-credit-card"></i> Кредит вільно: ${fmtMoney(creditAvail, 'UAH')}</span>` : ''}
            ${recurringTotal > 0 ? `<span class="dash-hero-pill warn" data-go="recurring"><i class="ti ti-calendar-repeat"></i> Платежі: ${fmtMoney(recurringTotal, 'UAH')}</span>` : ''}
            <span class="dash-hero-pill ${savRate >= 0 ? 'pos' : 'neg'}">
              <i class="ti ${savRate >= 0 ? 'ti-trending-up' : 'ti-trending-down'}"></i>
              ${savRate}% накопичено
            </span>
            <span class="dash-hero-month">${esc(periodLabel)}</span>
          </div>
        </div>
      </div>

      <!-- Швидкі дії -->
      <div class="dash-quick-actions">
        <button class="quick-action" data-quick="income"><i class="ti ti-arrow-down-circle"></i><span>Дохід</span></button>
        <button class="quick-action" data-quick="expense"><i class="ti ti-arrow-up-circle"></i><span>Витрата</span></button>
        <button class="quick-action" data-quick="transfer"><i class="ti ti-arrows-exchange"></i><span>Переказ</span></button>
        <button class="quick-action" data-quick="exchange"><i class="ti ti-currency-dollar"></i><span>Обмін</span></button>
        <button class="quick-action" data-quick="scanner"><i class="ti ti-scan"></i><span>Сканер</span></button>
      </div>

      <!-- Грід -->
      <div class="dash-grid">
        <div class="dash-col">
          <div class="dash-card dash-stat-card">
            <div class="dash-card-head">
              <span class="dash-card-title">Витрати · ${esc(periodLabel)}</span>
              <span class="dash-card-amount c-red">${fmtMoney(totalExpense, 'UAH')}</span>
            </div>
            ${renderSparkline(byDayView, 'red')}
          </div>

          <div class="dash-card dash-stat-card">
            <div class="dash-card-head">
              <span class="dash-card-title">Доходи · ${esc(periodLabel)}</span>
              <span class="dash-card-amount c-green">${fmtMoney(totalIncome, 'UAH')}</span>
            </div>
            ${renderSparkline(byDayIncomeView, 'green')}
          </div>

          ${renderFxCard()}
          ${renderForecastCard(totalExpense, totalIncome)}
          ${renderCategoriesBlock(d, byCategoryView, totalExpense)}
        </div>

        <div class="dash-col">
          <!-- Кошельки -->
          <div class="dash-card dash-wallets-card">
            <div class="dash-card-head">
              <span class="dash-card-title">Кошельки${viewAs ? ' · ' + esc(profiles[viewAs]?.name || viewAs) : ''}</span>
              <div class="dash-card-actions">
                <button class="dash-card-icon-btn" data-config="wallets" title="Налаштувати"><i class="ti ti-adjustments"></i></button>
                <a href="#" class="dash-card-action" data-go="wallets">Усі →</a>
              </div>
            </div>
            ${renderWalletsBlock(viewAs)}
          </div>

          <!-- НОВЕ: Кредитні картки -->
          ${renderCreditCardsBlock(viewAs)}

          <!-- НОВЕ: Найближчі платежі -->
          ${renderUpcomingPaymentsBlock(viewAs)}

          ${renderRecentBlock(d.recent || [], viewAs)}
        </div>
      </div>
    </div>
  `;

  bindHandlers(el);

  // Алерт по кредитках (один раз при завантаженні)
  const alerts = getCreditAlerts();
  if (alerts.length && !state._creditAlertShown) {
    state._creditAlertShown = true;
    setTimeout(() => showToast(alerts[0].message, 'error'), 1000);
  }
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
  if (!days.length) return `<div class="sparkline-empty">Немає даних</div>`;
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

// ── Блок кошельків ──────────────────────────────────────────
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
      ? '<div class="empty-mini">Усі кошельки приховано. Натисни ⚙ щоб налаштувати.</div>'
      : '<div class="empty-mini">Жодного кошелька. Додай на сторінці Кошельки.</div>';
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

// ── Діалог налаштування видимих кошельків ───────────────────
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
      title: 'Кошельки на дашборді',
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
