/**
 * nav-menu.js — Zehni Sukoon
 * Navbar account & settings dropdown: login/logout, language, mode, text size.
 * Options are shown as icons, the active one is highlighted, and the menu
 * closes on outside click or Escape. All actions delegate to the existing
 * i18n.js / theme.js engines so behavior stays identical to the old buttons.
 */

// ── Open / close ──────────────────────────────────────────────
function toggleNavMenu(e) {
  e.stopPropagation();
  const panel = document.getElementById('nav-menu-panel');
  const btn   = document.getElementById('nav-menu-btn');
  if (!panel || !btn) return;
  const open = !panel.classList.toggle('d-none');
  btn.setAttribute('aria-expanded', String(open));
  if (open) refreshNavMenu();
}

function closeNavMenu() {
  const panel = document.getElementById('nav-menu-panel');
  const btn   = document.getElementById('nav-menu-btn');
  if (!panel || panel.classList.contains('d-none')) return;
  panel.classList.add('d-none');
  btn.setAttribute('aria-expanded', 'false');
}

// ── Setters (delegate to theme.js / i18n.js) ─────────────────
function setNavLanguage(lang) {
  if (typeof applyLanguage === 'function' && getCurrentLang() !== lang) applyLanguage(lang);
  refreshNavMenu();
}

function setNavTheme(theme) {
  if (typeof applyTheme === 'function') applyTheme(theme);
  refreshNavMenu();
}

function setNavTextSize(idx) {
  if (typeof applyTextSize === 'function') applyTextSize(idx);
  refreshNavMenu();
}

// ── Reflect current choices on the menu buttons ──────────────
function refreshNavMenu() {
  const setActive = (id, on) => {
    const el = document.getElementById(id);
    if (el) el.classList.toggle('active', on);
  };
  // Storage keys kept in sync with theme.js / i18n.js
  const lang  = (typeof getCurrentLang === 'function') ? getCurrentLang() : 'ur';
  const theme = localStorage.getItem('zs_theme') || 'light';
  const size  = parseInt(localStorage.getItem('zs_textsize') || '0', 10);

  setActive('menu-lang-ur', lang === 'ur');
  setActive('menu-lang-en', lang === 'en');
  setActive('menu-theme-light', theme !== 'dark');
  setActive('menu-theme-dark', theme === 'dark');
  setActive('menu-size-0', size === 0);
  setActive('menu-size-1', size === 1);
  setActive('menu-size-2', size === 2);
}

// ── Global wiring ────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  refreshNavMenu();

  // Close when clicking anywhere outside the dropdown
  document.addEventListener('click', (e) => {
    const wrap = document.getElementById('nav-menu-wrap');
    if (wrap && !wrap.contains(e.target)) closeNavMenu();
  });

  // Close on Escape
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closeNavMenu();
  });

  // Keep highlights and the user badge in sync when the language flips
  new MutationObserver(() => {
    refreshNavMenu();
    if (typeof authUpdateHeader === 'function') authUpdateHeader();
  }).observe(document.documentElement, { attributes: true, attributeFilter: ['lang'] });
});

window.toggleNavMenu  = toggleNavMenu;
window.closeNavMenu   = closeNavMenu;
window.setNavLanguage = setNavLanguage;
window.setNavTheme    = setNavTheme;
window.setNavTextSize = setNavTextSize;
window.refreshNavMenu = refreshNavMenu;
