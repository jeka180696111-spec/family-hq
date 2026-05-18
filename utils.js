// ═══════════════════════════════════════════════════════════════
// UTILS — допоміжні функції
// ═══════════════════════════════════════════════════════════════

// Екранування HTML
export function esc(str) {
  if (str === null || str === undefined) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

// Форматування грошей
export function fmtMoney(amount, currency) {
  if (amount === null || amount === undefined || isNaN(amount)) return '0 ₴';
  const num = Math.round(Math.abs(amount)).toLocaleString('uk-UA');
  const sym = { UAH: '₴', USD: '$', EUR: '€', GBP: '£', PLN: 'zł', CHF: '₣', CAD: 'C$', CZK: 'Kč', JPY: '¥', CNY: '¥', TRY: '₺' }[currency] || (currency || '₴');
  return currency === 'UAH' || !currency ? `${num} ${sym}` : `${sym}${num}`;
}

// Конвертація суми у UAH (за поточним курсом НБУ)
export function toUah(amount, currency, fx) {
  if (!amount || isNaN(amount)) return 0;
  if (!currency || currency === 'UAH') return Math.round(amount);
  if (!fx || !fx[currency]) return Math.round(amount); // fallback: показуємо як є
  const rate = fx[currency].mid || fx[currency].buy || fx[currency].sale || 0;
  return Math.round(amount * rate);
}

// Формат із UAH в дужках для валютних гаманців
// USD/EUR → "$200 (≈ 8 798 ₴)" або "−$200 (≈ −8 798 ₴)"
// UAH → "40 077 ₴" або "−40 077 ₴" (без дужок)
export function fmtMoneyWithUah(amount, currency, fx) {
  if (amount === null || amount === undefined || isNaN(amount)) return '0 ₴';
  const sign = amount < 0 ? '−' : '';
  const abs = Math.abs(amount);
  if (!currency || currency === 'UAH') {
    return sign + fmtMoney(abs, 'UAH');
  }
  // Валютний — показуємо в його валюті + UAH в дужках
  const main = fmtMoney(abs, currency);
  const uahEquiv = toUah(abs, currency, fx);
  return `${sign}${main} <span class="cur-uah">(≈ ${sign}${fmtMoney(uahEquiv, 'UAH')})</span>`;
}

// Знак суми зі вставкою UAH
// для негативних: "−$200 (≈ −8 798 ₴)"
export function fmtMoneySigned(amount, currency, fx, withUah) {
  if (amount === null || amount === undefined || isNaN(amount)) return '0 ₴';
  const sign = amount < 0 ? '−' : (amount > 0 ? '+' : '');
  const absAmount = Math.abs(amount);
  if (!currency || currency === 'UAH' || !withUah) {
    return sign + fmtMoney(absAmount, currency || 'UAH');
  }
  const main = fmtMoney(absAmount, currency);
  const uahEquiv = toUah(absAmount, currency, fx);
  return `${sign}${main} <span class="cur-uah">(≈ ${sign}${fmtMoney(uahEquiv, 'UAH')})</span>`;
}

// Скорочена форма (1.2K, 145.8K)
export function fmtMoneyShort(amount, currency) {
  if (!amount) return '0';
  const abs = Math.abs(amount);
  let str;
  if (abs >= 1000000) str = (amount / 1000000).toFixed(1).replace(/\.0$/, '') + 'M';
  else if (abs >= 1000) str = (amount / 1000).toFixed(1).replace(/\.0$/, '') + 'K';
  else str = Math.round(amount).toString();
  const sym = { UAH: '₴', USD: '$', EUR: '€' }[currency] || '₴';
  return str + ' ' + sym;
}

// Безпечно встановлюємо текст по id
export function setText(id, text) {
  const el = document.getElementById(id);
  if (el) el.textContent = text;
}

// Безпечно отримуємо value з input
export function getValue(id) {
  const el = document.getElementById(id);
  return el ? el.value : '';
}

// Toast-повідомлення
export function showToast(message, type) {
  // Видаляємо старі тости
  document.querySelectorAll('.toast').forEach(t => t.remove());
  const toast = document.createElement('div');
  toast.className = 'toast' + (type === 'error' ? ' toast-error' : type === 'warn' ? ' toast-warn' : '');
  toast.textContent = message;
  document.body.appendChild(toast);
  setTimeout(() => toast.classList.add('show'), 10);
  setTimeout(() => {
    toast.classList.remove('show');
    setTimeout(() => toast.remove(), 300);
  }, 2500);
}

// Форматування дати
export function fmtDate(date, format) {
  if (!date) return '';
  const d = new Date(date);
  if (isNaN(d)) return '';
  const dd = String(d.getDate()).padStart(2, '0');
  const mm = String(d.getMonth() + 1).padStart(2, '0');
  const yyyy = d.getFullYear();
  const hh = String(d.getHours()).padStart(2, '0');
  const mi = String(d.getMinutes()).padStart(2, '0');
  if (format === 'full')  return `${dd}.${mm}.${yyyy} ${hh}:${mi}`;
  if (format === 'short') return `${dd}.${mm}`;
  if (format === 'iso')   return `${yyyy}-${mm}-${dd}`;
  return `${dd}.${mm}.${yyyy}`;
}

// Стандартний YYYY-MM ключ місяця
export function monthKey(date) {
  const d = date instanceof Date ? date : new Date(date);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
}

// Чи це сьогодні?
export function isToday(date) {
  const d = new Date(date);
  const now = new Date();
  return d.getDate() === now.getDate()
      && d.getMonth() === now.getMonth()
      && d.getFullYear() === now.getFullYear();
}

// Чи це той самий місяць
export function sameMonth(d1, d2) {
  const a = new Date(d1), b = new Date(d2);
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth();
}

// Debounce
export function debounce(fn, ms) {
  let t;
  return function(...args) {
    clearTimeout(t);
    t = setTimeout(() => fn.apply(this, args), ms);
  };
}

// Простий transliterate для id (ua → en-friendly)
export function slugify(str) {
  return String(str)
    .toLowerCase()
    .replace(/[ё]/g, 'e')
    .replace(/[й]/g, 'i')
    .replace(/[ц]/g, 'c')
    .replace(/[\s]+/g, '_')
    .replace(/[^a-z0-9_а-яіїєґ]/gi, '')
    .substring(0, 30);
}

// Унікальний ID
export function uid(prefix) {
  return (prefix || 'id') + '_' + Date.now().toString(36) + Math.random().toString(36).substring(2, 6);
}

// Логування з префіксом
export function log(...args) {
  if (typeof console !== 'undefined') console.log('[budget]', ...args);
}

export function logError(...args) {
  if (typeof console !== 'undefined') console.error('[budget:error]', ...args);
}

// ── Експорт операцій у CSV ───────────────────────────────────
export function exportOperationsToCSV(operations) {
  if (!Array.isArray(operations) || operations.length === 0) {
    showToast('Немає операцій для експорту', 'warn');
    return;
  }

  const SEP = ';';
  const headers = ['Дата', 'Тип', 'Категорія', 'Сума', 'Валюта', 'Сума (UAH)', 'Гаманець', 'Хто', 'Коментар'];

  function fmtDate(raw) {
    if (!raw) return '';
    const d = new Date(raw);
    if (isNaN(d)) return String(raw);
    const pad = n => String(n).padStart(2, '0');
    return `${pad(d.getDate())}.${pad(d.getMonth() + 1)}.${d.getFullYear()} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
  }

  function fmtType(t) {
    if (!t) return '';
    const map = { income: 'Дохід', expense: 'Витрата', transfer: 'Переказ' };
    return map[t.toLowerCase()] || t;
  }

  function csvCell(val) {
    const str = val === null || val === undefined ? '' : String(val);
    if (str.includes(SEP) || str.includes('"') || str.includes('\n')) {
      return '"' + str.replace(/"/g, '""') + '"';
    }
    return str;
  }

  const rows = operations.map(op => [
    csvCell(fmtDate(op.date || op.createdAt || '')),
    csvCell(fmtType(op.type || '')),
    csvCell(op.category || op.cat || ''),
    csvCell(op.amount !== undefined ? op.amount : (op.sum !== undefined ? op.sum : '')),
    csvCell(op.currency || 'UAH'),
    csvCell(op.amountUah !== undefined ? op.amountUah : (op.sumUah !== undefined ? op.sumUah : '')),
    csvCell(op.wallet || op.card || op.cardId || ''),
    csvCell(op.member || op.who || op.owner || ''),
    csvCell(op.comment || op.note || ''),
  ]);

  const csvContent = [`sep=${SEP}`, headers.map(csvCell).join(SEP), ...rows.map(r => r.join(SEP))].join('\r\n');

  // Визначаємо ім'я файлу: budget_export_YYYY-MM.csv
  const now = new Date();
  const yearMonth = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`;
  const filename = `budget_export_${yearMonth}.csv`;

  // Тригеримо скачування
  const blob = new Blob(['﻿' + csvContent, ''], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);

  showToast(`Експортовано ${operations.length} операцій`);
}
