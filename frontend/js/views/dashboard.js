/** Dashboard view — smart status line, KPI tiles with sparklines/deltas,
 * latest recommendation gauge, 7-day forecast, and recent predictions. All
 * data is real, fetched per the currently selected district
 * (frontend/js/state.js), and kept live with a 5-minute auto-refresh. */

import { getWeather, getForecast, getHistory, getFloodOverview } from '../api.js';
import { state, subscribe, isLoggedIn } from '../state.js';
import { skeleton, errorState, emptyState, escapeHtml, relativeTime, openModal, ILLUSTRATIONS, toastError, wireExpandToggles } from '../ui.js';
import { ICONS } from '../icons.js';
import { navigate } from '../router.js';
import { gaugeMarkup, animateGaugeNeedle } from '../gauge.js';
import { describeFactors, buildContextLine } from '../rules.js';
import { createChart, tickLabel, seriesColor } from '../charts.js';
import { sparklineSvg } from '../sparkline.js';
import { countUp } from '../countup.js';
import { recordAndDiff } from '../weatherTrend.js';
import { explainPanelMarkup, confidenceLineMarkup } from '../explainUi.js';
import { riskExpandableMarkup, RISK_BAND_TONE } from '../riskUi.js';
import { computeRiskComponents } from '../riskFormula.js';
import { getLastPredictionFor } from '../predictionCache.js';

const AUTO_REFRESH_MS = 5 * 60 * 1000;
const TICK_MS = 15 * 1000;

const TONE_VAR = {
  amber: 'var(--amber)',
  sky: 'var(--sky)',
  emerald: 'var(--emerald)',
  red: 'var(--red)',
  muted: 'var(--text-muted)',
};

// --- KPI tiles -------------------------------------------------------------

function deltaBadge(delta) {
  if (!delta || !Number.isFinite(delta.value)) return '';
  const abs = Math.abs(delta.value);
  const unit = delta.unit || '';
  const title = escapeHtml(delta.label || '');
  if (abs < 0.05) {
    return `<span class="kpi__delta kpi__delta--flat" title="${title}">± 0${unit}</span>`;
  }
  const tone = delta.value > 0 ? 'amber' : 'sky';
  const arrow = delta.value > 0 ? '↑' : '↓';
  const sign = delta.value > 0 ? '+' : '−';
  return `<span class="kpi__delta kpi__delta--${tone}" title="${title}">${sign}${abs.toFixed(1)}${unit} ${arrow}</span>`;
}

function kpiTile({ tone, icon, label, value, decimals = 1, unit, delta, sparkValues, sub, action }) {
  const isNumeric = typeof value === 'number' && Number.isFinite(value);
  const valueHtml = isNumeric
    ? `<span class="kpi__num" data-countup data-target="${value}" data-decimals="${decimals}">${(0).toFixed(decimals)}</span>`
    : `<span class="kpi__num">${escapeHtml(String(value))}</span>`;
  const validSpark = (sparkValues || []).filter((v) => typeof v === 'number' && Number.isFinite(v));
  const sparkHtml =
    validSpark.length >= 2
      ? `<div class="kpi__spark">${sparklineSvg(sparkValues, { color: TONE_VAR[tone] || TONE_VAR.muted })}</div>`
      : '';

  return `
    <div class="kpi kpi--${tone}">
      <div class="kpi__head"><span>${label}</span>${icon}</div>
      <div class="kpi__value-row">
        <div class="kpi__value">${valueHtml}${unit ? `<small>${unit}</small>` : ''}</div>
        ${deltaBadge(delta)}
      </div>
      ${sparkHtml}
      <div class="kpi__sub">${action ? `<a href="#" data-action="${action.id}">${action.label}</a>` : sub || ''}</div>
    </div>
  `;
}

function renderKpis({ district, weather, forecast, history }) {
  const trend = recordAndDiff(district, {
    temperature_c: weather.temperature_c,
    humidity_pct: weather.humidity_pct,
    rainfall_mm: weather.rainfall_mm,
    evapotranspiration_mm: weather.evapotranspiration_mm,
  });
  const trendLabel = trend ? (trend.daysAgo === 1 ? 'vs yesterday' : `vs ${trend.daysAgo} days ago`) : null;

  const days = (forecast && forecast.days) || [];
  const spark = {
    temp: days.map((d) => d.temperature_c),
    humidity: days.map((d) => d.humidity_pct),
    rain: days.map((d) => d.rainfall_mm),
    et0: days.map((d) => d.evapotranspiration_mm),
  };

  const latestRec = history && history.length ? history[0] : null;
  const prevRec = history && history.length > 1 ? history[1] : null;

  const tiles = [
    kpiTile({
      tone: 'amber',
      icon: ICONS.thermometer,
      label: 'Temperature',
      value: weather.temperature_c,
      decimals: 1,
      unit: '°C',
      delta: trend ? { value: weather.temperature_c - trend.temperature_c, unit: '°C', label: trendLabel } : null,
      sparkValues: spark.temp,
      sub: 'Live · Open-Meteo',
    }),
    kpiTile({
      tone: 'sky',
      icon: ICONS.percent,
      label: 'Humidity',
      value: weather.humidity_pct,
      decimals: 0,
      unit: '%',
      delta: trend ? { value: weather.humidity_pct - trend.humidity_pct, unit: '%', label: trendLabel } : null,
      sparkValues: spark.humidity,
      sub: 'Live · Open-Meteo',
    }),
    kpiTile({
      tone: 'sky',
      icon: ICONS.forecast,
      label: 'Rainfall today',
      value: weather.rainfall_mm,
      decimals: 1,
      unit: 'mm',
      delta: trend ? { value: weather.rainfall_mm - trend.rainfall_mm, unit: 'mm', label: trendLabel } : null,
      sparkValues: spark.rain,
      sub: 'Live · Open-Meteo',
    }),
    kpiTile({
      tone: 'emerald',
      icon: ICONS.wind,
      label: 'ET0',
      value: weather.evapotranspiration_mm,
      decimals: 1,
      unit: 'mm',
      delta: trend
        ? { value: weather.evapotranspiration_mm - trend.evapotranspiration_mm, unit: 'mm', label: trendLabel }
        : null,
      sparkValues: spark.et0,
      sub: 'Evapotranspiration',
    }),
    latestRec
      ? kpiTile({
          tone: 'emerald',
          icon: ICONS.predict,
          label: 'Latest Recommendation',
          value: latestRec.recommendation_mm,
          decimals: 1,
          unit: 'mm/24h',
          delta: prevRec
            ? { value: latestRec.recommendation_mm - prevRec.recommendation_mm, unit: 'mm', label: 'vs previous prediction' }
            : null,
          sparkValues: [...history].reverse().map((h) => h.recommendation_mm),
          sub: relativeTime(latestRec.created_at),
        })
      : kpiTile({
          tone: 'muted',
          icon: ICONS.predict,
          label: 'Latest Recommendation',
          value: '—',
          action: { id: 'go-predict', label: 'Run a prediction →' },
        }),
    riskKpiMarkup(latestRec),
  ];
  return tiles.join('');
}

// --- Farm Risk KPI tile (Phase 6) -------------------------------------------
// Irrigation-stress (dryness) score — distinct from the Flood Watch alert
// card above, which is a separate index (see docs/RISK_SCORE.md vs
// docs/FLOOD_RISK.md). Score/band always come from the real persisted
// risk_score/risk_band on the latest prediction; the click-to-expand
// component breakdown is computed client-side from that same row's real
// stored inputs (see riskFormula.js's docstring for why that's still real
// data, not a guess) since per-component detail isn't persisted per row.

function riskKpiMarkup(latestRec) {
  if (!latestRec || latestRec.risk_score === null || latestRec.risk_score === undefined) {
    return `
      <div class="kpi kpi--muted">
        <div class="kpi__head"><span>Farm Risk</span>${ICONS.shield}</div>
        <div class="kpi__value">—</div>
        <div class="kpi__sub">Run a prediction to see irrigation stress</div>
      </div>
    `;
  }
  const tone = RISK_BAND_TONE[latestRec.risk_band] || 'muted';
  const pseudoRisk = {
    score: latestRec.risk_score,
    band: latestRec.risk_band,
    components: computeRiskComponents(latestRec),
  };
  return `
    <div class="kpi kpi--${tone}">
      <div class="kpi__head"><span>Farm Risk</span>${ICONS.shield}</div>
      <div class="kpi__value-row">
        <div class="kpi__value">${escapeHtml(latestRec.risk_band)}<small> · ${latestRec.risk_score.toFixed(0)}/100</small></div>
      </div>
      <div class="kpi__sub">${riskExpandableMarkup(pseudoRisk, { id: 'dash-risk-breakdown', label: 'Irrigation stress' })}</div>
    </div>
  `;
}

// --- Recommendation card -----------------------------------------------------

function sourceChip(source) {
  return source === 'model_prediction'
    ? `<span class="chip chip--emerald">${ICONS.checkCircle}Model prediction</span>`
    : `<span class="chip chip--amber">${ICONS.alertTriangle}Fallback rule-based</span>`;
}

function renderRecommendationBody(rec) {
  const factors = describeFactors({
    soil_moisture_pct: rec.soil_moisture_pct,
    evapotranspiration_mm: rec.evapotranspiration_mm,
    rainfall_mm: rec.rainfall_mm,
    temperature_c: rec.temperature_c,
  });

  // GET /api/v1/history only persists risk_score/risk_band (not the full
  // SHAP explanation/confidence — see app/db.py) — the component breakdown
  // is recomputed client-side from this row's own real stored inputs (see
  // riskFormula.js). explanation/confidence only render when this exact
  // prediction was just run this session (see predictionCache.js) —
  // otherwise we honestly say so rather than showing nothing at all.
  const hasRisk = rec.risk_score !== null && rec.risk_score !== undefined;
  const pseudoRisk = hasRisk ? { score: rec.risk_score, band: rec.risk_band, components: computeRiskComponents(rec) } : null;
  const full = getLastPredictionFor(rec);

  return `
    <div class="rec-card">
      <div class="gauge">
        ${gaugeMarkup(rec.recommendation_mm, { max: 60, size: 240 })}
        <div class="gauge__value"><span id="rec-gauge-num">0.0</span><small> mm/24h</small></div>
        ${full && full.confidence ? `<div class="text-muted" style="font-size:11.5px;margin-top:4px;text-align:center">${confidenceLineMarkup(rec.recommendation_mm, full.confidence)}</div>` : ''}
      </div>
      <div class="gauge__chips">
        ${sourceChip(rec.source)}
        <span class="chip">${escapeHtml(rec.model_version || 'no model')}</span>
        <span class="chip">${escapeHtml(rec.district)} · ${escapeHtml(rec.crop_type)}</span>
        ${hasRisk ? riskExpandableMarkup(pseudoRisk, { id: 'dash-rec-risk-breakdown', label: 'Irrigation stress' }) : ''}
      </div>
      <div class="rec-card__footer">
        <p class="text-secondary" style="font-size:13px;line-height:1.5">${escapeHtml(factors)}</p>
        <p class="text-muted" style="font-size:11.5px">Rule-based summary of real inputs — not model-generated text.</p>
      </div>
      <div class="rec-card__why">
        <div class="card__title" style="margin-bottom:8px;font-size:12px">${ICONS.explainability}Why this prediction?</div>
        ${
          full
            ? explainPanelMarkup(full.explanation)
            : '<div class="text-muted" style="font-size:11.5px">Full breakdown is shown right after you run a prediction this session — open Predict to see it.</div>'
        }
      </div>
    </div>
  `;
}

// --- Recent predictions list -------------------------------------------------

function predRowSummary(h) {
  return `Soil ${h.soil_moisture_pct}% · Canal ${h.canal_flow_cusecs} cusecs · ${h.temperature_c.toFixed(1)}°C · ${h.humidity_pct.toFixed(0)}% humidity · ${h.rainfall_mm.toFixed(1)}mm rain · ET0 ${h.evapotranspiration_mm.toFixed(1)}mm`;
}

function renderRecentList(history) {
  return `
    <div class="pred-list">
      ${history
        .map(
          (h) => `
            <button type="button" class="pred-row" data-id="${h.id}" title="${escapeHtml(predRowSummary(h))}">
              <div class="pred-row__main">
                ${
                  h.source === 'model_prediction'
                    ? '<span class="chip chip--emerald">model</span>'
                    : '<span class="chip chip--amber">fallback</span>'
                }
                <span class="pred-row__district">${escapeHtml(h.district)}</span>
                <span class="chip">${escapeHtml(h.crop_type)}</span>
              </div>
              <div class="pred-row__meta">
                <span class="mono pred-row__value">${h.recommendation_mm.toFixed(1)}<small>mm</small></span>
                <span class="pred-row__time">${relativeTime(h.created_at)}</span>
              </div>
            </button>
          `
        )
        .join('')}
    </div>
  `;
}

function openPredictionModal(h) {
  const body = document.createElement('div');
  body.innerHTML = `
    <div class="modal__header"><h2>Prediction detail</h2></div>
    <div class="modal__body">
      <div class="flex gap-2" style="flex-wrap:wrap">
        ${sourceChip(h.source)}
        <span class="chip">${escapeHtml(h.model_version || 'no model')}</span>
        <span class="chip">${escapeHtml(h.district)} · ${escapeHtml(h.crop_type)}</span>
      </div>
      <div class="gauge">
        ${gaugeMarkup(h.recommendation_mm, { max: 60, size: 180 })}
        <div class="gauge__value">${h.recommendation_mm.toFixed(1)}<small> mm/24h</small></div>
      </div>
      <div class="table-wrap">
        <table class="table">
          <tbody>
            <tr><td>Soil moisture</td><td class="mono">${h.soil_moisture_pct}%</td></tr>
            <tr><td>Canal flow</td><td class="mono">${h.canal_flow_cusecs} cusecs</td></tr>
            <tr><td>Temperature</td><td class="mono">${h.temperature_c.toFixed(1)}°C</td></tr>
            <tr><td>Humidity</td><td class="mono">${h.humidity_pct.toFixed(0)}%</td></tr>
            <tr><td>Rainfall</td><td class="mono">${h.rainfall_mm.toFixed(1)}mm</td></tr>
            <tr><td>ET0</td><td class="mono">${h.evapotranspiration_mm.toFixed(1)}mm</td></tr>
            <tr><td>When</td><td class="text-muted">${new Date(h.created_at).toLocaleString()}</td></tr>
          </tbody>
        </table>
      </div>
    </div>
  `;
  const svg = body.querySelector('.gauge__svg');
  animateGaugeNeedle(svg, h.recommendation_mm, { max: 60 });
  openModal(body, { maxWidth: '420px' });
}

// --- Flood Watch alert card (Phase 5.5) -------------------------------------
// Nationwide, not tied to the selected district — only rendered when at
// least one district's current Flood Risk Index band is HIGH (see
// docs/FLOOD_RISK.md); hidden entirely otherwise so this is never a fake or
// stale-looking alert.

function floodAlertMarkup(highDistricts) {
  const names = highDistricts.map((d) => escapeHtml(d.district)).join(', ');
  return `
    <div class="card card--pad-sm" style="border-color:var(--red);background:var(--red-soft);margin-bottom:16px">
      <div class="flex items-center justify-between" style="flex-wrap:wrap;gap:10px">
        <div class="flex gap-2" style="align-items:flex-start">
          <span class="flood-alert__icon">${ICONS.alertTriangle}</span>
          <div>
            <div style="font-weight:600;font-size:13.5px">Flood Watch: ${highDistricts.length} district${highDistricts.length === 1 ? '' : 's'} at HIGH risk</div>
            <div class="text-muted" style="font-size:12px;margin-top:2px">${names} — heuristic indicator, not an official flood warning. Consult NDMA/PMD for real alerts.</div>
          </div>
        </div>
        <button type="button" class="btn btn--sm" id="flood-alert-view-map">${ICONS.map}<span>View on map</span></button>
      </div>
    </div>
  `;
}

async function loadFloodAlert(root) {
  const slot = root.querySelector('#flood-alert-slot');
  if (!slot) return;
  try {
    const overview = await getFloodOverview();
    const high = overview.districts.filter((d) => d.status === 'ok' && d.band === 'HIGH');
    if (!high.length) {
      slot.innerHTML = '';
      return;
    }
    slot.innerHTML = floodAlertMarkup(high);
    slot.querySelector('#flood-alert-view-map')?.addEventListener('click', () => {
      sessionStorage.setItem('lehar_map_mode_hint', 'flood');
      navigate('/map');
    });
  } catch {
    // Never fail the dashboard over the flood card — just leave it hidden.
    slot.innerHTML = '';
  }
}

// --- Mount ------------------------------------------------------------------

export function mountDashboard(root) {
  root.innerHTML = `
    <div class="view-header view-header--dashboard">
      <div>
        <div class="eyebrow">Dashboard</div>
        <p class="context-line" id="context-line">Select a district in the topbar to see live conditions.</p>
        <div class="quick-actions">
          <button type="button" class="btn btn--primary btn--sm" data-action="run-prediction">${ICONS.predict}<span>Run prediction</span></button>
          <button type="button" class="btn btn--ghost btn--sm" data-action="compare-districts">${ICONS.compare}<span>Compare districts</span></button>
          <button type="button" class="btn btn--ghost btn--sm" disabled title="Coming in Phase 12">${ICONS.reports}<span>Download report</span></button>
        </div>
      </div>
      <div class="live-indicator">
        <span class="text-muted" id="last-updated-label"></span>
        <button type="button" class="btn btn--icon btn--ghost" id="refresh-btn" aria-label="Refresh now" title="Refresh now">${ICONS.refresh}</button>
      </div>
    </div>

    <div id="flood-alert-slot"></div>

    <div class="grid grid--kpi" id="kpi-row">${skeleton.kpiRow(6)}</div>

    <div class="grid grid--2col">
      <div class="card" id="recommendation-card">
        <div class="card__header"><span class="card__title">${ICONS.predict}Irrigation Recommendation</span></div>
        <div id="recommendation-body">${skeleton.block(240)}</div>
      </div>

      <div class="flex flex-col gap-4">
        <div class="card">
          <div class="card__header"><span class="card__title">${ICONS.forecast}7-Day Forecast</span></div>
          <div id="forecast-body">${skeleton.block(110)}</div>
        </div>
        <div class="card">
          <div class="card__header"><span class="card__title">${ICONS.history}Recent Predictions</span></div>
          <div id="recent-body">${skeleton.block(150)}</div>
        </div>
      </div>
    </div>
  `;

  const refreshBtn = root.querySelector('#refresh-btn');
  const lastUpdatedLabel = root.querySelector('#last-updated-label');

  let forecastChart = null;
  let lastUpdated = null;
  let recentHistoryCache = [];

  function setRefreshSpinning(isSpinning) {
    if (!refreshBtn) return;
    refreshBtn.disabled = isSpinning;
    refreshBtn.classList.toggle('is-spinning', isSpinning);
  }

  function updateLastUpdatedLabel() {
    if (!lastUpdatedLabel) return;
    lastUpdatedLabel.textContent = lastUpdated ? `Updated ${relativeTime(lastUpdated)}` : '';
  }

  function renderContextLine(district, weather) {
    const el = root.querySelector('#context-line');
    if (!el) return;
    const ctx = buildContextLine(district, weather);
    const toneClass = ctx.level === 'HIGH' ? 'text-red' : ctx.level === 'MODERATE' ? 'text-amber' : 'text-emerald';
    el.innerHTML = `${escapeHtml(ctx.text)} Irrigation demand likely <strong class="${toneClass}">${ctx.level}</strong> today.`;
  }

  function renderKpiRow(bundle, { animate }) {
    const kpiEl = root.querySelector('#kpi-row');
    kpiEl.innerHTML = renderKpis(bundle);
    kpiEl.querySelectorAll('[data-action="go-predict"]').forEach((link) => {
      link.addEventListener('click', (e) => {
        e.preventDefault();
        navigate('/predict');
      });
    });
    kpiEl.querySelectorAll('[data-countup]').forEach((el) => {
      const target = Number(el.dataset.target);
      const decimals = Number(el.dataset.decimals || 1);
      if (animate) countUp(el, target, { decimals });
      else el.textContent = target.toFixed(decimals);
    });
    wireExpandToggles(kpiEl);
  }

  function renderRecommendationCard(history, { animate }) {
    const recEl = root.querySelector('#recommendation-body');
    const rec = history && history.length ? history[0] : null;
    if (!rec) {
      recEl.innerHTML = '';
      recEl.appendChild(
        emptyState({
          icon: ICONS.predict,
          title: isLoggedIn() ? 'No predictions yet for this district' : 'Log in to see your recommendations here',
          desc: 'Run a prediction to see the gauge, model source, and plain-English factors.',
          actionLabel: 'Run a prediction',
          onAction: () => navigate('/predict'),
        })
      );
      return;
    }
    recEl.innerHTML = renderRecommendationBody(rec);
    wireExpandToggles(recEl);
    const svg = recEl.querySelector('.gauge__svg');
    const numEl = recEl.querySelector('#rec-gauge-num');
    animateGaugeNeedle(svg, rec.recommendation_mm, { max: 60, duration: animate ? 400 : 0 });
    if (animate) countUp(numEl, rec.recommendation_mm, { decimals: 1 });
    else if (numEl) numEl.textContent = rec.recommendation_mm.toFixed(1);
  }

  function renderForecastChart(forecast) {
    const forecastEl = root.querySelector('#forecast-body');
    if (forecastChart) {
      forecastChart.destroy();
      forecastChart = null;
    }

    const labels = forecast.days.map((day) => {
      const date = new Date(day.date);
      return Number.isNaN(date.getTime()) ? day.date : date.toLocaleDateString(undefined, { weekday: 'short' });
    });

    forecastEl.innerHTML = '<div style="height:150px"><canvas id="forecast-chart"></canvas></div>';
    const canvas = forecastEl.querySelector('#forecast-chart');

    forecastChart = createChart(canvas, {
      data: {
        labels,
        datasets: [
          {
            type: 'line',
            label: 'Temperature (°C)',
            data: forecast.days.map((d) => d.temperature_c),
            borderColor: seriesColor('temperature'),
            backgroundColor: seriesColor('temperature'),
            yAxisID: 'y',
            tension: 0.35,
            borderWidth: 2,
            pointRadius: 2,
          },
          {
            type: 'bar',
            label: 'Rainfall (mm)',
            data: forecast.days.map((d) => d.rainfall_mm),
            backgroundColor: seriesColor('rainfall'),
            yAxisID: 'y1',
            borderRadius: 4,
            maxBarThickness: 20,
          },
        ],
      },
      options: {
        maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        scales: {
          y: { position: 'left', ticks: { callback: (v) => tickLabel(v, '°') } },
          y1: { position: 'right', grid: { drawOnChartArea: false }, ticks: { callback: (v) => tickLabel(v, 'mm') } },
        },
        plugins: { legend: { display: true, position: 'bottom', labels: { boxWidth: 10, font: { size: 11 } } } },
      },
    });
  }

  async function refreshAll(district, { silent = false } = {}) {
    const kpiEl = root.querySelector('#kpi-row');
    const recEl = root.querySelector('#recommendation-body');
    const forecastEl = root.querySelector('#forecast-body');

    if (!silent) {
      kpiEl.innerHTML = skeleton.kpiRow(6);
      recEl.innerHTML = skeleton.block(240);
      forecastEl.innerHTML = skeleton.block(150);
    }
    setRefreshSpinning(true);

    try {
      const [weather, forecast] = await Promise.all([getWeather(district), getForecast(district, 7)]);
      let history = [];
      if (isLoggedIn()) {
        try {
          history = await getHistory({ district, limit: 7 });
        } catch {
          history = [];
        }
      }
      lastUpdated = Date.now();

      renderContextLine(district, weather);
      renderKpiRow({ district, weather, forecast, history }, { animate: !silent });
      renderRecommendationCard(history, { animate: !silent });
      renderForecastChart(forecast);
      updateLastUpdatedLabel();
    } catch (err) {
      if (silent) {
        toastError(`Couldn't refresh live conditions: ${err.message}`);
      } else {
        kpiEl.innerHTML = '';
        kpiEl.appendChild(errorState({ message: err.message, onRetry: () => refreshAll(district) }));
        recEl.innerHTML = '';
        recEl.appendChild(errorState({ message: err.message, onRetry: () => refreshAll(district) }));
        forecastEl.innerHTML = '';
        forecastEl.appendChild(errorState({ message: err.message, onRetry: () => refreshAll(district) }));
      }
    } finally {
      setRefreshSpinning(false);
    }
  }

  function wireRecentList(el) {
    el.querySelectorAll('.pred-row').forEach((row) => {
      row.addEventListener('click', () => {
        const item = recentHistoryCache.find((h) => String(h.id) === row.dataset.id);
        if (item) openPredictionModal(item);
      });
    });
  }

  async function loadRecent({ silent = false } = {}) {
    const el = root.querySelector('#recent-body');
    if (!isLoggedIn()) {
      if (!silent) {
        el.innerHTML = '';
        el.appendChild(
          emptyState({
            icon: ICONS.user,
            title: 'Log in to see prediction history',
            desc: 'Your recent predictions will appear here once you have an account.',
          })
        );
      }
      return;
    }
    if (!silent) el.innerHTML = skeleton.block(150);

    try {
      const history = await getHistory({ limit: 5 });
      recentHistoryCache = history;
      if (!history.length) {
        el.innerHTML = '';
        el.appendChild(
          emptyState({
            illustration: ILLUSTRATIONS.noPredictions,
            title: 'No predictions yet',
            desc: 'Run your first prediction to start building history.',
            actionLabel: 'Run your first prediction',
            onAction: () => navigate('/predict'),
          })
        );
        return;
      }
      el.innerHTML = renderRecentList(history);
      wireRecentList(el);
    } catch (err) {
      if (silent) {
        toastError(`Couldn't refresh recent predictions: ${err.message}`);
      } else {
        el.innerHTML = '';
        el.appendChild(errorState({ message: err.message, onRetry: () => loadRecent() }));
      }
    }
  }

  root.querySelector('[data-action="run-prediction"]')?.addEventListener('click', () => navigate('/predict'));
  root.querySelector('[data-action="compare-districts"]')?.addEventListener('click', () => navigate('/compare'));
  refreshBtn?.addEventListener('click', () => {
    if (!state.district || refreshBtn.disabled) return;
    refreshAll(state.district, { silent: true });
    loadRecent({ silent: true });
  });

  // Only reload on changes that actually affect this view's data (district,
  // login state) — a theme toggle also calls subscribe()'s listeners, and
  // re-fetching everything just to re-skin colors would flash skeletons for
  // no reason.
  let lastKnownDistrict = null;
  let lastKnownLoggedIn = null;

  function loadAll() {
    const district = state.district;
    const loggedIn = isLoggedIn();
    const districtChanged = district !== lastKnownDistrict;
    const loginChanged = loggedIn !== lastKnownLoggedIn;
    lastKnownDistrict = district;
    lastKnownLoggedIn = loggedIn;
    if (!districtChanged && !loginChanged) return;

    if (!district) {
      const el = root.querySelector('#context-line');
      if (el) el.textContent = 'Select a district in the topbar to see live conditions.';
      return;
    }
    refreshAll(district);
    loadRecent();
  }

  loadAll();
  loadFloodAlert(root);
  const unsubscribe = subscribe(loadAll);
  const tickTimer = setInterval(updateLastUpdatedLabel, TICK_MS);
  const autoRefreshTimer = setInterval(() => {
    loadFloodAlert(root);
    if (!state.district) return;
    refreshAll(state.district, { silent: true });
    loadRecent({ silent: true });
  }, AUTO_REFRESH_MS);

  return () => {
    unsubscribe();
    clearInterval(tickTimer);
    clearInterval(autoRefreshTimer);
    if (forecastChart) forecastChart.destroy();
  };
}
