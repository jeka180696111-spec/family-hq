// ═══════════════════════════════════════════════════════════════
// OPERATIONS — додавання, редагування, переказ між членами
// ═══════════════════════════════════════════════════════════════

import { FAMILY_MEMBERS, state } from './config.js';
import { getCards, getExpCats, getIncCats, getProfiles, getDefaultWallet } from './storage.js';
import { apiPost } from './api.js';
import { esc, fmtMoney, showToast, uid } from './utils.js';
import { openBottomSheet, closeModal } from './modals.js';
import { whoAmI } from './auth.js';
import { queueOperation } from './offline-queue.js';

export function openOperationDialog(opts = {}) {
  let curType = opts.type || 'Витрата';
  const isEdit = !!opts.editing;
  const editing = opts.editing || {};

  const me = whoAmI() || FAMILY_MEMBERS[0];
  const defWallet = getDefaultWallet();

  let curMember = editing.who || opts.presetMember || me;
  // Auto-select default wallet if matches member
  const defCard = defWallet.member === curMember ? (defWallet.cardId || '') : '';
  let curCard = editing.card || opts.presetCard || defCard;
  let curCat   = editing.category || opts.presetCategory || '';
  // Auto-currency from card
  let curCur = editing.currency || 'UAH';
  if (!editing.currency && curCard) {
    const c = getCards(curMember).find(c => c.id === curCard);
    if (c?.currency) curCur = c.currency;
  }
  let curRate   = editing.rate || '';
  let curAmount = editing.amount || opts.presetAmount || '';
  let curDesc   = editing.desc   || opts.presetDesc   || '';
  let curDate   = editing.date ? new Date(editing.date)
                : opts.presetDate ? new Date(opts.presetDate) : new Date();

  // Transfer-specific
  let curToMember = FAMILY_MEMBERS.find(m => m !== curMember) || me;
  let curToCard   = '';

  const amtId  = uid('op-amt');
  const rateId = uid('op-rate');
  const descId = uid('op-desc');
  const dateId = uid('op-date');
  const saveId = uid('op-save');
  const delId  = uid('op-del');

  function toDatetimeLocal(d) {
    const dt = d instanceof Date ? d : new Date(d);
    const pad = n => String(n).padStart(2, '0');
    return `${dt.getFullYear()}-${pad(dt.getMonth()+1)}-${pad(dt.getDate())}T${pad(dt.getHours())}:${pad(dt.getMinutes())}`;
  }

  function getCats() { return curType === 'Дохід' ? getIncCats() : getExpCats(); }

  // ── Рендер форми витрата/дохід ──────────────────────────────
  function renderMainForm() {
    const profiles = getProfiles();
    const myCards = getCards(curMember);
    const fxRate = state.fx?.[curCur]?.mid;
    const rateDefault = curRate || (fxRate ? fxRate.toFixed(2) : '');
    const amtUah = curAmount && rateDefault ? Math.round(parseFloat(curAmount) * parseFloat(rateDefault)) : '';

    return `
      <div class="op-type-switch">
        <button type="button" class="op-type-btn ${curType==='Витрата'?'active expense':''}" data-op-type="Витрата"><i class="ti ti-arrow-up-circle"></i> Витрата</button>
        <button type="button" class="op-type-btn ${curType==='Дохід'?'active income':''}" data-op-type="Дохід"><i class="ti ti-arrow-down-circle"></i> Дохід</button>
        <button type="button" class="op-type-btn ${curType==='Переказ'?'active transfer':''}" data-op-type="Переказ"><i class="ti ti-arrows-exchange"></i> Переказ</button>
      </div>

      ${curType === 'Переказ' ? renderTransferForm() : `
        <div class="op-amount-row">
          <input id="${amtId}" class="op-amount-input" type="number" inputmode="decimal" step="0.01" placeholder="0" value="${esc(String(curAmount))}">
          <div class="op-cur-pills">
            <button type="button" class="op-cur-pill ${curCur==='UAH'?'active':''}" data-op-cur="UAH">₴ UAH</button>
            <button type="button" class="op-cur-pill ${curCur==='USD'?'active':''}" data-op-cur="USD">$ USD</button>
            <button type="button" class="op-cur-pill ${curCur==='EUR'?'active':''}" data-op-cur="EUR">€ EUR</button>
          </div>
        </div>

        ${curCur !== 'UAH' ? `
          <div class="op-rate-row">
            <label class="ip-label">Курс обміну (₴ за 1 ${curCur}) <span class="op-rate-hint">${amtUah ? '≈ ' + amtUah.toLocaleString('uk-UA') + ' ₴' : 'НБУ: ' + (fxRate?.toFixed(2) || '?')}</span></label>
            <input id="${rateId}" class="ip-input" type="number" step="0.01"
              value="${rateDefault}" placeholder="${fxRate?.toFixed(2) || 'курс'}">
          </div>
        ` : ''}

        <label class="ip-label">Хто</label>
        <div class="op-chips">
          ${FAMILY_MEMBERS.map(m => `
            <button type="button" class="chip op-chip-member ${m===curMember?'active':''}" data-op-member="${esc(m)}">
              ${esc(profiles[m]?.name || m)}
            </button>
          `).join('')}
        </div>

        <label class="ip-label">Гаманець</label>
        <div class="op-wallet-scroll">
          ${myCards.map(c => `
            <button type="button" class="op-wallet-item ${c.id===curCard?'active':''}" data-op-card="${esc(c.id)}"
              data-card-cur="${esc(c.currency||'UAH')}">
              <div class="op-wallet-item-icon" style="background:${c.bg};color:${c.color}">
                <i class="ti ${c.icon}"></i>
              </div>
              <div class="op-wallet-item-name">${esc(c.id)}</div>
              ${c.currency && c.currency !== 'UAH' ? `<div class="op-wallet-item-cur">${c.currency}</div>` : ''}
            </button>
          `).join('')}
          ${!myCards.length ? '<div class="empty-mini">Спочатку додай гаманець</div>' : ''}
        </div>

        <label class="ip-label">Категорія</label>
        <div class="op-chips op-chips-cats">
          ${getCats().map(c => `
            <button type="button" class="chip op-chip-cat ${c.id===curCat?'active':''}" data-op-cat="${esc(c.id)}"
              style="${c.id===curCat?`background:${c.bg};color:${c.color};border-color:${c.color}`:''}">
              <i class="ti ${c.icon}"></i> ${esc(c.id)}
            </button>
          `).join('')}
        </div>

        <label class="ip-label">Коментар</label>
        <input id="${descId}" class="ip-input" type="text" value="${esc(curDesc)}" placeholder="Наприклад: вечеря в кафе">

        <label class="ip-label">Дата</label>
        <input id="${dateId}" class="ip-input" type="datetime-local" value="${toDatetimeLocal(curDate)}">
      `}
    `;
  }

  // ── Рендер форми переказу між членами ───────────────────────
  function renderTransferForm() {
    const profiles = getProfiles();
    const fromCards = getCards(curMember);
    const toCards   = getCards(curToMember);
    const fxRate = state.fx?.[curCur]?.mid;
    const rateDefault = curRate || (fxRate ? fxRate.toFixed(2) : '');
    const amtUah = curAmount && rateDefault && curCur !== 'UAH'
      ? Math.round(parseFloat(curAmount) * parseFloat(rateDefault)) : '';

    return `
      <div class="op-transfer-grid">
        <div class="op-transfer-side">
          <label class="ip-label">Від кого</label>
          <div class="op-chips">
            ${FAMILY_MEMBERS.map(m => `
              <button type="button" class="chip op-chip-from ${m===curMember?'active':''}" data-from-member="${esc(m)}">
                ${esc(profiles[m]?.name || m)}
              </button>
            `).join('')}
          </div>
          <label class="ip-label">З гаманця</label>
          <div class="op-wallet-scroll">
            ${fromCards.map(c => `
              <button type="button" class="op-wallet-item ${c.id===curCard?'active':''}" data-from-card="${esc(c.id)}"
                data-card-cur="${esc(c.currency||'UAH')}">
                <div class="op-wallet-item-icon" style="background:${c.bg};color:${c.color}"><i class="ti ${c.icon}"></i></div>
                <div class="op-wallet-item-name">${esc(c.id)}</div>
                ${c.currency && c.currency !== 'UAH' ? `<div class="op-wallet-item-cur">${c.currency}</div>` : ''}
              </button>
            `).join('')}
          </div>
        </div>

        <div class="op-transfer-arrow"><i class="ti ti-arrow-right"></i></div>

        <div class="op-transfer-side">
          <label class="ip-label">Кому</label>
          <div class="op-chips">
            ${FAMILY_MEMBERS.map(m => `
              <button type="button" class="chip op-chip-to ${m===curToMember?'active':''}" data-to-member="${esc(m)}">
                ${esc(profiles[m]?.name || m)}
              </button>
            `).join('')}
          </div>
          <label class="ip-label">На гаманець</label>
          <div class="op-wallet-scroll">
            ${toCards.map(c => `
              <button type="button" class="op-wallet-item ${c.id===curToCard?'active':''}" data-to-card="${esc(c.id)}">
                <div class="op-wallet-item-icon" style="background:${c.bg};color:${c.color}"><i class="ti ${c.icon}"></i></div>
                <div class="op-wallet-item-name">${esc(c.id)}</div>
                ${c.currency && c.currency !== 'UAH' ? `<div class="op-wallet-item-cur">${c.currency}</div>` : ''}
              </button>
            `).join('')}
          </div>
        </div>
      </div>

      <div class="op-amount-row" style="margin-top:12px">
        <input id="${amtId}" class="op-amount-input" type="number" inputmode="decimal" step="0.01" placeholder="0" value="${esc(String(curAmount))}">
        <div class="op-cur-pills">
          <button type="button" class="op-cur-pill ${curCur==='UAH'?'active':''}" data-op-cur="UAH">₴ UAH</button>
          <button type="button" class="op-cur-pill ${curCur==='USD'?'active':''}" data-op-cur="USD">$ USD</button>
          <button type="button" class="op-cur-pill ${curCur==='EUR'?'active':''}" data-op-cur="EUR">€ EUR</button>
        </div>
      </div>

      ${curCur !== 'UAH' ? `
        <div class="op-rate-row">
          <label class="ip-label">Курс (₴ за 1 ${curCur}) ${amtUah ? '<span class="op-rate-hint">≈ '+amtUah.toLocaleString('uk-UA')+' ₴</span>' : ''}</label>
          <input id="${rateId}" class="ip-input" type="number" step="0.01" value="${rateDefault}" placeholder="${fxRate?.toFixed(2)||'курс'}">
        </div>
      ` : ''}

      <label class="ip-label">Коментар</label>
      <input id="${descId}" class="ip-input" type="text" value="${esc(curDesc)}" placeholder="Наприклад: на продукти">

      <label class="ip-label">Дата</label>
      <input id="${dateId}" class="ip-input" type="datetime-local" value="${toDatetimeLocal(curDate)}">
    `;
  }

  const modalId = openBottomSheet({
    title: isEdit ? 'Редагувати операцію' : 'Нова операція',
    content: renderMainForm(),
    footer: `
      ${isEdit ? `<button id="${delId}" class="btn-danger">Видалити</button>` : ''}
      <button class="btn-ghost" data-modal-close>Скасувати</button>
      <button id="${saveId}" class="btn-primary flex-1">${isEdit ? 'Зберегти' : 'Додати'}</button>
    `,
    size: 'lg',
    onOpen: (wrap) => {
      setTimeout(() => wrap.querySelector('#' + amtId)?.focus(), 200);
      bindHandlers(wrap);
    },
  });

  function rerender(wrap) {
    // Save current input values before re-render
    curAmount = wrap.querySelector('#' + amtId)?.value || curAmount;
    curDesc   = wrap.querySelector('#' + descId)?.value ?? curDesc;
    const rateEl = wrap.querySelector('#' + rateId);
    if (rateEl) curRate = rateEl.value;
    const dateEl = wrap.querySelector('#' + dateId);
    if (dateEl) curDate = new Date(dateEl.value);
    wrap.querySelector('.modal-body').innerHTML = renderMainForm();
    bindHandlers(wrap);
    wrap.querySelector('#' + amtId)?.focus();
  }

  function bindHandlers(wrap) {
    // Type switcher
    wrap.querySelectorAll('[data-op-type]').forEach(b => {
      b.addEventListener('click', () => {
        curType = b.dataset.opType;
        if (curType !== 'Переказ') curCat = '';
        rerender(wrap);
      });
    });

    // Member
    wrap.querySelectorAll('[data-op-member]').forEach(b => {
      b.addEventListener('click', () => {
        curMember = b.dataset.opMember;
        curCard = '';
        curCur = 'UAH';
        // Apply default wallet for new member
        const dw = getDefaultWallet();
        if (dw.member === curMember) { curCard = dw.cardId || ''; }
        rerender(wrap);
      });
    });

    // Card — also auto-set currency
    wrap.querySelectorAll('[data-op-card]').forEach(b => {
      b.addEventListener('click', () => {
        curCard = b.dataset.opCard;
        const cardCur = b.dataset.cardCur || 'UAH';
        if (cardCur !== curCur) {
          curCur = cardCur;
          curRate = state.fx?.[curCur]?.mid?.toFixed(2) || '';
          rerender(wrap);
          return;
        }
        wrap.querySelectorAll('[data-op-card]').forEach(x => {
          x.classList.remove('active');
          x.removeAttribute('style');
        });
        b.classList.add('active');
        const cards = getCards(curMember);
        const card = cards.find(c => c.id === curCard);
        if (card) b.style.cssText = `background:${card.bg};color:${card.color};border-color:${card.color}`;
      });
    });

    // Currency manual change
    wrap.querySelectorAll('[data-op-cur]').forEach(b => {
      b.addEventListener('click', () => {
        curCur = b.dataset.opCur;
        curRate = state.fx?.[curCur]?.mid?.toFixed(2) || '';
        rerender(wrap);
      });
    });

    // Rate input — update hint
    const rateInp = wrap.querySelector('#' + rateId);
    if (rateInp) {
      rateInp.addEventListener('input', () => {
        const amt = parseFloat(wrap.querySelector('#' + amtId)?.value || 0);
        const rate = parseFloat(rateInp.value || 0);
        const hint = wrap.querySelector('.op-rate-hint');
        if (hint && amt && rate) hint.textContent = '≈ ' + Math.round(amt * rate).toLocaleString('uk-UA') + ' ₴';
      });
    }

    // Category
    wrap.querySelectorAll('[data-op-cat]').forEach(b => {
      b.addEventListener('click', () => {
        curCat = b.dataset.opCat;
        wrap.querySelectorAll('[data-op-cat]').forEach(x => { x.classList.remove('active'); x.removeAttribute('style'); });
        const cats = getCats();
        const cat = cats.find(c => c.id === curCat);
        b.classList.add('active');
        if (cat) b.style.cssText = `background:${cat.bg};color:${cat.color};border-color:${cat.color}`;
      });
    });

    // Transfer: from-member
    wrap.querySelectorAll('[data-from-member]').forEach(b => {
      b.addEventListener('click', () => {
        curMember = b.dataset.fromMember;
        curCard = '';
        rerender(wrap);
      });
    });
    // Transfer: from-card
    wrap.querySelectorAll('[data-from-card]').forEach(b => {
      b.addEventListener('click', () => {
        curCard = b.dataset.fromCard;
        const cardCur = b.dataset.cardCur || 'UAH';
        if (cardCur !== curCur) { curCur = cardCur; curRate = state.fx?.[curCur]?.mid?.toFixed(2) || ''; rerender(wrap); return; }
        wrap.querySelectorAll('[data-from-card]').forEach(x => { x.classList.remove('active'); x.removeAttribute('style'); });
        b.classList.add('active');
        const card = getCards(curMember).find(c => c.id === curCard);
        if (card) b.style.cssText = `background:${card.bg};color:${card.color};border-color:${card.color}`;
      });
    });
    // Transfer: to-member
    wrap.querySelectorAll('[data-to-member]').forEach(b => {
      b.addEventListener('click', () => {
        curToMember = b.dataset.toMember;
        curToCard = '';
        rerender(wrap);
      });
    });
    // Transfer: to-card
    wrap.querySelectorAll('[data-to-card]').forEach(b => {
      b.addEventListener('click', () => {
        curToCard = b.dataset.toCard;
        wrap.querySelectorAll('[data-to-card]').forEach(x => { x.classList.remove('active'); x.removeAttribute('style'); });
        b.classList.add('active');
        const card = getCards(curToMember).find(c => c.id === curToCard);
        if (card) b.style.cssText = `background:${card.bg};color:${card.color};border-color:${card.color}`;
      });
    });

    // Save
    wrap.querySelector('#' + saveId)?.addEventListener('click', async () => {
      const amt  = parseFloat(wrap.querySelector('#' + amtId)?.value || 0);
      const desc = wrap.querySelector('#' + descId)?.value?.trim() || '';
      const dt   = wrap.querySelector('#' + dateId)?.value;
      const cur  = wrap.querySelector('#op-cur-sel')?.value || curCur;
      const rate = parseFloat(wrap.querySelector('#' + rateId)?.value || 0);
      const amountUah = cur !== 'UAH' && rate > 0 ? Math.round(amt * rate) : undefined;

      if (!amt || amt <= 0) { showToast('Введи суму', 'error'); return; }

      const btn = wrap.querySelector('#' + saveId);
      btn.disabled = true; btn.textContent = 'Збереження...';

      try {
        if (curType === 'Переказ') {
          if (!curCard)   { showToast('Вибери гаманець відправника', 'error'); btn.disabled=false; btn.textContent='Додати'; return; }
          if (!curToCard) { showToast('Вибери гаманець отримувача', 'error'); btn.disabled=false; btn.textContent='Додати'; return; }
          await apiPost({
            action: 'addTransfer',
            fromWho: curMember, fromCard: curCard,
            toWho: curToMember, toCard: curToCard,
            amount: amt, currency: cur,
            ...(amountUah !== undefined ? { amountUah } : {}),
            desc,
          });
        } else {
          if (!curCat)  { showToast('Вибери категорію', 'error'); btn.disabled=false; btn.textContent=isEdit?'Зберегти':'Додати'; return; }
          if (!curCard) { showToast('Вибери гаманець', 'error');  btn.disabled=false; btn.textContent=isEdit?'Зберегти':'Додати'; return; }
          const body = {
            action: isEdit ? 'updateOperation' : 'addOperation',
            type: curType, amount: amt, currency: cur,
            ...(amountUah !== undefined ? { amountUah } : {}),
            category: curCat, desc,
            date: dt ? new Date(dt).toISOString() : new Date().toISOString(),
            who: curMember, card: curCard,
          };
          if (isEdit) body.row = editing.row || editing.id;
          await apiPost(body);
        }

        closeModal(modalId);
        showToast(isEdit ? '✅ Збережено' : '✅ Операція додана');
        import('./operations-list.js').then(m => m.loadOperations());
        if (window.refreshDashboard) window.refreshDashboard();
      } catch (e) {
        const isNetworkError = !navigator.onLine
          || e.message === 'Failed to fetch'
          || e.message?.includes('network')
          || e.message?.includes('NetworkError');

        if (isNetworkError) {
          try {
            let opBody;
            if (curType === 'Переказ') {
              const amt  = parseFloat(wrap.querySelector('#' + amtId)?.value || 0);
              const desc = wrap.querySelector('#' + descId)?.value?.trim() || '';
              const dt   = wrap.querySelector('#' + dateId)?.value;
              const cur  = curCur;
              const rate = parseFloat(wrap.querySelector('#' + rateId)?.value || 0);
              const amountUah = cur !== 'UAH' && rate > 0 ? Math.round(amt * rate) : undefined;
              opBody = {
                action: 'addTransfer',
                fromWho: curMember, fromCard: curCard,
                toWho: curToMember, toCard: curToCard,
                amount: amt, currency: cur,
                ...(amountUah !== undefined ? { amountUah } : {}),
                desc,
              };
            } else {
              const amt  = parseFloat(wrap.querySelector('#' + amtId)?.value || 0);
              const desc = wrap.querySelector('#' + descId)?.value?.trim() || '';
              const dt   = wrap.querySelector('#' + dateId)?.value;
              const cur  = curCur;
              const rate = parseFloat(wrap.querySelector('#' + rateId)?.value || 0);
              const amountUah = cur !== 'UAH' && rate > 0 ? Math.round(amt * rate) : undefined;
              opBody = {
                action: isEdit ? 'updateOperation' : 'addOperation',
                type: curType, amount: amt, currency: cur,
                ...(amountUah !== undefined ? { amountUah } : {}),
                category: curCat, desc,
                date: dt ? new Date(dt).toISOString() : new Date().toISOString(),
                who: curMember, card: curCard,
              };
              if (isEdit) opBody.row = editing.row || editing.id;
            }
            await queueOperation(opBody);
            // Register background sync if supported
            if ('serviceWorker' in navigator && 'SyncManager' in window) {
              const reg = await navigator.serviceWorker.ready;
              await reg.sync.register('sync-operations');
            }
            closeModal(modalId);
            showToast('Збережено офлайн, синхронізується автоматично');
          } catch (queueErr) {
            showToast('Помилка: ' + e.message, 'error');
          }
        } else {
          showToast('Помилка: ' + e.message, 'error');
        }
        btn.disabled = false;
        btn.textContent = isEdit ? 'Зберегти' : 'Додати';
      }
    });

    // Delete
    wrap.querySelector('#' + delId)?.addEventListener('click', async () => {
      const ok = await import('./modals.js').then(m => m.confirmModal('Видалити операцію?', { danger: true, okText: 'Видалити' }));
      if (!ok) return;
      try {
        await apiPost({ action: 'deleteOperation', row: editing.row || editing.id });
        closeModal(modalId);
        showToast('Видалено');
        import('./operations-list.js').then(m => m.loadOperations());
        if (window.refreshDashboard) window.refreshDashboard();
      } catch (e) { showToast('Помилка: ' + e.message, 'error'); }
    });
  }

  return modalId;
}
