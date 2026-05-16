// ═══════════════════════════════════════════════════════════════
// AI REPORTS — звіти через Claude API (саркастичний стиль Кіосе)
// ═══════════════════════════════════════════════════════════════

import { state, FAMILY_MEMBERS } from './config.js';
import { fmtMoney, esc, showToast } from './utils.js';
import { getCards, getProfiles, getWalletTypeById } from './storage.js';
import { getCreditCards } from './credit-cards.js';
import { getPaymentReminders } from './recurring-payments.js';

const SYSTEM = `Ти — саркастичний фінансовий радник родини Кіосе. Стиль: дотепний, їдкий, але з любов'ю.
Правила:
- Пиши УКРАЇНСЬКОЮ, коротко і по суті
- Цифри, відсотки, порівняння — обов'язково
- Хвали що добре, жорстко (але з гумором) критикуй що погано
- Називай імена: хто винен — той відповідає 😈
- Використовуй емодзі помірно
- Не більше 300 слів
- Формат: абзаци, без markdown заголовків
- В кінці — одна конкретна порада`;

function collectData() {
  const ops = state.operations || [];
  const inc = ops.filter(o => o.type === 'Дохід').reduce((s, o) => s + (o.amountUah || o.amount || 0), 0);
  const exp = ops.filter(o => o.type === 'Витрата').reduce((s, o) => s + (o.amountUah || o.amount || 0), 0);
  const savRate = inc > 0 ? ((inc - exp) / inc * 100).toFixed(0) : 0;

  // По категоріях
  const byCat = {};
  ops.filter(o => o.type === 'Витрата').forEach(o => {
    byCat[o.category || 'Інше'] = (byCat[o.category || 'Інше'] || 0) + (o.amountUah || o.amount || 0);
  });
  const topCats = Object.entries(byCat).sort((a, b) => b[1] - a[1]).slice(0, 6)
    .map(([c, a]) => `${c}: ${a}₴`).join(', ');

  // По членах
  const byMember = {};
  FAMILY_MEMBERS.forEach(m => { byMember[m] = { inc: 0, exp: 0 }; });
  ops.forEach(o => {
    const t = byMember[o.who];
    if (!t) return;
    if (o.type === 'Дохід') t.inc += (o.amountUah || o.amount || 0);
    else if (o.type === 'Витрата') t.exp += (o.amountUah || o.amount || 0);
  });
  const memberStats = FAMILY_MEMBERS
    .map(m => `${m}: +${byMember[m].inc}₴ / -${byMember[m].exp}₴`)
    .join('; ');

  // Кредитки
  const credits = getCreditCards();
  const creditInfo = credits.length
    ? credits.map(c => `${c.id}(${c.owner}): ${c.pct}% ліміту`).join(', ')
    : 'немає';

  // Великі витрати
  const bigOps = ops.filter(o => o.type === 'Витрата' && (o.amountUah || o.amount) > 3000)
    .map(o => `${o.desc || o.category} ${o.amountUah || o.amount}₴ (${o.who})`).join(', ');

  const period = new Date().toLocaleDateString('uk-UA', { month: 'long', year: 'numeric' });

  return { period, inc, exp, savRate, topCats, memberStats, creditInfo, bigOps, opCount: ops.length };
}

async function callClaude(prompt) {
  const res = await fetch('https://api.anthropic.com/v1/messages', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      model: 'claude-sonnet-4-20250514',
      max_tokens: 1000,
      system: SYSTEM,
      messages: [{ role: 'user', content: prompt }],
    }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.error?.message || `API ${res.status}`);
  }
  const data = await res.json();
  return data.content?.filter(c => c.type === 'text').map(c => c.text).join('\n') || '';
}

export async function generateReport(type = 'monthly') {
  const d = collectData();
  const base = `Дані за ${d.period}: дохід ${d.inc}₴, витрати ${d.exp}₴, заощадження ${d.savRate}%, ${d.opCount} операцій.\nКатегорії: ${d.topCats}\nЧлени: ${d.memberStats}\nКредитки: ${d.creditInfo}`;

  const prompts = {
    monthly: `Місячний звіт родини Кіосе.\n${base}${d.bigOps ? '\nВеликі витрати: ' + d.bigOps : ''}`,
    forecast: `Спрогнозуй наступний місяць для Кіосе.\n${base}\nДай 3 конкретні поради.`,
    roast: `ЖОРСТКИЙ розбір фінансів Кіосе за ${d.period}. Хто винен — назви.\n${base}${d.bigOps ? '\nПІДОЗРІЛІ витрати: ' + d.bigOps : ''}\nВ кінці — як зекономити 1000₴.`,
  };

  return callClaude(prompts[type] || prompts.monthly);
}

// ── Рендер сторінки ──────────────────────────────────────────
export function renderAIReportsPage() {
  const el = document.getElementById('page-ai-reports');
  if (!el) return;

  const d = state.dashboard || {};
  const inc = d.totalIncome || 0;
  const exp = d.totalExpense || 0;
  const sav = inc > 0 ? Math.round((inc - exp) / inc * 100) : 0;
  const month = d.month ? new Date(d.month + '-01').toLocaleDateString('uk-UA', { month: 'long', year: 'numeric' }) : '';

  el.innerHTML = `
    <div class="page-inner">
      <div class="page-head"><h1 class="page-title">AI Аналітика</h1></div>

      ${inc || exp ? `
      <div class="ai-stats-banner">
        <div class="ai-stats-label"><i class="ti ti-robot"></i> Дані для аналізу · ${esc(month)}</div>
        <div class="ai-stats-row">
          <div class="ai-stat">
            <div class="ai-stat-val c-green">+${fmtMoney(inc)}</div>
            <div class="ai-stat-lbl">Доходи</div>
          </div>
          <div class="ai-stat">
            <div class="ai-stat-val c-red">−${fmtMoney(exp)}</div>
            <div class="ai-stat-lbl">Витрати</div>
          </div>
          <div class="ai-stat">
            <div class="ai-stat-val" style="color:var(--c-accent)">${sav}%</div>
            <div class="ai-stat-lbl">Заощадження</div>
          </div>
        </div>
      </div>` : ''}

      <div class="ai-section-label">Оберіть тип звіту</div>
      <div class="ai-cards">
        <button class="ai-card" data-type="monthly">
          <div class="ai-card-icon" style="background:#EEF2FF;color:#4F46E5"><i class="ti ti-chart-bar"></i></div>
          <div class="ai-card-info">
            <div class="ai-card-title">Місячний огляд</div>
            <div class="ai-card-desc">Аналіз доходів, витрат і заощаджень за місяць</div>
          </div>
          <i class="ti ti-sparkles" style="color:#4F46E5;font-size:18px"></i>
        </button>
        <button class="ai-card" data-type="forecast">
          <div class="ai-card-icon" style="background:#ECFDF5;color:#059669"><i class="ti ti-trending-up"></i></div>
          <div class="ai-card-info">
            <div class="ai-card-title">Прогноз</div>
            <div class="ai-card-desc">Прогноз наступного місяця + 3 конкретні поради</div>
          </div>
          <i class="ti ti-sparkles" style="color:#059669;font-size:18px"></i>
        </button>
        <button class="ai-card" data-type="roast">
          <div class="ai-card-icon" style="background:#FFF1F2;color:#E11D48"><i class="ti ti-flame"></i></div>
          <div class="ai-card-info">
            <div class="ai-card-title">Розбір 🔥</div>
            <div class="ai-card-desc">Саркастичний аналіз — хто і де витратив зайве</div>
          </div>
          <i class="ti ti-sparkles" style="color:#E11D48;font-size:18px"></i>
        </button>
      </div>

      <div id="ai-loading" class="ai-loading" style="display:none">
        <div class="ai-spinner"></div>
        <div class="ai-loading-text" id="ai-loading-text">Claude аналізує ваші фінанси...</div>
      </div>

      <div id="ai-result" class="ai-result" style="display:none">
        <div class="ai-result-head">
          <span id="ai-result-label"></span>
          <button class="btn-ghost-sm" id="ai-copy"><i class="ti ti-copy"></i> Копіювати</button>
        </div>
        <div id="ai-result-text" class="ai-result-text"></div>
        <div id="ai-result-time" class="ai-result-time"></div>
      </div>
    </div>
  `;

  el.querySelectorAll('.ai-card').forEach(btn => {
    btn.addEventListener('click', () => runReport(btn.dataset.type));
  });

  document.getElementById('ai-copy')?.addEventListener('click', () => {
    const text = document.getElementById('ai-result-text')?.innerText;
    if (text) navigator.clipboard.writeText(text).then(() => showToast('Скопійовано!'));
  });
}

const LOADING_MSGS = [
  'Claude аналізує ваші фінанси...',
  'Рахує доходи і витрати...',
  'Порівнює з попередніми місяцями...',
  'Формулює висновки...',
  'Майже готово...',
];

async function runReport(type) {
  const loading = document.getElementById('ai-loading');
  const result = document.getElementById('ai-result');
  const labels = { monthly: '📊 Місячний огляд', forecast: '📈 Прогноз', roast: '🔥 Розбір' };

  document.querySelectorAll('.ai-card').forEach(b => b.disabled = true);
  if (loading) loading.style.display = 'flex';
  if (result) result.style.display = 'none';

  // Animated loading messages
  let msgIdx = 0;
  const msgEl = document.getElementById('ai-loading-text');
  const msgInterval = setInterval(() => {
    msgIdx = (msgIdx + 1) % LOADING_MSGS.length;
    if (msgEl) msgEl.textContent = LOADING_MSGS[msgIdx];
  }, 2000);

  try {
    const text = await generateReport(type);
    clearInterval(msgInterval);
    if (loading) loading.style.display = 'none';
    if (result) {
      result.style.display = '';
      document.getElementById('ai-result-label').textContent = labels[type] || type;
      // Render paragraphs, highlight numbers
      document.getElementById('ai-result-text').innerHTML = text
        .split('\n')
        .filter(l => l.trim())
        .map(l => `<p>${esc(l).replace(/(\d[\d\s]*[₴$€%]?)/g, '<b>$1</b>')}</p>`)
        .join('');
      document.getElementById('ai-result-time').textContent =
        'Згенеровано: ' + new Date().toLocaleString('uk-UA');
    }
  } catch (e) {
    clearInterval(msgInterval);
    if (loading) loading.style.display = 'none';
    showToast('AI помилка: ' + e.message, 'error');
  } finally {
    document.querySelectorAll('.ai-card').forEach(b => b.disabled = false);
  }
}
