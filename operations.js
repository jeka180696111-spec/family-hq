// ═══════════════════════════════════════════════════════════════
// OPERATIONS — додавання, редагування операцій
// ═══════════════════════════════════════════════════════════════

import { FAMILY_MEMBERS, state } from './config.js';
import { getCards, getExpCats, getIncCats, getProfiles } from './storage.js';
import { apiPost } from './api.js';
import { esc, fmtMoney, fmtDate, showToast, uid } from './utils.js';
import { openBottomSheet, closeModal } from './modals.js';
import { whoAmI } from './auth.js';

// ── Відкриття форми операції ────────────────────────────────
// opts: { type:'Дохід'|'Витрата', editing:{row,...}, presetMember, presetCard, presetCategory }
export function openOperationDialog(opts = {}) {
  const type = opts.type || 'Витрата';
  const isEdit = !!opts.editing;
  const editing = opts.editing || {};

  // Дефолтні значення
  const me = whoAmI() || FAMILY_MEMBERS[0];
  let curMember = editing.who || opts.presetMember || me;
  let curCard   = editing.card || opts.presetCard || '';
  let curCat    = editing.category || opts.presetCategory || '';
  let curCur    = editing.currency || 'UAH';
  let curAmount = editing.amount || opts.presetAmount || '';
  let curDesc   = editing.desc || opts.presetDesc || '';
  let curDate   = editing.date ? new Date(editing.date) : (opts.presetDate ? new Date(opts.presetDate) : new Date());

  const amtId  = uid('op-amt');
  const curId  = uid('op-cur');
  const descId = uid('op-desc');
  const dateId = uid('op-date');
  const saveId = uid('op-save');
  const delId  = uid('op-del');

  function getCats() { return type === 'Дохід' ? getIncCats() : getExpCats(); }

  function renderContent() {
    const profiles = getProfiles();
    const myCards = getCards(curMember);

    return `
      <!-- Перемикач Витрата/Дохід -->
      <div class="op-type-switch">
        <button type="button" class="op-type-btn ${type === 'Витрата' ? 'active expense' : ''}" data-op-type="Витрата"><i class="ti ti-arrow-up-circle"></i> Витрата</button>
        <button type="button" class="op-type-btn ${type === 'Дохід' ? 'active income' : ''}" data-op-type="Дохід"><i class="ti ti-arrow-down-circle"></i> Дохід</button>
      </div>

      <!-- Сума і валюта -->
      <div class="op-amount-row">
        <input id="${amtId}" class="op-amount-input" type="number" inputmode="decimal" step="0.01" placeholder="0" value="${esc(curAmount)}">
        <select id="${curId}" class="op-cur-select">
          <option value="UAH" ${curCur === 'UAH' ? 'selected' : ''}>₴</option>
          <option value="USD" ${curCur === 'USD' ? 'selected' : ''}>$</option>
          <option value="EUR" ${curCur === 'EUR' ? 'selected' : ''}>€</option>
        </select>
      </div>

      <!-- Власник -->
      <label class="ip-label">Хто</label>
      <div class="op-chips">
        ${FAMILY_MEMBERS.map(m => `
          <button type="button" class="chip op-chip-member ${m === curMember ? 'active' : ''}" data-op-member="${esc(m)}">
            ${esc(profiles[m]?.name || m)}
          </button>
        `).join('')}
      </div>

      <!-- Кошельок -->
      <label class="ip-label">Кошельок</label>
      <div class="op-chips op-chips-cards">
        ${myCards.map(c => `
          <button type="button" class="chip op-chip-card ${c.id === curCard ? 'active' : ''}" data-op-card="${esc(c.id)}"
            style="${c.id === curCard ? `background:${c.bg};color:${c.color};border-color:${c.color}` : ''}">
            <i class="ti ${c.icon}"></i> ${esc(c.id)}
          </button>
        `).join('')}
        ${myCards.length === 0 ? '<div class="empty-mini">Спочатку додай кошельок</div>' : ''}
      </div>

      <!-- Категорія -->
      <label class="ip-label">Категорія</label>
      <div class="op-chips op-chips-cats">
        ${getCats().map(c => `
          <button type="button" class="chip op-chip-cat ${c.id === curCat ? 'active' : ''}" data-op-cat="${esc(c.id)}"
            style="${c.id === curCat ? `background:${c.bg};color:${c.color};border-color:${c.color}` : ''}">
            <i class="ti ${c.icon}"></i> ${esc(c.id)}
          </button>
        `).join('')}
      </div>

      <!-- Опис -->
      <label class="ip-label">Коментар</label>
      <input id="${descId}" class="ip-input" type="text" value="${esc(curDesc)}" placeholder="Наприклад: вечеря в кафе">

      <!-- Дата -->
      <label class="ip-label">Дата</label>
      <input id="${dateId}" class="ip-input" type="datetime-local" value="${toDatetimeLocal(curDate)}">
    `;
  }

  function toDatetimeLocal(d) {
    const dt = d instanceof Date ? d : new Date(d);
    const pad = n => String(n).padStart(2, '0');
    return `${dt.getFullYear()}-${pad(dt.getMonth()+1)}-${pad(dt.getDate())}T${pad(dt.getHours())}:${pad(dt.getMinutes())}`;
  }

  const modalId = openBottomSheet({
    title: isEdit ? 'Редагувати операцію' : 'Нова операція',
    content: renderContent(),
    footer: `
      ${isEdit ? `<button id="${delId}" class="btn-danger">Видалити</button>` : ''}
      <button class="btn-ghost" data-modal-close>Скасувати</button>
      <button id="${saveId}" class="btn-primary flex-1">${isEdit ? 'Зберегти' : 'Додати'}</button>
    `,
    size: 'lg',
    onOpen: (wrap) => {
      setTimeout(() => wrap.querySelector('#' + amtId)?.focus(), 200);

      // Перемикач типу
      wrap.querySelectorAll('[data-op-type]').forEach(b => {
        b.addEventListener('click', () => {
          opts.type = b.dataset.opType;
          // Перерендер модалки (зберігаючи введені дані)
          curAmount = wrap.querySelector('#' + amtId).value;
          curDesc   = wrap.querySelector('#' + descId).value;
          curCat = ''; // категорії різні для типів
          const body = wrap.querySelector('.modal-body');
          body.innerHTML = renderContent.call(null);
          bindHandlers(wrap);
        });
      });

      bindHandlers(wrap);
    }
  });

  function bindHandlers(wrap) {
    // Власник
    wrap.querySelectorAll('[data-op-member]').forEach(b => {
      b.addEventListener('click', () => {
        curMember = b.dataset.opMember;
        curCard = ''; // скидаємо вибір картки бо змінився власник
        const body = wrap.querySelector('.modal-body');
        // Зберігаємо значення інпутів перед перерендером
        curAmount = wrap.querySelector('#' + amtId).value;
        curDesc   = wrap.querySelector('#' + descId).value;
        body.innerHTML = renderContent();
        bindHandlers(wrap);
      });
    });

    // Картка
    wrap.querySelectorAll('[data-op-card]').forEach(b => {
      b.addEventListener('click', () => {
        curCard = b.dataset.opCard;
        wrap.querySelectorAll('[data-op-card]').forEach(x => x.classList.remove('active'));
        b.classList.add('active');
      });
    });

    // Категорія
    wrap.querySelectorAll('[data-op-cat]').forEach(b => {
      b.addEventListener('click', () => {
        curCat = b.dataset.opCat;
        wrap.querySelectorAll('[data-op-cat]').forEach(x => x.classList.remove('active'));
        b.classList.add('active');
      });
    });

    // Save
    wrap.querySelector('#' + saveId).addEventListener('click', async () => {
      const amt = parseFloat(wrap.querySelector('#' + amtId).value);
      const cur = wrap.querySelector('#' + curId).value;
      const desc = wrap.querySelector('#' + descId).value.trim();
      const dt = wrap.querySelector('#' + dateId).value;

      if (!amt || amt <= 0) { showToast('Введи суму', 'error'); return; }
      if (!curCat) { showToast('Вибери категорію', 'error'); return; }
      if (!curCard) { showToast('Вибери кошельок', 'error'); return; }

      const body = {
        action: isEdit ? 'updateOperation' : 'addOperation',
        type: opts.type,
        amount: amt,
        currency: cur,
        category: curCat,
        desc,
        date: new Date(dt).toISOString(),
        who: curMember,
        card: curCard,
        budget: curMember,
        source: isEdit ? editing.source : 'Ручний',
      };
      if (isEdit) body.row = editing.row;

      const btn = wrap.querySelector('#' + saveId);
      btn.disabled = true;
      btn.textContent = 'Збереження...';
      try {
        await apiPost(body);
        closeModal(modalId);
        showToast(isEdit ? '✅ Збережено' : '✅ Операція додана');
        // Оновлюємо і дашборд і список операцій
        import('./operations-list.js').then(m => m.loadOperations());
        if (window.refreshDashboard) window.refreshDashboard();
      } catch (e) {
        showToast('Помилка: ' + e.message, 'error');
        btn.disabled = false;
        btn.textContent = isEdit ? 'Зберегти' : 'Додати';
      }
    });

    // Delete
    const delBtn = wrap.querySelector('#' + delId);
    if (delBtn) {
      delBtn.addEventListener('click', async () => {
        const ok = await import('./modals.js').then(m => m.confirmModal('Видалити операцію?', { danger: true, okText: 'Видалити' }));
        if (!ok) return;
        try {
          await apiPost({ action: 'deleteOperation', row: editing.row || editing.id });
          closeModal(modalId);
          showToast('Видалено');
          import('./operations-list.js').then(m => m.loadOperations());
          if (window.refreshDashboard) window.refreshDashboard();
        } catch (e) {
          showToast('Помилка: ' + e.message, 'error');
        }
      });
    }
  }

  return modalId;
}
