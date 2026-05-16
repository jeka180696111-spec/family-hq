// ═══════════════════════════════════════════════════════════════
// Vercel Serverless Function — Telegram нагадування
// Cron: щодня о 9:00 (налаштувати в vercel.json)
// ═══════════════════════════════════════════════════════════════

export const config = { runtime: 'edge' };

// ── Firebase JWT → Access Token (Web Crypto API) ────────────
async function getFirestoreToken(clientEmail, privateKey) {
  const now = Math.floor(Date.now() / 1000);
  const header = { alg: 'RS256', typ: 'JWT' };
  const claim = {
    iss: clientEmail,
    scope: 'https://www.googleapis.com/auth/datastore',
    aud: 'https://oauth2.googleapis.com/token',
    iat: now,
    exp: now + 3600,
  };

  const b64url = obj =>
    btoa(JSON.stringify(obj)).replace(/=/g, '').replace(/\+/g, '-').replace(/\//g, '_');

  const unsigned = `${b64url(header)}.${b64url(claim)}`;

  const pemContents = privateKey.replace(/-----[^-]+-----/g, '').replace(/\s/g, '');
  const keyData = Uint8Array.from(atob(pemContents), c => c.charCodeAt(0));

  const cryptoKey = await crypto.subtle.importKey(
    'pkcs8',
    keyData,
    { name: 'RSASSA-PKCS1-v1_5', hash: 'SHA-256' },
    false,
    ['sign']
  );

  const signatureBuf = await crypto.subtle.sign(
    'RSASSA-PKCS1-v1_5',
    cryptoKey,
    new TextEncoder().encode(unsigned)
  );

  const sig = btoa(String.fromCharCode(...new Uint8Array(signatureBuf)))
    .replace(/=/g, '').replace(/\+/g, '-').replace(/\//g, '_');

  const jwt = `${unsigned}.${sig}`;

  const tokenRes = await fetch('https://oauth2.googleapis.com/token', {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: `grant_type=urn%3Aietf%3Aparams%3Aoauth%3Agrant-type%3Ajwt-bearer&assertion=${jwt}`,
  });

  const tokenData = await tokenRes.json();
  if (!tokenData.access_token) throw new Error(`Auth failed: ${JSON.stringify(tokenData)}`);
  return tokenData.access_token;
}

// ── Кількість днів у місяці ──────────────────────────────────
function daysInMonth(year, month) {
  return new Date(year, month + 1, 0).getDate();
}

export default async function handler(req) {
  const BOT_TOKEN = process.env.TELEGRAM_BOT_TOKEN;
  const CHAT_ID = process.env.TELEGRAM_CHAT_ID;
  const FIREBASE_PROJECT = process.env.FIREBASE_PROJECT_ID || 'familybudget-aa238';
  const FAMILY_ID = process.env.FAMILY_ID || 'koval';
  const CLIENT_EMAIL = process.env.FIREBASE_CLIENT_EMAIL;
  const PRIVATE_KEY = (process.env.FIREBASE_PRIVATE_KEY || '').replace(/\\n/g, '\n');

  if (!BOT_TOKEN || !CHAT_ID) {
    return new Response(JSON.stringify({ error: 'Missing TELEGRAM env vars' }), { status: 500 });
  }
  if (!CLIENT_EMAIL || !PRIVATE_KEY) {
    return new Response(JSON.stringify({ error: 'Missing FIREBASE auth env vars' }), { status: 500 });
  }

  try {
    const accessToken = await getFirestoreToken(CLIENT_EMAIL, PRIVATE_KEY);

    const fsUrl = `https://firestore.googleapis.com/v1/projects/${FIREBASE_PROJECT}/databases/(default)/documents/families/${FAMILY_ID}/recurringPayments`;
    const fsRes = await fetch(fsUrl, {
      headers: { Authorization: `Bearer ${accessToken}` },
    });
    const fsData = await fsRes.json();

    if (!fsData.documents) {
      return new Response(JSON.stringify({ ok: true, reminders: 0, note: 'no documents' }));
    }

    const today = new Date();
    const dayOfMonth = today.getDate();
    const maxDay = daysInMonth(today.getFullYear(), today.getMonth());
    const messages = [];

    for (const doc of fsData.documents) {
      const f = doc.fields;
      const active = f.active?.booleanValue !== false;
      const notify = f.notifyTelegram?.booleanValue !== false;
      if (!active || !notify) continue;

      const name = f.name?.stringValue || '?';
      const amount = Number(f.amount?.integerValue || f.amount?.doubleValue || 0);
      const remindBefore = Number(f.remindDaysBefore?.integerValue || 3);
      const who = f.who?.stringValue || '';

      // Якщо payDay більший за кількість днів у місяці — беремо останній день
      const rawPayDay = Number(f.dayOfMonth?.integerValue || 0);
      const payDay = Math.min(rawPayDay, maxDay);

      const daysUntil = payDay - dayOfMonth;

      if (daysUntil === 0) {
        messages.push(`🔴 *СЬОГОДНІ*: ${name} — ${amount} ₴ (${who})`);
      } else if (daysUntil === 1) {
        messages.push(`🟡 *Завтра*: ${name} — ${amount} ₴ (${who})`);
      } else if (daysUntil > 1 && daysUntil <= remindBefore) {
        messages.push(`📅 Через ${daysUntil} дн: ${name} — ${amount} ₴ (${who})`);
      }
    }

    if (messages.length > 0) {
      const text = `💰 *Нагадування про платежі*\n\n${messages.join('\n')}`;

      await fetch(`https://api.telegram.org/bot${BOT_TOKEN}/sendMessage`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ chat_id: CHAT_ID, text, parse_mode: 'Markdown' }),
      });
    }

    return new Response(JSON.stringify({ ok: true, reminders: messages.length }));
  } catch (e) {
    return new Response(JSON.stringify({ error: e.message }), { status: 500 });
  }
}
