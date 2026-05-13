// ═══════════════════════════════════════════════════════════════
// WALLETS — єдина сторінка "Кошельки" з фільтрами
// ═══════════════════════════════════════════════════════════════

import { FAMILY_MEMBERS, state } from './config.js';
import { getCards, setCards, getWalletTypes, getWalletTypeById, getProfiles } from './storage.js';
import { syncSettingsToSheet } from './api.js';
import { esc, fmtMoney, showToast } from './utils.js';
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

  // Підрахунок балансу для кожної картки (з state.operations)
  function cardBalance(card) {
    const ops = state.operations || [];
    let bal = 0;
    ops.forEach(o => {
      if (o.who === card.owner && o.card === card.id) {
        if (o.type === 'Дохід')   bal += (o.amountUah || o.amount || 0);
        if (o.type === 'Витрата') bal -= (o.amountUah || o.amount || 0);
      }
    });
    return bal;
  }

  // Загальна сума по фільтру
  const totalBalance = filtered.reduce((s, c) => s + cardBalance(c), 0);
  const totalCount = filtered.length;

  el.innerHTML = `
    <div class="page-inner">
      <div class="wallets-hero">
        <div class="wallets-hero-label">${ownerFilter === 'all' ? 'Усі рахунки' : 'Рахунки: ' + esc(profiles[ownerFilter]?.name || ownerFilter)}</div>
        <div class="wallets-hero-balance">${fmtMoney(totalBalance, 'UAH')}</div>
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
          const tp = getWalletTypeById(c.walletType);
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
                </div>
              </div>
              <div class="wallet-row-balance ${bal >= 0 ? 'pos' : 'neg'}">${fmtMoney(bal, 'UAH')}</div>
            </div>
          `;
        }).join('')}
      </div>

      <button class="btn-floating-add" id="add-wallet-btn" title="Додати кошельок">
        <i class="ti ti-plus"></i>
      </button>
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

  // Кнопка додати
  const addBtn = el.querySelector('#add-wallet-btn');
  if (addBtn) {
    addBtn.addEventListener('click', () => openCreateWallet());
  }
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
    typesList: types,
    selectedType: types[0]?.id,
    selectedIcon: types[0]?.icon || 'ti-wallet',
    selectedColor: { bg: types[0]?.bg || '#E6F1FB', color: types[0]?.color || '#0C447C' },
    isEdit: false,
    onSave: ({ name, icon, color, walletType, owner }) => {
      const ownerFinal = owner && FAMILY_MEMBERS.includes(owner) ? owner : selOwner;
      const cards = getCards(ownerFinal);
      // Перевірка унікальності
      if (cards.find(c => c.id === name)) {
        showToast('Кошельок з такою назвою вже існує', 'error');
        return;
      }
      cards.push({ id: name, icon, bg: color.bg, color: color.color, walletType });
      setCards(cards, ownerFinal);
      syncSettingsToSheet();
      showToast('✅ Кошельок додано');
      renderWalletsPage();
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
    typesList: types,
    selectedType: card.walletType || types[0]?.id,
    selectedIcon: card.icon,
    selectedColor: { bg: card.bg, color: card.color },
    isEdit: true,
    onSave: ({ name, icon, color, walletType, owner: newOwner }) => {
      const updated = { id: name, icon, bg: color.bg, color: color.color, walletType };
      // Якщо власник той же — просто оновлюємо
      if (newOwner === owner || !newOwner) {
        cards[idx] = updated;
        setCards(cards, owner);
      } else {
        // Переносимо в іншого власника
        cards.splice(idx, 1);
        setCards(cards, owner);
        const targetCards = getCards(newOwner);
        targetCards.push(updated);
        setCards(targetCards, newOwner);
      }
      syncSettingsToSheet();
      showToast('✅ Збережено');
      renderWalletsPage();
    },
    onDelete: () => {
      cards.splice(idx, 1);
      setCards(cards, owner);
      syncSettingsToSheet();
      showToast('Кошельок видалено');
      renderWalletsPage();
    }
  });
}
