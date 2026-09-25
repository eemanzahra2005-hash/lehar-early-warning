/** Compare view — 2-6 districts side by side, live weather + model
 * recommendation for shared crop/soil-moisture/canal-flow inputs. A single
 * district's weather/prediction failure renders as an inline error card,
 * never blocks the rest of the comparison (POST /api/v1/compare already
 * guarantees that server-side). */

import { getMeta, compareDistricts } from '../api.js';
import { state } from '../state.js';
import { skeleton, errorState, emptyState, escapeHtml, toastError } from '../ui.js';
import { ICONS } from '../icons.js';
import { createChart, tickLabel, seriesColor } from '../charts.js';
import { riskChip } from '../riskUi.js';

const MIN_DISTRICTS = 2;
const MAX_DISTRICTS = 6;

// One district = one color, drawn from the app-wide fixed categorical chart
// palette (slots 1-6 of 8) — deliberately separate from the status tokens
// (good/warning/critical don't apply to "which district is this").
const paletteColor = (i) => seriesColor(i);

const METRICS = [
  { key: 'temperature_c', label: 'Temperature', unit: '°C', path: (r) => r.weather?.temperature_c },
  { key: 'rainfall_mm', label: 'Rainfall', unit: 'mm', path: (r) => r.weather?.rainfall_mm },
  { key: 'humidity_pct', label: 'Humidity', unit: '%', path: (r) => r.weather?.humidity_pct },
  { key: 'evapotranspiration_mm', label: 'ET0', unit: 'mm', path: (r) => r.weather?.evapotranspiration_mm },
  { key: 'recommendation_mm', label: 'Recommendation', unit: 'mm', path: (r) => r.recommendation_mm },
];

function resultCard(result, color) {
  if (result.error) {
    return `
      <div class="card card--pad-sm" style="border-left:3px solid var(--red)">
        <div class="flex items-center gap-2" style="margin-bottom:8px">
          <span class="chip__dot" style="background:${color}"></span>
          <strong>${escapeHtml(result.district)}</strong>
        </div>
        <div class="text-red" style="font-size:12px">${escapeHtml(result.error)}</div>
      </div>
    `;
  }
  const w = result.weather;
  return `
    <div class="card card--pad-sm">
      <div class="flex items-center gap-2" style="margin-bottom:10px">
        <span class="chip__dot" style="background:${color}"></span>
        <strong>${escapeHtml(result.district)}</strong>
      </div>
      <div class="kpi__value" style="font-size:24px;margin-bottom:8px">${result.recommendation_mm.toFixed(1)}<small> mm/24h</small></div>
      <div class="flex flex-col gap-1" style="font-size:12px;color:var(--text-secondary)">
        <div>Temp: <span class="mono">${w.temperature_c.toFixed(1)}°C</span></div>
        <div>Humidity: <span class="mono">${w.humidity_pct.toFixed(0)}%</span></div>
        <div>Rainfall: <span class="mono">${w.rainfall_mm.toFixed(1)}mm</span></div>
        <div>ET0: <span class="mono">${w.evapotranspiration_mm.toFixed(1)}mm</span></div>
      </div>
      ${result.risk ? `<div style="margin-top:8px">${riskChip(result.risk)}</div>` : ''}
      <div class="text-muted" style="font-size:10.5px;margin-top:8px">${escapeHtml(result.model_version || 'no model')}</div>
    </div>
  `;
}

export function mountCompare(root) {
  root.innerHTML = `
    <div class="view-header">
      <div>
        <h1>Compare</h1>
        <p>Live weather and irrigation recommendation, side by side across 2-6 districts.</p>
      </div>
    </div>

    <div class="card">
      <div class="card__header"><span class="card__title">${ICONS.compare}Districts &amp; inputs</span></div>
      <div class="flex flex-col gap-4">
        <div class="field">
          <label for="compare-add-district">Add a district (2-6)</label>
          <div class="flex gap-2">
            <select class="select" id="compare-add-district"><option>Loading…</option></select>
            <button type="button" class="btn btn--sm" id="compare-add-btn">${ICONS.plus}<span>Add</span></button>
          </div>
        </div>
        <div class="flex gap-2" id="compare-chips" style="flex-wrap:wrap"></div>

        <div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px">
          <div class="field">
            <label for="compare-crop">Crop</label>
            <select class="select" id="compare-crop"><option>Loading…</option></select>
          </div>
          <div class="field">
            <label for="compare-soil">Soil moisture</label>
            <div class="range-row">
              <input class="range" type="range" id="compare-soil" min="0" max="100" step="1" value="30" />
              <span class="range-row__value" id="compare-soil-value">30%</span>
            </div>
          </div>
          <div class="field">
            <label for="compare-canal">Canal flow</label>
            <div class="range-row">
              <input class="range" type="range" id="compare-canal" min="0" max="1000" step="10" value="300" />
              <span class="range-row__value" id="compare-canal-value">300 cusecs</span>
            </div>
          </div>
        </div>

        <button type="button" class="btn btn--primary" id="compare-submit-btn" disabled>${ICONS.compare}<span>Compare</span></button>
      </div>
    </div>

    <div id="compare-results"></div>
  `;

  const addSelect = root.querySelector('#compare-add-district');
  const addBtn = root.querySelector('#compare-add-btn');
  const chipsEl = root.querySelector('#compare-chips');
  const cropSelect = root.querySelector('#compare-crop');
  const soilInput = root.querySelector('#compare-soil');
  const soilValue = root.querySelector('#compare-soil-value');
  const canalInput = root.querySelector('#compare-canal');
  const canalValue = root.querySelector('#compare-canal-value');
  const submitBtn = root.querySelector('#compare-submit-btn');
  const resultsEl = root.querySelector('#compare-results');

  let selected = state.district ? [state.district] : [];
  const charts = [];

  function renderChips() {
    chipsEl.innerHTML = selected
      .map(
        (d, i) => `
          <span class="chip" style="border-color:transparent;background:${paletteColor(i)}22;color:${paletteColor(i)}">
            <span class="chip__dot" style="background:${paletteColor(i)}"></span>${escapeHtml(d)}
            <button type="button" data-remove="${escapeHtml(d)}" style="background:none;border:none;color:inherit;cursor:pointer;padding:0;margin-left:2px;line-height:1">✕</button>
          </span>
        `
      )
      .join('');
    chipsEl.querySelectorAll('[data-remove]').forEach((btn) => {
      btn.addEventListener('click', () => {
        selected = selected.filter((d) => d !== btn.dataset.remove);
        renderChips();
        updateSubmitState();
      });
    });
  }

  function updateSubmitState() {
    submitBtn.disabled = selected.length < MIN_DISTRICTS || selected.length > MAX_DISTRICTS;
  }

  async function loadMeta() {
    try {
      const meta = await getMeta();
      addSelect.innerHTML = Object.entries(meta.districts_by_province)
        .map(([province, districts]) => `<optgroup label="${escapeHtml(province)}">${districts.map((d) => `<option value="${escapeHtml(d)}">${escapeHtml(d)}</option>`).join('')}</optgroup>`)
        .join('');
      cropSelect.innerHTML = meta.crops.map((c) => `<option value="${escapeHtml(c)}">${escapeHtml(c)}</option>`).join('');
      renderChips();
      updateSubmitState();
    } catch (err) {
      toastError(`Could not load districts/crops: ${err.message}`);
    }
  }

  addBtn.addEventListener('click', () => {
    const district = addSelect.value;
    if (!district) return;
    if (selected.includes(district)) {
      toastError(`${district} is already added.`);
      return;
    }
    if (selected.length >= MAX_DISTRICTS) {
      toastError(`You can compare at most ${MAX_DISTRICTS} districts.`);
      return;
    }
    selected.push(district);
    renderChips();
    updateSubmitState();
  });

  soilInput.addEventListener('input', () => (soilValue.textContent = `${soilInput.value}%`));
  canalInput.addEventListener('input', () => (canalValue.textContent = `${canalInput.value} cusecs`));

  function destroyCharts() {
    charts.forEach((c) => c && c.destroy());
    charts.length = 0;
  }

  function metricChartCard(metric) {
    return `
      <div class="card">
        <div class="card__header"><span class="card__title">${escapeHtml(metric.label)}</span></div>
        <div style="height:200px"><canvas id="compare-chart-${metric.key}"></canvas></div>
      </div>
    `;
  }

  function renderResults(results) {
    destroyCharts();
    resultsEl.innerHTML = `
      <div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px" id="compare-cards"></div>
      <div class="grid grid--split" id="compare-charts" style="margin-top:20px"></div>
    `;
    const cardsEl = resultsEl.querySelector('#compare-cards');
    cardsEl.innerHTML = results.map((r, i) => resultCard(r, paletteColor(i))).join('');

    const chartsEl = resultsEl.querySelector('#compare-charts');
    chartsEl.innerHTML = METRICS.map((m) => metricChartCard(m)).join('');

    METRICS.forEach((metric) => {
      const canvas = resultsEl.querySelector(`#compare-chart-${metric.key}`);
      const chart = createChart(canvas, {
        data: {
          labels: results.map((r) => r.district),
          datasets: [
            {
              type: 'bar',
              data: results.map((r) => {
                const value = r.error ? null : metric.path(r);
                return typeof value === 'number' ? Number(value.toFixed(1)) : null;
              }),
              backgroundColor: results.map((_, i) => paletteColor(i)),
              borderRadius: 4,
              maxBarThickness: 40,
            },
          ],
        },
        options: {
          maintainAspectRatio: false,
          plugins: { legend: { display: false } },
          scales: { y: { ticks: { callback: (v) => tickLabel(v, metric.unit) } } },
        },
      });
      charts.push(chart);
    });
  }

  submitBtn.addEventListener('click', async () => {
    if (selected.length < MIN_DISTRICTS || selected.length > MAX_DISTRICTS) return;
    submitBtn.disabled = true;
    resultsEl.innerHTML = skeleton.block(320);
    try {
      const response = await compareDistricts({
        districts: selected,
        crop_type: cropSelect.value,
        soil_moisture_pct: Number(soilInput.value),
        canal_flow_cusecs: Number(canalInput.value),
      });
      renderResults(response.results);
    } catch (err) {
      resultsEl.innerHTML = '';
      resultsEl.appendChild(errorState({ message: err.message, onRetry: () => submitBtn.click() }));
    } finally {
      updateSubmitState();
    }
  });

  resultsEl.appendChild(
    emptyState({
      icon: ICONS.compare,
      title: 'Add 2-6 districts and click Compare',
      desc: 'See live weather and irrigation recommendation side by side.',
    })
  );

  loadMeta();

  return () => destroyCharts();
}
