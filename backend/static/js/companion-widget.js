/* ═══════════════════════════════════════════════════════════════════════
   Floating Companion Chat Widget — "Humdum"
   Available on every page via base.html. Talks to /api/chat/companion
   through the existing Api.chat.companion() helper in api.js.
   ═══════════════════════════════════════════════════════════════════════ */
(function () {
  'use strict';

  const STORAGE_KEY = 'zs_companion_v1';

  let isOpen   = false;
  let greeted  = false;
  let history  = [];   // [{ role: 'user'|'assistant', content: string }]

  // ── DOM helpers ─────────────────────────────────────────────────────
  function qs(id) { return document.getElementById(id); }
  function lang() { return (typeof getCurrentLang === 'function') ? getCurrentLang() : 'ur'; }

  // ── Persistence (sessionStorage — cleared when tab closes) ─────────
  function persist() {
    try { sessionStorage.setItem(STORAGE_KEY, JSON.stringify({ history, greeted })); }
    catch { /* private mode / quota — safe to ignore */ }
  }
  function restore() {
    try {
      const raw = sessionStorage.getItem(STORAGE_KEY);
      if (!raw) return;
      const data = JSON.parse(raw);
      if (Array.isArray(data.history)) history = data.history;
      greeted = !!data.greeted;
    } catch { /* ignore corrupt state */ }
  }

  // ── Bubble rendering (reuses .chat-bubble styles already in style.css) ──
  function appendBubble(role, text) {
    const box = qs('companion-chat-window');
    if (!box) return;
    const el = document.createElement('div');
    el.className = 'chat-bubble ' + (role === 'user' ? 'user' : 'bot') + ' fade-in-up';
    el.textContent = text;
    box.appendChild(el);
    box.scrollTop = box.scrollHeight;
  }

  function renderAll() {
    const box = qs('companion-chat-window');
    if (!box) return;
    box.innerHTML = '';
    for (const m of history) {
      appendBubble(m.role === 'user' ? 'user' : 'bot', m.content);
    }
  }

  function greetingText() {
    return lang() === 'ur'
      ? 'خوش آمدید! میں ہمدم ہوں۔ آپ کیسا محسوس کر رہے ہیں؟ آپ بلا جھجھک مجھ سے کوئی بھی بات شیئر کر سکتے ہیں۔'
      : "Welcome! I'm Humdum. How are you feeling today? You can share whatever is on your mind.";
  }

  function fallbackText() {
    return lang() === 'ur'
      ? 'ہم آپ کے جذبات کا احترام کرتے ہیں۔ ہمدم اے آئی ابھی کچھ دیر میں آن لائن ہوگا۔'
      : "I hear you, and your feelings are important. Humdum will be back online shortly.";
  }

  // ── Open / close / toggle ───────────────────────────────────────────
  function setOpen(v) {
    isOpen = v;
    const panel = qs('companion-panel');
    const fab   = qs('companion-fab');
    if (panel) panel.classList.toggle('d-none', !v);
    if (fab) {
      fab.classList.toggle('open', v);
      fab.setAttribute('aria-expanded', v ? 'true' : 'false');
    }
  }

  function open() {
    if (!qs('companion-panel')) return; // widget not rendered on this page
    restore();
    setOpen(true);
    if (!greeted) {
      history.push({ role: 'assistant', content: greetingText() });
      greeted = true;
      persist();
    }
    renderAll();
    clearBadge();
    // Focus input after the panel becomes visible
    setTimeout(() => { const inp = qs('companion-chat-input'); if (inp) inp.focus(); }, 50);
  }

  function close() { setOpen(false); }

  function toggle() { isOpen ? close() : open(); }

  // ── Unread badge (small red dot on the FAB) ─────────────────────────
  function flashBadge()  { const b = qs('companion-fab-badge'); if (b) b.classList.add('show'); }
  function clearBadge()  { const b = qs('companion-fab-badge'); if (b) b.classList.remove('show'); }

  // ── Send a message ──────────────────────────────────────────────────
  async function send(e) {
    if (e && e.preventDefault) e.preventDefault();
    const input = qs('companion-chat-input');
    const btn   = qs('companion-send-btn');
    if (!input) return false;

    const text = (input.value || '').trim();
    if (!text) return false;

    appendBubble('user', text);
    history.push({ role: 'user', content: text });
    input.value = '';
    if (btn) btn.disabled = true;

    let reply = '';
    try {
      const res = await Api.chat.companion(text, history);
      reply = (res && typeof res.response === 'string') ? res.response : fallbackText();
    } catch {
      reply = fallbackText();
    } finally {
      if (btn) btn.disabled = false;
    }

    appendBubble('bot', reply);
    history.push({ role: 'assistant', content: reply });
    persist();

    // If the user closed the panel while we were awaiting, surface the reply via badge.
    if (!isOpen) flashBadge();

    return false;
  }

  // ── Reset (used when the user explicitly asks to start over) ────────
  function reset() {
    history = [];
    greeted = false;
    try { sessionStorage.removeItem(STORAGE_KEY); } catch { /* ignore */ }
    renderAll();
    if (isOpen) {
      history.push({ role: 'assistant', content: greetingText() });
      greeted = true;
      persist();
      renderAll();
    }
  }

  // ── Wire up the FAB click, keyboard shortcut & i18n re-render ──────
  function boot() {
    // The floating button is what the user actually clicks. It is rendered in
    // base.html before this script runs, so it is always findable here.
    const fab = qs('companion-fab');
    if (fab) fab.addEventListener('click', toggle);

    document.addEventListener('keydown', (ev) => {
      if (ev.key === 'Escape' && isOpen) { close(); }
    });

    // Re-translate the static greeting when the user flips language
    // while the panel is already open, without duplicating bubbles.
    const root = document.documentElement;
    if (root && typeof MutationObserver !== 'undefined') {
      new MutationObserver(() => {
        if (!isOpen) return;
        // Nothing to re-render mid-conversation; future replies already pick
        // the current language via lang(). Only the placeholder updates via
        // applyLanguage(), which is called globally by i18n.js.
      }).observe(root, { attributes: true, attributeFilter: ['lang'] });
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }

  // Expose for inline onclick handlers and other templates
  window.CompanionWidget = { open, close, toggle, send, reset, isOpen: () => isOpen };
})();
