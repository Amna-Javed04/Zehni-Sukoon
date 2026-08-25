/**
 * i18n.js — Zehni Sukoon
 * Bilingual RTL/LTR switching. Urdu (RTL) is the default.
 * All elements with data-ur / data-en attributes are translated.
 * Layout direction (dir="rtl"|"ltr") and font families swap together.
 */

const LANG_KEY = 'zs_lang';

function getCurrentLang() {
  return localStorage.getItem(LANG_KEY) || 'ur';
}

function applyLanguage(lang) {
  const html = document.getElementById('html-root') || document.documentElement;
  const isUrdu = lang === 'ur';

  // Set direction and lang attribute
  html.setAttribute('dir', isUrdu ? 'rtl' : 'ltr');
  html.setAttribute('lang', lang);

  // Translate all data-ur / data-en elements
  document.querySelectorAll('[data-ur], [data-en]').forEach(el => {
    const text = isUrdu ? el.getAttribute('data-ur') : el.getAttribute('data-en');
    if (text !== null && text !== '') el.textContent = text;
  });

  // Placeholder translations
  document.querySelectorAll('[data-ph-ur], [data-ph-en]').forEach(el => {
    const ph = isUrdu ? el.getAttribute('data-ph-ur') : el.getAttribute('data-ph-en');
    if (ph) el.setAttribute('placeholder', ph);
  });

  // Lang button label
  const btn = document.getElementById('lang-btn-label');
  if (btn) btn.textContent = isUrdu ? 'EN' : 'اردو';

  // Store preference
  localStorage.setItem(LANG_KEY, lang);
}

function toggleLanguage() {
  const current = getCurrentLang();
  applyLanguage(current === 'ur' ? 'en' : 'ur');
}

// Init on load
document.addEventListener('DOMContentLoaded', () => {
  applyLanguage(getCurrentLang());
});

window.getCurrentLang  = getCurrentLang;
window.applyLanguage   = applyLanguage;
window.toggleLanguage  = toggleLanguage;
