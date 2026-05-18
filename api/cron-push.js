// ═══════════════════════════════════════════════════════════════
// CRON PUSH — Vercel Cron endpoint: runs every hour
// ═══════════════════════════════════════════════════════════════

import { sendScheduledPushes } from './push-send.js';

export default async function handler(req, res) {
  if (req.headers.authorization !== `Bearer ${process.env.CRON_SECRET}`) {
    return res.status(401).end();
  }

  try {
    await sendScheduledPushes();
    res.json({ ok: true });
  } catch (e) {
    console.error('[cron-push] error:', e.message);
    res.status(500).json({ error: e.message });
  }
}
