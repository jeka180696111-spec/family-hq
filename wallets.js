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

      <div class="ops-filter-bar wallets-filter-bar" id="wallets-filter-bar">
        <button class="ops-filter-btn ${ownerFilter !== 'all' ? 'active' : ''}" id="wf-owner" data-wf="owner">
          <i class="ti ti-user"></i>
          <span>${ownerFilter !== 'all' ? esc(profiles[ownerFilter]?.name || ownerFilter) : 'Власник'}</span>
          <i class="ti ti-chevron-down opf-arrow"></i>
        </button>
        <button class="ops-filter-btn ${typeFilter !== 'all' ? 'active' : ''}" id="wf-type" data-wf="type">
          <i class="ti ti-wallet"></i>
          <span>${typeFilter !== 'all' ? esc(types.find(t=>t.id===typeFilter)?.name || typeFilter) : 'Тип'}</span>
          <i class="ti ti-chevron-down opf-arrow"></i>
        </button>
      </div>

      <div class="wallets-list">
        ${filtered.length === 0 ? `
          <div class="empty-state">
            <div class="empty-state-illustration">💳</div>
            <div class="empty-state-title">Немає кошельків</div>
            <div class="empty-state-text">Додай перший кошельок — готівка, картка або рахунок</div>
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

  // Animate hero balance
  requestAnimationFrame(() => {
    const balEl = el.querySelector('.wallets-hero-balance');
    if (!balEl) return;
    const target = totalBalanceUah;
    const duration = 600;
    const start = performance.now();
    function tick(now) {
      const p = Math.min((now - start) / duration, 1);
      const ease = p === 1 ? 1 : 1 - Math.pow(2, -10 * p);
      const cur = Math.round(Math.abs(target) * ease) * Math.sign(target);
      balEl.textContent = cur.toLocaleString('uk-UA') + ' ₴';
      if (p < 1) requestAnimationFrame(tick);
      else balEl.textContent = fmtMoney(target, 'UAH');
    }
    requestAnimationFrame(tick);
  });

  // Слухачі фільтрів — compact dropdown bar
  {
    const filterBar = el.querySelector('#wallets-filter-bar');
    let openDropdown = null;

    function closeWfDropdown() {
      if (openDropdown) {
        openDropdown.remove();
        openDropdown = null;
        filterBar && filterBar.querySelectorAll('.ops-filter-btn').forEach(b => b.classList.remove('open'));
      }
    }

    filterBar && filterBar.querySelectorAll('.ops-filter-btn[data-wf]').forEach(btn => {
      btn.addEventListener('click', e => {
        e.stopPropagation();
        const key = btn.dataset.wf;
        if (openDropdown && btn.classList.contains('open')) {
          closeWfDropdown();
          return;
        }
        closeWfDropdown();
        btn.classList.add('open');

        let options = [];
        if (key === 'owner') {
          options = [
            { val: 'all', label: 'Усі' },
            ...FAMILY_MEMBERS.map(m => ({ val: m, label: profiles[m]?.name || m })),
          ];
        } else if (key === 'type') {
          options = [
            { val: 'all', label: 'Усі' },
            ...types.map(t => ({ val: t.id, label: t.name })),
          ];
        }

        const curVal = key === 'owner' ? ownerFilter : typeFilter;
        const dd = document.createElement('div');
        dd.className = 'opf-dropdown open';
        dd.style.maxHeight = '240px';
        dd.style.overflowY = 'auto';

        options.forEach(opt => {
          const item = document.createElement('button');
          item.className = 'opf-item' + (opt.val === curVal ? ' active' : '');
          item.textContent = opt.label;
          item.addEventListener('click', e2 => {
            e2.stopPropagation();
            if (key === 'owner') state.walletFilter = opt.val;
            else state.walletTypeFilter = opt.val;
            closeWfDropdown();
            renderWalletsPage();
          });
          dd.appendChild(item);
        });

        const btnRect = btn.getBoundingClientRect();
        const barRect = filterBar.getBoundingClientRect();
        dd.style.left = (btnRect.left - barRect.left) + 'px';
        dd.style.top = (btnRect.bottom - barRect.top + 4) + 'px';

        filterBar.appendChild(dd);
        openDropdown = dd;
      });
    });

    document.addEventListener('click', function onWfOutsideClick(e) {
      if (openDropdown && filterBar && !filterBar.contains(e.target)) {
        closeWfDropdown();
      }
    }, { capture: true });
  }

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
