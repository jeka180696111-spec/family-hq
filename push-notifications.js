// ═══════════════════════════════════════════════════════════════
// PUSH NOTIFICATIONS — Web Push subscription + preferences
// ═══════════════════════════════════════════════════════════════

import { showToast } from './utils.js';
import { state } from './config.js';

// VAPID public key is fetched from /api/vapid-public-key (stored in Vercel env).
// Private key never touches client code — it lives only in Vercel env.
let _vapidKeyCache = null;
async function getVapidPublicKey() {
  if (_vapidKeyCache) return _vapidKeyCache;
  const res = await fetch('/api/vapid-public-key');
  if (!res.ok) throw new Error('VAPID ключ не налаштовано на сервері');
  const { key } = await res.json();
  _vapidKeyCache = key;
  return key;
}

const PREF_KEY = 'budget_push_prefs';

export function getPushPrefs() {
  try { return JSON.parse(localStorage.getItem(PREF_KEY) || 'null') || defaultPrefs(); }
  catch { return defaultPrefs(); }
}

function defaultPrefs() {
  return {
    enabled: false,
    limitWarning:      { on: true,  threshold: 80 },   // % of limit used
    recurringReminder: { on: true,  daysBefore: 1 },   // days before payment due
    dailySummary:      { on: false, time: '21:00' },
    weeklySummary:     { on: true,  dayOfWeek: 1 },    // 1=Monday
    goalMilestone:     { on: true },                   // when goal reaches 25/50/75/100%
  };
}

function savePref(key, val) {
  const p = getPushPrefs();
  if (key.includes('.')) {
    const [top, sub] = key.split('.');
    p[top] = { ...p[top], [sub]: val };
  } else {
    p[key] = val;
  }
  localStorage.setItem(PREF_KEY, JSON.stringify(p));
}

function urlBase64ToUint8Array(base64String) {
  const padding = '='.repeat((4 - base64String.length % 4) % 4);
  const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
  const rawData = window.atob(base64);
  return Uint8Array.from([...rawData].map(c => c.charCodeAt(0)));
}

export async function requestPushPermission() {
  if (!('Notification' in window) || !('serviceWorker' in navigator)) {
    showToast('Push-сповіщення не підтримуються цим браузером', 'error');
    return false;
  }

  const permission = await Notification.requestPermission();
  if (permission !== 'granted') {
    showToast('Дозвіл на сповіщення не надано', 'error');
    return false;
  }

  try {
    const reg = await navigator.serviceWorker.ready;
    const vapidKey = await getVapidPublicKey();
    const sub = await reg.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(vapidKey),
    });

    // Save subscription to backend
    await fetch('/api/push-subscribe', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        subscription: sub.toJSON(),
        familyId: state.familyId,
        prefs: getPushPrefs(),
      }),
    });

    savePref('enabled', true);
    showToast('Push-сповіщення увімкнено! ✅', 'success');
    return true;
  } catch(e) {
    showToast('Помилка підключення: ' + e.message, 'error');
    return false;
  }
}

export async function disablePush() {
  try {
    const reg = await navigator.serviceWorker.ready;
    const sub = await reg.pushManager.getSubscription();
    if (sub) await sub.unsubscribe();
    savePref('enabled', false);
    showToast('Push-сповіщення вимкнено');
  } catch(e) {
    savePref('enabled', false);
  }
}

export function renderPushSettingsPage() {
  const prefs = getPushPrefs();
  const supported = 'Notification' in window && 'serviceWorker' in navigator;

  return `
    <div class="settings-card">
      <div class="settings-row">
        <div class="settings-row-icon" style="background:#FEF3C7;color:#D97706"><i class="ti ti-bell"></i></div>
        <div class="settings-row-info">
          <div class="settings-row-name">Push-сповіщення</div>
          <div class="settings-row-sub">${supported ? 'Сповіщення прямо на телефон' : 'Не підтримується браузером'}</div>
        </div>
        ${supported ? `
          <label class="settings-toggle">
            <input type="checkbox" id="push-master-toggle" ${prefs.enabled ? 'checked' : ''}>
            <span></span>
          </label>
        ` : '<span style="font-size:12px;color:var(--c-red)">Недоступно</span>'}
      </div>
    </div>

    ${supported ? `
    <div class="settings-section-header">ПРО ЩО СПОВІЩАТИ</div>
    <div class="settings-card" id="push-prefs-section" style="${prefs.enabled ? '' : 'opacity:0.5;pointer-events:none'}">

      ${renderPushRow('limitWarning.on', prefs.limitWarning.on, 'ti-alert-triangle', 'Перевищення ліміту',
        `При досягненні <b id="push-thr-label">${prefs.limitWarning.threshold}%</b> від ліміту`,
        `<input type="range" min="50" max="100" step="5" value="${prefs.limitWarning.threshold}"
          id="push-limit-threshold" class="push-range">`
      )}

      ${renderPushRow('recurringReminder.on', prefs.recurringReminder.on, 'ti-calendar-due', 'Нагадування про платежі',
        'Заздалегідь до платежу',
        `<select id="push-days-before" class="settings-row-input" style="width:100%">
          <option value="0" ${prefs.recurringReminder.daysBefore===0?'selected':''}>В день платежу</option>
          <option value="1" ${prefs.recurringReminder.daysBefore===1?'selected':''}>За 1 день</option>
          <option value="2" ${prefs.recurringReminder.daysBefore===2?'selected':''}>За 2 дні</option>
          <option value="3" ${prefs.recurringReminder.daysBefore===3?'selected':''}>За 3 дні</option>
        </select>`
      )}

      ${renderPushRow('dailySummary.on', prefs.dailySummary.on, 'ti-chart-bar', 'Щоденний підсумок',
        'Підсумок витрат за день',
        `<input type="time" id="push-daily-time" value="${prefs.dailySummary.time}"
          class="settings-row-input" style="width:100%">`
      )}

      ${renderPushRow('weeklySummary.on', prefs.weeklySummary.on, 'ti-calendar-stats', 'Тижневий звіт',
        'Щопонеділка — підсумок тижня', ''
      )}

      ${renderPushRow('goalMilestone.on', prefs.goalMilestone.on, 'ti-target', 'Досягнення цілей',
        'При 25%, 50%, 75%, 100% цілі', ''
      )}
    </div>
    ` : ''}
  `;
}

function renderPushRow(prefKey, checked, icon, title, desc, extra) {
  return `
    <div class="settings-row">
      <div class="settings-row-icon" style="background:var(--c-accent-soft);color:var(--c-accent)"><i class="ti ${icon}"></i></div>
      <div class="settings-row-info">
        <div class="settings-row-name">${title}</div>
        <div class="settings-row-sub">${desc}</div>
      </div>
      <label class="settings-toggle">
        <input type="checkbox" data-push-pref="${prefKey}" ${checked ? 'checked' : ''}>
        <span></span>
      </label>
    </div>
    ${extra ? `<div class="settings-row push-row-extra">${extra}</div>` : ''}
  `;
}

export function bindPushSettingsHandlers(wrap) {
  const masterToggle = wrap.querySelector('#push-master-toggle');
  if (masterToggle) {
    masterToggle.addEventListener('change', async () => {
      if (masterToggle.checked) {
        const ok = await requestPushPermission();
        if (!ok) masterToggle.checked = false;
      } else {
        await disablePush();
      }
      const section = wrap.querySelector('#push-prefs-section');
      if (section) section.style.cssText = masterToggle.checked ? '' : 'opacity:0.5;pointer-events:none';
    });
  }

  wrap.querySelectorAll('[data-push-pref]').forEach(el => {
    el.addEventListener('change', () => {
      savePref(el.dataset.pushPref, el.type === 'checkbox' ? el.checked : el.value);
    });
  });

  const threshold = wrap.querySelector('#push-limit-threshold');
  if (threshold) {
    threshold.addEventListener('input', () => {
      savePref('limitWarning.threshold', parseInt(threshold.value));
      const lbl = wrap.querySelector('#push-thr-label');
      if (lbl) lbl.textContent = threshold.value + '%';
    });
  }

  const daysSelect = wrap.querySelector('#push-days-before');
  if (daysSelect) {
    daysSelect.addEventListener('change', () => savePref('recurringReminder.daysBefore', parseInt(daysSelect.value)));
  }

  const timeInput = wrap.querySelector('#push-daily-time');
  if (timeInput) {
    timeInput.addEventListener('change', () => savePref('dailySummary.time', timeInput.value));
  }
}
