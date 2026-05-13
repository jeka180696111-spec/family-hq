// ═══════════════════════════════════════════════════════════════
// DASHBOARD — головна сторінка
// ═══════════════════════════════════════════════════════════════

import { FAMILY_MEMBERS, state } from './config.js';
import { getCards, getProfiles, getWalletTypes, getWalletTypeById, getFamilyName } from './storage.js';
import { apiGet } from './api.js';
import { esc, fmtMoney, fmtMoneyShort, setText, fmtDate, monthKey, log } from './utils.js';
import { openOperationDialog } from './operations.js';

// ── Завантаження даних з сервера ────────────────────────────
export async function loadDashboard() {
  try {
    const data = await apiGet('dashboard');
    state.dashboard = data;
    // Зберігаємо час останньої синхронізації
    localStorage.setItem('budget_last_sync', new Date().toISOString());
    renderDashboard();
  } catch (e) {
    log('loadDashboard error:', e.message);
    // Все одно рендеримо що є (offline mode)
    renderDashboard();
  }
}

// Експортуємо щоб FAB міг тригернути перезавантаження
window.refreshDashboard = loadDashboard;

// ── Рендер ──────────────────────────────────────────────────
export function renderDashboard() {
  const el = document.getElementById('page-dashboard');
  if (!el) return;

  const d = state.dashboard || { totalIncome: 0, totalExpense: 0, balance: 0, byMember: {}, byCategory: {}, recent: [] };
  const profiles = getProfiles();

  // Привітання
  const hour = new Date().getHours();
  const greet = hour < 6 ? 'Доброї ночі' : hour < 12 ? 'Доброго ранку' : hour < 18 ? 'Доброго дня' : 'Доброго вечора';
  const myName = profiles[state.user ? whoAmIByEmail(state.user.email) : 'Євген']?.name || 'Друже';

  // Поточний місяць
  const monthName = new Date().toLocaleDateString('uk-UA', { month: 'long', year: 'numeric' });

  el.innerHTML = `
    <div class="dashboard">
      <!-- HERO: вітання + загальний баланс -->
      <div class="dash-hero">
        <div class="dash-hero-left">
          <div class="dash-greet">${greet}, ${esc(myName)}! 👋</div>
          <div class="dash-hero-label">Загальний баланс</div>
          <div class="dash-hero-balance">${fmtMoney(d.balance || 0, 'UAH')}</div>
          <div class="dash-hero-meta">
            <span class="dash-hero-pill ${d.savingsRate > 0 ? 'pos' : 'neg'}">
              <i class="ti ${d.savingsRate > 0 ? 'ti-trending-up' : 'ti-trending-down'}"></i>
              ${(d.savingsRate || 0).toFixed(0)}% накопичено
            </span>
            <span class="dash-hero-month">${esc(monthName)}</span>
          </div>
        </div>
        <div class="dash-hero-right"></div>
      </div>

      <!-- Швидкі дії (під hero) -->
      <div class="dash-quick-actions">
        <button class="quick-action" data-quick="income"><i class="ti ti-arrow-down-circle"></i><span>Дохід</span></button>
        <button class="quick-action" data-quick="expense"><i class="ti ti-arrow-up-circle"></i><span>Витрата</span></button>
        <button class="quick-action" data-quick="transfer"><i class="ti ti-arrows-exchange"></i><span>Переказ</span></button>
        <button class="quick-action" data-quick="exchange"><i class="ti ti-currency-dollar"></i><span>Обмін</span></button>
      </div>

      <!-- Грід: 2 колонки на десктопі, 1 на мобілці -->
      <div class="dash-grid">
        <!-- Колонка 1: Доходи/Витрати + Категорії -->
        <div class="dash-col">
          <div class="dash-card dash-incomes">
            <div class="dash-card-head">
              <span class="dash-card-title">Доходи місяця</span>
              <span class="dash-card-amount c-green">${fmtMoney(d.totalIncome || 0, 'UAH')}</span>
            </div>
            <div class="dash-mini-bar bar-green"></div>
          </div>

          <div class="dash-card dash-expenses">
            <div class="dash-card-head">
              <span class="dash-card-title">Витрати місяця</span>
              <span class="dash-card-amount c-red">${fmtMoney(d.totalExpense || 0, 'UAH')}</span>
            </div>
            <div class="dash-mini-bar bar-red"></div>
          </div>

          ${renderCategoriesBlock(d)}
        </div>

        <!-- Колонка 2: Кошельки + Останні операції -->
        <div class="dash-col">
          <div class="dash-card dash-wallets-card">
            <div class="dash-card-head">
              <span class="dash-card-title">Кошельки</span>
              <a href="#" class="dash-card-action" data-go="wallets">Усі →</a>
            </div>
            ${renderWalletsBlock()}
          </div>

          ${renderRecentBlock(d.recent || [])}
        </div>
      </div>
    </div>
  `;

  bindHandlers(el);
}

// ── Допоміжний: визначити мене ──────────────────────────────
function whoAmIByEmail(email) {
  if (!email) return 'Євген';
  const e = email.toLowerCase();
  if (e.includes('jeka') || e.includes('zhenya') || e.includes('evgen')) return 'Євген';
  if (e.includes('marina') || e.includes('maryna')) return 'Марина';
  return 'Євген';
}

// ── Блок кошельків ──────────────────────────────────────────
function renderWalletsBlock() {
  const profiles = getProfiles();
  const allCards = [];
  FAMILY_MEMBERS.forEach(m => {
    getCards(m).forEach((c, idx) => allCards.push({ ...c, owner: m, ownerIdx: idx }));
  });

  // Top 5 карт за балансом
  function cardBal(c) {
    const ops = state.operations || [];
    let bal = 0;
    ops.forEach(o => {
      if (o.who === c.owner && o.card === c.id) {
        if (o.type === 'Дохід') bal += (o.amountUah || o.amount || 0);
        if (o.type === 'Витрата') bal -= (o.amountUah || o.amount || 0);
      }
    });
    return bal;
  }

  const cardsWithBal = allCards.map(c => ({ ...c, balance: cardBal(c) }))
    .sort((a, b) => Math.abs(b.balance) - Math.abs(a.balance))
    .slice(0, 5);

  if (!cardsWithBal.length) {
    return '<div class="empty-mini">Жодного кошелька. Додай через "+" або в розділі Кошельки.</div>';
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
            <div class="dash-wallet-owner">${esc(c.owner)}</div>
          </div>
          <div class="dash-wallet-balance ${c.balance >= 0 ? 'pos' : 'neg'}">${fmtMoney(c.balance, 'UAH')}</div>
        </div>
      `).join('')}
    </div>
  `;
}

// ── Блок категорій ──────────────────────────────────────────
function renderCategoriesBlock(d) {
  const byCat = d.byCategory || {};
  const entries = Object.entries(byCat).sort((a, b) => b[1] - a[1]).slice(0, 5);
  const total = d.totalExpense || entries.reduce((s, [, v]) => s + v, 0) || 1;

  if (!entries.length) return '';

  return `
    <div class="dash-card">
      <div class="dash-card-head">
        <span class="dash-card-title">Топ категорій</span>
        <a href="#" class="dash-card-action" data-go="analytics">Аналіз →</a>
      </div>
      <div class="dash-cats-list">
        ${entries.map(([cat, val]) => {
          const pct = (val / total * 100).toFixed(0);
          return `
            <div class="dash-cat-row">
              <div class="dash-cat-name">${esc(cat)}</div>
              <div class="dash-cat-bar"><div class="dash-cat-bar-fill" style="width:${pct}%"></div></div>
              <div class="dash-cat-amount">${fmtMoney(val, 'UAH')}</div>
            </div>
          `;
        }).join('')}
      </div>
    </div>
  `;
}

// ── Блок останніх операцій ──────────────────────────────────
function renderRecentBlock(recent) {
  if (!recent || !recent.length) return '';
  return `
    <div class="dash-card">
      <div class="dash-card-head">
        <span class="dash-card-title">Останні операції</span>
        <a href="#" class="dash-card-action" data-go="operations">Усі →</a>
      </div>
      <div class="dash-recent-list">
        ${recent.slice(0, 5).map(op => {
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

// ── Слухачі ─────────────────────────────────────────────────
function bindHandlers(el) {
  // Швидкі дії
  el.querySelectorAll('[data-quick]').forEach(b => {
    b.addEventListener('click', () => {
      const act = b.dataset.quick;
      if (act === 'income')   openOperationDialog({ type: 'Дохід' });
      else if (act === 'expense')  openOperationDialog({ type: 'Витрата' });
      else if (act === 'transfer') import('./transfer.js').then(t => t.openTransferDialog());
      else if (act === 'exchange') import('./transfer.js').then(t => t.openTransferDialog({ exchange: true }));
    });
  });

  // Навігація
  el.querySelectorAll('[data-go]').forEach(a => {
    a.addEventListener('click', (e) => {
      e.preventDefault();
      import('./main.js').then(m => m.navigateTo(a.dataset.go));
    });
  });

  // Клік на кошельок → перехід до сторінки кошельків
  el.querySelectorAll('.dash-wallet-item').forEach(item => {
    item.addEventListener('click', () => {
      import('./main.js').then(m => m.navigateTo('wallets'));
    });
  });

  // Клік на операцію → редагувати
  el.querySelectorAll('.dash-recent-item').forEach(item => {
    item.addEventListener('click', () => {
      const row = parseInt(item.dataset.opRow);
      const op = (state.dashboard?.recent || []).find(o => o.row === row);
      if (op) openOperationDialog({ type: op.type, editing: op });
    });
  });
}
