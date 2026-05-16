// /api/analyze-receipt.js — Receipt analysis via Claude vision API

module.exports = async function handler(req, res) {
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
        model: 'claude-haiku-4-5-20251001',
        max_tokens: 256,
        system: 'Ти помічник для розпізнавання чеків. Повертай тільки валідний JSON без пояснень.',
        messages: [
          {
            role: 'user',
            content: [
              {
                type: 'image',
                source: {
                  type: 'base64',
                  media_type: mediaType,
                  data: image,
                },
              },
              {
                type: 'text',
                text: 'Це фото чека або квитанції. Витягни дані та поверни ТІЛЬКИ JSON без пояснень:\n{"amount": <число без валюти>, "store": "<назва магазину>", "date": "<YYYY-MM-DD або null>", "category": "<одна з: Продукти, Ресторани, Транспорт, Комунальні, Здоров\'я, Одяг, Розваги, Дім, Дитячі, Інше>"}\nЯкщо не можеш прочитати - поверни {"error": "не вдалося розпізнати"}',
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
    const text = data.content?.[0]?.text || '';

    try {
      const parsed = JSON.parse(text.trim());
      return res.status(200).json(parsed);
    } catch (e) {
      // Try to extract JSON from the response if wrapped in markdown
      const match = text.match(/\{[\s\S]*\}/);
      if (match) {
        try {
          return res.status(200).json(JSON.parse(match[0]));
        } catch {}
      }
      return res.status(200).json({ error: 'не вдалося розпізнати' });
    }
  } catch (error) {
    console.error('analyze-receipt error:', error);
    return res.status(200).json({ error: error.message });
  }
};
