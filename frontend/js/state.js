/**
 * Small global app state: selected district, current user, theme.
 * Plain pub-sub — subscribe(fn) gets called on every change. No framework.
 */

import { getToken, getUsername } from './api.js';

// All browser storage keys share the `lehar_` prefix so they never collide
// with other apps served from the same origin.
const THEME_KEY = 'lehar_theme';
const DISTRICT_KEY = 'lehar_district';
const DEFAULT_DISTRICT_KEY = 'lehar_default_district';
const LLM_PROVIDER_PREF_KEY = 'lehar_llm_provider_pref';

const listeners = new Set();

// Light is the default theme. On a first-ever visit (nothing saved yet) we
// still honor an explicit OS dark preference, matching the pre-paint check
// in index.html and the @media (prefers-color-scheme: dark) block in
// theme.css so there's no flash between them.
function detectPreferredTheme() {
  if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) return 'dark';
  return 'light';
}

export const state = {
  theme: localStorage.getItem(THEME_KEY) || detectPreferredTheme(),
  district: localStorage.getItem(DISTRICT_KEY) || localStorage.getItem(DEFAULT_DISTRICT_KEY) || null,
  user: getToken() ? { username: getUsername() } : null,
};

export function subscribe(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

function emit() {
  listeners.forEach((fn) => fn(state));
}

export function applyStoredTheme() {
  document.documentElement.setAttribute('data-theme', state.theme);
}

export function setTheme(theme) {
  state.theme = theme;
  localStorage.setItem(THEME_KEY, theme);
  document.documentElement.setAttribute('data-theme', theme);
  emit();
}

export function toggleTheme() {
  setTheme(state.theme === 'dark' ? 'light' : 'dark');
}

export function setDistrict(district) {
  state.district = district;
  if (district) localStorage.setItem(DISTRICT_KEY, district);
  emit();
}

export function getDefaultDistrict() {
  return localStorage.getItem(DEFAULT_DISTRICT_KEY) || '';
}

export function setDefaultDistrict(district) {
  if (district) localStorage.setItem(DEFAULT_DISTRICT_KEY, district);
}

export function isLoggedIn() {
  return Boolean(state.user);
}

// AI Assistant provider preference (Phase 6.6 hybrid assistant, Settings
// page) — "hybrid" | "local" | "cloud", sent as the optional `provider`
// override on every assistant chat request (backend/app/services/llm.py
// honors it only if that provider is actually available right now).
export function getLlmProviderPreference() {
  return localStorage.getItem(LLM_PROVIDER_PREF_KEY) || 'hybrid';
}

export function setLlmProviderPreference(preference) {
  localStorage.setItem(LLM_PROVIDER_PREF_KEY, preference);
}

window.addEventListener('auth:changed', () => {
  state.user = getToken() ? { username: getUsername() } : null;
  emit();
});
