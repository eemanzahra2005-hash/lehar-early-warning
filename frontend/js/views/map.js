/** Map view — interactive Pakistan district choropleth (Leaflet + vendored
 * OpenStreetMap raster tiles). Two modes, toggled with the tabs in the view
 * header:
 *   - "Irrigation" (default, Phase 5): district data from
 *     GET /api/v1/map/overview — live weather + a default-conditions
 *     recommendation, selectable metric.
 *   - "Flood Watch" (Phase 5.5): district data from GET /api/v1/flood/overview
 *     — the Flood Risk Index (see docs/FLOOD_RISK.md), colored
 *     yellow -> orange -> red by band, plus a ranked "Top 10 at-risk
 *     districts" panel and a per-district detail with discharge/rain charts.
 *     Heuristic research indicator, NOT an official flood warning.
 *
 * Polygons come from a static, committed geoBoundaries GeoJSON
 * (frontend/assets/geo/pakistan_districts.geojson, 126 ADM2 units); districts
 * outside our list render as gray "No data" — the choropleth still renders
 * even if the OSM tile layer fails to load, since the polygon layer is an
 * independent vector layer, not raster tiles. */

import { getMapOverview, getFloodOverview, getFloodDistrict } from '../api.js';
import { subscribe } from '../state.js';
import { navigate } from '../router.js';
import { setDistrict } from '../state.js';
import { skeleton, errorState, escapeHtml, toastError, wireExpandToggles } from '../ui.js';
import { ICONS } from '../icons.js';
import { shapeNameFor } from '../districtGeoMapping.js';
import { createChart, chartTokens, tickLabel, seriesColor } from '../charts.js';
import { riskExpandableMarkup } from '../riskUi.js';

const GEOJSON_URL = '/assets/geo/pakistan_districts.geojson';
// One-shot hint (frontend/js/views/dashboard.js's Flood Watch alert card
// "View on map" link sets this via sessionStorage, since the hash router
// has no query-param support) so landing on the Map page can jump straight
// into Flood Watch mode instead of always defaulting to Irrigation.
const MODE_HINT_KEY = 'lehar_map_mode_hint';
const PAKISTAN_CENTER = [30.3, 69.35];

const METRICS = {
  recommendation: {
    label: 'Irrigation recommendation',
    unit: 'mm',
    decimals: 1,
    get: (d) => (d && d.status === 'ok' ? d.recommendation_mm : null),
  },
  temperature: {
    label: 'Temperature',
    unit: '°C',
    decimals: 1,
    get: (d) => (d && d.status === 'ok' ? d.weather.temperature_c : null),
  },
  rainfall: {
    label: 'Rainfall',
    unit: 'mm',
    decimals: 1,
    get: (d) => (d && d.status === 'ok' ? d.weather.rainfall_mm : null),
  },
  et0: {
    label: 'ET0',
    unit: 'mm',
    decimals: 1,
    get: (d) => (d && d.status === 'ok' ? d.weather.evapotranspiration_mm : null),
  },
  humidity: {
    label: 'Humidity',
    unit: '%',
    decimals: 0,
    get: (d) => (d && d.status === 'ok' ? d.weather.humidity_pct : null),
  },
};

const FLOOD_BAND_CHIP = { LOW: 'chip--emerald', WATCH: 'chip--amber', HIGH: 'chip--red' };
const FLOOD_COMPONENT_LABELS = {
  discharge: 'River discharge anomaly',
  rain_3day: '3-day rain total',
  rain_intensity: 'Peak daily rain',
  exposure: 'Riverine exposure',
  monsoon: 'Monsoon season',
};

function readMapColors() {
  const css = getComputedStyle(document.documentElement);
  const v = (name) => css.getPropertyValue(name).trim();
  return {
    scale: [1, 2, 3, 4, 5].map((i) => v(`--seq-irrigation-${i}`)),
    flood: [1, 2, 3, 4, 5].map((i) => v(`--seq-flood-${i}`)),
    border: v('--border-strong') || '#333',
    hover: v('--text-primary') || '#fff',
    nodataFill: v('--nodata-fill') || '#e1e0d9',
    nodataBorder: v('--nodata-border') || '#c3c2b7',
  };
}

function computeScale(values) {
  const finite = values.filter((v) => typeof v === 'number' && Number.isFinite(v));
  if (!finite.length) return null;
  return { min: Math.min(...finite), max: Math.max(...finite) };
}

function bucketIndex(value, scale) {
  if (!scale || value === null || value === undefined) return null;
  const { min, max } = scale;
  if (max === min) return 2;
  const frac = (value - min) / (max - min);
  return Math.max(0, Math.min(4, Math.floor(frac * 5)));
}

function legendMarkup(metric, scale, colors) {
  const items = [];
  if (scale) {
    const step = (scale.max - scale.min) / 5;
    for (let i = 0; i < 5; i++) {
      const lo = scale.min + step * i;
      const hi = i === 4 ? scale.max : scale.min + step * (i + 1);
      items.push(
        `<div class="map-legend__item"><span class="map-legend__swatch" style="background:${colors.scale[i]}"></span>${lo.toFixed(metric.decimals)}–${hi.toFixed(metric.decimals)} ${escapeHtml(metric.unit)}</div>`
      );
    }
  }
  items.push(`<div class="map-legend__item"><span class="map-legend__swatch" style="background:${colors.nodataFill}"></span>No data</div>`);
  return items.join('');
}

function floodLegendMarkup(colors) {
  const rows = [
    ['LOW', 'score < 35', colors.flood[0]],
    ['WATCH', 'score 35–60', colors.flood[2]],
    ['HIGH', 'score > 60', colors.flood[4]],
  ];
  const items = rows.map(
    ([label, range, color]) =>
      `<div class="map-legend__item"><span class="map-legend__swatch" style="background:${color}"></span>${label} (${range})</div>`
  );
  items.push(`<div class="map-legend__item"><span class="map-legend__swatch" style="background:${colors.nodataFill}"></span>No data</div>`);
  return items.join('');
}

function floodColorFor(entry, colors) {
  if (!entry || entry.status !== 'ok') return null;
  if (entry.band === 'LOW') return colors.flood[0];
  if (entry.band === 'WATCH') return colors.flood[2];
  return colors.flood[4];
}

function statusChip(entry) {
  return entry.status === 'ok'
    ? `<span class="chip chip--emerald">${ICONS.checkCircle}Live</span>`
    : `<span class="chip chip--amber">${ICONS.alertTriangle}Weather unavailable</span>`;
}

function detailMarkup(entry, note) {
  const w = entry.weather;
  return `
    <div class="flex flex-col gap-4">
      <div class="flex items-center justify-between" style="flex-wrap:wrap;gap:8px">
        <div>
          <div style="font-size:16px;font-weight:600">${escapeHtml(entry.district)}</div>
          <div class="text-muted" style="font-size:12px">${escapeHtml(entry.province)}</div>
        </div>
        ${statusChip(entry)}
      </div>

      ${
        w
          ? `<div class="grid grid--kpi" style="gap:8px">
              <div class="kpi kpi--mini kpi--amber"><div class="kpi__head"><span>Temp</span></div><div class="kpi__value">${w.temperature_c.toFixed(1)}<small>°C</small></div></div>
              <div class="kpi kpi--mini kpi--sky"><div class="kpi__head"><span>Humidity</span></div><div class="kpi__value">${w.humidity_pct.toFixed(0)}<small>%</small></div></div>
              <div class="kpi kpi--mini kpi--sky"><div class="kpi__head"><span>Rainfall</span></div><div class="kpi__value">${w.rainfall_mm.toFixed(1)}<small>mm</small></div></div>
              <div class="kpi kpi--mini kpi--emerald"><div class="kpi__head"><span>ET0</span></div><div class="kpi__value">${w.evapotranspiration_mm.toFixed(1)}<small>mm</small></div></div>
            </div>`
          : ''
      }

      <div class="card card--pad-sm" style="background:var(--surface-2)">
        <div class="text-muted" style="font-size:11px;text-transform:uppercase;letter-spacing:0.04em;margin-bottom:4px">Irrigation recommendation</div>
        <div class="kpi__value" style="font-size:26px">${
          entry.recommendation_mm !== null ? entry.recommendation_mm.toFixed(1) : '—'
        }<small> mm/24h</small></div>
      </div>

      <div class="flex gap-2" style="align-items:center">
        <span class="map-risk-icon">${ICONS.shield}</span>${
          entry.risk
            ? riskExpandableMarkup(entry.risk, { id: `map-risk-breakdown-${entry.district.replace(/\s+/g, '-')}`, label: 'Irrigation stress' })
            : '<span class="text-muted" style="font-size:12px">Irrigation stress: n/a</span>'
        }
      </div>

      <p class="text-muted" style="font-size:11px;line-height:1.5">${escapeHtml(note)}</p>

      <button type="button" class="btn btn--primary btn--sm" id="map-open-predict">${ICONS.predict}<span>Open in Predict</span></button>
    </div>
  `;
}

function floodDetailShell(entry) {
  if (entry.status !== 'ok') {
    return `
      <div class="flex flex-col gap-4">
        <div class="flex items-center justify-between" style="flex-wrap:wrap;gap:8px">
          <div>
            <div style="font-size:16px;font-weight:600">${escapeHtml(entry.district)}</div>
            <div class="text-muted" style="font-size:12px">${escapeHtml(entry.province)}</div>
          </div>
          <span class="chip chip--amber">${ICONS.alertTriangle}Flood data unavailable</span>
        </div>
        <p class="text-muted" style="font-size:11.5px;line-height:1.5">${escapeHtml(entry.disclaimer || '')}</p>
      </div>
    `;
  }
  return `
    <div class="flex flex-col gap-4">
      <div class="flex items-center justify-between" style="flex-wrap:wrap;gap:8px">
        <div>
          <div style="font-size:16px;font-weight:600">${escapeHtml(entry.district)}</div>
          <div class="text-muted" style="font-size:12px">${escapeHtml(entry.province)}</div>
        </div>
        <span class="chip ${FLOOD_BAND_CHIP[entry.band] || ''}">${entry.band}</span>
      </div>

      <div class="card card--pad-sm" style="background:var(--surface-2)">
        <div class="text-muted" style="font-size:11px;text-transform:uppercase;letter-spacing:0.04em;margin-bottom:4px">Flood risk score</div>
        <div class="kpi__value" style="font-size:26px">${entry.score.toFixed(1)}<small> / 100</small></div>
        <div class="text-muted" style="font-size:11px;margin-top:2px">Discharge anomaly ${entry.discharge.anomaly_ratio.toFixed(2)}x baseline</div>
      </div>

      <div>
        <div class="text-muted" style="font-size:11px;text-transform:uppercase;letter-spacing:0.04em;margin-bottom:6px">River discharge — baseline vs forecast</div>
        <div style="height:150px"><canvas id="flood-discharge-chart"></canvas></div>
      </div>

      <div>
        <div class="text-muted" style="font-size:11px;text-transform:uppercase;letter-spacing:0.04em;margin-bottom:6px">Rain forecast (next 3 days)</div>
        <div style="height:110px"><canvas id="flood-rain-chart"></canvas></div>
      </div>

      <div>
        <div class="text-muted" style="font-size:11px;text-transform:uppercase;letter-spacing:0.04em;margin-bottom:6px">Risk component breakdown</div>
        <div style="height:150px"><canvas id="flood-components-chart"></canvas></div>
      </div>

      <p class="text-muted" style="font-size:11px;line-height:1.5">${escapeHtml(entry.disclaimer || '')}</p>

      <button type="button" class="btn btn--primary btn--sm" id="map-open-predict">${ICONS.predict}<span>Open in Predict</span></button>
    </div>
  `;
}

function top10Markup(floodOverview) {
  const ranked = floodOverview.districts
    .filter((d) => d.status === 'ok')
    .sort((a, b) => b.score - a.score)
    .slice(0, 10);
  if (!ranked.length) {
    return '<p class="text-muted" style="font-size:12.5px">No flood data available right now.</p>';
  }
  const rows = ranked
    .map(
      (d, i) => `
        <button type="button" class="pred-row" data-flood-district="${escapeHtml(d.district)}">
          <div class="pred-row__main">
            <span class="mono text-muted" style="width:18px;display:inline-block">${i + 1}</span>
            <span class="pred-row__district">${escapeHtml(d.district)}</span>
            <span class="chip">${escapeHtml(d.province)}</span>
          </div>
          <div class="pred-row__meta">
            <span class="chip ${FLOOD_BAND_CHIP[d.band] || ''}">${d.band}</span>
            <span class="mono pred-row__value">${d.score.toFixed(1)}</span>
          </div>
        </button>
      `
    )
    .join('');
  return `<div class="pred-list">${rows}</div>`;
}

export function mountMap(root) {
  root.innerHTML = `
    <div class="view-header">
      <div>
        <h1>Map</h1>
        <p id="map-subtitle">District-level irrigation recommendation and live weather across all districts.</p>
      </div>
      <div class="tabs" id="map-mode-tabs">
        <button type="button" class="tabs__btn is-active" data-mode="irrigation">Irrigation</button>
        <button type="button" class="tabs__btn" data-mode="flood">Flood Watch</button>
      </div>
    </div>

    <div class="grid grid--2col">
      <div class="card">
        <div class="card__header">
          <span class="card__title">${ICONS.map}Pakistan Districts</span>
          <select class="select" id="map-metric-select" style="max-width:230px">
            <option value="recommendation">Irrigation recommendation</option>
            <option value="temperature">Temperature</option>
            <option value="rainfall">Rainfall</option>
            <option value="et0">ET0</option>
            <option value="humidity">Humidity</option>
          </select>
          <span class="chip" id="map-flood-label" hidden>Flood Risk Score</span>
        </div>
        <p class="text-muted" id="map-note" style="font-size:11.5px;margin-bottom:10px"></p>
        <div id="map-body">${skeleton.block(560)}</div>
        <div class="map-legend" id="map-legend" style="margin-top:12px"></div>
      </div>

      <div class="card">
        <div class="card__header"><span class="card__title" id="map-detail-title">${ICONS.info || ''}District Details</span></div>
        <div id="map-detail" class="state-block">
          ${ICONS.map}
          <div class="state-block__title">No district selected</div>
          <div class="state-block__desc">Click a district on the map to see its full details here.</div>
        </div>
      </div>
    </div>

    <div class="card" id="flood-top10-card" hidden style="margin-top:16px">
      <div class="card__header"><span class="card__title">${ICONS.alertTriangle || ''}Top 10 At-Risk Districts</span></div>
      <div id="flood-top10-body">${skeleton.block(200)}</div>
    </div>
  `;

  const bodyEl = root.querySelector('#map-body');
  const legendEl = root.querySelector('#map-legend');
  const detailEl = root.querySelector('#map-detail');
  const detailTitleEl = root.querySelector('#map-detail-title');
  const noteEl = root.querySelector('#map-note');
  const subtitleEl = root.querySelector('#map-subtitle');
  const metricSelect = root.querySelector('#map-metric-select');
  const floodLabelEl = root.querySelector('#map-flood-label');
  const modeTabsEl = root.querySelector('#map-mode-tabs');
  const top10CardEl = root.querySelector('#flood-top10-card');
  const top10BodyEl = root.querySelector('#flood-top10-body');

  let map = null;
  let geoLayer = null;
  let layerByDistrict = new Map();
  let overview = null;
  let floodOverview = null;
  let byDistrict = new Map();
  let floodByDistrict = new Map();
  let shapeToDistrict = new Map();
  let currentMetric = 'recommendation';
  let currentMode = 'irrigation';
  let overviewNote = '';
  let floodLoading = false;

  let dischargeChart = null;
  let rainChart = null;
  let componentsChart = null;

  function destroyFloodCharts() {
    [dischargeChart, rainChart, componentsChart].forEach((c) => c && c.destroy());
    dischargeChart = rainChart = componentsChart = null;
  }

  function styleForFeature(feature) {
    const colors = readMapColors();
    const districtName = shapeToDistrict.get(feature.properties.shapeName);

    if (currentMode === 'flood') {
      const entry = districtName ? floodByDistrict.get(districtName) : null;
      const color = floodColorFor(entry, colors);
      return {
        fillColor: color || colors.nodataFill,
        fillOpacity: color ? 0.82 : 0.35,
        color: color ? colors.border : colors.nodataBorder,
        weight: 1,
      };
    }

    const metric = METRICS[currentMetric];
    const entry = districtName ? byDistrict.get(districtName) : null;
    const values = [...byDistrict.values()].map(metric.get);
    const scale = computeScale(values);
    const value = entry ? metric.get(entry) : null;
    const idx = bucketIndex(value, scale);
    return {
      fillColor: idx === null ? colors.nodataFill : colors.scale[idx],
      fillOpacity: idx === null ? 0.35 : 0.82,
      color: idx === null ? colors.nodataBorder : colors.border,
      weight: 1,
    };
  }

  function tooltipContentFor(districtName) {
    if (currentMode === 'flood') {
      const entry = districtName ? floodByDistrict.get(districtName) : null;
      const body =
        entry && entry.status === 'ok'
          ? `${entry.score.toFixed(1)} / 100 (${entry.band})`
          : 'No flood data for this district';
      return `<span class="map-district-tooltip">${escapeHtml(districtName || '')}<small>${body}</small></span>`;
    }
    const entry = districtName ? byDistrict.get(districtName) : null;
    const metric = METRICS[currentMetric];
    const value = entry ? metric.get(entry) : null;
    return `<span class="map-district-tooltip">${escapeHtml(districtName || '')}<small>${
      value !== null && value !== undefined ? `${value.toFixed(metric.decimals)} ${metric.unit}` : 'No data for this metric'
    }</small></span>`;
  }

  function renderLegend() {
    const colors = readMapColors();
    if (currentMode === 'flood') {
      legendEl.innerHTML = floodLegendMarkup(colors);
      return;
    }
    const metric = METRICS[currentMetric];
    const values = [...byDistrict.values()].map(metric.get);
    const scale = computeScale(values);
    legendEl.innerHTML = legendMarkup(metric, scale, colors);
  }

  function selectDistrictIrrigation(entry) {
    detailTitleEl.innerHTML = `${ICONS.info || ''}District Details`;
    detailEl.className = '';
    detailEl.innerHTML = detailMarkup(entry, overviewNote);
    wireExpandToggles(detailEl);
    detailEl.querySelector('#map-open-predict')?.addEventListener('click', () => {
      setDistrict(entry.district);
      navigate('/predict');
    });
  }

  async function selectDistrictFlood(districtName) {
    detailTitleEl.innerHTML = `${ICONS.alertTriangle || ''}Flood Detail`;
    detailEl.className = '';
    detailEl.innerHTML = skeleton.block(360);
    destroyFloodCharts();
    try {
      const entry = await getFloodDistrict(districtName);
      detailEl.innerHTML = floodDetailShell(entry);
      detailEl.querySelector('#map-open-predict')?.addEventListener('click', () => {
        setDistrict(districtName);
        navigate('/predict');
      });
      if (entry.status === 'ok') {
        const t = chartTokens();
        const dCanvas = detailEl.querySelector('#flood-discharge-chart');
        dischargeChart = createChart(dCanvas, {
          data: {
            labels: entry.discharge.dates.map((d) => d.slice(5)),
            datasets: [
              {
                type: 'line',
                label: 'Discharge (m³/s)',
                data: entry.discharge.values,
                borderColor: seriesColor('recommendation'),
                backgroundColor: seriesColor('recommendation'),
                borderWidth: 2,
                pointRadius: 0,
                tension: 0.25,
              },
              {
                type: 'line',
                label: '30-day baseline (median)',
                data: entry.discharge.values.map(() => entry.discharge.baseline_median),
                borderColor: t.text,
                borderDash: [4, 4],
                borderWidth: 1.5,
                pointRadius: 0,
              },
            ],
          },
          options: {
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            scales: { x: { ticks: { maxTicksLimit: 6 } }, y: { ticks: { callback: (v) => tickLabel(v, '') } } },
            plugins: { legend: { display: true, position: 'bottom', labels: { boxWidth: 10, font: { size: 10 } } } },
          },
        });

        const rCanvas = detailEl.querySelector('#flood-rain-chart');
        rainChart = createChart(rCanvas, {
          data: {
            labels: entry.rain.dates.map((d) => d.slice(5)),
            datasets: [
              {
                type: 'bar',
                label: 'Rain (mm)',
                data: entry.rain.values_mm,
                backgroundColor: seriesColor('rainfall'),
                borderRadius: 4,
                maxBarThickness: 28,
              },
            ],
          },
          options: {
            maintainAspectRatio: false,
            scales: { y: { ticks: { callback: (v) => tickLabel(v, 'mm') } } },
            plugins: { legend: { display: false } },
          },
        });

        const cCanvas = detailEl.querySelector('#flood-components-chart');
        const compKeys = Object.keys(entry.components);
        componentsChart = createChart(cCanvas, {
          data: {
            labels: compKeys.map((k) => FLOOD_COMPONENT_LABELS[k] || k),
            datasets: [
              {
                type: 'bar',
                label: 'Component (0–1)',
                data: compKeys.map((k) => entry.components[k]),
                backgroundColor: seriesColor('temperature'),
                borderRadius: 4,
                maxBarThickness: 22,
              },
            ],
          },
          options: {
            indexAxis: 'y',
            maintainAspectRatio: false,
            scales: { x: { min: 0, max: 1 } },
            plugins: { legend: { display: false } },
          },
        });
      }
    } catch (err) {
      detailEl.innerHTML = '';
      detailEl.appendChild(errorState({ message: err.message, onRetry: () => selectDistrictFlood(districtName) }));
    }
  }

  function handleDistrictClick(districtName) {
    if (!districtName) return;
    if (currentMode === 'flood') {
      selectDistrictFlood(districtName);
    } else {
      const entry = byDistrict.get(districtName);
      if (entry) selectDistrictIrrigation(entry);
    }
  }

  function wireFeatureInteractions(feature, layer) {
    const districtName = shapeToDistrict.get(feature.properties.shapeName);
    if (!districtName) return;
    layerByDistrict.set(districtName, layer);

    layer.bindTooltip(tooltipContentFor(districtName), { sticky: true });

    layer.on('mouseover', () => {
      const colors = readMapColors();
      layer.setStyle({ weight: 2.5, color: colors.hover });
      layer.bringToFront();
    });
    layer.on('mouseout', () => geoLayer.resetStyle(layer));
    layer.on('click', () => handleDistrictClick(districtName));
  }

  function restyleAll() {
    if (!geoLayer) return;
    geoLayer.eachLayer((layer) => {
      const style = styleForFeature(layer.feature);
      layer.setStyle(style);
      const districtName = shapeToDistrict.get(layer.feature.properties.shapeName);
      if (districtName) layer.setTooltipContent(tooltipContentFor(districtName));
    });
    renderLegend();
  }

  function renderTop10() {
    if (!floodOverview) return;
    top10BodyEl.innerHTML = top10Markup(floodOverview);
    top10BodyEl.querySelectorAll('[data-flood-district]').forEach((btn) => {
      btn.addEventListener('click', () => {
        const name = btn.dataset.floodDistrict;
        selectDistrictFlood(name);
        const layer = layerByDistrict.get(name);
        if (layer && map) {
          map.fitBounds(layer.getBounds(), { maxZoom: 8, padding: [16, 16] });
          layer.setStyle({ weight: 2.5 });
        }
      });
    });
  }

  async function ensureFloodOverview() {
    if (floodOverview || floodLoading) return;
    floodLoading = true;
    top10BodyEl.innerHTML = skeleton.block(200);
    try {
      floodOverview = await getFloodOverview();
      floodByDistrict = new Map(floodOverview.districts.map((d) => [d.district, d]));
      noteEl.textContent = floodOverview.disclaimer;
      restyleAll();
      renderTop10();
    } catch (err) {
      top10BodyEl.innerHTML = '';
      top10BodyEl.appendChild(errorState({ message: err.message, onRetry: ensureFloodOverview }));
      toastError(`Couldn't load flood data: ${err.message}`);
    } finally {
      floodLoading = false;
    }
  }

  function applyModeUI() {
    modeTabsEl.querySelectorAll('.tabs__btn').forEach((btn) => {
      btn.classList.toggle('is-active', btn.dataset.mode === currentMode);
    });
    const isFlood = currentMode === 'flood';
    metricSelect.hidden = isFlood;
    floodLabelEl.hidden = !isFlood;
    top10CardEl.hidden = !isFlood;
    subtitleEl.textContent = isFlood
      ? 'Heuristic Flood Risk Index from real GloFAS river-discharge + rainfall data — not an official flood warning.'
      : 'District-level irrigation recommendation and live weather across all districts.';
    noteEl.textContent = isFlood ? floodOverview?.disclaimer || '' : overviewNote;
    detailTitleEl.innerHTML = `${isFlood ? ICONS.alertTriangle || '' : ICONS.info || ''}${isFlood ? 'Flood Detail' : 'District Details'}`;
    detailEl.className = 'state-block';
    detailEl.innerHTML = `
      ${isFlood ? ICONS.alertTriangle || ICONS.map : ICONS.map}
      <div class="state-block__title">No district selected</div>
      <div class="state-block__desc">Click a district on the map${isFlood ? ' or the ranked list below' : ''} to see its full details here.</div>
    `;
  }

  async function setMode(newMode) {
    if (newMode === currentMode) return;
    currentMode = newMode;
    applyModeUI();
    if (currentMode === 'flood') {
      await ensureFloodOverview();
    }
    restyleAll();
  }

  async function initMap() {
    bodyEl.innerHTML = skeleton.block(560);
    try {
      const [overviewData, geoResponse] = await Promise.all([getMapOverview(), fetch(GEOJSON_URL)]);
      if (!geoResponse.ok) throw new Error(`Failed to load district boundaries (${geoResponse.status})`);
      const geojson = await geoResponse.json();

      overview = overviewData;
      overviewNote = overview.note;
      noteEl.textContent = overview.note;
      byDistrict = new Map(overview.districts.map((d) => [d.district, d]));
      shapeToDistrict = new Map(overview.districts.map((d) => [shapeNameFor(d.district), d.district]));

      const geoShapeNames = new Set(geojson.features.map((f) => f.properties.shapeName));
      let unmatchedCount = 0;
      for (const [shapeName, districtName] of shapeToDistrict) {
        if (!geoShapeNames.has(shapeName)) {
          unmatchedCount += 1;
          console.warn(
            `[map] No polygon found for district "${districtName}" (looked for shapeName "${shapeName}") — it will not appear on the choropleth.`
          );
        }
      }
      if (unmatchedCount > 0) {
        toastError(`${unmatchedCount} district${unmatchedCount === 1 ? '' : 's'} could not be matched to a map polygon — see console.`);
      }

      bodyEl.innerHTML = '<div class="map-container"><div id="map-canvas" style="height:100%;width:100%"></div></div>';
      const canvas = bodyEl.querySelector('#map-canvas');

      map = window.L.map(canvas, { scrollWheelZoom: true }).setView(PAKISTAN_CENTER, 5);

      window.L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: 12,
        minZoom: 4,
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
      }).addTo(map);

      geoLayer = window.L.geoJSON(geojson, {
        style: (feature) => styleForFeature(feature),
        onEachFeature: (feature, layer) => wireFeatureInteractions(feature, layer),
      }).addTo(map);

      // Fit to the actual polygon bounds rather than a fixed zoom, so
      // Pakistan fills the frame regardless of container aspect ratio.
      const bounds = geoLayer.getBounds();
      if (bounds.isValid()) map.fitBounds(bounds, { padding: [8, 8] });

      renderLegend();
    } catch (err) {
      bodyEl.innerHTML = '';
      bodyEl.appendChild(errorState({ message: err.message, onRetry: initMap }));
      legendEl.innerHTML = '';
    }
  }

  metricSelect.addEventListener('change', () => {
    currentMetric = metricSelect.value;
    restyleAll();
  });

  modeTabsEl.querySelectorAll('.tabs__btn').forEach((btn) => {
    btn.addEventListener('click', () => setMode(btn.dataset.mode));
  });

  const unsubscribe = subscribe(() => {
    if (map) restyleAll();
  });

  (async () => {
    await initMap();
    const hint = sessionStorage.getItem(MODE_HINT_KEY);
    if (hint === 'flood') {
      sessionStorage.removeItem(MODE_HINT_KEY);
      if (map) await setMode('flood');
    }
  })();

  return () => {
    unsubscribe();
    destroyFloodCharts();
    if (map) {
      map.remove();
      map = null;
    }
  };
}
