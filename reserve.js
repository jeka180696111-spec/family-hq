// ═══════════════════════════════════════════════════════════════
// RESERVE — Накопичення: кошельки типу "savings" + рез. резерв
// ═══════════════════════════════════════════════════════════════

import { FAMILY_MEMBERS, state } from './config.js';
import { apiGet, apiPost } from './api.js';
import { getCards, getProfiles, getWalletTypeById } from './storage.js';
import { esc, fmtMoney, fmtDate, showToast, uid } from './utils.js';
import { openBottomSheet, closeModal } from './modals.js';
import { openOperationDialog } from './operations.js';

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

  // ── Збираємо кошельки типу "savings" по всіх власниках ──
  const profiles = getProfiles();
  const savingsCards = [];
  FAMILY_MEMBERS.forEach(owner => {
    getCards(owner).forEach(c => {
      const wtype = getWalletTypeById(c.walletType);
      if (wtype && wtype.id === 'savings') {
        savingsCards.push({ ...c, owner });
      }
    });
  });

  // ── Рахуємо баланс кожного кошелька накопичень ──
  const ops = state.operations || [];
  function cardBalance(card) {
    let bal = 0;
    ops.forEach(o => {
      if (o.who === card.owner && o.card === card.id) {
        if (o.type === 'Дохід') bal += (o.amountUah || o.amount || 0);
        if (o.type === 'Витрата') bal -= (o.amountUah || o.amount || 0);
      }
    });
    return bal;
  }

  const cardsWithBal = savingsCards.map(c => ({ ...c, balance: cardBalance(c) }));
  const totalSavings = cardsWithBal.reduce((s, c) => s + c.balance, 0);

  // ── Старий резерв (з листа Резерв у таблиці) ──
  const r = state.reserve || {};
  const oldReserveTotal = r.totalUah || 0;
  const txs = r.transactions || [];
  const grandTotal = totalSavings + oldReserveTotal;

  el.innerHTML = `
    <div class="page-inner">
      <div class="page-head">
        <h1 class="page-title">Накопичення</h1>
      </div>

      <!-- HERO: загальний резерв -->
      <div class="reserve-hero">
        <div class="reserve-hero-label">Загальний резерв</div>
        <div class="reserve-hero-amount">${fmtMoney(grandTotal, 'UAH')}</div>
        <div class="reserve-hero-meta">
          ${cardsWithBal.length > 0 ? `<span class="chip">🏦 ${cardsWithBal.length} кошел.</span>` : ''}
          ${r.monthsCoverage > 0 ? `<span class="chip">🛡 На ${r.monthsCoverage} міс.</span>` : ''}
        </div>
      </div>

      <!-- Кошельки накопичень (нова логіка) -->
      ${cardsWithBal.length > 0 ? `
        <div class="dash-card">
          <div class="dash-card-head">
            <span class="dash-card-title">Кошельки накопичень</span>
            <span class="dash-card-amount">${fmtMoney(totalSavings, 'UAH')}</span>
          </div>
          <div class="reserve-cards-list">
            ${cardsWithBal.map(c => `
              <div class="dash-wallet-item" data-savings-card="${esc(c.owner)}::${esc(c.id)}">
                <div class="dash-wallet-icon" style="background:${c.bg}">
                  <i class="ti ${c.icon}" style="color:${c.color}"></i>
                </div>
                <div class="dash-wallet-info">
                  <div class="dash-wallet-name">${esc(c.id)}</div>
                  <div class="dash-wallet-owner">${esc(profiles[c.owner]?.name || c.owner)}</div>
                </div>
                <div class="dash-wallet-balance ${c.balance >= 0 ? 'pos' : 'neg'}">${fmtMoney(c.balance, 'UAH')}</div>
              </div>
            `).join('')}
          </div>
        </div>
      ` : `
        <div class="settings-hint" style="padding:14px;border-radius:var(--radius);background:var(--c-card);border:1px solid var(--c-border);margin-bottom:14px;">
          💡 Створи кошельок з типом <b>Накопичення</b> на сторінці Кошельки — і він автоматично з'явиться тут.
        </div>
      `}

      <!-- Старий розділ "Резерв" з листа Sheets (якщо є) -->
      ${oldReserveTotal > 0 || txs.length > 0 ? `
        <div class="dash-card">
          <div class="dash-card-head">
            <span class="dash-card-title">Старий резерв (з листа)</span>
            <span class="dash-card-amount">${fmtMoney(oldReserveTotal, 'UAH')}</span>
          </div>
          ${Object.keys(r.balances || {}).length > 0 ? `
            <div class="reserve-balances" style="margin:8px 0">
              ${Object.entries(r.balances || {}).map(([cur, val]) => `
                <div class="reserve-balance-card">
                  <div class="reserve-balance-cur">${cur}</div>
                  <div class="reserve-balance-val">${fmtMoney(val, cur)}</div>
                </div>
              `).join('')}
            </div>
          ` : ''}
        </div>
      ` : ''}

      <!-- Дії: поповнити, зняти -->
      <div class="reserve-actions">
        <button class="btn-primary flex-1" id="add-reserve-btn"><i class="ti ti-plus"></i> Поповнити</button>
        <button class="btn-ghost flex-1" id="withdraw-reserve-btn"><i class="ti ti-minus"></i> Зняти</button>
      </div>

      <!-- Історія транзакцій старого резерву -->
      ${txs.length > 0 ? `
        <div class="reserve-history">
          <div class="dash-card-head">
            <span class="dash-card-title">Історія резерву</span>
          </div>
          <div class="reserve-tx-list">
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
          </div>
        </div>
      ` : ''}
    </div>
  `;

  // Клік на кошельок накопичень — перехід в Кошельки
  el.querySelectorAll('[data-savings-card]').forEach(item => {
    item.addEventListener('click', () => {
      import('./main.js').then(m => m.navigateTo('wallets'));
    });
  });

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
      <div class="settings-hint" style="padding:0 0 12px;border:none;">
        💡 Це резерв (окремий лист у таблиці). Для накопичень у кошельках — додавай операції напряму через "+" на той кошельок.
      </div>
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
