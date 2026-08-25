/**
 * theme.js — Zehni Sukoon
 * Night mode toggle + text-size cycling
 */

const THEME_KEY    = 'zs_theme';
const TEXTSIZE_KEY = 'zs_textsize';
const TEXT_SIZES   = [1, 1.1, 1.2];  // scale multipliers: Normal / Large / Larger

// ── Night theme ───────────────────────────────────────────────
function applyTheme(theme) {
  document.body.setAttribute('data-theme', theme);
  const icon = document.getElementById('theme-icon');
  if (icon) {
    icon.className = theme === 'dark' ? 'fas fa-sun' : 'fas fa-moon';
  }
  localStorage.setItem(THEME_KEY, theme);
}

function toggleTheme() {
  const current = localStorage.getItem(THEME_KEY) || 'light';
  applyTheme(current === 'dark' ? 'light' : 'dark');
}

// ── Text-size cycling ─────────────────────────────────────────
function applyTextSize(idx) {
  const scale = TEXT_SIZES[idx] || 1;
  document.documentElement.style.setProperty('--text-scale', scale);
  localStorage.setItem(TEXTSIZE_KEY, idx);
}

function cycleTextSize() {
  const current = parseInt(localStorage.getItem(TEXTSIZE_KEY) || '0', 10);
  const next = (current + 1) % TEXT_SIZES.length;
  applyTextSize(next);
}

// ── Init ──────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  const savedTheme = localStorage.getItem(THEME_KEY) || 'light';
  applyTheme(savedTheme);

  const savedSize = parseInt(localStorage.getItem(TEXTSIZE_KEY) || '0', 10);
  applyTextSize(savedSize);
});

window.toggleTheme  = toggleTheme;
window.cycleTextSize = cycleTextSize;
