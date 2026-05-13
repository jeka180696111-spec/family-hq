// ═══════════════════════════════════════════════════════════════
// OPERATIONS LIST — сторінка зі списком операцій
// ═══════════════════════════════════════════════════════════════

import { FAMILY_MEMBERS, state } from './config.js';
import { apiGet } from './api.js';
import { esc, fmtMoney, fmtDate, monthKey } from './utils.js';
import { openOperationDialog } from './operations.js';
import { getProfiles } from './storage.js';

export async function loadOperations() {
  try {
    const cur = state.currentMonth instanceof Date ? state.currentMonth : new Date();
    const data = await apiGet('operations', { month: monthKey(cur), limit: 500 });
    state.operations = data.operations || [];
  } catch (e) {
    state.operations = [];
  }
  renderOperationsPage();
}

export function renderOperationsPage() {
  const el = document.getElementById('page-operations');
  if (!el) return;

  const profiles = getProfiles();
  let ops = state.operations || [];

  // Фільтри
  const f = state.opFilter || { who: 'all', type: 'all' };
  if (f.who !== 'all') ops = ops.filter(o => o.who === f.who);
  if (f.type !== 'all') ops = ops.filter(o => o.type === f.type);

  // Групуємо за датою
  const byDate = {};
  ops.forEach(o => {
    const k = fmtDate(o.date);
    if (!byDate[k]) byDate[k] = [];
    byDate[k].push(o);
  });

  const cur = state.currentMonth instanceof Date ? state.currentMonth : new Date();
  const monthLabel = cur.toLocaleDateString('uk-UA', { month: 'long', year: 'numeric' });

  el.innerHTML = `
    <div class="page-inner">
      <div class="page-head">
        <h1 class="page-title">Операції</h1>
        <div class="month-switcher">
          <button class="btn-icon" data-month="prev"><i class="ti ti-chevron-left"></i></button>
          <span class="month-label">${esc(monthLabel)}</span>
          <button class="btn-icon" data-month="next"><i class="ti ti-chevron-right"></i></button>
        </div>
      </div>

      <div class="ops-filters">
        <div class="wallets-filter-chips">
          <button class="chip ${f.who === 'all' ? 'active' : ''}" data-filter-who="all">Усі</button>
          ${FAMILY_MEMBERS.map(m => `
            <button class="chip ${f.who === m ? 'active' : ''}" data-filter-who="${esc(m)}">${esc(profiles[m]?.name || m)}</button>
          `).join('')}
        </div>
        <div class="wallets-filter-chips">
          <button class="chip ${f.type === 'all' ? 'active' : ''}" data-filter-type="all">Усі типи</button>
          <button class="chip ${f.type === 'Дохід' ? 'active' : ''}" data-filter-type="Дохід"><i class="ti ti-arrow-down-circle"></i> Дохід</button>
          <button class="chip ${f.type === 'Витрата' ? 'active' : ''}" data-filter-type="Витрата"><i class="ti ti-arrow-up-circle"></i> Витрата</button>
          <button class="chip ${f.type === 'Переказ' ? 'active' : ''}" data-filter-type="Переказ"><i class="ti ti-arrows-exchange"></i> Переказ</button>
        </div>
      </div>

      ${ops.length === 0 ? `
        <div class="empty-state">
          <i class="ti ti-list" style="font-size:48px;color:var(--c-text-3);opacity:.5;"></i>
          <div class="empty-state-title">Жодної операції</div>
          <div class="empty-state-text">Додай через "+"</div>
        </div>
      ` : `
        <div class="ops-list">
          ${Object.entries(byDate).map(([date, items]) => `
            <div class="ops-group">
              <div class="ops-group-date">${esc(date)}</div>
              ${items.map(op => renderOpItem(op)).join('')}
            </div>
          `).join('')}
        </div>
      `}
    </div>
  `;

  bindHandlers(el);
}

function renderOpItem(op) {
  const isExp = op.type === 'Витрата';
  const isInc = op.type === 'Дохід';
  const isTr = op.type === 'Переказ';
  const colorCls = isExp ? 'red' : isInc ? 'green' : 'blue';
  const iconCls = isExp ? 'ti-arrow-up' : isInc ? 'ti-arrow-down' : 'ti-arrows-exchange';
  const sign = isExp ? '−' : isInc ? '+' : '';
  return `
    <div class="op-item" data-op-row="${op.row}">
      <div class="op-item-icon bg-${colorCls}">
        <i class="ti ${iconCls}"></i>
      </div>
      <div class="op-item-info">
        <div class="op-item-name">${esc(op.category || '—')}${op.desc ? ` · ${esc(op.desc)}` : ''}</div>
        <div class="op-item-meta">${esc(op.who || '')}${op.card ? ` · ${esc(op.card)}` : ''}</div>
      </div>
      <div class="op-item-amount c-${colorCls === 'red' ? 'red' : 'green'}">
        ${sign}${fmtMoney(op.amount, op.currency)}
      </div>
    </div>
  `;
}

function bindHandlers(el) {
  // Фільтри
  el.querySelectorAll('[data-filter-who]').forEach(b => {
    b.addEventListener('click', () => {
      state.opFilter = state.opFilter || { who: 'all', type: 'all' };
      state.opFilter.who = b.dataset.filterWho;
      renderOperationsPage();
    });
  });
  el.querySelectorAll('[data-filter-type]').forEach(b => {
    b.addEventListener('click', () => {
      state.opFilter = state.opFilter || { who: 'all', type: 'all' };
      state.opFilter.type = b.dataset.filterType;
      renderOperationsPage();
    });
  });
  // Місяць
  el.querySelector('[data-month="prev"]')?.addEventListener('click', () => {
    const d = state.currentMonth instanceof Date ? state.currentMonth : new Date();
    state.currentMonth = new Date(d.getFullYear(), d.getMonth() - 1, 1);
    loadOperations();
  });
  el.querySelector('[data-month="next"]')?.addEventListener('click', () => {
    const d = state.currentMonth instanceof Date ? state.currentMonth : new Date();
    state.currentMonth = new Date(d.getFullYear(), d.getMonth() + 1, 1);
    loadOperations();
  });
  // Клік на операцію — редагування
  el.querySelectorAll('.op-item').forEach(item => {
    item.addEventListener('click', () => {
      const row = parseInt(item.dataset.opRow);
      const op = state.operations.find(o => o.row === row);
      if (op) openOperationDialog({ type: op.type, editing: op });
    });
  });
}
