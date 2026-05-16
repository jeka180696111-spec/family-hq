// ═══════════════════════════════════════════════════════════════
// AI CHAT — розмова з фінансовим радником Кіосе
// ═══════════════════════════════════════════════════════════════

import { state, FAMILY_MEMBERS } from './config.js';
import { fmtMoney, esc, showToast } from './utils.js';
import { getViewAsMember } from './storage.js';
import { getCreditCards } from './credit-cards.js';

const CHAT_SYSTEM = `Ти — саркастичний особистий фінансовий радник на ім'я Фінн.
Стиль: дотепний, їдкий, але з теплотою і турботою. Як старший друг який розбирається в фінансах.
Правила:
- Відповідай УКРАЇНСЬКОЮ
- Будь коротким: 2-4 речення максимум (якщо не просять детальний аналіз)
- Використовуй конкретні цифри з даних якщо вони є
- Хвали за хороші рішення, їдко критикуй за погані
- Емодзі помірно
- Не повторюй питання користувача
- Якщо питання не про фінанси — м'яко поверни до теми грошей`;

let chatHistory = [];

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

export function renderAIChatPage() {
  const el = document.getElementById('page-ai-chat');
  if (!el) return;

  el.innerHTML = `
    <div class="page-inner chat-page-inner">
      <div class="page-head">
        <h1 class="page-title">💬 Чат з Кіосе</h1>
        <button class="btn-ghost-sm" id="chat-clear"><i class="ti ti-trash"></i> Очистити</button>
      </div>

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
      </div>
    </div>
  `;

  const input = el.querySelector('#chat-input');
  const sendBtn = el.querySelector('#chat-send');
  const messagesEl = el.querySelector('#chat-messages');

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

  el.querySelector('#chat-clear').addEventListener('click', () => {
    chatHistory = [];
    messagesEl.innerHTML = `<div class="chat-bubble bot"><div class="chat-bubble-text">Почнемо спочатку 😏 Питай.</div></div>`;
  });

  scrollToBottom();
}
