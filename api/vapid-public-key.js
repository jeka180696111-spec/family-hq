// Vercel serverless — serve the VAPID public key from env (safe to expose)
export default function handler(req, res) {
  const key = process.env.VAPID_PUBLIC_KEY;
  if (!key) return res.status(500).json({ error: 'VAPID_PUBLIC_KEY not configured' });
  res.setHeader('Cache-Control', 's-maxage=86400, stale-while-revalidate');
  res.json({ key });
}
