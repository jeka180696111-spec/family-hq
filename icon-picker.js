// ═══════════════════════════════════════════════════════════════
// ICON PICKER — універсальний редактор з вибором іконки, кольору і типу
// ═══════════════════════════════════════════════════════════════

import { ICON_LIST } from './config.js';
import { esc, uid } from './utils.js';
import { openBottomSheet, closeModal } from './modals.js';

// Палітра кольорів (bg + color)
export const COLOR_PALETTE = [
  {bg:'#E1F5EE', color:'#085041'},
  {bg:'#FAECE7', color:'#712B13'},
  {bg:'#E6F1FB', color:'#0C447C'},
  {bg:'#FEF3E2', color:'#633806'},
  {bg:'#FBEAF0', color:'#72243E'},
  {bg:'#EEEDFE', color:'#3C3489'},
  {bg:'#F0F4FF', color:'#2D4AB7'},
  {bg:'#EAF3DE', color:'#27500A'},
  {bg:'#FAEEDA', color:'#633806'},
  {bg:'#1a1a2e', color:'#ffffff'},
  {bg:'#F0F0F0', color:'#555555'},
];

// ── Відкриття пікера ────────────────────────────────────────
// opts: {
//   title:       'Новий рахунок',
//   nameLabel:   'Назва',
//   nameValue:   '',
//   namePlaceholder: 'Наприклад: Картка ПУМБ',
//   showTypes:   true|false,        // показати селектор типу (для кошельків)
//   typesList:   [{id,name,icon,bg,color}], // які типи на вибір
//   selectedType: 'savings',          // обраний за замовчуванням
//   selectedIcon: 'ti-wallet',
//   selectedColor: {bg, color},
//   isEdit:      false,
//   onSave:      ({name, icon, color, walletType}) => {},
//   onDelete:    () => {},             // якщо є — показуємо кнопку Видалити
//   extraFields: '<HTML>',             // додаткові поля (напр. вибір власника)
// }
export function openIconPicker(opts) {
  const namId = uid('ip-name');
  const iconsId = uid('ip-icons');
  const colorsId = uid('ip-colors');
  const typesId = uid('ip-types');
  const curId = uid('ip-cur');
  const saveId = uid('ip-save');
  const delId = uid('ip-del');

  let selName  = opts.nameValue || '';
  let selIcon  = opts.selectedIcon || 'ti-wallet';
  let selColor = opts.selectedColor || COLOR_PALETTE[0];
  let selType  = opts.selectedType || null;
  let selCur   = opts.selectedCurrency || 'UAH';

  const showTypes = opts.showTypes && Array.isArray(opts.typesList) && opts.typesList.length > 0;
  if (showTypes && !selType) selType = opts.typesList[0].id;

  const showCurrency = opts.showCurrency;

  const content = `
    ${opts.extraFields || ''}
    <label class="ip-label">${esc(opts.nameLabel || 'Назва')}</label>
    <input id="${namId}" class="ip-input" type="text" value="${esc(selName)}" placeholder="${esc(opts.namePlaceholder || '')}">

    ${showCurrency ? `
      <label class="ip-label">Валюта</label>
      <div class="ip-cur-row">
        <button type="button" class="ip-cur-btn ${selCur === 'UAH' ? 'active' : ''}" data-cur="UAH">
          <span class="ip-cur-sym">₴</span>
          <span class="ip-cur-name">Гривня</span>
        </button>
        <button type="button" class="ip-cur-btn ${selCur === 'USD' ? 'active' : ''}" data-cur="USD">
          <span class="ip-cur-sym">$</span>
          <span class="ip-cur-name">Долар</span>
        </button>
        <button type="button" class="ip-cur-btn ${selCur === 'EUR' ? 'active' : ''}" data-cur="EUR">
          <span class="ip-cur-sym">€</span>
          <span class="ip-cur-name">Євро</span>
        </button>
      </div>
    ` : ''}

    ${showTypes ? `
      <label class="ip-label">Тип рахунку</label>
      <div id="${typesId}" class="ip-types"></div>
    ` : ''}

    <label class="ip-label">Іконка</label>
    <div id="${iconsId}" class="ip-icons"></div>

    <label class="ip-label">Колір</label>
    <div id="${colorsId}" class="ip-colors"></div>
  `;

  const footer = `
    ${opts.onDelete ? `<button id="${delId}" class="btn-danger">Видалити</button>` : ''}
    <button id="${saveId}" class="btn-primary flex-1">${opts.isEdit ? 'Зберегти' : 'Додати'}</button>
  `;

  const modalId = openBottomSheet({
    title: opts.title || 'Новий запис',
    content,
    footer,
    size: 'md',
    onOpen: (wrap) => {
      const nameEl   = wrap.querySelector('#' + namId);
      const iconsEl  = wrap.querySelector('#' + iconsId);
      const colorsEl = wrap.querySelector('#' + colorsId);
      const typesEl  = wrap.querySelector('#' + typesId);

      // Авто-фокус на полі назви
      setTimeout(() => nameEl && nameEl.focus(), 100);

      function render() {
        // Іконки
        if (iconsEl) {
          iconsEl.innerHTML = ICON_LIST.map(ic => `
            <button type="button" class="ip-icon-btn ${ic === selIcon ? 'active' : ''}" data-ic="${ic}"
              style="background:${ic === selIcon ? selColor.bg : ''};border-color:${ic === selIcon ? selColor.color : ''};">
              <i class="ti ${ic}" style="color:${ic === selIcon ? selColor.color : ''}"></i>
            </button>
          `).join('');
          iconsEl.querySelectorAll('[data-ic]').forEach(b => {
            b.addEventListener('click', () => { selIcon = b.dataset.ic; render(); });
          });
        }
        // Кольори
        if (colorsEl) {
          colorsEl.innerHTML = COLOR_PALETTE.map((c, i) => `
            <button type="button" class="ip-color-btn ${c.bg === selColor.bg && c.color === selColor.color ? 'active' : ''}"
              data-cidx="${i}"
              style="background:${c.bg};border-color:${c.bg === selColor.bg && c.color === selColor.color ? c.color : 'transparent'};">
            </button>
          `).join('');
          colorsEl.querySelectorAll('[data-cidx]').forEach(b => {
            b.addEventListener('click', () => {
              selColor = COLOR_PALETTE[parseInt(b.dataset.cidx)];
              render();
            });
          });
        }
        // Типи
        if (typesEl) {
          typesEl.innerHTML = opts.typesList.map(t => {
            const active = t.id === selType;
            return `
              <button type="button" class="ip-type-btn ${active ? 'active' : ''}" data-tp="${esc(t.id)}"
                style="background:${active ? (t.bg || selColor.bg) : ''};border-color:${active ? (t.color || selColor.color) : ''};color:${active ? (t.color || selColor.color) : ''}">
                <i class="ti ${t.icon || 'ti-wallet'}"></i>
                <span>${esc(t.name)}</span>
              </button>
            `;
          }).join('');
          typesEl.querySelectorAll('[data-tp]').forEach(b => {
            b.addEventListener('click', () => {
              selType = b.dataset.tp;
              // Авто-підбір іконки і кольору з типу (якщо не редагуємо)
              const tp = opts.typesList.find(x => x.id === selType);
              if (tp && !opts.isEdit) {
                if (tp.icon) selIcon = tp.icon;
                if (tp.bg && tp.color) selColor = { bg: tp.bg, color: tp.color };
              }
              render();
            });
          });
        }
      }
      render();

      // Перемикач валюти
      wrap.querySelectorAll('[data-cur]').forEach(b => {
        b.addEventListener('click', () => {
          selCur = b.dataset.cur;
          wrap.querySelectorAll('[data-cur]').forEach(x => x.classList.toggle('active', x.dataset.cur === selCur));
        });
      });

      // Save
      wrap.querySelector('#' + saveId).addEventListener('click', () => {
        const name = (nameEl.value || '').trim();
        if (!name) {
          import('./utils.js').then(u => u.showToast('Введи назву', 'error'));
          nameEl.focus();
          return;
        }
        const result = { name, icon: selIcon, color: selColor };
        if (showTypes) result.walletType = selType;
        if (showCurrency) result.currency = selCur;
        // extra fields
        wrap.querySelectorAll('[data-ip-extra]').forEach(el => {
          result[el.dataset.ipExtra] = el.value;
        });
        closeModal(modalId);
        opts.onSave(result);
      });

      // Delete
      const delBtn = wrap.querySelector('#' + delId);
      if (delBtn) {
        delBtn.addEventListener('click', async () => {
          const ok = await import('./modals.js').then(m => m.confirmModal('Видалити?', { danger: true, okText: 'Видалити' }));
          if (ok) {
            closeModal(modalId);
            opts.onDelete();
          }
        });
      }
    }
  });
  return modalId;
}
