// ═══════════════════════════════════════════════════════════════
// THEME — перемикач світлої/темної теми
// ═══════════════════════════════════════════════════════════════

import { getTheme, setTheme, hasUserSetTheme, getPalette, setPalette } from './storage.js';

// Доступні теми
export const THEMES = ['light', 'dark'];
export const PALETTES = ['default', 'ocean', 'sunset', 'midnight', 'neon', 'glass'];

export function applyPalette(palette) {
  if (!PALETTES.includes(palette)) palette = 'default';
  setPalette(palette);
  document.documentElement.setAttribute('data-palette', palette);
  // Neon завжди темний
  if (palette === 'neon') {
    document.documentElement.setAttribute('data-theme', 'dark');
  }
}

export function initPalette() {
  const p = getPalette();
  document.documentElement.setAttribute('data-palette', p);
  if (p === 'neon') {
    document.documentElement.setAttribute('data-theme', 'dark');
  }
}

// Визначає поточну активну тему (з урахуванням системних налаштувань)
function resolveTheme() {
  const saved = getTheme();
  if (saved !== null) return saved;
  // Юзер не зафіксував тему — використовуємо системну
  if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
    return 'dark';
  }
  return 'light';
}

// Застосовуємо тему при старті
export function initTheme() {
  initPalette();
  const theme = resolveTheme();
  document.documentElement.setAttribute('data-theme', theme);
  updateThemeMeta(theme);

  // Слухач на зміни системної теми — тільки якщо юзер не зафіксував тему
  if (window.matchMedia) {
    const mq = window.matchMedia('(prefers-color-scheme: dark)');
    mq.addEventListener('change', (e) => {
      if (!hasUserSetTheme()) {
        const systemTheme = e.matches ? 'dark' : 'light';
        document.documentElement.setAttribute('data-theme', systemTheme);
        updateThemeMeta(systemTheme);
      }
    });
  }
}

// Перемкнути тему
export function toggleTheme() {
  const cur = resolveTheme();
  const next = cur === 'light' ? 'dark' : 'light';
  setTheme(next);
  updateThemeMeta(next);
  return next;
}

// Встановити конкретну тему
export function applyTheme(theme) {
  if (!THEMES.includes(theme)) theme = 'light';
  setTheme(theme);
  updateThemeMeta(theme);
}


// Оновлюємо <meta name="theme-color">
function updateThemeMeta(theme) {
  const meta = document.querySelector('meta[name="theme-color"]');
  const color = theme === 'dark' ? '#1A1A2E' : '#F8FAF9';
  if (meta) meta.setAttribute('content', color);
  // Manifest background теж
  const manifest = document.querySelector('link[rel="manifest"]');
  if (manifest) {
    // PWA шапка
  }
}
