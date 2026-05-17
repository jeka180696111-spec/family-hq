// ═══════════════════════════════════════════════════════════════
// THEME — перемикач світлої/темної теми
// ═══════════════════════════════════════════════════════════════

import { getTheme, setTheme } from './storage.js';

// Доступні теми
export const THEMES = ['light', 'dark'];

// Застосовуємо тему при старті
export function initTheme() {
  const theme = getTheme();
  document.documentElement.setAttribute('data-theme', theme);
  updateThemeMeta(theme);
}

// Перемкнути тему
export function toggleTheme() {
  const cur = getTheme();
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

// Застосувати палітру кольорів
export function applyPalette(palette) {
  if (!palette) palette = 'default';
  document.documentElement.setAttribute('data-palette', palette);
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
