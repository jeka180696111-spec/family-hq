// ═══════════════════════════════════════════════════════════════
// AI — Аналітика + Чат (об'єднана вкладка)
// ═══════════════════════════════════════════════════════════════

import { state, FAMILY_MEMBERS } from './config.js';
import { fmtMoney, esc, showToast } from './utils.js';
import { getViewAsMember } from './storage.js';
import { getCreditCards } from './credit-cards.js';
import { generateReport } from './ai-reports.js';

let chatHistory = [];
let activeTab = 'analytics'; // 'analytics' | 'chat'

function getFinancialContext() {
  const d = state.dashboard || {};
  const viewAs = getViewAsMember();
  const inc = viewAs ? (d.byMember?.[viewAs]?.income || 0) : (d.totalIncome || 0);
  const exp = viewAs ? (d.byMember?.[viewAs]?.expense || 0) : (d.totalExpense || 0);
  const month = d.month || '';

  const byCat = viewAs ? (d.byCategoryMember?.[viewAs] || {}) : (d.byCategory || {});
  const topCats = Object.entries(byCat).sort((a, b) => b[1] - a[1]).slice(0, 4)
    .map(([c, a]) => `${c}: ${Math.round(a)}₴`).join(', ');

  const credits = getCreditCards(viewAs);
  const creditInfo = credits.length
    ? credits.map(c => `${c.id}: використано ${c.pct}% ліміту`).join(', ')
    : '';

  const who = viewAs || 'сім\'я';
  return `Фінансові дані (${month}): ${who} — доходи ${Math.round(inc)}₴, витрати ${Math.round(exp)}₴, баланс ${Math.round(inc - exp)}₴.${topCats ? ' Топ витрат: ' + topCats + '.' : ''}${creditInfo ? ' Кредитки: ' + creditInfo + '.' : ''}`;
}

async function sendToClaude(userMessage) {
  const context = getFinancialContext();
  const messages = [
    ...chatHistory,
    { role: 'user', content: userMessage },
  ];

  const res = await fetch('/api/ai-chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ messages, context }),
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.error || `HTTP ${res.status}`);
  }
  const data = await res.json();
  return data.text || '';
}

// ── Головний рендер ──────────────────────────────────────────
export function renderAIChatPage() {
  const el = document.getElementById('page-ai-chat');
  if (!el) return;

  el.innerHTML = `
    <div class="ai-combined-page">
      <div class="ai-combined-head">
        <div style="display:flex;align-items:center;gap:10px">
          <div style="width:40px;height:40px;border-radius:12px;background:linear-gradient(135deg,#4F46E5,#7C3AED);display:flex;align-items:center;justify-content:center;font-size:20px">🤖</div>
          <div>
            <div style="font-size:18px;font-weight:800;line-height:1.2">AI · Фінн</div>
            <div style="font-size:12px;color:var(--c-text-3)">Фінансовий радник</div>
          </div>
        </div>
      </div>

      <div class="ai-tabs">
        <button class="ai-tab ${activeTab === 'analytics' ? 'active' : ''}" data-tab="analytics">
          <i class="ti ti-chart-bar"></i> Аналітика
        </button>
        <button class="ai-tab ${activeTab === 'chat' ? 'active' : ''}" data-tab="chat">
          <i class="ti ti-message-chatbot"></i> Чат з Фінном
        </button>
      </div>

      <div id="ai-tab-analytics" class="ai-tab-panel ${activeTab === 'analytics' ? 'active' : ''}">
        <div class="ai-analytics-scroll">${renderAnalyticsTab()}</div>
      </div>
      <div id="ai-tab-chat" class="ai-tab-panel ${activeTab === 'chat' ? 'active' : ''}">
        ${renderChatTab()}
      </div>
    </div>
  `;

  el.querySelectorAll('.ai-tab').forEach(btn => {
    btn.addEventListener('click', () => {
      activeTab = btn.dataset.tab;
      el.querySelectorAll('.ai-tab').forEach(b => b.classList.toggle('active', b.dataset.tab === activeTab));
      el.querySelectorAll('.ai-tab-panel').forEach(p => p.classList.toggle('active', p.id === 'ai-tab-' + activeTab));
    });
  });

  bindAnalyticsHandlers(el);
  bindChatHandlers(el);
}

// ── Аналітика ────────────────────────────────────────────────
function renderAnalyticsTab() {
  const d = state.dashboard || {};
  const viewAs = getViewAsMember();
  const inc = viewAs ? (d.byMember?.[viewAs]?.income || 0) : (d.totalIncome || 0);
  const exp = viewAs ? (d.byMember?.[viewAs]?.expense || 0) : (d.totalExpense || 0);
  const sav = inc > 0 ? Math.round((inc - exp) / inc * 100) : 0;
  const month = d.month ? new Date(d.month + '-01').toLocaleDateString('uk-UA', { month: 'long', year: 'numeric' }) : '';

  return `
    ${inc || exp ? `
    <div class="ai-stats-banner">
      <div class="ai-stats-label"><i class="ti ti-robot"></i> Дані для аналізу${month ? ' · ' + esc(month) : ''}</div>
      <div class="ai-stats-row">
        <div class="ai-stat">
          <div class="ai-stat-val" style="color:#fff">+${fmtMoney(inc)}</div>
          <div class="ai-stat-lbl">Доходи</div>
        </div>
        <div class="ai-stat">
          <div class="ai-stat-val" style="color:rgba(255,255,255,0.85)">−${fmtMoney(exp)}</div>
          <div class="ai-stat-lbl">Витрати</div>
        </div>
        <div class="ai-stat">
          <div class="ai-stat-val" style="color:#fff">${sav}%</div>
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
  `;
}

const LOADING_MSGS = [
  'Claude аналізує ваші фінанси...',
  'Рахує доходи і витрати...',
  'Порівнює з попередніми місяцями...',
  'Формулює висновки...',
  'Майже готово...',
];

function bindAnalyticsHandlers(el) {
  el.querySelectorAll('.ai-card[data-type]').forEach(btn => {
    btn.addEventListener('click', () => runReport(btn.dataset.type));
  });
  el.querySelector('#ai-copy')?.addEventListener('click', () => {
    const text = el.querySelector('#ai-result-text')?.innerText;
    if (text) navigator.clipboard.writeText(text).then(() => showToast('Скопійовано!'));
  });
}

async function runReport(type) {
  const loading = document.getElementById('ai-loading');
  const result = document.getElementById('ai-result');
  const labels = { monthly: '📊 Місячний огляд', forecast: '📈 Прогноз', roast: '🔥 Розбір' };

  document.querySelectorAll('.ai-card[data-type]').forEach(b => b.disabled = true);
  if (loading) loading.style.display = 'flex';
  if (result) result.style.display = 'none';

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
    document.querySelectorAll('.ai-card[data-type]').forEach(b => b.disabled = false);
  }
}

// ── Чат ─────────────────────────────────────────────────────
function renderChatTab() {
  return `
    <div class="chat-hints">
      <button class="chat-hint-btn" data-hint="Як я витрачаю цього місяця?">📊 Як я витрачаю?</button>
      <button class="chat-hint-btn" data-hint="Де я можу зекономити?">💡 Де зекономити?</button>
      <button class="chat-hint-btn" data-hint="Зроби жорсткий розбір моїх фінансів">🔥 Розбір</button>
      <button class="chat-hint-btn" data-hint="Дай прогноз на наступний місяць">🔮 Прогноз</button>
    </div>

    <div class="chat-messages" id="chat-messages">
      <div class="chat-bubble bot">
        <div class="chat-bubble-text">Привіт! Я Фінн — твій саркастичний фінансовий радник 😈<br>Запитуй про витрати, доходи, заощадження — скажу все як є, не соромлячись.</div>
      </div>
    </div>

    <div class="chat-input-row">
      <input id="chat-input" class="chat-input" type="text" placeholder="Запитай про свої фінанси..." autocomplete="off">
      <button id="chat-send" class="chat-send-btn"><i class="ti ti-send"></i></button>
      <button class="btn-ghost-sm" id="chat-clear" title="Очистити чат"><i class="ti ti-trash"></i></button>
    </div>
  `;
}

function bindChatHandlers(el) {
  const input = el.querySelector('#chat-input');
  const sendBtn = el.querySelector('#chat-send');
  const messagesEl = el.querySelector('#chat-messages');
  if (!input || !sendBtn || !messagesEl) return;

  function scrollToBottom() {
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  function appendMessage(role, text, loading = false) {
    const div = document.createElement('div');
    div.className = `chat-bubble ${role}${loading ? ' loading' : ''}`;
    div.innerHTML = `<div class="chat-bubble-text">${loading ? '<span class="chat-typing"><span></span><span></span><span></span></span>' : esc(text).replace(/\n/g, '<br>')}</div>`;
    messagesEl.appendChild(div);
    scrollToBottom();
    return div;
  }

  async function sendMessage() {
    const text = input.value.trim();
    if (!text) return;
    input.value = '';
    sendBtn.disabled = true;

    appendMessage('user', text);
    const botBubble = appendMessage('bot', '', true);

    try {
      const reply = await sendToClaude(text);
      chatHistory.push({ role: 'user', content: text });
      chatHistory.push({ role: 'assistant', content: reply });
      if (chatHistory.length > 20) chatHistory = chatHistory.slice(-20);

      botBubble.classList.remove('loading');
      botBubble.querySelector('.chat-bubble-text').innerHTML = esc(reply).replace(/\n/g, '<br>');
    } catch (e) {
      botBubble.classList.remove('loading');
      botBubble.querySelector('.chat-bubble-text').textContent = 'Помилка: ' + e.message;
      botBubble.classList.add('error');
    }
    sendBtn.disabled = false;
    input.focus();
    scrollToBottom();
  }

  sendBtn.addEventListener('click', sendMessage);
  input.addEventListener('keydown', e => { if (e.key === 'Enter') sendMessage(); });

  el.querySelectorAll('.chat-hint-btn').forEach(b => {
    b.addEventListener('click', () => {
      input.value = b.dataset.hint;
      sendMessage();
    });
  });

  el.querySelector('#chat-clear')?.addEventListener('click', () => {
    chatHistory = [];
    messagesEl.innerHTML = `<div class="chat-bubble bot"><div class="chat-bubble-text">Почнемо спочатку 😏 Питай.</div></div>`;
  });

  scrollToBottom();
}
