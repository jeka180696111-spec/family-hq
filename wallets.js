// ═══════════════════════════════════════════════════════════════
// WALLETS — єдина сторінка "Кошельки" з фільтрами
// ═══════════════════════════════════════════════════════════════

import { FAMILY_MEMBERS, state } from './config.js';
import { getCards, setCards, getWalletTypes, getWalletTypeById, getProfiles } from './storage.js';
import { syncSettingsToSheet } from './api.js';
import { esc, fmtMoney, fmtMoneyWithUah, toUah, showToast } from './utils.js';
import { openIconPicker } from './icon-picker.js';
import { confirmModal } from './modals.js';

// ── Рендер сторінки ─────────────────────────────────────────
export function renderWalletsPage() {
  const el = document.getElementById('page-wallets');
  if (!el) return;

  const ownerFilter = state.walletFilter && state.walletFilter !== 'all' && FAMILY_MEMBERS.includes(state.walletFilter)
    ? state.walletFilter : 'all';
  const typeFilter = state.walletTypeFilter || 'all';

  // Збираємо всі картки з прапором owner
  const allCards = [];
  FAMILY_MEMBERS.forEach(m => {
    getCards(m).forEach((c, idx) => allCards.push({ ...c, owner: m, ownerIdx: idx }));
  });

  // Фільтруємо
  let filtered = allCards;
  if (ownerFilter !== 'all') filtered = filtered.filter(c => c.owner === ownerFilter);
  if (typeFilter !== 'all') filtered = filtered.filter(c => (c.walletType || '_other') === typeFilter);

  const types = getWalletTypes();
  const profiles = getProfiles();

  // Підрахунок балансу для кожної картки
  // Для кредитних карток використовуємо all-time дані з dashboard
  function cardBalance(card) {
    const limit = Number(card.creditLimit) || 0;
    if (limit > 0 && state.dashboard?.cardBalances) {
      const key = `${card.owner}:${card.id}`;
      const b = state.dashboard.cardBalances[key];
      if (b) return Math.round(b.income - b.expense);
    }
    // Звичайний кошелек — поточні операції у власній валюті
    const ops = state.operations || [];
    let bal = 0;
    ops.forEach(o => {
      if (o.who === card.owner && o.card === card.id) {
        const opCur = o.currency || 'UAH';
        const cardCur = card.currency || 'UAH';
        let val = 0;
        if (opCur === cardCur) {
          val = o.amount || 0;
        } else {
          val = o.amountUah || o.amount || 0;
          if (cardCur !== 'UAH' && state.fx && state.fx[cardCur]) {
            const rate = state.fx[cardCur].mid || 1;
            val = val / rate;
          }
        }
        if (o.type === 'Дохід')   bal += val;
        if (o.type === 'Витрата') bal -= val;
      }
    });
    return bal;
  }

  // Інфо про кредит для картки з лімітом
  function creditInfo(card, bal) {
    const limit = Number(card.creditLimit) || 0;
    if (!limit) return null;
    const ownFunds = Math.max(0, bal);
    const creditUsed = Math.max(0, -bal);
    const creditAvail = Math.max(0, limit - creditUsed);
    const pct = Math.min(100, Math.round((creditUsed / limit) * 100));
    const status = pct >= 90 ? 'danger' : pct >= 60 ? 'warning' : '';
    return { limit, ownFunds, creditUsed, creditAvail, pct, status };
  }

  // Загальна сума по фільтру в UAH
  const totalBalanceUah = filtered.reduce((s, c) => {
    const bal = cardBalance(c);
    return s + toUah(bal, c.currency || 'UAH', state.fx);
  }, 0);
  const totalCount = filtered.length;

  el.innerHTML = `
    <div class="page-inner">
      <div class="wallets-hero">
        <div class="wallets-hero-label">${ownerFilter === 'all' ? 'Усі рахунки' : 'Рахунки: ' + esc(profiles[ownerFilter]?.name || ownerFilter)}</div>
        <div class="wallets-hero-balance">${fmtMoney(totalBalanceUah, 'UAH')}</div>
        <div class="wallets-hero-meta">${totalCount} ${totalCount === 1 ? 'кошельок' : 'кошельків'}</div>
      </div>

      <div class="wallets-filters">
        <div class="wallets-filter-group">
          <div class="wallets-filter-label">Власник</div>
          <div class="wallets-filter-chips">
            <button class="chip ${ownerFilter === 'all' ? 'active' : ''}" data-owner="all">Усі</button>
            ${FAMILY_MEMBERS.map(m => `
              <button class="chip ${ownerFilter === m ? 'active' : ''}" data-owner="${esc(m)}">${esc(profiles[m]?.name || m)}</button>
            `).join('')}
          </div>
        </div>
        <div class="wallets-filter-group">
          <div class="wallets-filter-label">Тип</div>
          <div class="wallets-filter-chips">
            <button class="chip ${typeFilter === 'all' ? 'active' : ''}" data-type="all">Усі</button>
            ${types.map(t => `
              <button class="chip ${typeFilter === t.id ? 'active' : ''}" data-type="${esc(t.id)}"
                style="${typeFilter === t.id ? `background:${t.bg};color:${t.color};border-color:${t.color}` : ''}">
                <i class="ti ${t.icon || 'ti-wallet'}"></i> ${esc(t.name)}
              </button>
            `).join('')}
          </div>
        </div>
      </div>

      <div class="wallets-list">
        ${filtered.length === 0 ? `
          <div class="empty-state">
            <i class="ti ti-wallet" style="font-size:48px;color:var(--c-text-3);opacity:.5;"></i>
            <div class="empty-state-title">Жодного кошелька</div>
            <div class="empty-state-text">Додай перший — натисни «+» внизу</div>
          </div>
        ` : filtered.map(c => {
          const bal = cardBalance(c);
          const cur = c.currency || 'UAH';
          const tp = getWalletTypeById(c.walletType);
          const credit = creditInfo(c, bal);
          return `
            <div class="wallet-row" data-owner="${esc(c.owner)}" data-idx="${c.ownerIdx}">
              <div class="wallet-row-icon" style="background:${c.bg}">
                <i class="ti ${c.icon}" style="color:${c.color}"></i>
              </div>
              <div class="wallet-row-info">
                <div class="wallet-row-name">${esc(c.id)}</div>
                <div class="wallet-row-sub">
                  <span class="wallet-row-owner">${esc(c.owner)}</span>
                  ${tp ? `<span class="wallet-row-type" style="color:${tp.color}">· ${esc(tp.name)}</span>` : ''}
                  <span class="wallet-row-cur">· ${cur}</span>
                </div>
                ${credit ? `
                  <div class="wallet-credit-row">
                    <div class="wallet-credit-track">
                      <div class="wallet-credit-fill ${credit.status}" style="width:${credit.pct}%"></div>
                    </div>
                    <span class="wallet-credit-label ${credit.creditUsed > 0 ? 'used' : ''}">
                      ${credit.creditUsed > 0
                        ? `Кредит: ${fmtMoney(credit.creditUsed)} / ${fmtMoney(credit.limit)} · вільно ${fmtMoney(credit.creditAvail)}`
                        : `Ліміт: ${fmtMoney(credit.limit)} · вільний`}
                    </span>
                  </div>
                ` : ''}
              </div>
              <div class="wallet-row-balance ${bal >= 0 ? 'pos' : 'neg'}">${fmtMoneyWithUah(bal, cur, state.fx)}</div>
            </div>
          `;
        }).join('')}
      </div>

    </div>
  `;

  // Слухачі фільтрів
  el.querySelectorAll('[data-owner]').forEach(b => {
    b.addEventListener('click', () => {
      state.walletFilter = b.dataset.owner;
      renderWalletsPage();
    });
  });
  el.querySelectorAll('[data-type]').forEach(b => {
    b.addEventListener('click', () => {
      state.walletTypeFilter = b.dataset.type;
      renderWalletsPage();
    });
  });

  // Клік на кошельок — редагування
  el.querySelectorAll('.wallet-row').forEach(row => {
    row.addEventListener('click', () => {
      const owner = row.dataset.owner;
      const idx = parseInt(row.dataset.idx);
      openEditWallet(owner, idx);
    });
  });
}

// ── Створення кошелька ──────────────────────────────────────
export function openCreateWallet(presetOwner) {
  const types = getWalletTypes();
  const profiles = getProfiles();
  // Якщо є preset (наприклад з FAB або фільтра) — використовуємо його
  let selOwner = presetOwner;
  if (!selOwner && state.walletFilter && FAMILY_MEMBERS.includes(state.walletFilter)) {
    selOwner = state.walletFilter;
  }
  if (!selOwner) selOwner = FAMILY_MEMBERS[0];

  // Дод. поле: вибір власника
  const ownerSelect = `
    <label class="ip-label">Власник</label>
    <select class="ip-input" data-ip-extra="owner">
      ${FAMILY_MEMBERS.map(m => `
        <option value="${esc(m)}" ${m === selOwner ? 'selected' : ''}>${esc(profiles[m]?.name || m)}</option>
      `).join('')}
    </select>
  `;

  openIconPicker({
    title: 'Новий кошельок',
    nameLabel: 'Назва',
    namePlaceholder: 'Наприклад: Монобанк USD',
    extraFields: ownerSelect,
    showTypes: true,
    showCurrency: true,
    showCreditLimit: true,
    typesList: types,
    selectedType: types[0]?.id,
    selectedCurrency: 'UAH',
    selectedIcon: types[0]?.icon || 'ti-wallet',
    selectedColor: { bg: types[0]?.bg || '#E6F1FB', color: types[0]?.color || '#0C447C' },
    isEdit: false,
    onSave: ({ name, icon, color, walletType, currency, creditLimit, owner }) => {
      const ownerFinal = owner && FAMILY_MEMBERS.includes(owner) ? owner : selOwner;
      const cards = getCards(ownerFinal);
      // Перевірка унікальності
      if (cards.find(c => c.id === name)) {
        showToast('Кошельок з такою назвою вже існує', 'error');
        return;
      }
      const card = { id: name, icon, bg: color.bg, color: color.color, walletType, currency: currency || 'UAH' };
      if (creditLimit > 0) card.creditLimit = creditLimit;
      cards.push(card);
      setCards(cards, ownerFinal);
      renderWalletsPage();
      showToast('💾 Зберігаю...');
      syncSettingsToSheet()
        .then(() => showToast('✅ Кошельок збережено на сервер'))
        .catch(e => showToast('⚠️ Збережено локально, але не на сервер: ' + e.message, 'error'));
    }
  });
}

// ── Редагування ─────────────────────────────────────────────
export function openEditWallet(owner, idx) {
  const cards = getCards(owner);
  const card = cards[idx];
  if (!card) return;
  const types = getWalletTypes();
  const profiles = getProfiles();

  // Дозволяємо переносити кошельок між власниками
  const ownerSelect = `
    <label class="ip-label">Власник</label>
    <select class="ip-input" data-ip-extra="owner">
      ${FAMILY_MEMBERS.map(m => `
        <option value="${esc(m)}" ${m === owner ? 'selected' : ''}>${esc(profiles[m]?.name || m)}</option>
      `).join('')}
    </select>
  `;

  openIconPicker({
    title: 'Редагувати кошельок',
    nameLabel: 'Назва',
    nameValue: card.id,
    extraFields: ownerSelect,
    showTypes: true,
    showCurrency: true,
    showCreditLimit: true,
    typesList: types,
    selectedType: card.walletType || types[0]?.id,
    selectedCurrency: card.currency || 'UAH',
    selectedCreditLimit: card.creditLimit || 0,
    selectedIcon: card.icon,
    selectedColor: { bg: card.bg, color: card.color },
    isEdit: true,
    onSave: ({ name, icon, color, walletType, currency, creditLimit, owner: newOwner }) => {
      const updated = { id: name, icon, bg: color.bg, color: color.color, walletType, currency: currency || 'UAH' };
      if (creditLimit > 0) updated.creditLimit = creditLimit;
      if (newOwner === owner || !newOwner) {
        cards[idx] = updated;
        setCards(cards, owner);
      } else {
        cards.splice(idx, 1);
        setCards(cards, owner);
        const targetCards = getCards(newOwner);
        targetCards.push(updated);
        setCards(targetCards, newOwner);
      }
      renderWalletsPage();
      showToast('💾 Зберігаю...');
      syncSettingsToSheet()
        .then(() => showToast('✅ Збережено на сервер'))
        .catch(e => showToast('⚠️ Локально OK, сервер: ' + e.message, 'error'));
    },
    onDelete: () => {
      cards.splice(idx, 1);
      setCards(cards, owner);
      renderWalletsPage();
      showToast('💾 Видаляю...');
      syncSettingsToSheet()
        .then(() => showToast('✅ Кошельок видалено'))
        .catch(e => showToast('⚠️ Видалено локально, сервер: ' + e.message, 'error'));
    }
  });
}
