// ═══════════════════════════════════════════════════════════════
// RESERVE — накопичення / резерв
// ═══════════════════════════════════════════════════════════════

import { state } from './config.js';
import { apiGet, apiPost } from './api.js';
import { esc, fmtMoney, fmtDate, showToast, uid } from './utils.js';
import { openBottomSheet, closeModal } from './modals.js';

export async function loadReserve() {
  try {
    state.reserve = await apiGet('reserve');
  } catch (e) {
    state.reserve = null;
  }
  renderReservePage();
}

export function renderReservePage() {
  const el = document.getElementById('page-reserve');
  if (!el) return;

  const r = state.reserve || {};
  const total = r.totalUah || 0;
  const months = r.monthsCoverage || 0;
  const txs = r.transactions || [];

  el.innerHTML = `
    <div class="page-inner">
      <div class="page-head">
        <h1 class="page-title">Накопичення</h1>
      </div>

      <div class="reserve-hero">
        <div class="reserve-hero-label">Загальний резерв</div>
        <div class="reserve-hero-amount">${fmtMoney(total, 'UAH')}</div>
        <div class="reserve-hero-meta">
          ${months > 0 ? `<span class="chip">🛡 На ${months} міс.</span>` : ''}
          ${r.addedThisMonth > 0 ? `<span class="chip pos">+${fmtMoney(r.addedThisMonth, 'UAH')} цей місяць</span>` : ''}
        </div>
      </div>

      <div class="reserve-balances">
        ${Object.entries(r.balances || {}).map(([cur, val]) => `
          <div class="reserve-balance-card">
            <div class="reserve-balance-cur">${cur}</div>
            <div class="reserve-balance-val">${fmtMoney(val, cur)}</div>
          </div>
        `).join('')}
      </div>

      <div class="reserve-actions">
        <button class="btn-primary flex-1" id="add-reserve-btn"><i class="ti ti-plus"></i> Поповнити</button>
        <button class="btn-ghost flex-1" id="withdraw-reserve-btn"><i class="ti ti-minus"></i> Зняти</button>
      </div>

      <div class="reserve-history">
        <div class="dash-card-head">
          <span class="dash-card-title">Історія</span>
        </div>
        ${txs.length === 0 ? '<div class="empty-mini">Жодних транзакцій</div>' :
          `<div class="reserve-tx-list">
            ${txs.map(tx => `
              <div class="reserve-tx-item">
                <div class="reserve-tx-icon ${tx.type === 'Поповнення' ? 'in' : 'out'}">
                  <i class="ti ${tx.type === 'Поповнення' ? 'ti-arrow-down' : 'ti-arrow-up'}"></i>
                </div>
                <div class="reserve-tx-info">
                  <div class="reserve-tx-type">${esc(tx.type)}</div>
                  <div class="reserve-tx-meta">${esc(tx.comment || '')} · ${esc(tx.who || '')} · ${fmtDate(tx.date)}</div>
                </div>
                <div class="reserve-tx-amt ${tx.type === 'Поповнення' ? 'pos' : 'neg'}">
                  ${tx.type === 'Поповнення' ? '+' : '−'}${fmtMoney(Math.abs(tx.amount), tx.currency)}
                </div>
              </div>
            `).join('')}
          </div>`
        }
      </div>
    </div>
  `;

  el.querySelector('#add-reserve-btn')?.addEventListener('click', () => openReserveDialog('Поповнення'));
  el.querySelector('#withdraw-reserve-btn')?.addEventListener('click', () => openReserveDialog('Зняття'));
}

function openReserveDialog(type) {
  const amtId = uid('rs-amt');
  const curId = uid('rs-cur');
  const cmtId = uid('rs-cmt');
  const saveId = uid('rs-save');

  const modalId = openBottomSheet({
    title: type,
    content: `
      <div class="op-amount-row">
        <input id="${amtId}" class="op-amount-input" type="number" inputmode="decimal" step="0.01" placeholder="0">
        <select id="${curId}" class="op-cur-select">
          <option value="UAH">₴</option><option value="USD">$</option><option value="EUR">€</option>
        </select>
      </div>
      <label class="ip-label">Коментар</label>
      <input id="${cmtId}" class="ip-input" type="text" placeholder="Наприклад: від зарплати">
    `,
    footer: `
      <button class="btn-ghost" data-modal-close>Скасувати</button>
      <button id="${saveId}" class="btn-primary flex-1">${type}</button>
    `,
    onOpen: (wrap) => {
      setTimeout(() => wrap.querySelector('#' + amtId).focus(), 100);
      wrap.querySelector('#' + saveId).addEventListener('click', async () => {
        const amt = parseFloat(wrap.querySelector('#' + amtId).value);
        if (!amt || amt <= 0) { showToast('Введи суму', 'error'); return; }
        const cur = wrap.querySelector('#' + curId).value;
        const cmt = wrap.querySelector('#' + cmtId).value.trim();
        try {
          await apiPost({ action: 'addReserve', type, amount: amt, currency: cur, comment: cmt });
          closeModal(modalId);
          showToast('✅ Збережено');
          loadReserve();
        } catch (e) { showToast(e.message, 'error'); }
      });
    }
  });
}
