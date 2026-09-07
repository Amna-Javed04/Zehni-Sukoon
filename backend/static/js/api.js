/**
 * api.js — Zehni Sukoon
 * Single source of truth for all backend API calls.
 * Replaces all localStorage session logic with real API calls.
 */

const API_BASE = window.ZS_API_BASE || '/api';

async function apiFetch(path, options = {}) {
  const token = authGetToken();
  const guestId = authGetGuestId();

  const headers = {
    'Content-Type': 'application/json',
    ...(token ? { 'Authorization': `Bearer ${token}` } : {}),
    ...(guestId && !token ? { 'X-Guest-Session': guestId } : {}),
    ...(options.headers || {}),
  };

  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers,
  });

  const data = await response.json().catch(() => ({}));

  if (!response.ok) {
    throw new ApiError(response.status, data.error || 'Request failed', data);
  }

  return data;
}

class ApiError extends Error {
  constructor(status, message, data = {}) {
    super(message);
    this.status = status;
    this.data = data;
  }
}

// Build `?a=b&c=d` from an object, skipping empty/undefined values.
function qs(params = {}) {
  const q = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== '') q.set(k, v);
  });
  const s = q.toString();
  return s ? `?${s}` : '';
}

// Auth endpoints
const Api = {
  auth: {
    signup: (email, password) =>
      apiFetch('/auth/signup', { method: 'POST', body: JSON.stringify({ email, password }) }),
    login: (email, password) =>
      apiFetch('/auth/login', { method: 'POST', body: JSON.stringify({ email, password }) }),
    guest: () =>
      apiFetch('/auth/guest', { method: 'POST' }),
    forgotPassword: (email) =>
      apiFetch('/auth/forgot-password', { method: 'POST', body: JSON.stringify({ email }) }),
    resetPassword: (token, password) =>
      apiFetch('/auth/reset-password', { method: 'POST', body: JSON.stringify({ token, password }) }),
  },
  screening: {
    start: (payload) =>
      apiFetch('/screening/start', { method: 'POST', body: JSON.stringify(payload) }),
    answer: (payload) =>
      apiFetch('/screening/answer', { method: 'POST', body: JSON.stringify(payload) }),
    result: (payload) =>
      apiFetch('/screening/result', { method: 'POST', body: JSON.stringify(payload) }),
  },
  chat: {
    extractScore: (payload) =>
      apiFetch('/chat/extract-score', { method: 'POST', body: JSON.stringify(payload) }),
    screeningTurn: (payload) =>
      apiFetch('/chat/screening-turn', { method: 'POST', body: JSON.stringify(payload) }),
    companion: (message, history) =>
      apiFetch('/chat/companion', { method: 'POST', body: JSON.stringify({ message, history }) }),
  },
  user: {
    overview: (params = {}) => apiFetch(`/user/overview${qs(params)}`),
    history:  (params = {}) => apiFetch(`/user/history${qs(params)}`),
  },
  admin: {
    stats:     (params = {}) => apiFetch(`/admin/stats${qs(params)}`),
    users:     (params = {}) => apiFetch(`/admin/users${qs(params)}`),
    addUser:   (payload)      => apiFetch('/admin/users', { method: 'POST', body: JSON.stringify(payload) }),
    deleteUser: (id)         => apiFetch(`/admin/users/${id}`, { method: 'DELETE' }),
  },
};

window.Api = Api;
window.ApiError = ApiError;
