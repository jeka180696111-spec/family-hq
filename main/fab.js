// ═══════════════════════════════════════════════════════════════
// FAB — Floating Action Button (одна кнопка з 4 діями)
// ═══════════════════════════════════════════════════════════════

import { openOperationDialog } from './operations.js';
import { openTransferDialog } from './transfer.js';
import { openScannerChoice } from './receipt-scanner.js';

let fabOpen = false;

// ── Ініціалізація FAB ──────────────────────────────────────
export function initFAB() {
  const fab = document.getElementById('fab-main') || document.getElementById('bn-fab-btn');
  if (!fab) return;
  fab.addEventListener('click', toggleFabMenu);

  // Закриття при кліку поза FAB
  document.addEventListener('click', (e) => {
    if (!fabOpen) return;
    if (!e.target.closest('#fab-main') && !e.target.closest('#bn-fab-btn') && !e.target.closest('#fab-menu')) {
      closeFabMenu();
    }
  });
}

export function toggleFabMenu() {
  if (fabOpen) closeFabMenu();
  else openFabMenu();
}

function openFabMenu() {
  if (fabOpen) return;
  fabOpen = true;
  // Створюємо меню
  let menu = document.getElementById('fab-menu');
  if (menu) menu.remove();
  menu = document.createElement('div');
  menu.id = 'fab-menu';
  menu.className = 'fab-menu';
  menu.innerHTML = `
    <button class="fab-item" data-act="income">
      <div class="fab-item-icon" style="background:var(--c-green-soft);color:var(--c-green)">
        <i class="ti ti-arrow-down-circle"></i>
      </div>
      <span class="fab-item-label">Дохід</span>
    </button>
    <button class="fab-item" data-act="expense">
      <div class="fab-item-icon" style="background:var(--c-red-soft);color:var(--c-red)">
        <i class="ti ti-arrow-up-circle"></i>
      </div>
      <span class="fab-item-label">Витрата</span>
    </button>
    <button class="fab-item" data-act="transfer">
      <div class="fab-item-icon" style="background:var(--c-blue-soft);color:var(--c-blue)">
        <i class="ti ti-arrows-exchange"></i>
      </div>
      <span class="fab-item-label">Переказ</span>
    </button>
    <button class="fab-item" data-act="exchange">
      <div class="fab-item-icon" style="background:var(--c-purple-soft);color:var(--c-purple)">
        <i class="ti ti-currency-dollar"></i>
      </div>
      <span class="fab-item-label">Обмін</span>
    </button>
    <button class="fab-item" data-act="scanner">
      <div class="fab-item-icon" style="background:var(--c-accent-soft);color:var(--c-accent)">
        <i class="ti ti-scan"></i>
      </div>
      <span class="fab-item-label">Сканер</span>
    </button>
  `;
  document.body.appendChild(menu);
  // Анімація появи
  requestAnimationFrame(() => menu.classList.add('show'));

  // Поворот плюса
  const fab = document.getElementById('fab-main');
  if (fab) fab.classList.add('open');

  // Слухачі
  menu.querySelectorAll('[data-act]').forEach(b => {
    b.addEventListener('click', () => {
      const act = b.dataset.act;
      closeFabMenu();
      setTimeout(() => handleFabAction(act), 50);
    });
  });
}

function closeFabMenu() {
  if (!fabOpen) return;
  fabOpen = false;
  const menu = document.getElementById('fab-menu');
  if (menu) {
    menu.classList.remove('show');
    setTimeout(() => menu.remove(), 200);
  }
  const fab = document.getElementById('fab-main');
  if (fab) fab.classList.remove('open');
}

function handleFabAction(act) {
  switch (act) {
    case 'income':
      openOperationDialog({ type: 'Дохід' });
      break;
    case 'expense':
      openOperationDialog({ type: 'Витрата' });
      break;
    case 'transfer':
      openTransferDialog();
      break;
    case 'exchange':
      openTransferDialog({ exchange: true });
      break;
    case 'scanner':
      openScannerChoice();
      break;
  }
}
