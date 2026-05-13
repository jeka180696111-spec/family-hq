// ═══════════════════════════════════════════════════════════════
// MODALS — універсальна система модальних вікон
// ═══════════════════════════════════════════════════════════════

import { uid, esc } from './utils.js';

let currentModals = []; // стек відкритих модалок

// ── Базова модалка ──────────────────────────────────────────
// opts: { title, content (HTML), footer (HTML), onOpen, onClose, size: 'sm'|'md'|'lg', sheet: bool }
export function openModal(opts) {
  const id = uid('modal');
  const zIndex = 600 + currentModals.length * 10;
  const wrap = document.createElement('div');
  wrap.id = id;
  wrap.className = 'modal-overlay' + (opts.sheet ? ' modal-sheet' : '');
  wrap.style.zIndex = zIndex;

  const sizeCls = 'modal-' + (opts.size || 'md');
  wrap.innerHTML = `
    <div class="modal ${sizeCls}" data-modal-id="${id}">
      ${opts.sheet ? '<div class="modal-grabber"></div>' : ''}
      ${opts.title ? `<div class="modal-header"><div class="modal-title">${opts.title}</div><button class="modal-close" data-modal-close><i class="ti ti-x"></i></button></div>` : ''}
      <div class="modal-body">${opts.content || ''}</div>
      ${opts.footer ? `<div class="modal-footer">${opts.footer}</div>` : ''}
    </div>`;
  document.body.appendChild(wrap);
  document.body.style.overflow = 'hidden';

  // Закриття по кліку на фон
  wrap.addEventListener('click', (e) => {
    if (e.target === wrap) closeModal(id);
  });
  // Закриття по кнопці X
  wrap.querySelectorAll('[data-modal-close]').forEach(b => {
    b.addEventListener('click', () => closeModal(id));
  });
  // ESC
  const onKey = (e) => { if (e.key === 'Escape') closeModal(id); };
  document.addEventListener('keydown', onKey);

  // Анімація появи
  requestAnimationFrame(() => wrap.classList.add('show'));

  currentModals.push({ id, wrap, onClose: opts.onClose, onKey });
  if (opts.onOpen) opts.onOpen(wrap);
  return id;
}

// ── Закрити модалку ─────────────────────────────────────────
export function closeModal(id) {
  // Якщо id не вказаний — закриваємо останню
  if (!id && currentModals.length) id = currentModals[currentModals.length - 1].id;
  const idx = currentModals.findIndex(m => m.id === id);
  if (idx === -1) return;
  const m = currentModals[idx];
  m.wrap.classList.remove('show');
  m.wrap.classList.add('hide');
  document.removeEventListener('keydown', m.onKey);
  setTimeout(() => {
    m.wrap.remove();
    if (m.onClose) m.onClose();
  }, 200);
  currentModals.splice(idx, 1);
  if (currentModals.length === 0) document.body.style.overflow = '';
}

// ── Закрити всі ─────────────────────────────────────────────
export function closeAllModals() {
  while (currentModals.length) closeModal(currentModals[currentModals.length - 1].id);
}

// ── Confirm (просте підтвердження) ──────────────────────────
export function confirmModal(text, opts = {}) {
  return new Promise((resolve) => {
    const id = openModal({
      title: opts.title || 'Підтвердіть',
      content: `<p class="modal-text">${esc(text)}</p>`,
      footer: `
        <button class="btn-ghost" data-act="cancel">${opts.cancelText || 'Скасувати'}</button>
        <button class="btn-${opts.danger ? 'danger' : 'primary'}" data-act="ok">${opts.okText || 'OK'}</button>
      `,
      size: 'sm',
      onOpen: (wrap) => {
        wrap.querySelector('[data-act="cancel"]').addEventListener('click', () => {
          closeModal(id); resolve(false);
        });
        wrap.querySelector('[data-act="ok"]').addEventListener('click', () => {
          closeModal(id); resolve(true);
        });
      }
    });
  });
}

// ── Prompt (введення тексту) ────────────────────────────────
export function promptModal(label, defaultValue = '', opts = {}) {
  return new Promise((resolve) => {
    const inputId = uid('prompt');
    const id = openModal({
      title: opts.title || label,
      content: `<input id="${inputId}" class="modal-input" type="text" value="${esc(defaultValue)}" placeholder="${esc(opts.placeholder || '')}">`,
      footer: `
        <button class="btn-ghost" data-act="cancel">Скасувати</button>
        <button class="btn-primary" data-act="ok">${opts.okText || 'OK'}</button>
      `,
      size: 'sm',
      onOpen: (wrap) => {
        const inp = wrap.querySelector('#' + inputId);
        setTimeout(() => inp.focus(), 100);
        inp.addEventListener('keydown', e => {
          if (e.key === 'Enter') { closeModal(id); resolve(inp.value.trim()); }
        });
        wrap.querySelector('[data-act="cancel"]').addEventListener('click', () => {
          closeModal(id); resolve(null);
        });
        wrap.querySelector('[data-act="ok"]').addEventListener('click', () => {
          closeModal(id); resolve(inp.value.trim());
        });
      }
    });
  });
}

// ── Bottom sheet (для мобільного — підіймається знизу) ──────
export function openBottomSheet(opts) {
  return openModal({ ...opts, sheet: true });
}
