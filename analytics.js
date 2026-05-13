// ═══════════════════════════════════════════════════════════════
// ANALYTICS — аналітика витрат
// ═══════════════════════════════════════════════════════════════

import { state } from './config.js';
import { esc, fmtMoney } from './utils.js';
import { getExpCats } from './storage.js';

export function renderAnalyticsPage() {
  const el = document.getElementById('page-analytics');
  if (!el) return;

  const d = state.dashboard || {};
  const byCat = d.byCategory || {};
  const byDay = d.byDay || {};
  const total = d.totalExpense || 0;
  const catsList = getExpCats();

  // Сортуємо категорії за сумою
  const sorted = Object.entries(byCat).sort((a, b) => b[1] - a[1]);

  el.innerHTML = `
    <div class="page-inner">
      <div class="page-head">
        <h1 class="page-title">Аналіз</h1>
      </div>

      <div class="dash-card">
        <div class="dash-card-head">
          <span class="dash-card-title">Витрати по днях</span>
          <span class="dash-card-amount">${fmtMoney(total, 'UAH')}</span>
        </div>
        ${renderDayChart(byDay)}
      </div>

      <div class="dash-card">
        <div class="dash-card-head">
          <span class="dash-card-title">По категоріях</span>
        </div>
        ${sorted.length === 0 ? '<div class="empty-mini">Немає даних</div>' :
          `<div class="dash-cats-list">
            ${sorted.map(([cat, val]) => {
              const pct = total ? (val / total * 100).toFixed(0) : 0;
              const catMeta = catsList.find(c => c.id === cat) || {};
              return `
                <div class="dash-cat-row">
                  <div class="dash-cat-icon" style="background:${catMeta.bg || '#F0F0F0'}">
                    <i class="ti ${catMeta.icon || 'ti-dots'}" style="color:${catMeta.color || '#555'}"></i>
                  </div>
                  <div class="dash-cat-name">${esc(cat)} <span class="dash-cat-pct">${pct}%</span></div>
                  <div class="dash-cat-bar"><div class="dash-cat-bar-fill" style="width:${pct}%;background:${catMeta.color || 'var(--c-accent)'}"></div></div>
                  <div class="dash-cat-amount">${fmtMoney(val, 'UAH')}</div>
                </div>
              `;
            }).join('')}
          </div>`
        }
      </div>
    </div>
  `;
}

function renderDayChart(byDay) {
  const days = Object.keys(byDay).map(Number).sort((a, b) => a - b);
  if (!days.length) return '<div class="empty-mini">Немає витрат у цьому місяці</div>';
  const max = Math.max(...days.map(d => byDay[d]));
  const today = new Date().getDate();

  return `
    <div class="analytics-bars">
      ${days.map(d => {
        const v = byDay[d];
        const h = max ? (v / max * 100) : 0;
        const isToday = d === today && state.currentMonth.getMonth() === new Date().getMonth();
        return `
          <div class="analytics-bar-col" title="${d}: ${fmtMoney(v, 'UAH')}">
            <div class="analytics-bar" style="height:${h}%;${isToday ? 'background:var(--c-accent)' : ''}"></div>
            <div class="analytics-bar-label">${d}</div>
          </div>
        `;
      }).join('')}
    </div>
  `;
}
