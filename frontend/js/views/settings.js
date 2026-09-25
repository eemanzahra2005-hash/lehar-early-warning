/** Settings view: theme, default district, and an About card with real
 * values pulled from /api/v1/health + /api/v1/meta — no fabricated metrics. */

import { getHealth, getMeta, getAssistantStatus } from '../api.js';
import { state, setTheme, setDefaultDistrict, getDefaultDistrict, getLlmProviderPreference, setLlmProviderPreference } from '../state.js';
import { skeleton, errorState, escapeHtml } from '../ui.js';
import { toastSuccess } from '../ui.js';

export async function mountSettings(root) {
  root.innerHTML = `
    <div class="view-header">
      <div>
        <h1>Settings</h1>
        <p>Preferences are stored in this browser only.</p>
      </div>
    </div>

    <div class="grid grid--split">
      <div class="card">
        <div class="card__header"><span class="card__title">Appearance</span></div>
        <div class="field">
          <label for="settings-theme">Theme</label>
          <select class="select" id="settings-theme">
            <option value="dark">Dark</option>
            <option value="light">Light</option>
          </select>
          <div class="field-hint">Applies immediately across the app.</div>
        </div>
      </div>

      <div class="card">
        <div class="card__header"><span class="card__title">Defaults</span></div>
        <div class="field" id="default-district-field">
          <label for="settings-default-district">Default district</label>
          <select class="select" id="settings-default-district"><option>Loading…</option></select>
          <div class="field-hint">Used the next time you open LEHAR on this device.</div>
        </div>
      </div>
    </div>

    <div class="card" id="assistant-settings-card">
      <div class="card__header"><span class="card__title">AI Assistant</span></div>
      <div class="field">
        <label for="settings-llm-provider">Provider preference</label>
        <select class="select" id="settings-llm-provider">
          <option value="hybrid">Hybrid (cloud, falls back to local)</option>
          <option value="local">Local only</option>
          <option value="cloud">Cloud only</option>
        </select>
        <div class="field-hint">Sent with every message; honored only when that provider is actually available.</div>
      </div>
      <div class="field-hint" id="assistant-provider-status">Checking provider availability…</div>
    </div>

    <div class="card" id="about-card">
      <div class="card__header"><span class="card__title">About</span></div>
      <div id="about-body">${skeleton.block(160)}</div>
    </div>
  `;

  const themeSelect = root.querySelector('#settings-theme');
  themeSelect.value = state.theme;
  themeSelect.addEventListener('change', () => {
    setTheme(themeSelect.value);
    toastSuccess(`Theme set to ${themeSelect.value}.`);
  });

  const districtSelect = root.querySelector('#settings-default-district');

  const llmProviderSelect = root.querySelector('#settings-llm-provider');
  llmProviderSelect.value = getLlmProviderPreference();
  llmProviderSelect.addEventListener('change', () => {
    setLlmProviderPreference(llmProviderSelect.value);
    toastSuccess(`AI assistant provider preference set to ${llmProviderSelect.options[llmProviderSelect.selectedIndex].text}.`);
  });

  async function loadAssistantStatus() {
    const statusEl = root.querySelector('#assistant-provider-status');
    try {
      const s = await getAssistantStatus();
      const cloudText = s.cloud.available ? `online (${s.cloud.model})` : 'unavailable (no key or unreachable)';
      const localText = s.local.available ? `online (${s.local.model})` : 'unavailable (ollama not reachable)';
      statusEl.innerHTML = `Cloud: <strong class="${s.cloud.available ? 'text-emerald' : 'text-muted'}">${escapeHtml(cloudText)}</strong> &nbsp;·&nbsp; Local: <strong class="${s.local.available ? 'text-emerald' : 'text-muted'}">${escapeHtml(localText)}</strong>`;
    } catch (err) {
      statusEl.textContent = `Could not check provider status: ${err.message}`;
    }
  }
  loadAssistantStatus();

  async function loadAbout() {
    const aboutBody = root.querySelector('#about-body');
    try {
      const [health, meta] = await Promise.all([getHealth(), getMeta()]);

      districtSelect.innerHTML = meta.districts
        .map((d) => `<option value="${escapeHtml(d)}">${escapeHtml(d)}</option>`)
        .join('');
      const current = getDefaultDistrict() || state.district || meta.districts[0];
      districtSelect.value = current;
      districtSelect.addEventListener('change', () => {
        setDefaultDistrict(districtSelect.value);
        toastSuccess(`Default district set to ${districtSelect.value}.`);
      });

      aboutBody.innerHTML = `
        <div class="grid grid--split">
          <div class="flex flex-col gap-2">
            <div><span class="text-muted">App</span><br />${escapeHtml(health.app)}</div>
            <div><span class="text-muted">API version</span><br /><span class="code">${escapeHtml(health.version)}</span></div>
            <div><span class="text-muted">Environment</span><br />${escapeHtml(health.environment)}</div>
            <div><span class="text-muted">Model version</span><br /><span class="code">${escapeHtml(health.model_version || 'not trained')}</span></div>
          </div>
          <div class="flex flex-col gap-2">
            <div><span class="text-muted">Districts covered</span><br /><span class="mono">${meta.districts.length}</span></div>
            <div><span class="text-muted">Crops covered</span><br /><span class="mono">${meta.crops.length}</span></div>
            <div><span class="text-muted">Reference note</span><br /><span class="text-secondary">${escapeHtml(meta.note)}</span></div>
          </div>
        </div>
        <div class="field-hint" style="margin-top:16px;padding-top:16px;border-top:1px solid var(--border)">
          <strong class="text-amber">Synthetic data notice:</strong> every dataset, weather value, and prediction in this
          application is generated for research and demonstration purposes. Nothing here is verified agronomic,
          meteorological, or hydrological data — do not use it to make real irrigation decisions.
        </div>
      `;
    } catch (err) {
      districtSelect.innerHTML = '<option value="">Unavailable</option>';
      aboutBody.innerHTML = '';
      aboutBody.appendChild(errorState({ message: err.message, onRetry: loadAbout }));
    }
  }

  loadAbout();
}
