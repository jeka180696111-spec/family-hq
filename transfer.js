// ═══════════════════════════════════════════════════════════════
// TRANSFER — переказ між кошельками
// ═══════════════════════════════════════════════════════════════

import { FAMILY_MEMBERS, state } from './config.js';
import { getCards, getProfiles } from './storage.js';
import { apiPost } from './api.js';
import { esc, fmtMoney, showToast, uid } from './utils.js';
import { openBottomSheet, closeModal } from './modals.js';

// ── Відкриття діалогу переказу ──────────────────────────────
// presets: { fromOwner, fromCard, toOwner, toCard }
export function openTransferDialog(presets = {}) {
  // Збираємо всі кошельки
  const allCards = [];
  FAMILY_MEMBERS.forEach(m => {
    getCards(m).forEach(c => allCards.push({ ...c, owner: m }));
  });
  // Спецоб'єкти "Резерв" і "Ціль"
  const specialDestinations = [
    { id: '__reserve__', label: '🛡 Накопичення (резерв)', special: 'reserve' },
  ];

  const profiles = getProfiles();
  const fromId = uid('tr-from');
  const toId = uid('tr-to');
  const amtId = uid('tr-amt');
  const curId = uid('tr-cur');
  const descId = uid('tr-desc');
  const saveId = uid('tr-save');

  // Дефолтні значення
  let selFrom = `${presets.fromOwner || allCards[0]?.owner}::${presets.fromCard || allCards[0]?.id}`;
  let selTo   = presets.toOwner && presets.toCard ? `${presets.toOwner}::${presets.toCard}` : '__reserve__';

  function makeOptions(selected) {
    let html = '';
    FAMILY_MEMBERS.forEach(m => {
      const cards = getCards(m);
      if (!cards.length) return;
      html += `<optgroup label="${esc(profiles[m]?.name || m)}">`;
      cards.forEach(c => {
        const val = `${m}::${c.id}`;
        html += `<option value="${esc(val)}" ${val === selected ? 'selected' : ''}>${esc(c.id)}</option>`;
      });
      html += `</optgroup>`;
    });
    return html;
  }

  function makeOptionsWithSpecial(selected) {
    let html = makeOptions(selected);
    html += `<optgroup label="Інше">`;
    specialDestinations.forEach(d => {
      html += `<option value="${esc(d.id)}" ${d.id === selected ? 'selected' : ''}>${esc(d.label)}</option>`;
    });
    html += `</optgroup>`;
    return html;
  }

  const modalId = openBottomSheet({
    title: 'Переказ',
    content: `
      <div class="transfer-row">
        <label class="ip-label">З кошелька</label>
        <select id="${fromId}" class="ip-input">${makeOptions(selFrom)}</select>
      </div>

      <div class="transfer-arrow"><i class="ti ti-arrow-down"></i></div>

      <div class="transfer-row">
        <label class="ip-label">На кошельок</label>
        <select id="${toId}" class="ip-input">${makeOptionsWithSpecial(selTo)}</select>
      </div>

      <div class="transfer-amount-row">
        <div class="transfer-row" style="flex:1">
          <label class="ip-label">Сума</label>
          <input id="${amtId}" class="ip-input ip-input-big" type="number" inputmode="decimal" placeholder="0" step="0.01">
        </div>
        <div class="transfer-row" style="width:100px">
          <label class="ip-label">Валюта</label>
          <select id="${curId}" class="ip-input">
            <option value="UAH">UAH ₴</option>
            <option value="USD">USD $</option>
            <option value="EUR">EUR €</option>
          </select>
        </div>
      </div>

      <div class="transfer-row">
        <label class="ip-label">Опис (необов'язково)</label>
        <input id="${descId}" class="ip-input" type="text" placeholder="Наприклад: зняв готівкою">
      </div>
    `,
    footer: `
      <button class="btn-ghost" data-modal-close>Скасувати</button>
      <button id="${saveId}" class="btn-primary flex-1"><i class="ti ti-arrows-exchange"></i> Переказати</button>
    `,
    size: 'md',
    onOpen: (wrap) => {
      const fromEl = wrap.querySelector('#' + fromId);
      const toEl   = wrap.querySelector('#' + toId);
      const amtEl  = wrap.querySelector('#' + amtId);

      setTimeout(() => amtEl.focus(), 200);

      wrap.querySelector('#' + saveId).addEventListener('click', async () => {
        const fromVal = fromEl.value;
        const toVal = toEl.value;
        const amt = parseFloat(amtEl.value);
        const cur = wrap.querySelector('#' + curId).value;
        const desc = wrap.querySelector('#' + descId).value.trim();

        if (!amt || amt <= 0) { showToast('Введи суму', 'error'); return; }
        if (fromVal === toVal) { showToast('Не можна переказувати самому собі', 'error'); return; }

        const [fromOwner, fromCard] = fromVal.split('::');

        // Перевіряємо тип призначення
        let toOwner = null, toCard = null, toReserve = false;
        if (toVal === '__reserve__') {
          toReserve = true;
        } else {
          [toOwner, toCard] = toVal.split('::');
        }

        const body = {
          action: 'addTransfer',
          fromWho: fromOwner,
          fromCard,
          toWho: toOwner,
          toCard,
          amount: amt,
          currency: cur,
          desc,
        };
        if (toReserve) body.toReserve = true;

        const btn = wrap.querySelector('#' + saveId);
        btn.disabled = true;
        btn.textContent = 'Збереження...';
        try {
          await apiPost(body);
          closeModal(modalId);
          showToast('✅ Переказ виконано');
          // Оновлюємо дашборд
          if (window.refreshDashboard) window.refreshDashboard();
        } catch (e) {
          showToast('Помилка: ' + e.message, 'error');
          btn.disabled = false;
          btn.innerHTML = '<i class="ti ti-arrows-exchange"></i> Переказати';
        }
      });
    }
  });
  return modalId;
}
