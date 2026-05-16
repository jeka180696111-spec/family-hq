// ═══════════════════════════════════════════════════════════════
// GOALS — фінансові цілі
// ═══════════════════════════════════════════════════════════════

import { state } from './config.js';
import { apiGet, apiPost } from './api.js';
import { esc, fmtMoney, fmtDate, showToast, uid } from './utils.js';
import { openBottomSheet, closeModal, confirmModal } from './modals.js';

// ── Завантаження ─────────────────────────────────────────────
export async function loadGoals() {
  try {
    const data = await apiGet('goals');
    state.goals = data.goals || [];
  } catch (e) {
    state.goals = [];
  }
  renderGoalsPage();
}

// ── Рендер ──────────────────────────────────────────────────
export function renderGoalsPage() {
  const el = document.getElementById('page-goals');
  if (!el) return;

  const goals = state.goals || [];

  el.innerHTML = `
    <div class="page-inner">
      <div class="page-head">
        <h1 class="page-title">Цілі</h1>
        <button class="btn-primary" id="add-goal-btn">
          <i class="ti ti-plus"></i> Нова ціль
        </button>
      </div>

      ${goals.length === 0 ? `
        <div class="empty-state">
          <div class="empty-state-illustration">🎯</div>
          <div class="empty-state-title">Немає цілей</div>
          <div class="empty-state-text">Постав першу фінансову ціль і йди до неї крок за кроком</div>
        </div>
      ` : `
        <div class="goals-grid">
          ${goals.map(g => renderGoalCard(g)).join('')}
        </div>
      `}
    </div>
  `;

  // Слухачі
  el.querySelector('#add-goal-btn')?.addEventListener('click', () => openGoalDialog());
  el.querySelectorAll('[data-goal-row]').forEach(card => {
    card.addEventListener('click', () => {
      const row = card.dataset.goalRow;
      const g = goals.find(x => String(x.row) === String(row) || String(x.id) === String(row));
      if (g) openGoalDialog(g);
    });
  });
}

// ── Карточка цілі ───────────────────────────────────────────
function renderGoalCard(g) {
  const pct = Math.min(100, Math.max(0, g.percent || 0));
  const remaining = Math.max(0, (g.target || 0) - (g.saved || 0));
  const daysLeft = g.deadline ? Math.ceil((new Date(g.deadline) - new Date()) / (86400 * 1000)) : null;
  return `
    <div class="goal-card" data-goal-row="${g.row}">
      <div class="goal-card-head">
        <div class="goal-card-name">${esc(g.displayName || g.name)}</div>
        ${daysLeft !== null ? `<div class="goal-card-deadline">${daysLeft > 0 ? `за ${daysLeft} дн` : daysLeft === 0 ? 'сьогодні' : `${-daysLeft} дн тому`}</div>` : ''}
      </div>
      <div class="goal-card-progress">
        <div class="goal-card-bar"><div class="goal-card-bar-fill" style="width:${pct}%"></div></div>
        <div class="goal-card-pct">${pct}%</div>
      </div>
      <div class="goal-card-amounts">
        <div class="goal-card-saved">${fmtMoney(g.saved || 0, 'UAH')}</div>
        <div class="goal-card-target">з ${fmtMoney(g.target || 0, 'UAH')}</div>
      </div>
      <div class="goal-card-remaining">залишилось ${fmtMoney(remaining, 'UAH')}</div>
    </div>
  `;
}

// ── Діалог створення/редагування ────────────────────────────
function openGoalDialog(editing) {
  const isEdit = !!editing;
  const nameId = uid('g-name');
  const tgtId = uid('g-tgt');
  const savedId = uid('g-saved');
  const dlId = uid('g-dl');
  const saveId = uid('g-save');
  const delId = uid('g-del');

  const modalId = openBottomSheet({
    title: isEdit ? 'Редагувати ціль' : 'Нова ціль',
    content: `
      <label class="ip-label">Назва</label>
      <input id="${nameId}" class="ip-input" type="text" value="${esc(editing?.displayName || editing?.name || '')}" placeholder="🏖 Відпустка в Греції">

      <label class="ip-label">Потрібно</label>
      <input id="${tgtId}" class="ip-input ip-input-big" type="number" inputmode="decimal" value="${editing?.target || ''}" placeholder="50000">

      <label class="ip-label">Накопичено</label>
      <input id="${savedId}" class="ip-input" type="number" inputmode="decimal" value="${editing?.saved || 0}" placeholder="0">

      <label class="ip-label">Дедлайн (необов'язково)</label>
      <input id="${dlId}" class="ip-input" type="date" value="${editing?.deadline || ''}">
    `,
    footer: `
      ${isEdit ? `<button id="${delId}" class="btn-danger">Видалити</button>` : ''}
      <button class="btn-ghost" data-modal-close>Скасувати</button>
      <button id="${saveId}" class="btn-primary flex-1">${isEdit ? 'Зберегти' : 'Створити'}</button>
    `,
    onOpen: (wrap) => {
      setTimeout(() => wrap.querySelector('#' + nameId).focus(), 100);

      wrap.querySelector('#' + saveId).addEventListener('click', async () => {
        const name = wrap.querySelector('#' + nameId).value.trim();
        const target = parseFloat(wrap.querySelector('#' + tgtId).value);
        const saved = parseFloat(wrap.querySelector('#' + savedId).value) || 0;
        const deadline = wrap.querySelector('#' + dlId).value;

        if (!name) { showToast('Введи назву', 'error'); return; }
        if (!target || target <= 0) { showToast('Введи цільову суму', 'error'); return; }

        const body = isEdit
          ? { action: 'updateGoal', row: editing.row, name, target, saved, deadline }
          : { action: 'addGoal', name, target, saved, deadline };

        try {
          await apiPost(body);
          closeModal(modalId);
          showToast(isEdit ? '✅ Збережено' : '✅ Ціль створена');
          loadGoals();
        } catch (e) {
          showToast('Помилка: ' + e.message, 'error');
        }
      });

      const delBtn = wrap.querySelector('#' + delId);
      if (delBtn) {
        delBtn.addEventListener('click', async () => {
          const ok = await confirmModal('Видалити ціль?', { danger: true, okText: 'Видалити' });
          if (!ok) return;
          try {
            await apiPost({ action: 'deleteGoal', row: editing.row });
            closeModal(modalId);
            showToast('Видалено');
            loadGoals();
          } catch (e) { showToast(e.message, 'error'); }
        });
      }
    }
  });
}
