// /api/ai-report.js — проксі для Claude AI звітів

const SYSTEM = `Ти — саркастичний фінансовий радник на ім'я Фінн. Стиль: дотепний, їдкий, але з любов'ю.
Правила:
- Пиши УКРАЇНСЬКОЮ, коротко і по суті
- Цифри, відсотки, порівняння — обов'язково
- Хвали що добре, жорстко (але з гумором) критикуй що погано
- Називай імена: хто винен — той відповідає 😈
- Використовуй емодзі помірно
- Не більше 300 слів
- Формат: абзаци, без markdown заголовків
- В кінці — одна конкретна порада`;

export default async function handler(req, res) {
  if (req.method !== 'POST') return res.status(405).json({ error: 'Method not allowed' });

  const { prompt } = req.body || {};
  if (!prompt) return res.status(400).json({ error: 'No prompt' });

  const apiKey = process.env.ANTHROPIC_API_KEY;
  if (!apiKey) return res.status(500).json({ error: 'ANTHROPIC_API_KEY not configured' });

  try {
    const response = await fetch('https://api.anthropic.com/v1/messages', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'x-api-key': apiKey,
        'anthropic-version': '2023-06-01',
      },
      body: JSON.stringify({
        model: 'claude-sonnet-4-6',
        max_tokens: 1000,
        system: SYSTEM,
        messages: [{ role: 'user', content: prompt }],
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
