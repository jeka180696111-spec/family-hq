// ═══════════════════════════════════════════════════════════════
// RECURRING PAYMENTS — обов'язкові платежі + Telegram нагадування
// ═══════════════════════════════════════════════════════════════

import { state, FAMILY_MEMBERS } from './config.js';
import { fmtMoney, esc, showToast } from './utils.js';
import { getExpCats } from './storage.js';
import { openBottomSheet, closeModal } from './modals.js';

// ── Firestore CRUD ───────────────────────────────────────────
function ref() {
  return firebase.firestore()
    .collection('families').doc(state.familyId)
    .collection('recurringPayments');
}

export async function loadRecurringPayments() {
  try {
    const snap = await ref().orderBy('dayOfMonth').get();
    state.recurringPayments = snap.docs.map(d => ({ id: d.id, ...d.data() }));
  } catch (e) {
    console.warn('loadRecurringPayments:', e);
    state.recurringPayments = state.recurringPayments || [];
  }
  return state.recurringPayments;
}

async function addPayment(data) {
  const doc = await ref().add({ ...data, active: true, createdAt: firebase.firestore.FieldValue.serverTimestamp() });
  data.id = doc.id;
  if (!state.recurringPayments) state.recurringPayments = [];
  state.recurringPayments.push(data);
  return data;
}

async function updatePayment(id, data) {
  await ref().doc(id).update(data);
  const p = (state.recurringPayments || []).find(p => p.id === id);
  if (p) Object.assign(p, data);
}

async function deletePayment(id) {
  await ref().doc(id).delete();
  state.recurringPayments = (state.recurringPayments || []).filter(p => p.id !== id);
}

// ── Модальне вікно ───────────────────────────────────────────
export function openPaymentModal(existing = null) {
  const isEdit = !!existing;
  const cats = getExpCats();
  const modalId = 'rp-modal-' + Date.now();

  const catOpts = cats.map(c =>
    `<option value="${esc(c.id)}" ${existing?.category === c.id ? 'selected' : ''}>${esc(c.id)}</option>`
  ).join('');

  const whoOpts = [...FAMILY_MEMBERS, 'Загальний'].map(m =>
    `<option value="${esc(m)}" ${existing?.who === m ? 'selected' : ''}>${esc(m)}</option>`
  ).join('');

  const html = `
    <div class="modal-head"><div class="modal-title">${isEdit ? 'Редагувати' : 'Новий обов\'язковий платіж'}</div></div>

    <div class="modal-row">
      <label class="modal-label">Назва</label>
      <input type="text" id="rp-name" class="modal-input" placeholder="Квартплата, інтернет..." value="${esc(existing?.name || '')}">
    </div>
    <div class="modal-row">
      <label class="modal-label">Сума (₴)</label>
      <input type="number" id="rp-amount" class="modal-input" placeholder="0" inputmode="decimal" value="${existing?.amount || ''}">
    </div>
    <div class="modal-row-grid">
      <div class="modal-row">
        <label class="modal-label">День місяця</label>
        <input type="number" id="rp-day" class="modal-input" min="1" max="31" placeholder="1-31" value="${existing?.dayOfMonth || ''}">
      </div>
      <div class="modal-row">
        <label class="modal-label">Хто платить</label>
        <select id="rp-who" class="modal-select">${whoOpts}</select>
      </div>
    </div>
    <div class="modal-row">
      <label class="modal-label">Категорія</label>
      <select id="rp-cat" class="modal-select">${catOpts}</select>
    </div>
    <div class="modal-row">
      <label class="modal-label">Картка (необов'язково)</label>
      <input type="text" id="rp-card" class="modal-input" placeholder="Моно чорна" value="${esc(existing?.card || '')}">
    </div>
    <div class="modal-row" style="display:flex;align-items:center;gap:10px;">
      <input type="checkbox" id="rp-tg" ${existing?.notifyTelegram !== false ? 'checked' : ''}>
      <label for="rp-tg" style="font-size:13px;font-weight:600;cursor:pointer;">
        <i class="ti ti-brand-telegram" style="color:#229ED9"></i> Нагадування в Telegram
      </label>
    </div>
    <div class="modal-row-grid">
      <div class="modal-row">
        <label class="modal-label">Нагадати за (днів)</label>
        <input type="number" id="rp-remind" class="modal-input" min="0" max="14" value="${existing?.remindDaysBefore ?? 3}">
      </div>
      <div class="modal-row">
        <label class="modal-label">Повторення</label>
        <select id="rp-freq" class="modal-select">
          <option value="monthly" ${existing?.frequency !== 'yearly' ? 'selected' : ''}>Щомісяця</option>
          <option value="yearly" ${existing?.frequency === 'yearly' ? 'selected' : ''}>Щороку</option>
        </select>
      </div>
    </div>

    <div class="modal-actions">
      ${isEdit ? '<button class="modal-btn modal-btn-danger" id="rp-del"><i class="ti ti-trash"></i></button>' : ''}
      <button class="modal-btn modal-btn-primary" id="rp-save" style="flex:1">${isEdit ? 'Зберегти' : 'Додати'}</button>
    </div>
  `;

  const sheetId = openBottomSheet({ content: html });

  document.getElementById('rp-save')?.addEventListener('click', async () => {
    const name = document.getElementById('rp-name')?.value?.trim();
    const amount = Number(document.getElementById('rp-amount')?.value);
    const dayOfMonth = Number(document.getElementById('rp-day')?.value);
    if (!name) return showToast('Введіть назву', 'error');
    if (!amount || amount <= 0) return showToast('Введіть суму', 'error');
    if (!dayOfMonth || dayOfMonth < 1 || dayOfMonth > 31) return showToast('День 1-31', 'error');

    const data = {
      name, amount, dayOfMonth,
      who: document.getElementById('rp-who')?.value || 'Загальний',
      category: document.getElementById('rp-cat')?.value || 'Комунальні',
      card: document.getElementById('rp-card')?.value || '',
      notifyTelegram: document.getElementById('rp-tg')?.checked ?? true,
      remindDaysBefore: Number(document.getElementById('rp-remind')?.value) || 3,
      frequency: document.getElementById('rp-freq')?.value || 'monthly',
    };

    try {
      if (isEdit) { await updatePayment(existing.id, data); showToast('✅ Оновлено'); }
      else { await addPayment(data); showToast('✅ Додано'); }
      closeModal(sheetId);
      renderRecurringPage();
    } catch (e) { showToast('Помилка: ' + e.message, 'error'); }
  });

  document.getElementById('rp-del')?.addEventListener('click', async () => {
    if (!confirm('Видалити платіж?')) return;
    try {
      await deletePayment(existing.id);
      showToast('Видалено');
      closeModal(sheetId);
      renderRecurringPage();
    } catch (e) { showToast('Помилка: ' + e.message, 'error'); }
  });
}

// ── Рендер сторінки ──────────────────────────────────────────
export function renderRecurringPage() {
  const el = document.getElementById('page-recurring');
  if (!el) return;

  const payments = state.recurringPayments || [];
  const today = new Date().getDate();
  const sorted = [...payments].sort((a, b) => a.dayOfMonth - b.dayOfMonth);
  const upcoming = sorted.filter(p => p.dayOfMonth >= today);
  const passed = sorted.filter(p => p.dayOfMonth < today);
  const monthly = payments.filter(p => p.frequency !== 'yearly').reduce((s, p) => s + (p.amount || 0), 0);

  const daysInMonth = new Date(new Date().getFullYear(), new Date().getMonth() + 1, 0).getDate();
  const monthPct = Math.round((today / daysInMonth) * 100);
  const paidAmt = passed.reduce((s, p) => s + (p.amount || 0), 0);
  const upcomingAmt = upcoming.reduce((s, p) => s + (p.amount || 0), 0);

  el.innerHTML = `
    <div class="page-inner">
      <div class="page-head">
        <h1 class="page-title">Платежі</h1>
        <button class="btn-primary" id="add-rp-btn"><i class="ti ti-plus"></i> Додати</button>
      </div>

      <div class="rp-hero">
        <div class="rp-hero-top">
          <div>
            <div class="rp-hero-label">Щомісяця</div>
            <div class="rp-hero-amount">${fmtMoney(monthly, 'UAH')}</div>
          </div>
          <div class="rp-hero-chips">
            <div class="rp-hero-chip rp-chip-done"><i class="ti ti-check"></i> ${fmtMoney(paidAmt)} сплачено</div>
            <div class="rp-hero-chip rp-chip-up"><i class="ti ti-clock"></i> ${fmtMoney(upcomingAmt)} очікується</div>
          </div>
        </div>
        <div class="rp-month-bar-wrap">
          <div class="rp-month-bar"><div class="rp-month-bar-fill" style="width:${monthPct}%"></div></div>
          <div class="rp-month-bar-label">${today} з ${daysInMonth} дні місяця</div>
        </div>
      </div>

      <div class="rp-kpi-row">
        <div class="rp-kpi"><div class="rp-kpi-label">Всього</div><div class="rp-kpi-val">${payments.length}</div></div>
        <div class="rp-kpi"><div class="rp-kpi-label">Сплачено</div><div class="rp-kpi-val" style="color:var(--c-green)">${passed.length}</div></div>
        <div class="rp-kpi"><div class="rp-kpi-label">Очікується</div><div class="rp-kpi-val" style="color:var(--c-red)">${upcoming.length}</div></div>
      </div>

      ${upcoming.length ? `<div class="rp-section-label"><i class="ti ti-clock"></i> Найближчі</div>${upcoming.map(p => rpItem(p, today)).join('')}` : ''}
      ${passed.length ? `<div class="rp-section-label"><i class="ti ti-check"></i> Цього місяця сплачено</div>${passed.map(p => rpItem(p, today)).join('')}` : ''}
      ${!payments.length ? `<div class="empty-state"><i class="ti ti-calendar-repeat" style="font-size:48px;color:var(--c-text-3)"></i><p style="margin-top:12px;font-weight:600;">Немає обов'язкових платежів</p><p style="font-size:12px;color:var(--c-text-3)">Додайте квартплату, інтернет, підписки</p></div>` : ''}
    </div>
  `;

  document.getElementById('add-rp-btn')?.addEventListener('click', () => openPaymentModal());
  el.querySelectorAll('.rp-item').forEach(item => {
    item.addEventListener('click', () => {
      const p = payments.find(p => p.id === item.dataset.id);
      if (p) openPaymentModal(p);
    });
  });
}

function rpItem(p, today) {
  const d = p.dayOfMonth - today;
  const cat = (getExpCats() || []).find(c => c.id === p.category) || { icon: 'ti-receipt', bg: '#F0F0F0', color: '#555' };
  let badge = '';
  if (d === 0) badge = '<span class="rp-badge rp-today">Сьогодні!</span>';
  else if (d > 0 && d <= 3) badge = `<span class="rp-badge rp-soon">${d} дн.</span>`;
  else if (d < 0) badge = '<span class="rp-badge rp-done">✓</span>';

  return `
    <div class="rp-item ${d === 0 ? 'rp-item-today' : d > 0 && d <= 3 ? 'rp-item-soon' : ''}" data-id="${p.id}">
      <div class="rp-item-icon" style="background:${cat.bg}"><i class="ti ${cat.icon}" style="color:${cat.color}"></i></div>
      <div class="rp-item-info">
        <div class="rp-item-name">${esc(p.name)} ${badge}</div>
        <div class="rp-item-meta">${p.dayOfMonth} числа · ${esc(p.who)}${p.notifyTelegram ? ' · <i class="ti ti-brand-telegram" style="color:#229ED9;font-size:11px"></i>' : ''}</div>
      </div>
      <div class="rp-item-amount">${fmtMoney(p.amount, 'UAH')}</div>
    </div>`;
}

// ── Міні-блок для дашборду ───────────────────────────────────
export function renderUpcomingPaymentsBlock(viewAs) {
  const payments = (state.recurringPayments || [])
    .filter(p => !viewAs || p.who === viewAs || p.who === 'Загальний');
  const today = new Date().getDate();
  const upcoming = payments
    .filter(p => p.dayOfMonth >= today && p.dayOfMonth <= today + 7)
    .sort((a, b) => a.dayOfMonth - b.dayOfMonth)
    .slice(0, 3);

  if (!upcoming.length) return '';

  return `
    <div class="dash-card">
      <div class="dash-card-head">
        <span class="dash-card-title"><i class="ti ti-calendar-due"></i> Найближчі платежі</span>
        <a href="#" class="dash-card-action" data-go="recurring">Всі →</a>
      </div>
      ${upcoming.map(p => {
        const isToday = p.dayOfMonth === today;
        const isTomorrow = p.dayOfMonth === today + 1;
        const extraClass = isToday ? ' rp-dash-item--today' : isTomorrow ? ' rp-dash-item--tomorrow' : '';
        const prefix = isToday ? '🔴 ' : isTomorrow ? '🟡 ' : '';
        return `
        <div class="rp-dash-item${extraClass}">
          <div class="rp-dash-day">${p.dayOfMonth}</div>
          <div class="rp-dash-info">
            <div class="rp-dash-name">${prefix}${esc(p.name)}</div>
            <div class="rp-dash-who">${esc(p.who)}</div>
          </div>
          <div class="rp-dash-amount">${fmtMoney(p.amount, 'UAH')}</div>
        </div>
        `;
      }).join('')}
    </div>`;
}

// ── Нагадування (для Telegram serverless function) ───────────
export function getPaymentReminders() {
  const payments = state.recurringPayments || [];
  const today = new Date().getDate();
  return payments.filter(p => p.notifyTelegram && p.active !== false).map(p => {
    const d = p.dayOfMonth - today;
    if (d === 0) return { type: 'today', payment: p, message: `🔴 Сьогодні: ${p.name} — ${p.amount} ₴ (${p.who})` };
    if (d === 1) return { type: 'tomorrow', payment: p, message: `🟡 Завтра: ${p.name} — ${p.amount} ₴ (${p.who})` };
    if (d > 0 && d <= (p.remindDaysBefore || 3)) return { type: 'upcoming', payment: p, message: `📅 Через ${d} дн: ${p.name} — ${p.amount} ₴` };
    return null;
  }).filter(Boolean);
}
