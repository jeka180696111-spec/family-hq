// Vercel serverless — save push subscription to Firestore
export default async function handler(req, res) {
  if (req.method !== 'POST') return res.status(405).end();

  try {
    const { subscription, familyId, prefs } = req.body;
    if (!subscription || !familyId) return res.status(400).json({ error: 'Missing fields' });

    const { initializeApp, getApps, cert } = await import('firebase-admin/app');
    const { getFirestore } = await import('firebase-admin/firestore');

    if (!getApps().length) {
      initializeApp({ credential: cert(JSON.parse(process.env.FIREBASE_SERVICE_ACCOUNT)) });
    }
    const db = getFirestore();

    await db.collection('families').doc(familyId)
      .collection('pushSubscriptions')
      .add({
        subscription,
        prefs: prefs || {},
        createdAt: new Date().toISOString(),
      });

    res.json({ ok: true });
  } catch(e) {
    res.status(500).json({ error: e.message });
  }
}
