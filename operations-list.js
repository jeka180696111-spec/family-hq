// ═══════════════════════════════════════════════════════════════
// OPERATIONS LIST — сторінка зі списком операцій + календарем
// ═══════════════════════════════════════════════════════════════

import { FAMILY_MEMBERS, state } from './config.js';
import { apiGet } from './api.js';
import { esc, fmtMoney, fmtMoneyShort, fmtDate, monthKey, showToast } from './utils.js';
import { openOperationDialog } from './operations.js';
import { getProfiles, getViewAsMember, getExpCats, getIncCats } from './storage.js';
import { addLongPress, addSwipeDelete } from './gestures.js';

export async function loadOperations() {
  try {
    const cur = state.currentMonth instanceof Date ? state.currentMonth : new Date();
    const data = await apiGet('operations', { month: monthKey(cur), limit: 50 });
    state.operations = data.operations || [];
    state.opsAllLoaded = (data.operations || []).length < 50;
  } catch (e) {
    state.operations = [];
    state.opsAllLoaded = true;
  }
  renderOperationsPage();
}

export function renderOperationsPage() {
  const el = document.getElementById('page-operations');
  if (!el) return;

  // Режим: 'list' | 'calendar'
  if (!state.opsView) state.opsView = 'list';

  const profiles = getProfiles();
  const allOps = state.operations || [];
  const ops = getFilteredOps();
  const f = state.opFilter || { who: 'all', type: 'all', cat: 'all', card: 'all' };
  const viewAs = getViewAsMember();
  const effectiveWho = f.who !== 'all' ? f.who : (viewAs || 'all');
  const searchQ = (state.opSearch || '').trim().toLowerCase();

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

      <!-- Пошук -->
      <input class="ops-search-input" id="ops-search" type="search" placeholder="Пошук операцій..." value="${esc(state.opSearch || '')}">

      <!-- Фільтри -->
      <div class="ops-filters">
        <div class="wallets-filter-chips">
          <button class="chip ${effectiveWho === 'all' ? 'active' : ''}" data-filter-who="all">Усі</button>
          ${FAMILY_MEMBERS.map(m => `
            <button class="chip ${effectiveWho === m ? 'active' : ''}" data-filter-who="${esc(m)}">${esc(profiles[m]?.name || m)}</button>
          `).join('')}
        </div>
        <div class="wallets-filter-chips">
          <button class="chip ${f.type === 'all' ? 'active' : ''}" data-filter-type="all">Усі типи</button>
          <button class="chip ${f.type === 'Дохід' ? 'active' : ''}" data-filter-type="Дохід"><i class="ti ti-arrow-down-circle"></i> Дохід</button>
          <button class="chip ${f.type === 'Витрата' ? 'active' : ''}" data-filter-type="Витрата"><i class="ti ti-arrow-up-circle"></i> Витрата</button>
          <button class="chip ${f.type === 'Переказ' ? 'active' : ''}" data-filter-type="Переказ"><i class="ti ti-arrows-exchange"></i> Переказ</button>
        </div>
        ${(() => {
          const cats = [...new Set(allOps.map(o => o.category).filter(Boolean))].sort();
          if (cats.length <= 3) return '';
          const curCat = f.cat || 'all';
          return `<div class="wallets-filter-chips" id="filter-cats-row">
            <button class="chip ${curCat === 'all' ? 'active' : ''}" data-filter-cat="all">Всі</button>
            ${cats.map(c => `<button class="chip ${curCat === c ? 'active' : ''}" data-filter-cat="${esc(c)}">${esc(c)}</button>`).join('')}
          </div>`;
        })()}
        ${(() => {
          const cards = [...new Set(allOps.map(o => o.card).filter(Boolean))].sort();
          if (cards.length <= 3) return '';
          const curCard = f.card || 'all';
          return `<div class="wallets-filter-chips" id="filter-cards-row">
            <button class="chip ${curCard === 'all' ? 'active' : ''}" data-filter-card="all">Всі</button>
            ${cards.map(c => `<button class="chip ${curCard === c ? 'active' : ''}" data-filter-card="${esc(c)}">${esc(c)}</button>`).join('')}
          </div>`;
        })()}
      </div>

      <div id="ops-content">
        ${state.opsView === 'calendar' ? renderCalendarView(ops, cur) : renderListView(ops)}
        ${state.opsView === 'list' && !state.opsAllLoaded && !searchQ
          ? `<button class="btn-ghost ops-load-more">Завантажити ще...</button>`
          : ''}
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
        <div class="empty-state-illustration">📊</div>
        <div class="empty-state-title">Немає операцій</div>
        <div class="empty-state-text">Додай першу витрату або дохід через «+»</div>
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

function getCatStyle(op) {
  const cats = op.type === 'Дохід' ? getIncCats() : getExpCats();
  const cat = cats.find(c => (c.id || c.name || c) === op.category);
  if (cat && cat.icon && cat.bg) return { icon: cat.icon, bg: cat.bg, color: cat.color };
  if (op.type === 'Дохід') return { icon: 'ti-arrow-down', bg: 'var(--c-green-soft)', color: 'var(--c-green)' };
  if (op.type === 'Переказ') return { icon: 'ti-arrows-exchange', bg: 'var(--c-blue-soft)', color: 'var(--c-blue)' };
  return { icon: 'ti-arrow-up', bg: 'var(--c-red-soft)', color: 'var(--c-red)' };
}

function renderOpItem(op) {
  const isExp = op.type === 'Витрата';
  const isInc = op.type === 'Дохід';
  const sign = isExp ? '−' : isInc ? '+' : '';
  const style = getCatStyle(op);
  const mainAmount = `${sign}${fmtMoney(op.amount, op.currency)}`;
  const subAmount = op.amountUah && op.currency !== 'UAH'
    ? `≈ ${fmtMoney(op.amountUah, 'UAH')}`
    : '';
  const amountColor = isExp ? 'var(--c-red)' : isInc ? 'var(--c-green)' : 'var(--c-blue)';
  return `
    <div class="op-item" data-op-row="${op.row}">
      <div class="op-item-icon" style="background:${style.bg}">
        <i class="ti ${style.icon}" style="color:${style.color}"></i>
      </div>
      <div class="op-item-info">
        <div class="op-item-name">${esc(op.category || '—')}${op.desc ? ` · ${esc(op.desc)}` : ''}</div>
        <div class="op-item-meta">${esc(op.who || '')}${op.card ? ` · ${esc(op.card)}` : ''}</div>
      </div>
      <div class="op-item-right">
        <div class="op-item-amount" style="color:${amountColor}">${mainAmount}</div>
        ${subAmount ? `<div class="op-item-amount-sub">${subAmount}</div>` : ''}
      </div>
    </div>
  `;
}

function getFilteredOps() {
  let ops = [...(state.operations || [])].sort((a, b) => {
    const dateA = a.date || '', dateB = b.date || '';
    if (dateA !== dateB) return dateB.localeCompare(dateA);
    return (b.createdAt || '').localeCompare(a.createdAt || '');
  });
  const f = state.opFilter || { who: 'all', type: 'all', cat: 'all', card: 'all' };
  const viewAs = getViewAsMember();
  const effectiveWho = f.who !== 'all' ? f.who : (viewAs || 'all');
  if (effectiveWho !== 'all') ops = ops.filter(o => o.who === effectiveWho);
  if (f.type !== 'all') ops = ops.filter(o => o.type === f.type);
  if (f.cat && f.cat !== 'all') ops = ops.filter(o => o.category === f.cat);
  if (f.card && f.card !== 'all') ops = ops.filter(o => o.card === f.card);
  const searchQ = (state.opSearch || '').trim().toLowerCase();
  if (searchQ) ops = ops.filter(o =>
    (o.category || '').toLowerCase().includes(searchQ) ||
    (o.desc     || '').toLowerCase().includes(searchQ) ||
    (o.who      || '').toLowerCase().includes(searchQ) ||
    (o.card     || '').toLowerCase().includes(searchQ)
  );
  return ops;
}

function refreshOpsContent() {
  const content = document.getElementById('ops-content');
  if (!content) return;
  const ops = getFilteredOps();
  const cur = state.currentMonth instanceof Date ? state.currentMonth : new Date();
  content.innerHTML = state.opsView === 'calendar' ? renderCalendarView(ops, cur) : renderListView(ops);
  // re-bind op clicks and calendar day clicks
  content.querySelectorAll('.op-item').forEach(item => {
    item.addEventListener('click', () => {
      const row = item.dataset.opRow;
      const op = state.operations.find(o => String(o.row) === String(row) || String(o.id) === String(row));
      if (op) openOperationDialog({ type: op.type, editing: op });
    });

    // Long press → edit
    addLongPress(item, () => {
      const row = item.dataset.opRow;
      const op = (state.operations || []).find(o => String(o.row || o.id) === String(row));
      if (op) openOperationDialog({ type: op.type, editing: op });
    });

    // Swipe left → delete
    addSwipeDelete(item, async () => {
      const row = item.dataset.opRow;
      const op = (state.operations || []).find(o => String(o.row || o.id) === String(row));
      if (!op) return;
      const { confirmModal } = await import('./modals.js');
      const ok = await confirmModal('Видалити операцію?', { danger: true, okText: 'Видалити' });
      if (!ok) return;
      const { apiPost } = await import('./api.js');
      await apiPost({ action: 'deleteOperation', row: op.row || op.id });
      state.operations = state.operations.filter(o => String(o.row || o.id) !== String(op.row || op.id));
      refreshOpsContent();
      if (window.refreshDashboard) window.refreshDashboard();
    });
  });
  content.querySelectorAll('.cal-cell[data-day]').forEach(cell => {
    cell.addEventListener('click', () => {
      const day = parseInt(cell.dataset.day);
      state.selectedCalDay = state.selectedCalDay === day ? null : day;
      refreshOpsContent();
    });
  });
  const loadMoreBtn = content.querySelector('#ops-load-more');
  if (loadMoreBtn) {
    loadMoreBtn.addEventListener('click', async () => {
      loadMoreBtn.disabled = true;
      loadMoreBtn.textContent = 'Завантаження...';
      const monthKey2 = (() => { const d = state.currentMonth instanceof Date ? state.currentMonth : new Date(); return d.getFullYear() + '-' + String(d.getMonth()+1).padStart(2,'0'); })();
      const more = await import('./api.js').then(m => m.apiGet('operations', { month: monthKey2, limit: 50, offset: state.operations.length }));
      if (more.operations?.length) {
        state.operations = [...state.operations, ...more.operations];
        if (more.operations.length < 50) state.opsAllLoaded = true;
      } else { state.opsAllLoaded = true; }
      refreshOpsContent();
    });
  }
}

function filterOpsInPlace(q) {
  q = (q || '').trim().toLowerCase();
  document.querySelectorAll('#ops-content .op-item').forEach(item => {
    if (!q) { item.style.display = ''; return; }
    const row = item.dataset.opRow;
    const op = (state.operations || []).find(o => String(o.row || o.id) === String(row));
    const matches = op && (
      (op.category || '').toLowerCase().includes(q) ||
      (op.desc     || '').toLowerCase().includes(q) ||
      (op.who      || '').toLowerCase().includes(q) ||
      (op.card     || '').toLowerCase().includes(q)
    );
    item.style.display = (matches || !op) ? '' : 'none';
  });
  document.querySelectorAll('#ops-content .ops-group').forEach(group => {
    const anyVisible = [...group.querySelectorAll('.op-item')].some(i => i.style.display !== 'none');
    group.style.display = anyVisible ? '' : 'none';
  });
}

function bindHandlers(el) {
  // Пошук — тільки CSS show/hide, DOM не змінюється → клавіатура не ховається
  el.querySelector('#ops-search')?.addEventListener('input', e => {
    state.opSearch = e.target.value;
    filterOpsInPlace(e.target.value);
  });

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
      state.opFilter = state.opFilter || { who: 'all', type: 'all', cat: 'all', card: 'all' };
      state.opFilter.who = b.dataset.filterWho;
      renderOperationsPage();
    });
  });
  el.querySelectorAll('[data-filter-type]').forEach(b => {
    b.addEventListener('click', () => {
      state.opFilter = state.opFilter || { who: 'all', type: 'all', cat: 'all', card: 'all' };
      state.opFilter.type = b.dataset.filterType;
      renderOperationsPage();
    });
  });
  el.querySelectorAll('[data-filter-cat]').forEach(b => {
    b.addEventListener('click', () => {
      state.opFilter = state.opFilter || { who: 'all', type: 'all', cat: 'all', card: 'all' };
      state.opFilter.cat = b.dataset.filterCat;
      renderOperationsPage();
    });
  });
  el.querySelectorAll('[data-filter-card]').forEach(b => {
    b.addEventListener('click', () => {
      state.opFilter = state.opFilter || { who: 'all', type: 'all', cat: 'all', card: 'all' };
      state.opFilter.card = b.dataset.filterCard;
      renderOperationsPage();
    });
  });

  // Місяць
  el.querySelector('[data-month="prev"]')?.addEventListener('click', () => {
    const d = state.currentMonth instanceof Date ? state.currentMonth : new Date();
    state.currentMonth = new Date(d.getFullYear(), d.getMonth() - 1, 1);
    state.selectedCalDay = null;
    state.opsAllLoaded = false;
    loadOperations();
  });
  el.querySelector('[data-month="next"]')?.addEventListener('click', () => {
    const d = state.currentMonth instanceof Date ? state.currentMonth : new Date();
    state.currentMonth = new Date(d.getFullYear(), d.getMonth() + 1, 1);
    state.selectedCalDay = null;
    state.opsAllLoaded = false;
    loadOperations();
  });

  // Завантажити ще
  el.querySelector('.ops-load-more')?.addEventListener('click', async () => {
    const btn = el.querySelector('.ops-load-more');
    if (btn) { btn.disabled = true; btn.textContent = 'Завантаження...'; }
    try {
      const cur = state.currentMonth instanceof Date ? state.currentMonth : new Date();
      const data = await apiGet('operations', { month: monthKey(cur), limit: 50, offset: state.operations.length });
      const newOps = data.operations || [];
      state.operations = [...state.operations, ...newOps];
      if (newOps.length === 0) state.opsAllLoaded = true;
      else if (newOps.length < 50) state.opsAllLoaded = true;
    } catch (e) {
      state.opsAllLoaded = true;
    }
    renderOperationsPage();
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

  // Клік на операцію — редагування + жести
  el.querySelectorAll('.op-item').forEach(item => {
    item.addEventListener('click', () => {
      const row = item.dataset.opRow;
      const op = state.operations.find(o => String(o.row) === String(row) || String(o.id) === String(row));
      if (op) openOperationDialog({ type: op.type, editing: op });
    });

    // Long press → edit
    addLongPress(item, () => {
      const row = item.dataset.opRow;
      const op = (state.operations || []).find(o => String(o.row || o.id) === String(row));
      if (op) openOperationDialog({ type: op.type, editing: op });
    });

    // Swipe left → delete
    addSwipeDelete(item, async () => {
      const row = item.dataset.opRow;
      const op = (state.operations || []).find(o => String(o.row || o.id) === String(row));
      if (!op) return;
      const { confirmModal } = await import('./modals.js');
      const ok = await confirmModal('Видалити операцію?', { danger: true, okText: 'Видалити' });
      if (!ok) return;
      const { apiPost } = await import('./api.js');
      await apiPost({ action: 'deleteOperation', row: op.row || op.id });
      state.operations = state.operations.filter(o => String(o.row || o.id) !== String(op.row || op.id));
      refreshOpsContent();
      if (window.refreshDashboard) window.refreshDashboard();
    });
  });
}
