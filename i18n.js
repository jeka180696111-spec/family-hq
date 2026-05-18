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
const EN = {};

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
