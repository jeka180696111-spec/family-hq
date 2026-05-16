// ═══════════════════════════════════════════════════════════════
// CHALLENGES — Досягнення та сімейні челенджі
// ═══════════════════════════════════════════════════════════════

import { state } from './config.js';
import { esc, fmtMoney, showToast, uid } from './utils.js';
import { getCategoryLimits } from './storage.js';
import { openBottomSheet, closeModal } from './modals.js';
import { apiGet, apiPost } from './api.js';
import { whoAmI } from './auth.js';

// ── Визначення досягнень ────────────────────────────────────
const ACHIEVEMENTS = [
  {
    id: 'gourmet',
    icon: '🍕',
    title: 'Гурман',
    desc: 'Витратив 2 000+ ₴ на ресторани за місяць',
    check: (d) => (d.byCategory?.['Ресторани'] || 0) >= 2000,
    progress: (d) => Math.min(100, Math.round(((d.byCategory?.['Ресторани'] || 0) / 2000) * 100)),
  },
  {
    id: 'driver',
    icon: '🚗',
    title: 'Автомобіліст',
    desc: 'Витратив 2 000+ ₴ на транспорт за місяць',
    check: (d) => (d.byCategory?.['Транспорт'] || 0) >= 2000,
    progress: (d) => Math.min(100, Math.round(((d.byCategory?.['Транспорт'] || 0) / 2000) * 100)),
  },
  {
    id: 'shopper',
    icon: '🛒',
    title: 'Закупівельник',
    desc: 'Витратив 5 000+ ₴ на продукти за місяць',
    check: (d) => (d.byCategory?.['Продукти'] || 0) >= 5000,
    progress: (d) => Math.min(100, Math.round(((d.byCategory?.['Продукти'] || 0) / 5000) * 100)),
  },
  {
    id: 'saver',
    icon: '💰',
    title: 'Ощадливий',
    desc: 'Зекономив 20%+ від місячного доходу',
    check: (d) => d.totalIncome > 0 && (d.totalIncome - d.totalExpense) / d.totalIncome >= 0.2,
    progress: (d) => {
      if (!d.totalIncome) return 0;
      return Math.min(100, Math.round(((d.totalIncome - d.totalExpense) / d.totalIncome / 0.2) * 100));
    },
  },
  {
    id: 'disciplined',
    icon: '🎯',
    title: 'Дисциплінований',
    desc: 'Жоден ліміт витрат не перевищено за місяць',
    check: (d, limits) => {
      const entries = Object.entries(limits);
      if (!entries.length) return false;
      return entries.every(([cat, lim]) => (d.byCategory?.[cat] || 0) <= lim);
    },
    progress: (d, limits) => {
      const entries = Object.entries(limits);
      if (!entries.length) return 0;
      const ok = entries.filter(([cat, lim]) => (d.byCategory?.[cat] || 0) <= lim).length;
      return Math.round((ok / entries.length) * 100);
    },
  },
  {
    id: 'healthy',
    icon: '💊',
    title: 'Дбайливий',
    desc: "Витратив 500+ ₴ на здоров'я за місяць",
    check: (d) => (d.byCategory?.["Здоров'я"] || 0) >= 500,
    progress: (d) => Math.min(100, Math.round(((d.byCategory?.["Здоров'я"] || 0) / 500) * 100)),
  },
  {
    id: 'big_earner',
    icon: '🏆',
    title: 'Великий заробіток',
    desc: 'Дохід за місяць понад 50 000 ₴',
    check: (d) => (d.totalIncome || 0) >= 50000,
    progress: (d) => Math.min(100, Math.round(((d.totalIncome || 0) / 50000) * 100)),
  },
  {
    id: 'no_restaurants',
    icon: '🥗',
    title: 'Домашня кухня',
    desc: 'Не витрачав на ресторани весь місяць',
    check: (d) => d.totalExpense > 0 && !(d.byCategory?.['Ресторани']),
    progress: (d) => d.totalExpense > 0 && !(d.byCategory?.['Ресторани']) ? 100 : 0,
  },
  {
    id: 'scanner_user',
    icon: '🧾',
    title: 'Цифровий бухгалтер',
    desc: 'Відсканував перший чек через AI',
    check: () => !!localStorage.getItem('budget_scanned_receipt'),
    progress: () => localStorage.getItem('budget_scanned_receipt') ? 100 : 0,
  },
  {
    id: 'ai_chat_user',
    icon: '🤖',
    title: 'Друг Фінна',
    desc: 'Поставив питання AI-радникові Фінну',
    check: () => !!localStorage.getItem('budget_ai_chat_used'),
    progress: () => localStorage.getItem('budget_ai_chat_used') ? 100 : 0,
  },
];

let activeTab = 'achievements';
let challenges = [];

export async function loadChallenges() {
  try {
    const data = await apiGet('challenges');
    challenges = data?.challenges || [];
  } catch (e) {
    challenges = [];
  }
  renderChallengesPage();
}

export function renderChallengesPage() {
  const el = document.getElementById('page-challenges');
  if (!el) return;

  const d = state.dashboard || {};
  const limits = getCategoryLimits();

  const earned = ACHIEVEMENTS.filter(a => a.check(d, limits));
  const inProgress = ACHIEVEMENTS.filter(a => !a.check(d, limits));

  el.innerHTML = `
    <div class="page-inner">
      <div class="page-head">
        <h1 class="page-title">🏅 Гра</h1>
      </div>

      <div class="ch-tabs">
        <button class="ch-tab ${activeTab === 'achievements' ? 'active' : ''}" data-tab="achievements">
          🏅 Досягнення <span class="ch-tab-badge">${earned.length}/${ACHIEVEMENTS.length}</span>
        </button>
        <button class="ch-tab ${activeTab === 'challenges' ? 'active' : ''}" data-tab="challenges">
          🎯 Челенджі <span class="ch-tab-badge">${challenges.filter(c => c.status === 'active').length}</span>
        </button>
      </div>

      <div id="ch-tab-content">
        ${activeTab === 'achievements' ? renderAchievementsTab(earned, inProgress, d, limits) : renderChallengesTab()}
      </div>
    </div>
  `;

  el.querySelectorAll('.ch-tab').forEach(tab => {
    tab.addEventListener('click', () => {
      activeTab = tab.dataset.tab;
      renderChallengesPage();
    });
  });

  el.querySelectorAll('[data-create-challenge]').forEach(b => {
    b.addEventListener('click', () => openCreateChallengeDialog());
  });

  el.querySelectorAll('[data-complete-challenge]').forEach(b => {
    b.addEventListener('click', async () => {
      const id = b.dataset.completeChallenge;
      try {
        await apiPost({ action: 'completeChallenge', challengeId: id });
        showToast('🏆 Челендж виконано!');
        await loadChallenges();
      } catch(e) { showToast(e.message, 'error'); }
    });
  });
}

function renderAchievementsTab(earned, inProgress, d, limits) {
  const now = new Date();
  const month = now.toLocaleDateString('uk-UA', { month: 'long', year: 'numeric' });

  return `
    ${earned.length > 0 ? `
      <div class="ch-section-label">✅ Отримано цього місяця (${month})</div>
      <div class="ch-achievements-grid">
        ${earned.map(a => `
          <div class="ch-achievement earned">
            <div class="ch-achievement-icon">${a.icon}</div>
            <div class="ch-achievement-title">${esc(a.title)}</div>
            <div class="ch-achievement-desc">${esc(a.desc)}</div>
          </div>
        `).join('')}
      </div>
    ` : `
      <div class="ch-empty-state">
        <div style="font-size:48px;margin-bottom:12px">🎯</div>
        <div style="font-weight:600;margin-bottom:6px">Ще немає досягнень цього місяця</div>
        <div style="font-size:13px;color:var(--c-text-3)">Продовжуй — трофеї чекають!</div>
      </div>
    `}

    ${inProgress.length > 0 ? `
      <div class="ch-section-label" style="margin-top:20px">🔄 В процесі</div>
      <div class="ch-achievements-grid">
        ${inProgress.map(a => {
          const pct = a.progress(d, limits);
          return `
            <div class="ch-achievement">
              <div class="ch-achievement-icon locked">${a.icon}</div>
              <div class="ch-achievement-title">${esc(a.title)}</div>
              <div class="ch-achievement-desc">${esc(a.desc)}</div>
              <div class="ch-progress-bar">
                <div class="ch-progress-fill" style="width:${pct}%"></div>
              </div>
              <div class="ch-progress-label">${pct}%</div>
            </div>
          `;
        }).join('')}
      </div>
    ` : ''}
  `;
}

function renderChallengesTab() {
  const active = challenges.filter(c => c.status === 'active');
  const done = challenges.filter(c => c.status === 'completed');

  return `
    <button class="btn-primary" style="width:100%;margin-bottom:16px" data-create-challenge>
      <i class="ti ti-plus"></i> Створити челендж
    </button>

    ${active.length === 0 && done.length === 0 ? `
      <div class="ch-empty-state">
        <div style="font-size:48px;margin-bottom:12px">🎯</div>
        <div style="font-weight:600;margin-bottom:6px">Немає активних челенджів</div>
        <div style="font-size:13px;color:var(--c-text-3)">Створи перший сімейний виклик!</div>
      </div>
    ` : ''}

    ${active.map(c => renderChallengeCard(c)).join('')}

    ${done.length > 0 ? `
      <div class="ch-section-label" style="margin-top:20px">✅ Завершені</div>
      ${done.map(c => renderChallengeCard(c, true)).join('')}
    ` : ''}
  `;
}

function renderChallengeCard(c, completed = false) {
  const d = state.dashboard || {};
  let progress = 0;
  let progressLabel = '';

  if (c.type === 'save') {
    const saved = Math.max(0, (d.totalIncome || 0) - (d.totalExpense || 0));
    progress = c.targetAmount > 0 ? Math.min(100, Math.round((saved / c.targetAmount) * 100)) : 0;
    progressLabel = `${fmtMoney(saved, 'UAH')} з ${fmtMoney(c.targetAmount, 'UAH')}`;
  } else if (c.type === 'limit') {
    const spent = d.byCategory?.[c.targetCategory] || 0;
    const target = c.targetAmount;
    progress = target > 0 ? Math.min(100, Math.round((spent / target) * 100)) : (spent === 0 ? 100 : 0);
    progressLabel = target > 0 ? `${fmtMoney(spent, 'UAH')} з ${fmtMoney(target, 'UAH')} ліміту` : (spent === 0 ? 'Поки тримаємось!' : `Витрачено ${fmtMoney(spent, 'UAH')}`);
    progress = c.type === 'limit' && target > 0 ? (100 - progress) : progress;
    progress = Math.max(0, progress);
  }

  return `
    <div class="ch-challenge-card ${completed ? 'completed' : ''}">
      <div class="ch-challenge-header">
        <div class="ch-challenge-prize">${esc(c.prize || '🏆')}</div>
        <div class="ch-challenge-info">
          <div class="ch-challenge-title">${esc(c.title)}</div>
          <div class="ch-challenge-desc">${esc(c.description || '')}</div>
          ${c.endDate ? `<div class="ch-challenge-date">до ${esc(c.endDate)}</div>` : ''}
        </div>
      </div>
      ${!completed ? `
        <div class="ch-progress-bar" style="margin:10px 0 4px">
          <div class="ch-progress-fill ${progress >= 100 ? 'done' : ''}" style="width:${progress}%"></div>
        </div>
        <div style="display:flex;justify-content:space-between;font-size:12px;color:var(--c-text-2)">
          <span>${progressLabel}</span>
          <span>${progress}%</span>
        </div>
        ${progress >= 100 ? `<button class="btn-primary" style="width:100%;margin-top:10px" data-complete-challenge="${esc(c.id)}">🏆 Отримати приз!</button>` : ''}
      ` : `<div style="color:var(--c-green);font-size:13px;font-weight:600;margin-top:8px">✅ Виконано! Приз: ${esc(c.prizeAwarded || c.prize || '🏆')}</div>`}
    </div>
  `;
}

function openCreateChallengeDialog() {
  const titleId = uid('ch-title');
  const typeId = uid('ch-type');
  const catId = uid('ch-cat');
  const amtId = uid('ch-amt');
  const prizeId = uid('ch-prize');
  const endId = uid('ch-end');
  const saveId = uid('ch-save');

  const EXPENSE_CATS = ['Продукти', 'Ресторани', 'Транспорт', 'Комунальні', "Здоров'я", 'Одяг', 'Розваги', 'Дім', 'Дитячі', 'Інше'];

  const modalId = openBottomSheet({
    title: 'Новий челендж',
    content: `
      <label class="ip-label">Назва челенджу</label>
      <input id="${titleId}" class="ip-input" placeholder="Наприклад: Місяць без кафе">

      <label class="ip-label" style="margin-top:12px">Тип</label>
      <select id="${typeId}" class="ip-input">
        <option value="save">💰 Зекономити суму</option>
        <option value="limit">🚫 Не витрачати більше X на категорію</option>
        <option value="custom">🎯 Власний челендж</option>
      </select>

      <div id="ch-type-fields">
        <label class="ip-label" style="margin-top:12px">Сума цілі (₴)</label>
        <input id="${amtId}" class="ip-input" type="number" placeholder="10000">
      </div>

      <label class="ip-label" style="margin-top:12px">Приз / опис нагороди</label>
      <input id="${prizeId}" class="ip-input" placeholder="🏆 Вечеря в ресторані">

      <label class="ip-label" style="margin-top:12px">Дата закінчення</label>
      <input id="${endId}" class="ip-input" type="date" value="${new Date().toISOString().slice(0,7)}-28">
    `,
    footer: `
      <button class="btn-ghost" data-modal-close>Скасувати</button>
      <button id="${saveId}" class="btn-primary flex-1">Створити</button>
    `,
    onOpen: (wrap) => {
      const typeEl = wrap.querySelector('#' + typeId);
      const fieldsEl = wrap.querySelector('#ch-type-fields');

      typeEl.addEventListener('change', () => {
        const t = typeEl.value;
        if (t === 'limit') {
          fieldsEl.innerHTML = `
            <label class="ip-label" style="margin-top:12px">Категорія</label>
            <select id="${catId}" class="ip-input">
              ${EXPENSE_CATS.map(c => `<option value="${c}">${c}</option>`).join('')}
            </select>
            <label class="ip-label" style="margin-top:12px">Максимум витрат (₴)</label>
            <input id="${amtId}" class="ip-input" type="number" placeholder="2000">
          `;
        } else if (t === 'save') {
          fieldsEl.innerHTML = `
            <label class="ip-label" style="margin-top:12px">Сума для накопичення (₴)</label>
            <input id="${amtId}" class="ip-input" type="number" placeholder="10000">
          `;
        } else {
          fieldsEl.innerHTML = `
            <label class="ip-label" style="margin-top:12px">Опис умови</label>
            <input id="${amtId}" class="ip-input" placeholder="Наприклад: ходити пішки на роботу">
          `;
        }
      });

      wrap.querySelector('#' + saveId).addEventListener('click', async () => {
        const title = wrap.querySelector('#' + titleId)?.value.trim();
        const type = wrap.querySelector('#' + typeId)?.value;
        const prize = wrap.querySelector('#' + prizeId)?.value.trim();
        const endDate = wrap.querySelector('#' + endId)?.value;
        const catEl = wrap.querySelector('#' + catId);
        const amtEl = wrap.querySelector('#' + amtId);

        if (!title) { showToast('Введи назву', 'error'); return; }

        try {
          await apiPost({
            action: 'createChallenge',
            title,
            type,
            targetCategory: catEl?.value || '',
            targetAmount: parseFloat(amtEl?.value) || 0,
            prize: prize || '🏆',
            endDate: endDate || '',
            createdBy: whoAmI() || 'Невідомий',
          });
          closeModal(modalId);
          showToast('✅ Челендж створено!');
          loadChallenges();
        } catch(e) { showToast(e.message, 'error'); }
      });
    }
  });
}
