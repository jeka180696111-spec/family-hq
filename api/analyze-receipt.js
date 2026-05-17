// /api/analyze-receipt.js — Receipt analysis via Claude vision API

export default async function handler(req, res) {
  if (req.method !== 'POST') {
    return res.status(405).json({ error: 'Method not allowed' });
  }

  try {
    const { image, mediaType } = req.body || {};
    if (!image || !mediaType) {
      return res.status(400).json({ error: 'Missing image or mediaType' });
    }

    const response = await fetch('https://api.anthropic.com/v1/messages', {
      method: 'POST',
      headers: {
        'x-api-key': process.env.ANTHROPIC_API_KEY,
        'anthropic-version': '2023-06-01',
        'content-type': 'application/json',
      },
      body: JSON.stringify({
        model: 'claude-sonnet-4-6',
        max_tokens: 512,
        system: `Ти — точний OCR-аналізатор чеків для українського застосунку обліку витрат.
Завдання: витягнути дані з фото чека/квитанції та повернути ТІЛЬКИ валідний JSON.
Правила:
- amount: загальна сума до сплати (число, без валюти)
- store: назва магазину/закладу (коротко)
- date: дата у форматі YYYY-MM-DD (або null якщо не видно)
- category: ОДНА категорія з переліку: Продукти, Ресторани, Транспорт, Комунальні, Здоров'я, Одяг, Розваги, Дім, Дитячі, Інше
- items: масив позицій [{name, amount}] (до 5 позицій, лише якщо чітко видно)
Якщо не вдається розпізнати — {"error": "не вдалося розпізнати"}
Повертай ТІЛЬКИ JSON, без пояснень, без markdown.`,
        messages: [
          {
            role: 'user',
            content: [
              {
                type: 'image',
                source: { type: 'base64', media_type: mediaType, data: image },
              },
              {
                type: 'text',
                text: 'Проаналізуй цей чек і поверни JSON з полями: amount, store, date, category, items.',
              },
            ],
          },
        ],
      }),
    });

    if (!response.ok) {
      const err = await response.text();
      console.error('Claude API error:', err);
      return res.status(200).json({ error: 'Claude API error' });
    }

    const data = await response.json();
    const text = (data.content?.[0]?.text || '').trim();

    // Try direct parse first
    try {
      return res.status(200).json(JSON.parse(text));
    } catch (_) {
      // Extract JSON from potential markdown wrapper
      const match = text.match(/\{[\s\S]*\}/);
      if (match) {
        try { return res.status(200).json(JSON.parse(match[0])); } catch (_) {}
      }
      return res.status(200).json({ error: 'не вдалося розпізнати' });
    }
  } catch (error) {
    console.error('analyze-receipt error:', error);
    return res.status(200).json({ error: error.message });
  }
};
