// ═══════════════════════════════════════════════════════════════
// I18N — багатомовність інтерфейсу
//
// Підхід: український рядок = ключ. t('Текст') повертає:
//   • українською — сам рядок (ключ)
//   • англійською — EN[рядок] або сам рядок, якщо переклад ще не додано
// Тому обгортання t() нічого не ламає; англійські переклади
// наповнюються поступово у dict.en (по екранах).
// ═══════════════════════════════════════════════════════════════

const LANG_KEY = 'budget_lang';

export const LANGUAGES = [
  { code: 'uk', label: 'Українська', flag: '🇺🇦' },
  { code: 'en', label: 'English',    flag: '🇬🇧' },
];

// Англійський словник: ключ = український оригінал.
// Наповнюється поетапно у наступних фазах (по екранах).
const EN = {
  // ── Загальні ──
  'Назад': 'Back',
  'Помилка: ': 'Error: ',
  'Зачекайте...': 'Please wait...',
  'Мова': 'Language',
  'Стиль теми': 'Theme style',

  // ── Екран входу (index.html) ──
  'Увійди через Google щоб синхронізувати дані': 'Sign in with Google to sync your data',
  'Увійти через Google': 'Sign in with Google',

  // ── Онбординг ──
  'Розумний фінансовий менеджер': 'Smart money manager',
  'AI-аналітика': 'AI analytics',
  '— фінансовий радник Фінн допоможе контролювати витрати': '— financial advisor Finn helps you control spending',
  'Сімейний бюджет': 'Family budget',
  '— спільний облік для всієї родини в реальному часі': '— shared tracking for the whole family in real time',
  'Telegram-бот': 'Telegram bot',
  '— додавай витрати де завгодно за лічені секунди': '— add expenses anywhere in seconds',
  "Твоє ім'я": 'Your name',
  'Наприклад: Євген': 'e.g. John',
  "Ім'я має бути не менше 2 символів": 'Name must be at least 2 characters',
  'Твій аватар': 'Your avatar',
  'Розпочати →': 'Get started →',
  'Крок 2 з 2 — Твоя родина': 'Step 2 of 2 — Your family',
  'Створи нову родину або приєднайся до існуючої за кодом запрошення.': 'Create a new family or join an existing one with an invite code.',
  'Створити нову родину': 'Create a new family',
  'Ти станеш адміністратором і зможеш запросити інших': "You'll be the admin and can invite others",
  'Приєднатись до існуючої': 'Join an existing one',
  'Потрібен 6-символьний invite-код від адміністратора родини': 'Requires a 6-character invite code from the family admin',
  'Назва родини': 'Family name',
  'Наприклад: Ковалі': 'e.g. Smiths',
  'Введіть назву родини': 'Enter a family name',
  'Аватар родини': 'Family avatar',
  'Створити родину': 'Create family',
  'Код запрошення': 'Invite code',
  'Введіть 6-символьний код': 'Enter a 6-character code',
  'Попроси адміністратора родини надіслати тобі 6-символьний invite-код з розділу «Налаштування».': 'Ask the family admin to send you a 6-character invite code from the Settings section.',
  'Приєднатись до родини': 'Join family',
  'Помилка входу: ': 'Sign-in error: ',
  'Помилка завантаження профілю: ': 'Profile loading error: ',

  // ── Дашборд ──
  'Доброї ночі': 'Good night',
  'Доброго ранку': 'Good morning',
  'Доброго дня': 'Good afternoon',
  'Доброго вечора': 'Good evening',
  'дивлюсь як': 'viewing as',
  'Можна витратити': 'Available to spend',
  'Накопичення': 'Savings',
  'Готівка': 'Cash',
  'Кредит вільно': 'Credit available',
  'Платежі': 'Payments',
  'накопичено': 'saved',
  'Дохід': 'Income',
  'Витрата': 'Expense',
  'Переказ': 'Transfer',
  'Обмін': 'Exchange',
  'Сканер': 'Scanner',
  'Можна витрачати на день': 'Daily budget',
  'Залишилось': 'Remaining',
  'день': 'day',
  'дні': 'days',
  'днів': 'days',
  'у місяці': 'in the month',
  'Цілі': 'Goals',
  'Баланс': 'Balance',
  'Немає даних': 'No data',
  'Витрати': 'Expenses',
  'Доходи': 'Income',
  'Гаманці': 'Wallets',
  'Налаштувати': 'Configure',
  'Усі →': 'All →',

  // ── Валюти ──
  'Валюта': 'Currency',
  'Гривня': 'Hryvnia',
  'Долар': 'US Dollar',
  'Євро': 'Euro',
  'Фунт': 'Pound',
  'Злотий': 'Zloty',
  'Франк': 'Franc',
  'Канад. долар': 'Canadian Dollar',
  'Крона (CZK)': 'Koruna (CZK)',
  'Єна': 'Yen',
  'Юань': 'Yuan',
  'Ліра': 'Lira',
};

export const dict = { en: EN };

// ── Визначення мови ──────────────────────────────────────────
function detectLang() {
  const nav = (navigator.language || navigator.userLanguage || 'en').toLowerCase();
  if (nav.startsWith('uk') || nav.startsWith('ru')) return 'uk';
  return 'en';
}

export function getLang() {
  const saved = localStorage.getItem(LANG_KEY);
  if (saved === 'uk' || saved === 'en') return saved;
  return detectLang();
}

export function setLang(lang) {
  if (lang !== 'uk' && lang !== 'en') return;
  localStorage.setItem(LANG_KEY, lang);
  document.documentElement.setAttribute('lang', lang);
  // Повне перерендерення — найнадійніше для всіх екранів
  location.reload();
}

let _lang = null;

export function initI18n() {
  _lang = getLang();
  document.documentElement.setAttribute('lang', _lang);
  return _lang;
}

// ── Переклад ─────────────────────────────────────────────────
// t('Текст')                       → рядок
// t('Привіт, {name}!', {name:'X'}) → інтерполяція {ключ}
export function t(str, vars) {
  if (_lang === null) _lang = getLang();
  let out = str;
  if (_lang === 'en') {
    out = EN[str] != null ? EN[str] : str;
  }
  if (vars) {
    out = out.replace(/\{(\w+)\}/g, (m, k) => (vars[k] != null ? vars[k] : m));
  }
  return out;
}

export function currentLang() {
  return _lang || getLang();
}
