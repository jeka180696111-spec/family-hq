// ═══════════════════════════════════════════════════════════════
// OPERATIONS LIST — сторінка зі списком операцій + календарем
// ═══════════════════════════════════════════════════════════════

import { FAMILY_MEMBERS, state } from './config.js';
import { apiGet } from './api.js';
import { esc, fmtMoney, fmtMoneyShort, fmtDate, monthKey } from './utils.js';
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

  // Режим: 'list' | 'calendar'
  if (!state.opsView) state.opsView = 'list';

  const profiles = getProfiles();
  let ops = state.operations || [];

  // Сортуємо: нові зверху (за датою, потім за часом створення)
  ops = [...ops].sort((a, b) => {
    // Спочатку по даті (DESC)
    const dateA = a.date || '';
    const dateB = b.date || '';
    if (dateA !== dateB) return dateB.localeCompare(dateA);
    // Якщо дата однакова — по часу створення (DESC)
    const timeA = a.createdAt || '';
    const timeB = b.createdAt || '';
    return timeB.localeCompare(timeA);
  });

  const f = state.opFilter || { who: 'all', type: 'all' };
  if (f.who !== 'all') ops = ops.filter(o => o.who === f.who);
  if (f.type !== 'all') ops = ops.filter(o => o.type === f.type);

  const cur = state.currentMonth instanceof Date ? state.currentMonth : new Date();
  const monthLabel = cur.toLocaleDateString('uk-UA', { month: 'long', year: 'numeric' });

  // Підсумок місяця — БЕЗ переказів!
  const realOps = ops.filter(o => o.category !== 'Переказ');
  const totalInc = realOps.filter(o => o.type === 'Дохід').reduce((s, o) => s + (o.amountUah || o.amount || 0), 0);
  const totalExp = realOps.filter(o => o.type === 'Витрата').reduce((s, o) => s + (o.amountUah || o.amount || 0), 0);

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

      <!-- Сумарка місяця -->
      <div class="ops-summary">
        <div class="ops-summary-item ops-summary-inc">
          <div class="ops-summary-label">Доходи</div>
          <div class="ops-summary-amount">+${fmtMoney(totalInc, 'UAH')}</div>
        </div>
        <div class="ops-summary-item ops-summary-exp">
          <div class="ops-summary-label">Витрати</div>
          <div class="ops-summary-amount">−${fmtMoney(totalExp, 'UAH')}</div>
        </div>
        <div class="ops-summary-item ops-summary-bal">
          <div class="ops-summary-label">Баланс</div>
          <div class="ops-summary-amount ${totalInc - totalExp >= 0 ? 'c-green' : 'c-red'}">${totalInc - totalExp >= 0 ? '+' : '−'}${fmtMoney(Math.abs(totalInc - totalExp), 'UAH')}</div>
        </div>
      </div>

      <!-- Перемикач Список / Календар -->
      <div class="ops-view-switch">
        <button class="ops-view-btn ${state.opsView === 'list' ? 'active' : ''}" data-view="list">
          <i class="ti ti-list"></i> Список
        </button>
        <button class="ops-view-btn ${state.opsView === 'calendar' ? 'active' : ''}" data-view="calendar">
          <i class="ti ti-calendar-month"></i> Календар
        </button>
      </div>

      <!-- Фільтри -->
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

      <div id="ops-content">
        ${state.opsView === 'calendar' ? renderCalendarView(ops, cur) : renderListView(ops)}
      </div>
    </div>
  `;

  bindHandlers(el);
}

// ── Вид списком ─────────────────────────────────────────────
function renderListView(ops) {
  if (!ops.length) {
    return `
      <div class="empty-state">
        <i class="ti ti-list" style="font-size:48px;color:var(--c-text-3);opacity:.5;"></i>
        <div class="empty-state-title">Жодної операції</div>
        <div class="empty-state-text">Додай через "+"</div>
      </div>
    `;
  }

  // Групуємо за датою (DESC)
  const byDate = {};
  ops.forEach(o => {
    const k = fmtDate(o.date);
    if (!byDate[k]) byDate[k] = [];
    byDate[k].push(o);
  });

  const dateKeys = Object.keys(byDate).sort((a, b) => {
    // Парсимо DD.MM.YYYY
    const pa = a.split('.').reverse().join('-');
    const pb = b.split('.').reverse().join('-');
    return pb.localeCompare(pa);
  });

  return `
    <div class="ops-list">
      ${dateKeys.map(date => `
        <div class="ops-group">
          <div class="ops-group-date">${esc(date)}</div>
          ${byDate[date].map(op => renderOpItem(op)).join('')}
        </div>
      `).join('')}
    </div>
  `;
}

// ── Вид календарем ──────────────────────────────────────────
function renderCalendarView(ops, monthDate) {
  const year = monthDate.getFullYear();
  const month = monthDate.getMonth();
  const firstDay = new Date(year, month, 1);
  const lastDay = new Date(year, month + 1, 0);
  const daysInMonth = lastDay.getDate();

  // День тижня першого дня (ПН=0, ВС=6)
  let firstWeekday = firstDay.getDay() - 1;
  if (firstWeekday < 0) firstWeekday = 6;

  // Підраховуємо суми по днях (БЕЗ переказів!)
  const byDay = {}; // { 1: {inc, exp}, ... }
  ops.forEach(o => {
    if (o.category === 'Переказ') return; // переказы не враховуємо
    const d = new Date(o.date);
    if (d.getMonth() !== month || d.getFullYear() !== year) return;
    const day = d.getDate();
    if (!byDay[day]) byDay[day] = { inc: 0, exp: 0, count: 0 };
    if (o.type === 'Дохід') byDay[day].inc += (o.amountUah || o.amount || 0);
    if (o.type === 'Витрата') byDay[day].exp += (o.amountUah || o.amount || 0);
    byDay[day].count++;
  });

  // Максимальна витрата за день (для heatmap)
  const maxExp = Math.max(...Object.values(byDay).map(d => d.exp), 1);

  // Заголовки днів тижня
  const weekdays = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Нд'];

  let cells = '';
  // Порожні клітинки перед першим днем
  for (let i = 0; i < firstWeekday; i++) {
    cells += `<div class="cal-cell cal-empty"></div>`;
  }

  const today = new Date();
  const isCurrentMonth = today.getMonth() === month && today.getFullYear() === year;

  for (let day = 1; day <= daysInMonth; day++) {
    const dayData = byDay[day];
    const intensity = dayData ? Math.min(1, dayData.exp / maxExp) : 0;
    const isToday = isCurrentMonth && day === today.getDate();
    const isSelected = state.selectedCalDay === day;
    const dayOfWeek = (firstWeekday + day - 1) % 7;
    const isWeekend = dayOfWeek === 5 || dayOfWeek === 6;

    cells += `
      <div class="cal-cell ${dayData ? 'has-data' : ''} ${isToday ? 'today' : ''} ${isSelected ? 'selected' : ''} ${isWeekend ? 'weekend' : ''}"
        data-day="${day}"
        style="${dayData ? `--heat:${intensity}` : ''}">
        <div class="cal-day-num">${day}</div>
        ${dayData ? `
          <div class="cal-day-info">
            ${dayData.exp > 0 ? `<div class="cal-exp">−${fmtMoneyShort(dayData.exp, 'UAH')}</div>` : ''}
            ${dayData.inc > 0 ? `<div class="cal-inc">+${fmtMoneyShort(dayData.inc, 'UAH')}</div>` : ''}
          </div>
        ` : ''}
      </div>
    `;
  }

  // Деталі обраного дня
  let dayDetails = '';
  if (state.selectedCalDay) {
    const dayOps = ops.filter(o => {
      const d = new Date(o.date);
      return d.getMonth() === month && d.getFullYear() === year && d.getDate() === state.selectedCalDay;
    }).sort((a, b) => new Date(b.date) - new Date(a.date));

    if (dayOps.length) {
      dayDetails = `
        <div class="cal-day-details">
          <div class="cal-day-details-head">${state.selectedCalDay} ${monthDate.toLocaleDateString('uk-UA', { month: 'long' })}</div>
          ${dayOps.map(op => renderOpItem(op)).join('')}
        </div>
      `;
    } else {
      dayDetails = `
        <div class="cal-day-details">
          <div class="cal-day-details-head">${state.selectedCalDay} ${monthDate.toLocaleDateString('uk-UA', { month: 'long' })}</div>
          <div class="empty-mini">Жодної операції цього дня</div>
        </div>
      `;
    }
  }

  return `
    <div class="cal-wrap">
      <div class="cal-weekdays">
        ${weekdays.map(d => `<div class="cal-weekday">${d}</div>`).join('')}
      </div>
      <div class="cal-grid">
        ${cells}
      </div>
      ${dayDetails}
    </div>
  `;
}

function renderOpItem(op) {
  const isExp = op.type === 'Витрата';
  const isInc = op.type === 'Дохід';
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
  // Перемикач Список / Календар
  el.querySelectorAll('[data-view]').forEach(b => {
    b.addEventListener('click', () => {
      state.opsView = b.dataset.view;
      state.selectedCalDay = null;
      renderOperationsPage();
    });
  });

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
    state.selectedCalDay = null;
    loadOperations();
  });
  el.querySelector('[data-month="next"]')?.addEventListener('click', () => {
    const d = state.currentMonth instanceof Date ? state.currentMonth : new Date();
    state.currentMonth = new Date(d.getFullYear(), d.getMonth() + 1, 1);
    state.selectedCalDay = null;
    loadOperations();
  });

  // Клік на день календаря
  el.querySelectorAll('.cal-cell[data-day]').forEach(cell => {
    cell.addEventListener('click', () => {
      const day = parseInt(cell.dataset.day);
      // Тоглимо: вдруге клік по тому ж дню — закриваємо
      state.selectedCalDay = state.selectedCalDay === day ? null : day;
      renderOperationsPage();
    });
  });

  // Клік на операцію — редагування
  el.querySelectorAll('.op-item').forEach(item => {
    item.addEventListener('click', () => {
      const row = item.dataset.opRow;
      const op = state.operations.find(o => String(o.row) === String(row) || String(o.id) === String(row));
      if (op) openOperationDialog({ type: op.type, editing: op });
    });
  });
}
