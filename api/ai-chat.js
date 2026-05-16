// /api/ai-chat.js — чат з AI фінансовим радником

const SYSTEM = `Ти — саркастичний особистий фінансовий радник на ім'я Фінн.
Стиль: дотепний, їдкий, але з теплотою і турботою. Як старший друг який розбирається в фінансах.
Правила:
- Відповідай УКРАЇНСЬКОЮ
- Будь коротким: 2-5 речень (якщо не просять детальний аналіз)
- Використовуй конкретні цифри якщо вони є
- Хвали за хороші рішення, їдко критикуй за погані
- Емодзі помірно
- Якщо питання не про фінанси — м'яко поверни до теми грошей`;

export default async function handler(req, res) {
  if (req.method !== 'POST') return res.status(405).json({ error: 'Method not allowed' });

  const { messages = [], context = '' } = req.body || {};
  const apiKey = process.env.ANTHROPIC_API_KEY;
  if (!apiKey) return res.status(500).json({ error: 'ANTHROPIC_API_KEY not configured' });

  const systemWithContext = context
    ? `${SYSTEM}\n\nПоточні фінансові дані користувача:\n${context}`
    : SYSTEM;

  try {
    const response = await fetch('https://api.anthropic.com/v1/messages', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'x-api-key': apiKey,
        'anthropic-version': '2023-06-01',
      },
      body: JSON.stringify({
        model: 'claude-haiku-4-5-20251001',
        max_tokens: 600,
        system: systemWithContext,
        messages: messages.slice(-10),
      }),
    });

    if (!response.ok) {
      const err = await response.json().catch(() => ({}));
      return res.status(response.status).json({ error: err.error?.message || `API ${response.status}` });
    }

    const data = await response.json();
    const text = data.content?.filter(c => c.type === 'text').map(c => c.text).join('\n') || '';
    return res.json({ text });
  } catch (e) {
    return res.status(500).json({ error: e.message });
  }
}
