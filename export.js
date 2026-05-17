import { apiGet } from './api.js';
import { state } from './config.js';
import { getCards, getProfiles, getExpCats } from './storage.js';
import { showToast } from './utils.js';
import { fmtMoney } from './utils.js';

function loadXLSX() {
  return new Promise((resolve, reject) => {
    if (window.XLSX) { resolve(window.XLSX); return; }
    const s = document.createElement('script');
    s.src = 'https://cdn.jsdelivr.net/npm/xlsx@0.18.5/dist/xlsx.full.min.js';
    s.onload = () => resolve(window.XLSX);
    s.onerror = () => reject(new Error('Не вдалося завантажити XLSX'));
    document.head.appendChild(s);
  });
}

export async function exportToExcel() {
  showToast('Готую файл...');
  try {
    const XLSX = await loadXLSX();

    // Load all operations
    let ops = [];
    try {
      const data = await apiGet('operations', { limit: 9999 });
      ops = data.operations || [];
    } catch(e) {
      ops = state.operations || [];
    }

    const wb = XLSX.utils.book_new();

    // ── Sheet 1: All operations ──────────────────────────────
    const MONTHS_UA = ['Січ','Лют','Бер','Кві','Тра','Чер','Лип','Сер','Вер','Жов','Лис','Гру'];
    const opRows = ops.map(o => ({
      'Дата': o.date ? o.date.slice(0, 10) : '',
      'Тип': o.type || '',
      'Сума': o.amount || 0,
      'Валюта': o.currency || 'UAH',
      'Сума (UAH)': o.amountUah || o.amount || 0,
      'Категорія': o.category || '',
      'Гаманець': o.card || '',
      'Учасник': o.who || '',
      'Опис': o.desc || '',
    }));
    const ws1 = XLSX.utils.json_to_sheet(opRows);
    // Column widths
    ws1['!cols'] = [
      {wch:12},{wch:10},{wch:10},{wch:8},{wch:12},
      {wch:16},{wch:14},{wch:12},{wch:28}
    ];
    XLSX.utils.book_append_sheet(wb, ws1, 'Операції');

    // ── Sheet 2: By category ─────────────────────────────────
    const byCat = {};
    ops.filter(o => o.type === 'Витрата').forEach(o => {
      const cat = o.category || 'Без категорії';
      byCat[cat] = (byCat[cat] || 0) + (o.amountUah || o.amount || 0);
    });
    const catRows = Object.entries(byCat)
      .sort((a,b) => b[1]-a[1])
      .map(([cat, amt]) => ({ 'Категорія': cat, 'Витрати (UAH)': Math.round(amt) }));
    if (catRows.length) {
      const ws2 = XLSX.utils.json_to_sheet(catRows);
      ws2['!cols'] = [{wch:20},{wch:16}];
      XLSX.utils.book_append_sheet(wb, ws2, 'По категоріях');
    }

    // ── Sheet 3: By month ────────────────────────────────────
    const byMonth = {};
    ops.forEach(o => {
      const key = o.date ? o.date.slice(0,7) : 'unknown';
      if (!byMonth[key]) byMonth[key] = { inc: 0, exp: 0 };
      if (o.type === 'Дохід')   byMonth[key].inc += (o.amountUah || o.amount || 0);
      if (o.type === 'Витрата') byMonth[key].exp += (o.amountUah || o.amount || 0);
    });
    const monthRows = Object.keys(byMonth).sort().map(m => ({
      'Місяць': m,
      'Доходи (UAH)': Math.round(byMonth[m].inc),
      'Витрати (UAH)': Math.round(byMonth[m].exp),
      'Баланс (UAH)': Math.round(byMonth[m].inc - byMonth[m].exp),
    }));
    if (monthRows.length) {
      const ws3 = XLSX.utils.json_to_sheet(monthRows);
      ws3['!cols'] = [{wch:10},{wch:14},{wch:14},{wch:14}];
      XLSX.utils.book_append_sheet(wb, ws3, 'По місяцях');
    }

    const today = new Date().toISOString().slice(0,10);
    XLSX.writeFile(wb, `money-budget-${today}.xlsx`);
    showToast(`Готово! Експортовано ${ops.length} операцій`, 'success');
  } catch(e) {
    showToast('Помилка експорту: ' + e.message, 'error');
  }
}
