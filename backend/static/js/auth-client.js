/**
 * auth-client.js — Zehni Sukoon
 * Manages JWT token and guest session in sessionStorage (not localStorage).
 * Updates header auth state and admin tab visibility.
 * Handles login/logout/guest flows via API.
 */

const TOKEN_KEY   = 'zs_token';
const GUEST_KEY   = 'zs_guest_id';
const USER_KEY    = 'zs_user';

// ── Token helpers ──────────────────────────────────────────────
function authGetToken()   { return sessionStorage.getItem(TOKEN_KEY); }
function authGetGuestId() { return sessionStorage.getItem(GUEST_KEY); }
function authGetUser()    {
  try { return JSON.parse(sessionStorage.getItem(USER_KEY)); }
  catch { return null; }
}
function authSetSession(token, user) {
  sessionStorage.setItem(TOKEN_KEY, token);
  sessionStorage.setItem(USER_KEY, JSON.stringify(user));
  sessionStorage.removeItem(GUEST_KEY);
}
function authSetGuest(sessionId) {
  sessionStorage.setItem(GUEST_KEY, sessionId);
  sessionStorage.removeItem(TOKEN_KEY);
  sessionStorage.removeItem(USER_KEY);
}
function authClear() {
  sessionStorage.removeItem(TOKEN_KEY);
  sessionStorage.removeItem(GUEST_KEY);
  sessionStorage.removeItem(USER_KEY);
}

// ── Header UI update ──────────────────────────────────────────
function authUpdateHeader() {
  const user = authGetUser();
  const guestId = authGetGuestId();

  const loggedOut = document.getElementById('auth-logged-out');
  const loggedIn  = document.getElementById('auth-logged-in');
  const badge     = document.getElementById('nav-user-badge');
  const adminItem = document.getElementById('admin-nav-item');

  if (user) {
    loggedOut?.classList.add('d-none');
    loggedIn?.classList.remove('d-none');
    if (badge) {
      const lang = document.documentElement.getAttribute('lang') === 'ur' ? 'ur' : 'en';
      const roleLabel = user.is_admin
        ? (lang === 'ur' ? 'ایڈمن' : 'Admin')
        : (lang === 'ur' ? 'صارف' : 'User');
      badge.textContent = `${user.email} · ${roleLabel}`;
    }
    // Show admin tab only for admin users
    if (adminItem) {
      user.is_admin ? adminItem.classList.remove('d-none') : adminItem.classList.add('d-none');
    }
  } else if (guestId) {
    loggedOut?.classList.remove('d-none');
    loggedIn?.classList.add('d-none');
    if (adminItem) adminItem.classList.add('d-none');
  } else {
    loggedOut?.classList.remove('d-none');
    loggedIn?.classList.add('d-none');
    if (adminItem) adminItem.classList.add('d-none');
  }
}

// ── Actions ──────────────────────────────────────────────────
async function handleSignup(email, password) {
  const data = await Api.auth.signup(email, password);
  authSetSession(data.token, data.user);
  authUpdateHeader();
  return data.user;
}

async function handleLogin(email, password) {
  const data = await Api.auth.login(email, password);
  authSetSession(data.token, data.user);
  authUpdateHeader();
  return data.user; // has redirect_to field
}

async function handleGuestSession() {
  const data = await Api.auth.guest();
  authSetGuest(data.session_id);
  authUpdateHeader();
  return data.session_id;
}

function handleLogout() {
  authClear();
  authUpdateHeader();
  window.location.href = '/';
}

// ── Quick Exit ───────────────────────────────────────────────
function quickExit() {
  authClear();
  window.location.replace('https://www.google.com');
}

// ── Route protection helpers ─────────────────────────────────
function requireAuth() {
  const token = authGetToken();
  if (!token) { window.location.href = '/login'; return false; }
  return true;
}
function requireAdmin() {
  const user = authGetUser();
  if (!user || !user.is_admin) { window.location.href = '/'; return false; }
  return true;
}

// ── Flash message helper ─────────────────────────────────────
function showFlash(message, type = 'info') {
  const container = document.getElementById('flash-container');
  if (!container) return;
  const el = document.createElement('div');
  el.className = `flash-msg ${type}`;
  el.innerHTML = `<i class="fas fa-${type === 'error' ? 'exclamation-circle' : type === 'success' ? 'check-circle' : 'info-circle'}"></i> ${message}`;
  container.appendChild(el);
  setTimeout(() => el.remove(), 5000);
}

// ── Init on DOM ready ─────────────────────────────────────────
document.addEventListener('DOMContentLoaded', authUpdateHeader);

// Export to window
window.authGetToken    = authGetToken;
window.authGetGuestId  = authGetGuestId;
window.authGetUser     = authGetUser;
window.authSetSession  = authSetSession;
window.authSetGuest    = authSetGuest;
window.authClear       = authClear;
window.handleSignup    = handleSignup;
window.handleLogin     = handleLogin;
window.handleGuestSession = handleGuestSession;
window.handleLogout    = handleLogout;
window.quickExit       = quickExit;
window.requireAuth     = requireAuth;
window.requireAdmin    = requireAdmin;
window.showFlash       = showFlash;
