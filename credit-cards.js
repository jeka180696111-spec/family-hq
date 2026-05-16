// ═══════════════════════════════════════════════════════════════
// CREDIT CARDS — кредитні картки з лімітами на дашборді
// ═══════════════════════════════════════════════════════════════

import { state, FAMILY_MEMBERS } from './config.js';
import { getCards, setCards, getWalletTypeById } from './storage.js';
import { fmtMoney, esc } from './utils.js';

// ── Зібрати всі кредитки з лімітами ─────────────────────────
export function getCreditCards(viewAs) {
  const result = [];
  const members = viewAs ? [viewAs] : [...FAMILY_MEMBERS];

  members.forEach(member => {
    const cards = getCards(member);
    cards.forEach(card => {
      const wt = getWalletTypeById(card.walletType);
      const isCredit = wt?.id === 'credit' || (card.id || '').toLowerCase().includes('кредит');
      const limit = Number(card.creditLimit) || 0;
      if (!isCredit || limit <= 0) return;

      const used = calcCreditUsed(member, card.id);
      const available = Math.max(0, limit - used);
      const pct = Math.min(100, Math.round((used / limit) * 100));

      result.push({
        ...card,
        owner: member,
        limit, used, available, pct,
        status: pct >= 90 ? 'danger' : pct >= 60 ? 'warning' : 'ok',
      });
    });
  });
  return result;
}

function calcCreditUsed(member, cardId) {
  let used = 0;
  (state.operations || []).forEach(op => {
    if (op.who !== member || op.card !== cardId) return;
    if (op.category === 'Переказ') return;
    const amt = op.amountUah || op.amount || 0;
    if (op.type === 'Витрата') used += amt;
    if (op.type === 'Дохід') used -= amt;
  });
  return Math.max(0, used);
}

// ── Рендер блоку для дашборду ────────────────────────────────
export function renderCreditCardsBlock(viewAs) {
  const credits = getCreditCards(viewAs);
  if (!credits.length) return '';

  const totalLimit = credits.reduce((s, c) => s + c.limit, 0);
  const totalUsed = credits.reduce((s, c) => s + c.used, 0);
  const totalPct = totalLimit > 0 ? Math.min(100, Math.round((totalUsed / totalLimit) * 100)) : 0;
  const barClass = totalPct >= 90 ? 'danger' : totalPct >= 60 ? 'warning' : '';

  return `
    <div class="dash-card credit-block">
      <div class="credit-block-head">
        <span class="dash-card-title"><i class="ti ti-credit-card-pay"></i> Кредитні картки</span>
        <span class="credit-head-total">
          <span class="c-red">${fmtMoney(totalUsed, 'UAH')}</span>
          <span class="c-muted"> / ${fmtMoney(totalLimit, 'UAH')}</span>
        </span>
      </div>
      <div class="credit-total-bar">
        <div class="credit-total-bar-fill ${barClass}" style="width:${totalPct}%"></div>
      </div>
      <div class="credit-avail">Доступно: <strong>${fmtMoney(totalLimit - totalUsed, 'UAH')}</strong></div>
      <div class="credit-cards-list">
        ${credits.map(c => `
          <div class="credit-card-row ${c.status !== 'ok' ? 'credit-' + c.status : ''}">
            <div class="credit-card-icon" style="background:${c.bg}">
              <i class="ti ${c.icon}" style="color:${c.color}"></i>
            </div>
            <div class="credit-card-info">
              <div class="credit-card-name">${esc(c.id)}</div>
              <div class="credit-card-owner">${esc(c.owner)}</div>
            </div>
            <div class="credit-card-bar-wrap">
              <div class="credit-card-mini-bar">
                <div class="credit-card-mini-fill ${c.status !== 'ok' ? 'credit-' + c.status : ''}" style="width:${c.pct}%"></div>
              </div>
              <div class="credit-card-pct">${c.pct}%</div>
            </div>
            <div class="credit-card-used">${fmtMoney(c.used, 'UAH')}</div>
          </div>
        `).join('')}
      </div>
    </div>
  `;
}

// ── Алерти по кредитках ──────────────────────────────────────
export function getCreditAlerts() {
  return getCreditCards().filter(c => c.pct >= 80).map(c => ({
    type: c.pct >= 95 ? 'critical' : 'warning',
    message: `💳 ${c.id} (${c.owner}): ${c.pct}% ліміту (${fmtMoney(c.available, 'UAH')} залишилось)`,
  }));
}
