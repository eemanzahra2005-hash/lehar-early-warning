/**
 * App entry point: builds the interactive parts of the shell (nav, topbar,
 * theme toggle, district selector, auth area, API status chip) and starts
 * the router. Views live under js/views/ and are wired in below.
 */

import { getMeta, getHealth, clearSession } from './api.js';
import {
  state,
  subscribe,
  applyStoredTheme,
  toggleTheme,
  setDistrict,
  isLoggedIn,
} from './state.js';
import { ICONS, NAV_ITEMS } from './icons.js';
import { toastError, toastInfo, escapeHtml } from './ui.js';
import { openAuthModal } from './auth.js';
import { registerRoute, startRouter, navigate } from './router.js';
import { initCommandPalette } from './commandPalette.js';
import { initAssistant } from './assistant.js';

import { mountDashboard } from './views/dashboard.js';
import { mountPredict } from './views/predict.js';
import { mountSettings } from './views/settings.js';
import { mountMap } from './views/map.js';
import { mountAnalytics } from './views/analytics.js';
import { mountForecast } from './views/forecast.js';
import { mountCompare } from './views/compare.js';
import { mountHistory } from './views/history.js';
import { mountWaterSavings } from './views/waterSavings.js';
import { mountExplainability } from './views/explainability.js';
import { mountModels } from './views/models.js';
import { mountMonitoring } from './views/monitoring.js';
import { mountReports } from './views/reports.js';

// --- Theme -------------------------------------------------------------

applyStoredTheme();

function wireThemeToggle() {
  const btn = document.getElementById('theme-toggle');
  const update = () => {
    btn.innerHTML = state.theme === 'dark' ? ICONS.sun : ICONS.moon;
  };
  update();
  btn.addEventListener('click', () => {
    toggleTheme();
    update();
  });
}

// --- Sidebar nav ---------------------------------------------------------

let closeMobileSidebar = () => {};

function renderNav() {
  const nav = document.getElementById('nav');
  nav.innerHTML = NAV_ITEMS.map(
    (item) => `
      <a class="nav__link" href="#${item.path}" data-path="${item.path}">
        ${item.icon}
        <span class="nav__link-label">${escapeHtml(item.label)}</span>
      </a>
    `
  ).join('');
  nav.querySelectorAll('.nav__link').forEach((link) => {
    link.addEventListener('click', () => closeMobileSidebar());
  });
}

function wireMobileNav() {
  const hamburger = document.getElementById('hamburger');
  const sidebar = document.getElementById('sidebar');
  const scrim = document.getElementById('scrim');
  hamburger.innerHTML = ICONS.menu;

  const open = () => {
    sidebar.classList.add('is-open');
    scrim.classList.add('is-visible');
  };
  const close = () => {
    sidebar.classList.remove('is-open');
    scrim.classList.remove('is-visible');
  };
  closeMobileSidebar = close;

  hamburger.addEventListener('click', () => {
    sidebar.classList.contains('is-open') ? close() : open();
  });
  scrim.addEventListener('click', close);
}

// --- District selector ---------------------------------------------------

// Cached so the command palette doesn't have to re-fetch /meta every time
// it opens; populated once initDistrictSelect() succeeds.
let metaCache = null;

async function initDistrictSelect() {
  const select = document.getElementById('district-select');
  select.innerHTML = '<option>Loading districts…</option>';
  select.disabled = true;

  try {
    const meta = await getMeta();
    metaCache = meta;
    const groups = Object.entries(meta.districts_by_province);
    select.innerHTML = groups
      .map(
        ([province, districts]) => `
          <optgroup label="${escapeHtml(province)}">
            ${districts.map((d) => `<option value="${escapeHtml(d)}">${escapeHtml(d)}</option>`).join('')}
          </optgroup>
        `
      )
      .join('');
    select.disabled = false;

    const initial = state.district && meta.districts.includes(state.district) ? state.district : meta.districts[0];
    select.value = initial;
    setDistrict(initial);
  } catch (err) {
    select.innerHTML = '<option value="">Districts unavailable</option>';
    toastError(`Could not load districts: ${err.message}`);
  }

  select.addEventListener('change', () => setDistrict(select.value));
}

// --- Auth area (login button / user menu) ---------------------------------

function renderAuthArea() {
  const area = document.getElementById('auth-area');
  area.innerHTML = '';

  if (isLoggedIn()) {
    const wrap = document.createElement('div');
    wrap.className = 'user-menu';
    const initial = (state.user.username || '?').slice(0, 1).toUpperCase();
    wrap.innerHTML = `
      <button type="button" class="user-menu__trigger" id="user-menu-trigger">
        <span class="user-menu__avatar">${escapeHtml(initial)}</span>
        <span>${escapeHtml(state.user.username)}</span>
        ${ICONS.chevronDown}
      </button>
      <div class="user-menu__dropdown" id="user-menu-dropdown">
        <button type="button" class="user-menu__item" data-action="settings">${ICONS.settings}<span>Settings</span></button>
        <button type="button" class="user-menu__item" data-action="logout">${ICONS.logout}<span>Log out</span></button>
      </div>
    `;
    area.appendChild(wrap);

    const trigger = wrap.querySelector('#user-menu-trigger');
    const dropdown = wrap.querySelector('#user-menu-dropdown');
    trigger.addEventListener('click', (e) => {
      e.stopPropagation();
      dropdown.classList.toggle('is-open');
    });
    wrap.querySelector('[data-action="logout"]').addEventListener('click', () => {
      clearSession();
      toastInfo('Logged out.');
      navigate('/dashboard');
    });
    wrap.querySelector('[data-action="settings"]').addEventListener('click', () => navigate('/settings'));
  } else {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'btn btn--primary btn--sm';
    btn.textContent = 'Log in';
    btn.addEventListener('click', () => openAuthModal('login'));
    area.appendChild(btn);
  }
}

subscribe(renderAuthArea);

// Single delegated listener (registered once, not per-render) closes the
// user menu dropdown on any click outside it.
document.addEventListener('click', (e) => {
  const dropdown = document.getElementById('user-menu-dropdown');
  if (dropdown && !dropdown.parentElement.contains(e.target)) {
    dropdown.classList.remove('is-open');
  }
});

// --- API status chip -------------------------------------------------------

async function pollHealth() {
  const chip = document.getElementById('api-status-chip');
  const label = document.getElementById('api-status-label');
  const started = performance.now();
  try {
    const health = await getHealth();
    const latencyMs = Math.round(performance.now() - started);
    chip.classList.remove('is-down');
    chip.classList.add('is-ok');
    label.textContent = health.model_version ? `Online · ${health.model_version}` : 'Online';
    chip.title = `Round-trip latency: ${latencyMs}ms`;
  } catch {
    chip.classList.remove('is-ok');
    chip.classList.add('is-down');
    label.textContent = 'API offline';
    chip.title = 'Could not reach the API.';
  }
}

// --- Command palette (Ctrl+K / Cmd+K) ---------------------------------------

function wireCommandPalette() {
  const palette = initCommandPalette({
    pages: NAV_ITEMS,
    getDistricts: () => (metaCache ? metaCache.districts : []),
    onNavigate: (path) => navigate(path),
    onSelectDistrict: (district) => {
      setDistrict(district);
      const select = document.getElementById('district-select');
      if (select) select.value = district;
    },
  });
  const trigger = document.getElementById('cmdk-trigger');
  trigger?.addEventListener('click', () => palette.open());
}

// --- Session expiry --------------------------------------------------------

window.addEventListener('auth:unauthorized', () => {
  toastError('Your session expired. Please log in again.');
  openAuthModal('login');
});

// --- Routes ----------------------------------------------------------------

registerRoute('/dashboard', mountDashboard);
registerRoute('/predict', mountPredict);
registerRoute('/settings', mountSettings);
registerRoute('/map', mountMap);
registerRoute('/analytics', mountAnalytics);
registerRoute('/forecast', mountForecast);
registerRoute('/compare', mountCompare);
registerRoute('/history', mountHistory);
registerRoute('/water-savings', mountWaterSavings);
registerRoute('/explainability', mountExplainability);
registerRoute('/models', mountModels);
registerRoute('/monitoring', mountMonitoring);
registerRoute('/reports', mountReports);

// --- Boot --------------------------------------------------------------

renderNav();
wireThemeToggle();
wireMobileNav();
wireCommandPalette();
renderAuthArea();
initDistrictSelect();
initAssistant();
pollHealth();
setInterval(pollHealth, 30000);
startRouter();
