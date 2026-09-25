/**
 * Fetch wrapper for the backend API. Attaches the JWT from localStorage,
 * turns every error response into a readable message, and on 401 clears the
 * session and broadcasts 'auth:unauthorized' so app.js can open the login
 * modal — this module never touches the DOM directly.
 */

const BASE = '/api/v1';
// All browser storage keys share the `lehar_` prefix so they never collide
// with other apps served from the same origin.
const TOKEN_KEY = 'lehar_token';
const REFRESH_TOKEN_KEY = 'lehar_refresh_token';
const USERNAME_KEY = 'lehar_username';

export class ApiError extends Error {
  constructor(message, status, detail) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
  }
}

export function getToken() {
  return localStorage.getItem(TOKEN_KEY);
}

export function getRefreshToken() {
  return localStorage.getItem(REFRESH_TOKEN_KEY);
}

export function getUsername() {
  return localStorage.getItem(USERNAME_KEY);
}

export function setSession(token, username, refreshToken) {
  localStorage.setItem(TOKEN_KEY, token);
  localStorage.setItem(USERNAME_KEY, username);
  if (refreshToken) localStorage.setItem(REFRESH_TOKEN_KEY, refreshToken);
  window.dispatchEvent(new CustomEvent('auth:changed'));
}

export function clearSession() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(REFRESH_TOKEN_KEY);
  localStorage.removeItem(USERNAME_KEY);
  window.dispatchEvent(new CustomEvent('auth:changed'));
}

// --- Silent access-token refresh (Phase 11) ---------------------------------
//
// On a 401, request() below tries this exactly ONCE before giving up (a
// `_isRetry` flag on the recursive retry call prevents any further attempt,
// so a request that 401s again right after a successful refresh — e.g. the
// refresh token itself just expired between calls — falls straight through
// to clearSession() instead of looping). Concurrent 401s (e.g. several
// dashboard tiles fetching in parallel) share one in-flight refresh via
// `refreshPromise` instead of each firing their own POST /auth/refresh.
let refreshPromise = null;

async function silentRefresh() {
  const refreshToken = getRefreshToken();
  if (!refreshToken) return false;
  if (!refreshPromise) {
    refreshPromise = fetch(new URL(BASE + '/auth/refresh', window.location.origin), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: refreshToken }),
    })
      .then(async (response) => {
        if (!response.ok) return false;
        const data = await response.json();
        localStorage.setItem(TOKEN_KEY, data.access_token);
        window.dispatchEvent(new CustomEvent('auth:changed'));
        return true;
      })
      .catch(() => false)
      .finally(() => {
        refreshPromise = null;
      });
  }
  return refreshPromise;
}

function formatDetail(detail) {
  if (!detail) return null;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((item) => {
        const field = Array.isArray(item.loc) ? item.loc[item.loc.length - 1] : null;
        return field ? `${field}: ${item.msg}` : item.msg;
      })
      .join('; ');
  }
  return null;
}

async function request(path, { method = 'GET', body, auth = true, query, _isRetry = false } = {}) {
  const url = new URL(BASE + path, window.location.origin);
  if (query) {
    Object.entries(query).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== '') {
        url.searchParams.set(key, value);
      }
    });
  }

  const headers = { 'Content-Type': 'application/json' };
  const token = getToken();
  if (auth && token) headers.Authorization = `Bearer ${token}`;

  let response;
  try {
    response = await fetch(url, {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new ApiError('Cannot reach the API. Is the server running?', 0, null);
  }

  if (response.status === 204) return null;

  const text = await response.text();
  let payload = null;
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = null;
    }
  }

  if (!response.ok) {
    if (response.status === 401 && auth && token) {
      if (!_isRetry && (await silentRefresh())) {
        return request(path, { method, body, auth, query, _isRetry: true });
      }
      clearSession();
      window.dispatchEvent(new CustomEvent('auth:unauthorized'));
    }
    const message = formatDetail(payload && payload.detail) || response.statusText || 'Request failed.';
    throw new ApiError(message, response.status, payload && payload.detail);
  }

  return payload;
}

export const api = {
  get: (path, opts) => request(path, { ...opts, method: 'GET' }),
  post: (path, body, opts) => request(path, { ...opts, method: 'POST', body }),
  del: (path, opts) => request(path, { ...opts, method: 'DELETE' }),
};

// --- Typed convenience wrappers for each endpoint ---------------------------

export const getHealth = () => api.get('/health', { auth: false });
export const getMeta = () => api.get('/meta', { auth: false });
export const getWeather = (district) => api.get('/weather', { auth: false, query: { district } });
export const getForecast = (district, days = 7, opts = {}) =>
  api.get('/forecast', { auth: false, query: { district, days, ...opts } });
// Phase 16 — a live Open-Meteo model estimate, never a field sensor reading (docs/SOIL_MOISTURE.md).
export const getSoilMoisture = (district) => api.get('/soil-moisture', { auth: false, query: { district } });

export const getMapOverview = () => api.get('/map/overview', { auth: false });
export const compareDistricts = (payload) => api.post('/compare', payload, { auth: false });

export const getFloodOverview = () => api.get('/flood/overview', { auth: false });
export const getFloodDistrict = (district) =>
  api.get(`/flood/district/${encodeURIComponent(district)}`, { auth: false });

export const login = (username, password) =>
  api.post('/auth/login', { username, password }, { auth: false });
export const register = (username, password, email) =>
  api.post('/auth/register', { username, password, email }, { auth: false });

// Works anonymously (no token) but must still attach one when present —
// a logged-in prediction needs the token so the backend can attribute it
// to the user (and to use field_id), so this does NOT pass { auth: false }.
export const predict = (payload) => api.post('/predict', payload);

export const getFields = () => api.get('/fields');
export const createField = (payload) => api.post('/fields', payload);
export const deleteField = (id) => api.del(`/fields/${id}`);

export const getHistory = (params = {}) => api.get('/history', { query: params });
// Phase 10 — records a real outcome against one of the caller's own past
// predictions; see the History page's "Record actual" action.
export const recordActual = (predictionId, payload) => api.post(`/history/${predictionId}/actual`, payload);

export const getFeatureImportance = () => api.get('/models/feature-importance', { auth: false });
export const getModelInfo = () => api.get('/models/info', { auth: false });
export const getGlobalExplain = () => api.get('/explain/global', { auth: false });

// Phase 7 — MLOps registry (list is public; promote/rollback need auth, see api.post's default auth: true).
export const getModels = () => api.get('/models', { auth: false });
export const promoteModel = (version) => api.post(`/models/${encodeURIComponent(version)}/promote`);
export const rollbackModel = () => api.post('/models/rollback');

// Anonymous-safe (works without login) but still attaches a token when
// present, same rationale as predict() above — a logged-in chat can be
// grounded in the user's real prediction history.
export const getAssistantStatus = () => api.get('/assistant/status', { auth: false });
export const assistantChat = (payload) => api.post('/assistant/chat', payload);

// Phase 8 — read-only, same transparency stance as getModels() above.
export const getDrift = () => api.get('/monitoring/drift', { auth: false });
// Phase 10 — read-only; honest empty state until real actuals exist (app/services/performance.py).
export const getPerformance = () => api.get('/monitoring/performance', { auth: false });

// Phase 12 — GET /report returns a raw file (xlsx/pdf), not JSON, so this
// bypasses request() entirely: fetches directly, still attaches the JWT the
// same way, and hands the caller a real Blob + the server-chosen filename
// (parsed from Content-Disposition) so the download always matches what the
// backend actually named it (see report_data.py's report_filename()).
export async function downloadReport({ format = 'xlsx', fieldId, district, from, to } = {}) {
  const url = new URL(BASE + '/report', window.location.origin);
  url.searchParams.set('format', format);
  if (fieldId !== undefined && fieldId !== null) url.searchParams.set('field_id', fieldId);
  if (district) url.searchParams.set('district', district);
  if (from) url.searchParams.set('from', from);
  if (to) url.searchParams.set('to', to);

  const token = getToken();
  const headers = {};
  if (token) headers.Authorization = `Bearer ${token}`;

  let response;
  try {
    response = await fetch(url, { headers });
  } catch {
    throw new ApiError('Cannot reach the API. Is the server running?', 0, null);
  }

  if (!response.ok) {
    let detail = null;
    try {
      const payload = await response.json();
      detail = payload && payload.detail;
    } catch {
      // Non-JSON error body — fall through to a generic message below.
    }
    if (response.status === 401) {
      clearSession();
      window.dispatchEvent(new CustomEvent('auth:unauthorized'));
    }
    throw new ApiError(formatDetail(detail) || response.statusText || 'Report generation failed.', response.status, detail);
  }

  const blob = await response.blob();
  const disposition = response.headers.get('Content-Disposition') || '';
  const match = disposition.match(/filename="?([^"]+)"?/);
  const filename = match ? match[1] : `lehar-report.${format}`;
  return { blob, filename };
}
