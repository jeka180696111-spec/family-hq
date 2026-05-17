// ═══════════════════════════════════════════════════════════════
// PUSH NOTIFICATIONS — Web Push subscription + preferences
// ═══════════════════════════════════════════════════════════════

import { showToast } from './utils.js';
import { state } from './config.js';

// VAPID public key — replace with real key from web-push or https://vapidkeys.com
const VAPID_PUBLIC_KEY = 'BEl62iUYgUivxIkv69yViEuiBIa-Ib9-SkvMeAtA3LFgDzkrxZJjSgSnfckjBJuBkr3qBUYIHBQFLXYp5Nksh8U';

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
    const sub = await reg.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(VAPID_PUBLIC_KEY),
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
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px">
        <div>
          <div style="font-size:15px;font-weight:700">Push-сповіщення</div>
          <div style="font-size:12px;color:var(--c-text-3);margin-top:2px">${supported ? 'Сповіщення прямо на телефон' : 'Не підтримується цим браузером'}</div>
        </div>
        ${supported ? `
          <label class="toggle-switch">
            <input type="checkbox" id="push-master-toggle" ${prefs.enabled ? 'checked' : ''}>
            <span class="toggle-slider"></span>
          </label>
        ` : '<span style="font-size:12px;color:var(--c-red)">Недоступно</span>'}
      </div>
    </div>

    ${supported ? `
    <div class="settings-card" id="push-prefs-section" style="${prefs.enabled ? '' : 'opacity:0.5;pointer-events:none'}">
      <div style="font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:0.07em;color:var(--c-text-3);margin-bottom:12px">Про що сповіщати</div>

      ${renderPushRow('limitWarning.on', prefs.limitWarning.on, '⚠️ Перевищення ліміту',
        `При досягненні <b>${prefs.limitWarning.threshold}%</b> від ліміту категорії`,
        `<input type="range" min="50" max="100" step="5" value="${prefs.limitWarning.threshold}"
          id="push-limit-threshold" style="width:100%;margin-top:6px">`
      )}

      ${renderPushRow('recurringReminder.on', prefs.recurringReminder.on, '📅 Нагадування про платежі',
        `За <b>${prefs.recurringReminder.daysBefore}</b> ${prefs.recurringReminder.daysBefore === 1 ? 'день' : 'дні'} до платежу`,
        `<select id="push-days-before" class="ip-input" style="margin-top:6px;padding:6px 10px;font-size:13px">
          <option value="0" ${prefs.recurringReminder.daysBefore===0?'selected':''}>В день платежу</option>
          <option value="1" ${prefs.recurringReminder.daysBefore===1?'selected':''}>За 1 день</option>
          <option value="2" ${prefs.recurringReminder.daysBefore===2?'selected':''}>За 2 дні</option>
          <option value="3" ${prefs.recurringReminder.daysBefore===3?'selected':''}>За 3 дні</option>
        </select>`
      )}

      ${renderPushRow('dailySummary.on', prefs.dailySummary.on, '📊 Щоденний підсумок',
        `О <b>${prefs.dailySummary.time}</b>`,
        `<input type="time" id="push-daily-time" value="${prefs.dailySummary.time}"
          class="ip-input" style="margin-top:6px;padding:6px 10px;font-size:13px;width:auto">`
      )}

      ${renderPushRow('weeklySummary.on', prefs.weeklySummary.on, '📈 Тижневий звіт',
        'Щопонеділка — підсумок тижня', ''
      )}

      ${renderPushRow('goalMilestone.on', prefs.goalMilestone.on, '🎯 Досягнення цілей',
        'При досягненні 25%, 50%, 75%, 100% цілі', ''
      )}
    </div>
    ` : ''}
  `;
}

function renderPushRow(prefKey, checked, title, desc, extra) {
  return `
    <div class="settings-row" style="margin-bottom:12px;flex-direction:column;align-items:flex-start;gap:4px">
      <div style="display:flex;align-items:center;justify-content:space-between;width:100%">
        <div>
          <div style="font-size:14px;font-weight:600">${title}</div>
          <div style="font-size:12px;color:var(--c-text-3)">${desc}</div>
        </div>
        <label class="toggle-switch" style="flex-shrink:0;margin-left:12px">
          <input type="checkbox" data-push-pref="${prefKey}" ${checked ? 'checked' : ''}>
          <span class="toggle-slider"></span>
        </label>
      </div>
      ${extra ? `<div style="width:100%">${extra}</div>` : ''}
    </div>
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
      const desc = threshold.previousElementSibling?.querySelector('b');
      if (desc) desc.textContent = threshold.value + '%';
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
