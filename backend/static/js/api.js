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

// Binary GET (PDF export): same auth rules as apiFetch, but returns a Blob.
async function apiBlob(path) {
  const token = authGetToken();
  const response = await fetch(`${API_BASE}${path}`, {
    headers: token ? { 'Authorization': `Bearer ${token}` } : {},
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new ApiError(response.status, data.error || 'Export failed', data);
  }
  return response.blob();
}

// Trigger a browser download for a Blob (used by the PDF export buttons).
function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename || 'download.pdf';
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
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
    signupTherapist: (payload) =>
      apiFetch('/auth/signup-therapist', { method: 'POST', body: JSON.stringify(payload) }),
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
    // PDF export of the signed-in user's own history (never chat content).
    exportPdf: () => apiBlob('/screening/export-pdf'),
  },
  chat: {
    extractScore: (payload) =>
      apiFetch('/chat/extract-score', { method: 'POST', body: JSON.stringify(payload) }),
    screeningTurn: (payload) =>
      apiFetch('/chat/screening-turn', { method: 'POST', body: JSON.stringify(payload) }),
    companion: (message, history, language) =>
      apiFetch('/chat/companion', { method: 'POST', body: JSON.stringify({ message, history, language }) }),
  },
  user: {
    overview: (params = {}) => apiFetch(`/user/overview${qs(params)}`),
    history:  (params = {}) => apiFetch(`/user/history${qs(params)}`),
    // Remembered screening demographics + consent status (signed-in users)
    profile:  ()            => apiFetch('/user/profile'),
    // Therapist link (patient side)
    getTherapistLink: ()        => apiFetch('/patient/therapist'),
    linkTherapist:    (payload) => apiFetch('/patient/therapist/link', { method: 'POST', body: JSON.stringify(payload) }),
    unlinkTherapist:  ()        => apiFetch('/patient/therapist/link', { method: 'DELETE' }),
  },
  therapist: {
    inviteCode:         ()     => apiFetch('/therapist/invite-code'),
    regenerateCode:     ()     => apiFetch('/therapist/invite-code', { method: 'POST' }),
    patients:           ()     => apiFetch('/therapist/patients'),
    patientScreenings:  (id)   => apiFetch(`/therapist/patients/${id}/screenings`),
    exportPatientPdf:   (id)   => apiBlob(`/therapist/patients/${id}/export-pdf`),
  },
  admin: {
    stats:     (params = {}) => apiFetch(`/admin/stats${qs(params)}`),
    users:     (params = {}) => apiFetch(`/admin/users${qs(params)}`),
    addUser:   (payload)      => apiFetch('/admin/users', { method: 'POST', body: JSON.stringify(payload) }),
    deleteUser: (id)         => apiFetch(`/admin/users/${id}`, { method: 'DELETE' }),
    therapists:      (params = {}) => apiFetch(`/admin/therapists${qs(params)}`),
    verifyTherapist: (id)           => apiFetch(`/admin/therapists/${id}/verify`, { method: 'POST' }),
    rejectTherapist: (id)           => apiFetch(`/admin/therapists/${id}`, { method: 'DELETE' }),
  },
};

window.Api = Api;
window.ApiError = ApiError;
window.downloadBlob = downloadBlob;
