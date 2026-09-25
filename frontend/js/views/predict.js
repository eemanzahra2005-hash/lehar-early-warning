/** Predict view — form (left) + result panel (right). Works anonymously;
 * saved fields and "save as field" are only available when logged in. */

import { getMeta, predict, getFields, createField, getSoilMoisture } from '../api.js';
import { state, isLoggedIn } from '../state.js';
import { skeleton, errorState, emptyState, toastSuccess, toastError, escapeHtml, wireExpandToggles } from '../ui.js';
import { ICONS } from '../icons.js';
import { gaugeMarkup, animateGaugeNeedle } from '../gauge.js';
import { describeFactors } from '../rules.js';
import { explainPanelMarkup, confidenceLineMarkup } from '../explainUi.js';
import { riskExpandableMarkup } from '../riskUi.js';
import { setLastPrediction } from '../predictionCache.js';
import { explainPredictionInUrdu } from '../assistant.js';

// Phase 16 — must match backend/app/services/soil.py's SOURCE_LIVE / LIVE_LABEL
// (asserted by backend/tests/test_soil_moisture.py) so the UI, API, and
// assistant always describe a live value in exactly the same words.
const SOIL_SOURCE_LIVE = 'live (Open-Meteo model estimate)';
const SOIL_LIVE_LABEL = 'model-estimated — Open-Meteo, not a field sensor';

function sourceChip(source) {
  return source === 'model_prediction'
    ? `<span class="chip chip--emerald">${ICONS.checkCircle}Model prediction</span>`
    : `<span class="chip chip--amber">${ICONS.alertTriangle}Fallback rule-based</span>`;
}

/** Phase 16 — soil moisture value + its source for the "Inputs used" table.
 * A live value always shows the raw Open-Meteo layers it came from and the
 * model-estimate label, so it can never pass for a field sensor reading. */
function soilMoistureRowsMarkup(result) {
  const value = result.soil_moisture_used ?? result.inputs_used.soil_moisture_pct;
  const source = result.soil_moisture_source || 'manual';
  const valueRow = `<tr><td>Soil moisture</td><td><span class="mono">${value}%</span> <span class="chip">${escapeHtml(source)}</span></td></tr>`;
  const layers = result.soil_moisture_layers;
  if (source !== SOIL_SOURCE_LIVE || !layers) return valueRow;
  return `${valueRow}
    <tr>
      <td>Soil layers (${escapeHtml(layers.unit)})</td>
      <td>
        <span class="mono">1–3 cm ${layers.soil_moisture_1_to_3cm.toFixed(3)} · 3–9 cm ${layers.soil_moisture_3_to_9cm.toFixed(3)} · 9–27 cm ${layers.soil_moisture_9_to_27cm.toFixed(3)} → root zone ${layers.root_zone.toFixed(3)}</span><br />
        <span class="text-muted" style="font-size:11.5px">${escapeHtml(SOIL_LIVE_LABEL)} · hour ${escapeHtml(layers.observed_at)} local</span>
      </td>
    </tr>`;
}

function renderResult(result) {
  const factors = describeFactors({
    soil_moisture_pct: result.inputs_used.soil_moisture_pct,
    evapotranspiration_mm: result.weather_used.evapotranspiration_mm,
    rainfall_mm: result.weather_used.rainfall_mm,
    temperature_c: result.weather_used.temperature_c,
  });

  return `
    <div class="flex flex-col gap-4">
      <div class="flex items-center gap-4" style="flex-wrap:wrap">
        <div class="gauge">
          ${gaugeMarkup(result.irrigation_recommendation_mm, { max: 60, size: 220 })}
          <div class="gauge__value">${result.irrigation_recommendation_mm.toFixed(1)}<small> mm/24h</small></div>
          ${result.confidence ? `<div class="text-muted" style="font-size:11.5px;margin-top:4px;text-align:center">${confidenceLineMarkup(result.irrigation_recommendation_mm, result.confidence)}</div>` : ''}
        </div>
        <div class="flex flex-col gap-3" style="flex:1;min-width:200px">
          <div class="flex gap-2" style="flex-wrap:wrap;align-items:center">
            ${sourceChip(result.source)}
            <span class="chip">${escapeHtml(result.model_version || 'no model')}</span>
            ${riskExpandableMarkup(result.risk, { id: 'predict-risk-breakdown' })}
          </div>
          <p class="text-secondary" style="font-size:13px;line-height:1.5">${escapeHtml(factors)}</p>
          <button type="button" class="btn btn--sm btn--ghost" id="explain-urdu-btn" style="align-self:flex-start">${ICONS.globe}<span>Explain in Urdu</span></button>
          ${result.reason ? `<p class="text-amber" style="font-size:12px">${escapeHtml(result.reason)}</p>` : ''}
          ${result.soil_moisture_note ? `<p class="text-amber" style="font-size:12px">${escapeHtml(result.soil_moisture_note)}</p>` : ''}
        </div>
      </div>

      <div>
        <div class="card__title" style="margin-bottom:8px;font-size:12.5px">${ICONS.explainability}Why this prediction?</div>
        ${explainPanelMarkup(result.explanation)}
      </div>

      <div>
        <div class="card__title" style="margin-bottom:8px;font-size:12.5px">${ICONS.forecast}Weather used <span class="chip" style="margin-left:6px">${escapeHtml(result.weather_used.source)}</span></div>
        <div class="grid grid--kpi" style="gap:8px">
          <div class="kpi kpi--mini kpi--amber"><div class="kpi__head"><span>Temp</span></div><div class="kpi__value">${result.weather_used.temperature_c.toFixed(1)}<small>°C</small></div></div>
          <div class="kpi kpi--mini kpi--sky"><div class="kpi__head"><span>Humidity</span></div><div class="kpi__value">${result.weather_used.humidity_pct.toFixed(0)}<small>%</small></div></div>
          <div class="kpi kpi--mini kpi--sky"><div class="kpi__head"><span>Rainfall</span></div><div class="kpi__value">${result.weather_used.rainfall_mm.toFixed(1)}<small>mm</small></div></div>
          <div class="kpi kpi--mini kpi--emerald"><div class="kpi__head"><span>ET0</span></div><div class="kpi__value">${result.weather_used.evapotranspiration_mm.toFixed(1)}<small>mm</small></div></div>
        </div>
      </div>

      <div>
        <div class="card__title" style="margin-bottom:8px;font-size:12.5px">${ICONS.settings}Inputs used</div>
        <div class="table-wrap">
          <table class="table">
            <tbody>
              <tr><td>District</td><td class="mono">${escapeHtml(result.inputs_used.district)}</td></tr>
              <tr><td>Crop</td><td class="mono">${escapeHtml(result.inputs_used.crop_type)}</td></tr>
              ${soilMoistureRowsMarkup(result)}
              <tr><td>Canal flow</td><td class="mono">${result.inputs_used.canal_flow_cusecs} cusecs</td></tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  `;
}

export function mountPredict(root) {
  root.innerHTML = `
    <div class="view-header">
      <div>
        <h1>Predict</h1>
        <p>Generate an irrigation recommendation from live or manual weather.</p>
      </div>
    </div>

    <div class="grid grid--2col">
      <div class="card">
        <div class="card__header"><span class="card__title">${ICONS.settings}Inputs</span></div>
        <form id="predict-form" class="flex flex-col gap-4" novalidate>
          <div class="field" id="saved-field-wrap" hidden>
            <label for="saved-field-select">Saved field</label>
            <select class="select" id="saved-field-select"><option value="">— none —</option></select>
          </div>

          <div class="field">
            <label for="predict-district">District</label>
            <select class="select" id="predict-district" required><option>Loading…</option></select>
          </div>

          <div class="field">
            <label for="predict-crop">Crop</label>
            <select class="select" id="predict-crop" required><option>Loading…</option></select>
          </div>

          <div class="field">
            <label for="predict-soil">Soil moisture</label>
            <div class="range-row">
              <input class="range" type="range" id="predict-soil" min="0" max="100" step="1" value="35" />
              <span class="range-row__value" id="predict-soil-value">35%</span>
            </div>
            <p class="text-muted" id="predict-soil-live-label" style="font-size:11.5px" hidden>${SOIL_LIVE_LABEL}</p>
            <p class="text-amber" id="predict-soil-notice" style="font-size:12px" role="status" hidden></p>
          </div>

          <div class="field">
            <label for="predict-canal">Canal flow</label>
            <div class="range-row">
              <input class="range" type="range" id="predict-canal" min="0" max="1000" step="10" value="300" />
              <span class="range-row__value" id="predict-canal-value">300 cusecs</span>
            </div>
          </div>

          <div class="flex gap-4" style="flex-wrap:wrap">
            <label class="switch">
              <input type="checkbox" id="use-live-weather" checked />
              <span class="switch__track"><span class="switch__thumb"></span></span>
              <span>Use live weather</span>
            </label>

            <label class="switch">
              <input type="checkbox" id="use-live-soil" />
              <span class="switch__track"><span class="switch__thumb"></span></span>
              <span>Use live soil moisture</span>
            </label>
          </div>

          <div id="manual-weather-fields" class="flex flex-col gap-3" hidden>
            <div class="field"><label for="manual-temp">Temperature (°C)</label><input class="input" type="number" id="manual-temp" step="0.1" value="30" /></div>
            <div class="field"><label for="manual-humidity">Humidity (%)</label><input class="input" type="number" id="manual-humidity" step="0.1" value="45" min="0" max="100" /></div>
            <div class="field"><label for="manual-rainfall">Rainfall (mm)</label><input class="input" type="number" id="manual-rainfall" step="0.1" value="2" min="0" /></div>
            <div class="field"><label for="manual-et0">ET0 (mm)</label><input class="input" type="number" id="manual-et0" step="0.1" value="5" min="0" /></div>
          </div>

          <label class="switch">
            <input type="checkbox" id="sensor-fault" />
            <span class="switch__track"><span class="switch__thumb"></span></span>
            <span>Simulate sensor fault</span>
            <span class="chip" title="Bypasses the ML model entirely and uses the documented rule-based fallback: max(0, (35 - soil moisture) x 0.9). Tests graceful degradation when sensors can't be trusted.">${ICONS.info}</span>
          </label>

          <button type="submit" class="btn btn--primary btn--block" id="predict-submit">Get recommendation</button>

          <div class="flex gap-2" id="save-field-row" hidden>
            <input class="input" id="save-field-name" placeholder="Field name (e.g. North Plot)" />
            <button type="button" class="btn btn--sm" id="save-field-btn">${ICONS.save}<span>Save as field</span></button>
          </div>
        </form>
      </div>

      <div class="card">
        <div class="card__header"><span class="card__title">${ICONS.checkCircle}Result</span></div>
        <div id="predict-result"></div>
      </div>
    </div>
  `;

  const form = root.querySelector('#predict-form');
  const districtSelect = root.querySelector('#predict-district');
  const cropSelect = root.querySelector('#predict-crop');
  const soilInput = root.querySelector('#predict-soil');
  const soilValue = root.querySelector('#predict-soil-value');
  const soilLiveLabel = root.querySelector('#predict-soil-live-label');
  const soilNotice = root.querySelector('#predict-soil-notice');
  const canalInput = root.querySelector('#predict-canal');
  const canalValue = root.querySelector('#predict-canal-value');
  const useLive = root.querySelector('#use-live-weather');
  const useLiveSoil = root.querySelector('#use-live-soil');
  const manualFields = root.querySelector('#manual-weather-fields');
  const sensorFault = root.querySelector('#sensor-fault');
  const submitBtn = root.querySelector('#predict-submit');
  const resultEl = root.querySelector('#predict-result');
  const savedFieldWrap = root.querySelector('#saved-field-wrap');
  const savedFieldSelect = root.querySelector('#saved-field-select');
  const saveFieldRow = root.querySelector('#save-field-row');
  const saveFieldBtn = root.querySelector('#save-field-btn');
  const saveFieldName = root.querySelector('#save-field-name');

  resultEl.appendChild(
    emptyState({
      icon: ICONS.predict,
      title: 'No recommendation yet',
      desc: 'Fill in the form and click "Get recommendation".',
    })
  );

  // --- Phase 16: "Use live soil moisture" toggle (docs/SOIL_MOISTURE.md) ----
  // manualSoil is the user's own slider value, kept apart from any live value
  // on display: it's what switching the toggle off (or a failed live fetch)
  // restores, and it's always sent as soil_moisture_pct — the value the
  // server itself falls back to if its live fetch fails at predict time.
  let manualSoil = Number(soilInput.value);
  // Bumped on every live fetch / toggle-off, so a slow response for an
  // earlier district (or after switching off) can't overwrite current state.
  let liveSoilRequestId = 0;

  function showManualSoil() {
    soilInput.disabled = false;
    soilInput.value = manualSoil;
    manualSoil = Number(soilInput.value); // snapped to the slider's step, same as before Phase 16
    soilValue.textContent = `${manualSoil}%`;
    soilValue.classList.remove('is-live');
    soilLiveLabel.hidden = true;
  }

  function showLiveSoil(value) {
    soilInput.disabled = true;
    soilInput.value = value;
    soilValue.textContent = `${value.toFixed(1)}%`;
    soilValue.classList.add('is-live');
    soilLiveLabel.hidden = false;
  }

  // Never blocks prediction: switch back to manual and say why, visibly.
  function fallBackToManualSoil(message) {
    liveSoilRequestId++;
    useLiveSoil.checked = false;
    showManualSoil();
    soilNotice.textContent = message;
    soilNotice.hidden = false;
  }

  async function loadLiveSoil() {
    const requestId = ++liveSoilRequestId;
    soilNotice.hidden = true;
    soilInput.disabled = true;
    soilValue.textContent = '…';
    try {
      const reading = await getSoilMoisture(districtSelect.value);
      if (requestId !== liveSoilRequestId) return;
      showLiveSoil(reading.soil_moisture_pct);
    } catch (err) {
      if (requestId !== liveSoilRequestId) return;
      fallBackToManualSoil(`Live soil moisture unavailable (${err.message}) — using your manual value instead.`);
    }
  }

  // The server does its own live fetch at predict time; mirror what it
  // actually used so the form never disagrees with the result panel.
  function syncSoilWithResult(result) {
    if (!useLiveSoil.checked) return;
    if (result.soil_moisture_source === SOIL_SOURCE_LIVE) {
      liveSoilRequestId++;
      showLiveSoil(result.soil_moisture_used);
    } else if (result.soil_moisture_note) {
      fallBackToManualSoil(result.soil_moisture_note);
    }
  }

  soilInput.addEventListener('input', () => {
    manualSoil = Number(soilInput.value);
    soilValue.textContent = `${soilInput.value}%`;
  });
  canalInput.addEventListener('input', () => {
    canalValue.textContent = `${canalInput.value} cusecs`;
  });
  useLive.addEventListener('change', () => {
    manualFields.hidden = useLive.checked;
  });
  useLiveSoil.addEventListener('change', () => {
    if (useLiveSoil.checked) {
      loadLiveSoil();
    } else {
      liveSoilRequestId++;
      soilNotice.hidden = true;
      showManualSoil();
    }
  });
  districtSelect.addEventListener('change', () => {
    if (useLiveSoil.checked) loadLiveSoil();
  });

  let fieldsCache = [];

  async function loadMeta() {
    try {
      const meta = await getMeta();
      districtSelect.innerHTML = Object.entries(meta.districts_by_province)
        .map(
          ([province, districts]) => `
            <optgroup label="${escapeHtml(province)}">
              ${districts.map((d) => `<option value="${escapeHtml(d)}">${escapeHtml(d)}</option>`).join('')}
            </optgroup>
          `
        )
        .join('');
      cropSelect.innerHTML = meta.crops.map((c) => `<option value="${escapeHtml(c)}">${escapeHtml(c)}</option>`).join('');

      const initialDistrict = state.district && meta.districts.includes(state.district) ? state.district : meta.districts[0];
      districtSelect.value = initialDistrict;
    } catch (err) {
      districtSelect.innerHTML = '<option value="">Unavailable</option>';
      cropSelect.innerHTML = '<option value="">Unavailable</option>';
      toastError(`Could not load districts/crops: ${err.message}`);
    }
  }

  async function loadFields() {
    if (!isLoggedIn()) {
      savedFieldWrap.hidden = true;
      saveFieldRow.hidden = true;
      return;
    }
    savedFieldWrap.hidden = false;
    saveFieldRow.hidden = false;
    try {
      fieldsCache = await getFields();
      savedFieldSelect.innerHTML =
        '<option value="">— none —</option>' +
        fieldsCache
          .map((f) => `<option value="${f.id}">${escapeHtml(f.name)} (${escapeHtml(f.district)})</option>`)
          .join('');
    } catch (err) {
      toastError(`Could not load saved fields: ${err.message}`);
    }
  }

  savedFieldSelect.addEventListener('change', () => {
    const field = fieldsCache.find((f) => String(f.id) === savedFieldSelect.value);
    if (!field) return;
    districtSelect.value = field.district;
    cropSelect.value = field.crop_type;
    if (field.default_soil_moisture_pct !== null && field.default_soil_moisture_pct !== undefined) {
      manualSoil = Number(field.default_soil_moisture_pct);
      if (!useLiveSoil.checked) showManualSoil();
    }
    if (field.default_canal_flow_cusecs !== null && field.default_canal_flow_cusecs !== undefined) {
      canalInput.value = field.default_canal_flow_cusecs;
      canalValue.textContent = `${canalInput.value} cusecs`;
    }
    // Setting districtSelect.value programmatically fires no 'change' event.
    if (useLiveSoil.checked) loadLiveSoil();
  });

  saveFieldBtn.addEventListener('click', async () => {
    const name = saveFieldName.value.trim();
    if (!name) {
      toastError('Give the field a name first.');
      return;
    }
    saveFieldBtn.disabled = true;
    try {
      await createField({
        name,
        district: districtSelect.value,
        crop_type: cropSelect.value,
        // The user's own value — a live model estimate is never saved as a
        // field's default soil moisture.
        default_soil_moisture_pct: manualSoil,
        default_canal_flow_cusecs: Number(canalInput.value),
      });
      toastSuccess(`Saved field "${name}".`);
      saveFieldName.value = '';
      await loadFields();
    } catch (err) {
      toastError(err.message);
    } finally {
      saveFieldBtn.disabled = false;
    }
  });

  async function submitPrediction() {
    const payload = {
      district: districtSelect.value,
      crop_type: cropSelect.value,
      soil_moisture_pct: manualSoil,
      canal_flow_cusecs: Number(canalInput.value),
      use_live_weather: useLive.checked,
      use_live_soil: useLiveSoil.checked,
      simulate_sensor_fault: sensorFault.checked,
      field_id: isLoggedIn() && savedFieldSelect.value ? Number(savedFieldSelect.value) : null,
    };
    if (!useLive.checked) {
      payload.manual_temperature_c = Number(root.querySelector('#manual-temp').value);
      payload.manual_humidity_pct = Number(root.querySelector('#manual-humidity').value);
      payload.manual_rainfall_mm = Number(root.querySelector('#manual-rainfall').value);
      payload.manual_evapotranspiration_mm = Number(root.querySelector('#manual-et0').value);
    }

    submitBtn.disabled = true;
    submitBtn.textContent = 'Calculating…';
    resultEl.innerHTML = skeleton.block(260);

    try {
      const result = await predict(payload);
      setLastPrediction(result);
      syncSoilWithResult(result);
      resultEl.innerHTML = renderResult(result);
      animateGaugeNeedle(resultEl.querySelector('.gauge__svg'), result.irrigation_recommendation_mm, { max: 60 });
      wireExpandToggles(resultEl);
      resultEl.querySelector('#explain-urdu-btn')?.addEventListener('click', () => explainPredictionInUrdu(result));
      toastSuccess('Recommendation ready.');
    } catch (err) {
      resultEl.innerHTML = '';
      resultEl.appendChild(errorState({ message: err.message, onRetry: submitPrediction }));
      toastError(err.message);
    } finally {
      submitBtn.disabled = false;
      submitBtn.textContent = 'Get recommendation';
    }
  }

  form.addEventListener('submit', (e) => {
    e.preventDefault();
    submitPrediction();
  });

  loadMeta();
  loadFields();
}
