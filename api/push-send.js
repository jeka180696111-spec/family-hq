// ═══════════════════════════════════════════════════════════════
// PUSH SEND — internal module for sending scheduled push notifications
// ═══════════════════════════════════════════════════════════════

import webpush from 'web-push';
import { initializeApp, getApps, cert } from 'firebase-admin/app';
import { getFirestore } from 'firebase-admin/firestore';

webpush.setVapidDetails(
  'mailto:support@moneybudget.app',
  process.env.VAPID_PUBLIC_KEY,
  process.env.VAPID_PRIVATE_KEY
);

function getDB() {
  if (!getApps().length) {
    initializeApp({ credential: cert(JSON.parse(process.env.FIREBASE_SERVICE_ACCOUNT)) });
  }
  return getFirestore();
}

async function sendPush(subscription, payload) {
  try {
    await webpush.sendNotification(subscription, JSON.stringify(payload));
    return true;
  } catch (e) {
    // 410 Gone or 404 Not Found means subscription is no longer valid
    if (e.statusCode === 410 || e.statusCode === 404) return 'stale';
    console.warn('[push-send] sendNotification error:', e.message);
    return false;
  }
}

function nowKyiv() {
  return new Date().toLocaleString('sv-SE', { timeZone: 'Europe/Kyiv' });
}

function kyivHHMM() {
  return nowKyiv().slice(11, 16); // "HH:MM"
}

function kyivDayOfWeek() {
  const d = new Date();
  // getDay() in Kyiv timezone
  const kyivStr = d.toLocaleDateString('en-US', { timeZone: 'Europe/Kyiv', weekday: 'short' });
  const map = { Sun: 0, Mon: 1, Tue: 2, Wed: 3, Thu: 4, Fri: 5, Sat: 6 };
  return map[kyivStr] ?? d.getDay();
}

function kyivDateStr() {
  return new Date().toLocaleDateString('sv-SE', { timeZone: 'Europe/Kyiv' });
}

export async function sendScheduledPushes() {
  const db = getDB();
  const now = new Date();
  const currentTime = kyivHHMM();        // e.g. "21:00"
  const currentDow  = kyivDayOfWeek();   // 0–6
  const todayStr    = kyivDateStr();     // "YYYY-MM-DD"

  const familiesSnap = await db.collection('families').get();

  for (const familyDoc of familiesSnap.docs) {
    const familyId   = familyDoc.id;
    const familyData = familyDoc.data();

    // ── Gather push subscriptions ──────────────────────────
    const subsSnap = await db
      .collection('families').doc(familyId)
      .collection('pushSubscriptions')
      .get();

    if (subsSnap.empty) continue;

    // Collect notifications to send for this family
    const notifications = [];

    // ── limitWarning ──────────────────────────────────────
    // Check each family member's category spending vs limits
    try {
      const limitsSnap = await db
        .collection('families').doc(familyId)
        .collection('settings').doc('limits')
        .get();
      const limits = limitsSnap.exists ? (limitsSnap.data()?.categories || {}) : {};

      if (Object.keys(limits).length) {
        // Get this month's operations
        const monthStart = todayStr.slice(0, 7) + '-01'; // "YYYY-MM-01"
        const opsSnap = await db
          .collection('families').doc(familyId)
          .collection('operations')
          .where('date', '>=', monthStart)
          .where('type', '==', 'Витрата')
          .get();

        // Sum by category
        const spent = {};
        opsSnap.forEach(doc => {
          const op = doc.data();
          const cat = op.category;
          if (cat) spent[cat] = (spent[cat] || 0) + (op.amountUah || op.amount || 0);
        });

        for (const [cat, limit] of Object.entries(limits)) {
          if (!limit || limit <= 0) continue;
          const usedPct = ((spent[cat] || 0) / limit) * 100;
          if (usedPct >= 100) {
            notifications.push({
              tag: `limit-exceeded-${cat}`,
              title: 'Ліміт перевищено',
              body: `Категорія "${cat}": витрачено ${Math.round(usedPct)}% від ліміту`,
              icon: '/icon-192.png',
              prefKey: 'limitWarning',
            });
          }
        }
      }
    } catch (e) {
      console.warn('[push-send] limitWarning check error:', e.message);
    }

    // ── recurringReminder ─────────────────────────────────
    try {
      const recurringSnap = await db
        .collection('families').doc(familyId)
        .collection('recurringPayments')
        .get();

      recurringSnap.forEach(doc => {
        const rp = doc.data();
        if (!rp.nextDate) return;
        const daysUntil = Math.round(
          (new Date(rp.nextDate) - new Date(todayStr)) / (1000 * 60 * 60 * 24)
        );
        notifications.push({
          tag: `recurring-${doc.id}`,
          title: 'Нагадування про платіж',
          body: `"${rp.name || rp.desc || 'Платіж'}" — через ${daysUntil} ${daysUntil === 1 ? 'день' : 'дні'}`,
          icon: '/icon-192.png',
          prefKey: 'recurringReminder',
          prefDaysBefore: rp,
          daysUntil,
        });
      });
    } catch (e) {
      console.warn('[push-send] recurringReminder check error:', e.message);
    }

    // ── dailySummary ──────────────────────────────────────
    // Fetch today's ops for summary
    try {
      const todayOpsSnap = await db
        .collection('families').doc(familyId)
        .collection('operations')
        .where('date', '>=', todayStr)
        .where('type', '==', 'Витрата')
        .get();

      let totalToday = 0;
      todayOpsSnap.forEach(doc => {
        const op = doc.data();
        totalToday += op.amountUah || op.amount || 0;
      });

      notifications.push({
        tag: 'daily-summary',
        title: 'Щоденний підсумок',
        body: `Витрати сьогодні: ${totalToday.toLocaleString('uk-UA')} ₴`,
        icon: '/icon-192.png',
        prefKey: 'dailySummary',
        summaryTime: true,
        totalToday,
      });
    } catch (e) {
      console.warn('[push-send] dailySummary check error:', e.message);
    }

    // ── weeklySummary ─────────────────────────────────────
    try {
      const weekStart = new Date(now);
      weekStart.setDate(weekStart.getDate() - 7);
      const weekStartStr = weekStart.toLocaleDateString('sv-SE', { timeZone: 'Europe/Kyiv' });

      const weekOpsSnap = await db
        .collection('families').doc(familyId)
        .collection('operations')
        .where('date', '>=', weekStartStr)
        .where('type', '==', 'Витрата')
        .get();

      let totalWeek = 0;
      weekOpsSnap.forEach(doc => {
        const op = doc.data();
        totalWeek += op.amountUah || op.amount || 0;
      });

      notifications.push({
        tag: 'weekly-summary',
        title: 'Тижневий підсумок',
        body: `Витрати за тиждень: ${totalWeek.toLocaleString('uk-UA')} ₴`,
        icon: '/icon-192.png',
        prefKey: 'weeklySummary',
        weeklySummary: true,
        totalWeek,
      });
    } catch (e) {
      console.warn('[push-send] weeklySummary check error:', e.message);
    }

    // ── Send to each subscription ─────────────────────────
    const staleSubIds = [];

    for (const subDoc of subsSnap.docs) {
      const { subscription, prefs = {} } = subDoc.data();
      if (!subscription) continue;

      // Check per-subscription prefs (merged with family defaults)
      for (const notif of notifications) {
        const pref = prefs[notif.prefKey];
        if (!pref || pref.on === false) continue;

        // Per-type gate checks
        if (notif.prefKey === 'limitWarning') {
          const threshold = pref.threshold ?? 80;
          // Already filtered above (usedPct >= 100), but respect threshold for warnings
          // If we want to send at threshold% as well, we need to recheck:
          // (handled in the limitWarning section — only sends when >= limit for simplicity)
          // No extra gate needed here
        }

        if (notif.prefKey === 'recurringReminder') {
          const daysBefore = pref.daysBefore ?? 1;
          if (notif.daysUntil === undefined || notif.daysUntil !== daysBefore) continue;
        }

        if (notif.prefKey === 'dailySummary') {
          const configuredTime = pref.time || '21:00';
          // Only send if current hour matches (cron runs every hour)
          if (currentTime.slice(0, 2) !== configuredTime.slice(0, 2)) continue;
        }

        if (notif.prefKey === 'weeklySummary') {
          const configuredDow = pref.dayOfWeek ?? 1;
          if (currentDow !== configuredDow) continue;
          // Send only once per day — check hour = 08:00
          if (currentTime.slice(0, 2) !== '08') continue;
        }

        const { prefKey, prefDaysBefore, daysUntil, summaryTime, weeklySummary: isWeekly, ...payload } = notif;
        const result = await sendPush(subscription, payload);
        if (result === 'stale') {
          staleSubIds.push(subDoc.id);
          break; // No need to send more to this stale subscription
        }
      }
    }

    // Remove stale subscriptions
    for (const staleId of staleSubIds) {
      try {
        await db
          .collection('families').doc(familyId)
          .collection('pushSubscriptions').doc(staleId)
          .delete();
      } catch (e) {
        console.warn('[push-send] failed to delete stale sub:', e.message);
      }
    }
  }
}
