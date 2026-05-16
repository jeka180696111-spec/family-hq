// ═══════════════════════════════════════════════════════════════
// ANALYTICS — повна сторінка аналізу: Місяць / Квартал / Рік
// ═══════════════════════════════════════════════════════════════

import { state, FAMILY_MEMBERS } from './config.js';
import { apiGet } from './api.js';
import { esc, fmtMoney, fmtMoneyShort, log } from './utils.js';
import { getExpCats, getProfiles, getDashPeriod, setDashPeriod, getViewAsMember } from './storage.js';

let analyticsData = null;
let trendData = null;
let loading = false;

export async function loadAnalytics() {
  if (loading) return;
  loading = true;
  try {
    const period = getDashPeriod();
    const [data, trend] = await Promise.all([
      apiGet('dashboard', { period }),
      trendData ? Promise.resolve({ trend: trendData }) : apiGet('trend'),
    ]);
    analyticsData = data;
    trendData = trend.trend;
    renderAnalyticsPage();
  } catch (e) {
    log('loadAnalytics error:', e.message);
    renderAnalyticsPage();
  } finally {
    loading = false;
  }
}

export function renderAnalyticsPage() {
  const el = document.getElementById('page-analytics');
  if (!el) return;

  const d = analyticsData || state.dashboard || { totalIncome: 0, totalExpense: 0, balance: 0, byMember: {}, byCategory: {}, byDay: {}, byDayIncome: {} };
  const period = getDashPeriod();
  const viewAs = getViewAsMember();
  const profiles = getProfiles();
  const catsList = getExpCats();

  // Заголовок періоду
  const now = new Date();
  let periodLabel = '';
  if (period === 'month') {
    periodLabel = now.toLocaleDateString('uk-UA', { month: 'long', year: 'numeric' });
  } else if (period === 'quarter') {
    const q = Math.floor(now.getMonth() / 3) + 1;
    periodLabel = `Q${q} ${now.getFullYear()}`;
  } else {
    periodLabel = String(now.getFullYear());
  }

  // Фільтр по viewAs
  let totalIncome = d.totalIncome || 0;
  let totalExpense = d.totalExpense || 0;
  let byCat = d.byCategory || {};
  let byDay = d.byDay || {};
  if (viewAs) {
    totalIncome = d.byMember?.[viewAs]?.income || 0;
    totalExpense = d.byMember?.[viewAs]?.expense || 0;
    byCat = d.byCategoryMember?.[viewAs] || {};
    byDay = d.byDayMember?.[viewAs] || {};
  }
  const balance = totalIncome - totalExpense;
  const savRate = totalIncome > 0 ? Math.round((totalIncome - totalExpense) / totalIncome * 100) : 0;

  const sorted = Object.entries(byCat).sort((a, b) => b[1] - a[1]);

  el.innerHTML = `
    <div class="page-inner">
      <div class="page-head">
        <h1 class="page-title">Аналіз${viewAs ? ' · ' + esc(profiles[viewAs]?.name || viewAs) : ''}</h1>
      </div>

      <!-- Перемикач періоду -->
      <div class="period-switch">
        <button class="period-btn ${period === 'month' ? 'active' : ''}" data-period="month">Місяць</button>
        <button class="period-btn ${period === 'quarter' ? 'active' : ''}" data-period="quarter">Квартал</button>
        <button class="period-btn ${period === 'year' ? 'active' : ''}" data-period="year">Рік</button>
      </div>

      <!-- Підсумок 3 цифри -->
      <div class="ops-summary">
        <div class="ops-summary-item ops-summary-inc">
          <div class="ops-summary-label">Доходи · ${esc(periodLabel)}</div>
          <div class="ops-summary-amount">+${fmtMoney(totalIncome, 'UAH')}</div>
        </div>
        <div class="ops-summary-item ops-summary-exp">
          <div class="ops-summary-label">Витрати · ${esc(periodLabel)}</div>
          <div class="ops-summary-amount">−${fmtMoney(totalExpense, 'UAH')}</div>
        </div>
        <div class="ops-summary-item ops-summary-bal">
          <div class="ops-summary-label">Баланс</div>
          <div class="ops-summary-amount ${balance >= 0 ? 'c-green' : 'c-red'}">${balance >= 0 ? '+' : '−'}${fmtMoney(Math.abs(balance), 'UAH')}</div>
        </div>
      </div>

      <!-- Накопичено % -->
      ${totalIncome > 0 ? `
        <div class="analytics-savings">
          <div class="analytics-savings-label">Норма заощаджень</div>
          <div class="analytics-savings-bar">
            <div class="analytics-savings-fill ${savRate >= 0 ? 'pos' : 'neg'}" style="width:${Math.min(100, Math.abs(savRate))}%"></div>
          </div>
          <div class="analytics-savings-text">${savRate >= 0 ? `Зекономлено ${savRate}% доходів` : `Витрачено на ${Math.abs(savRate)}% більше за доходи`}</div>
        </div>
      ` : ''}

      <!-- Тренд по місяцях -->
      ${renderTrendChart(trendData)}

      <!-- Графік по днях -->
      ${period === 'month' && Object.keys(byDay).length ? `
        <div class="dash-card">
          <div class="dash-card-head">
            <span class="dash-card-title">Витрати по днях</span>
            <span class="dash-card-amount c-red">${fmtMoney(totalExpense, 'UAH')}</span>
          </div>
          ${renderDayChart(byDay, now)}
        </div>
      ` : ''}

      <!-- По категоріях -->
      <div class="dash-card">
        <div class="dash-card-head">
          <span class="dash-card-title">По категоріях</span>
          <span class="dash-card-amount">${sorted.length} ${sorted.length === 1 ? 'категорія' : 'категорій'}</span>
        </div>
        ${sorted.length === 0 ? '<div class="empty-mini">Немає витрат у цьому періоді</div>' :
          `<div class="dash-cats-list">
            ${sorted.map(([cat, val]) => {
              const pct = totalExpense ? (val / totalExpense * 100).toFixed(0) : 0;
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

      <!-- По членах сім'ї -->
      ${!viewAs ? renderByMember(d.byMember || {}) : ''}
    </div>
  `;

  bindHandlers(el);
}

function renderByMember(byMember) {
  const entries = Object.entries(byMember).filter(([k]) => k);
  if (!entries.length) return '';
  const profiles = getProfiles();
  return `
    <div class="dash-card">
      <div class="dash-card-head">
        <span class="dash-card-title">По членах сім'ї</span>
      </div>
      <div class="analytics-members">
        ${entries.map(([name, info]) => {
          const inc = info.income || 0;
          const exp = info.expense || 0;
          const bal = info.balance || 0;
          return `
            <div class="analytics-member-card">
              <div class="analytics-member-head">
                <div class="topbar-viewas-avatar" style="width:36px;height:36px;font-size:14px">${(profiles[name]?.name || name)[0]}</div>
                <div class="analytics-member-name">${esc(profiles[name]?.name || name)}</div>
              </div>
              <div class="analytics-member-stats">
                <div class="analytics-member-stat">
                  <div class="analytics-member-stat-label">Дохід</div>
                  <div class="analytics-member-stat-value c-green">+${fmtMoney(inc, 'UAH')}</div>
                </div>
                <div class="analytics-member-stat">
                  <div class="analytics-member-stat-label">Витрата</div>
                  <div class="analytics-member-stat-value c-red">−${fmtMoney(exp, 'UAH')}</div>
                </div>
                <div class="analytics-member-stat">
                  <div class="analytics-member-stat-label">Баланс</div>
                  <div class="analytics-member-stat-value ${bal >= 0 ? 'c-green' : 'c-red'}">${bal >= 0 ? '+' : '−'}${fmtMoney(Math.abs(bal), 'UAH')}</div>
                </div>
              </div>
            </div>
          `;
        }).join('')}
      </div>
    </div>
  `;
}

function renderTrendChart(trend) {
  if (!trend || trend.length < 2) return '';
  const maxVal = Math.max(...trend.flatMap(m => [m.income, m.expense]), 1);
  const MONTHS_UA = ['Січ','Лют','Бер','Кві','Тра','Чер','Лип','Сер','Вер','Жов','Лис','Гру'];

  return `
    <div class="dash-card">
      <div class="dash-card-head">
        <span class="dash-card-title">📈 Тренд за 6 місяців</span>
      </div>
      <div class="trend-chart">
        ${trend.map(m => {
          const [y, mon] = m.month.split('-').map(Number);
          const label = MONTHS_UA[mon - 1];
          const incH = Math.round((m.income  / maxVal) * 100);
          const expH = Math.round((m.expense / maxVal) * 100);
          const bal  = m.income - m.expense;
          return `
            <div class="trend-col" title="${label} ${y}: +${fmtMoneyShort(m.income)} / −${fmtMoneyShort(m.expense)}">
              <div class="trend-bars">
                <div class="trend-bar inc" style="height:${incH}%" title="Дохід: ${fmtMoneyShort(m.income)}"></div>
                <div class="trend-bar exp" style="height:${expH}%" title="Витрата: ${fmtMoneyShort(m.expense)}"></div>
              </div>
              <div class="trend-bal ${bal >= 0 ? 'pos' : 'neg'}">${bal >= 0 ? '+' : ''}${fmtMoneyShort(bal)}</div>
              <div class="trend-label">${label}</div>
            </div>
          `;
        }).join('')}
      </div>
      <div class="trend-legend">
        <span class="trend-legend-inc">▌ Дохід</span>
        <span class="trend-legend-exp">▌ Витрата</span>
      </div>
    </div>
  `;
}

function renderDayChart(byDay, monthDate) {
  const days = Object.keys(byDay).map(Number).sort((a, b) => a - b);
  if (!days.length) return '<div class="empty-mini">Немає витрат</div>';
  const max = Math.max(...days.map(d => byDay[d]));
  const today = new Date().getDate();
  const isCurMonth = monthDate.getMonth() === new Date().getMonth() && monthDate.getFullYear() === new Date().getFullYear();

  return `
    <div class="analytics-bars">
      ${days.map(d => {
        const v = byDay[d];
        const h = max ? (v / max * 100) : 0;
        const isToday = isCurMonth && d === today;
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

function bindHandlers(el) {
  el.querySelectorAll('[data-period]').forEach(b => {
    b.addEventListener('click', () => {
      setDashPeriod(b.dataset.period);
      loadAnalytics();
    });
  });
}
