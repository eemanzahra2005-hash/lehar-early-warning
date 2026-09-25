/** Monitoring page (#/monitoring) — Phase 8 data-drift half (the
 * model-performance half is Phase 10). Real PSI (Population Stability
 * Index) per feature, computed server-side between the active production
 * model's training-time reference distribution and the last DRIFT_WINDOW
 * real prediction inputs (GET /api/v1/monitoring/drift) — see
 * docs/DRIFT.md. Fewer than DRIFT_MIN_SAMPLES logged predictions renders
 * an honest "insufficient data" empty state, never a fabricated chart. */

import { getDrift, getPerformance } from '../api.js';
import { skeleton, errorState, emptyState, escapeHtml, wireExpandToggles } from '../ui.js';
import { ICONS } from '../icons.js';
import { createChart, tickLabel, chartTokens, seriesColor } from '../charts.js';

const STATUS_META = {
  stable: { icon: ICONS.checkCircle, label: 'Stable', tone: 'emerald', desc: 'No feature shows a meaningful shift from the training data.' },
  warning: { icon: ICONS.alertTriangle, label: 'Warning', tone: 'amber', desc: 'At least one feature has drifted somewhat from the training data — worth a look.' },
  significant_drift: { icon: ICONS.xCircle, label: 'Significant Drift', tone: 'red', desc: 'At least one feature looks substantially different from the training data.' },
  insufficient_data: { icon: ICONS.info, label: 'Insufficient data', tone: 'neutral', desc: 'Not enough real predictions logged yet to compute drift for the active model.' },
};

const FEATURE_LABELS = {
  temperature_c: 'Temperature (°C)',
  humidity_pct: 'Humidity (%)',
  rainfall_mm: 'Rainfall (mm)',
  evapotranspiration_mm: 'ET0 (mm)',
  canal_flow_cusecs: 'Canal flow (cusecs)',
  soil_moisture_pct: 'Soil moisture (%)',
  district: 'District',
  crop_type: 'Crop type',
};

const BAND_LABEL = { stable: 'stable', warning: 'warning', significant_drift: 'significant drift' };

function bannerMarkup(drift) {
  const meta = STATUS_META[drift.status] || STATUS_META.insufficient_data;
  const tone = meta.tone === 'neutral' ? null : meta.tone;
  const borderColor = tone ? `var(--${tone})` : 'var(--border)';
  const background = tone ? `var(--${tone}-soft)` : 'var(--surface-2)';
  const iconColor = tone ? `var(--${tone})` : 'var(--text-secondary)';
  const versionLabel = drift.reference_model_version
    ? `<span class="code">${escapeHtml(drift.reference_model_version)}</span>`
    : '—';
  return `
    <div class="card card--pad-sm" style="border-color:${borderColor};background:${background};margin-bottom:16px">
      <div class="flex gap-2" style="align-items:flex-start">
        <span class="drift-banner__icon" style="color:${iconColor}">${meta.icon}</span>
        <div>
          <div style="font-weight:600;font-size:14.5px">${escapeHtml(meta.label)}</div>
          <div class="text-muted" style="font-size:12.5px;margin-top:2px">${escapeHtml(meta.desc)}</div>
          <div class="text-muted" style="font-size:12px;margin-top:6px">
            Comparing the most recent <strong>${drift.samples_available}</strong> of a ${drift.window_used}-prediction
            window against model ${versionLabel}'s training baseline.
          </div>
        </div>
      </div>
    </div>
  `;
}

function insufficientDataMarkup(drift) {
  return emptyState({
    icon: ICONS.monitoring,
    title: 'Not enough predictions logged yet',
    desc: `${drift.samples_available} real prediction${drift.samples_available === 1 ? '' : 's'} logged so far — drift can't be computed reliably from too few samples. Run some predictions (Predict page) and check back.`,
  });
}

/** Custom Chart.js plugin (no external annotation library — everything
 * vendored locally, CLAUDE.md rule 7): draws the two dashed PSI threshold
 * lines directly on the canvas at their real x-axis pixel position. */
function thresholdLinePlugin(warnValue, alertValue) {
  return {
    id: 'driftThresholds',
    afterDraw(chart) {
      const { ctx, chartArea, scales } = chart;
      const xScale = scales.x;
      if (!xScale || !chartArea) return;
      const t = chartTokens();
      ctx.save();
      [
        [warnValue, t.amber],
        [alertValue, t.red],
      ].forEach(([value, color]) => {
        if (value == null) return;
        const x = xScale.getPixelForValue(value);
        if (x < chartArea.left || x > chartArea.right) return;
        ctx.beginPath();
        ctx.strokeStyle = color;
        ctx.lineWidth = 1.5;
        ctx.setLineDash([4, 4]);
        ctx.moveTo(x, chartArea.top);
        ctx.lineTo(x, chartArea.bottom);
        ctx.stroke();
      });
      ctx.restore();
    },
  };
}

function renderPsiChart(canvas, features, warn, alert, onSelect) {
  const t = chartTokens();
  const bandColor = { stable: t.emerald, warning: t.amber, significant_drift: t.red };
  return createChart(canvas, {
    type: 'bar',
    data: {
      labels: features.map((f) => FEATURE_LABELS[f.name] || f.name),
      datasets: [
        {
          label: 'PSI',
          data: features.map((f) => f.psi),
          backgroundColor: features.map((f) => bandColor[f.band] || t.sky),
          borderRadius: 4,
          barThickness: 18,
        },
      ],
    },
    options: {
      indexAxis: 'y',
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        x: { beginAtZero: true, ticks: { callback: (v) => tickLabel(v, '', 2) } },
        y: { grid: { display: false } },
      },
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: (ctx) => `PSI ${ctx.parsed.x.toFixed(3)} (${BAND_LABEL[features[ctx.dataIndex].band] || features[ctx.dataIndex].band})`,
          },
        },
      },
      onClick(evt, elements) {
        if (!elements.length) return;
        onSelect(features[elements[0].index]);
      },
    },
    plugins: [thresholdLinePlugin(warn, alert)],
  });
}

function binLabel(edges, i, isCategorical) {
  if (isCategorical) return String(edges[i]);
  const lo = Number(edges[i]).toFixed(1);
  const hi = Number(edges[i + 1]).toFixed(1);
  return `${lo}–${hi}`;
}

/** Converts raw counts to a percent-of-window share. The reference window
 * (all of training, tens of thousands of rows) and the current window
 * (DRIFT_WINDOW, ~50-200 rows) differ in size by orders of magnitude — on
 * a shared raw-count axis the current bars would be visually flat next to
 * reference, even though PSI itself compares proportions, not counts.
 * Percent-of-window is what actually makes the two shapes comparable. */
function toPercent(counts) {
  const total = counts.reduce((sum, c) => sum + c, 0);
  if (total <= 0) return counts.map(() => 0);
  return counts.map((c) => (c / total) * 100);
}

function renderHistogramChart(canvas, feature) {
  const isCategorical = feature.name === 'district' || feature.name === 'crop_type';
  const edges = feature.reference_hist.edges;
  const labelCount = isCategorical ? edges.length : edges.length - 1;
  const labels = Array.from({ length: labelCount }, (_, i) => binLabel(edges, i, isCategorical));

  return createChart(canvas, {
    type: 'bar',
    data: {
      labels,
      datasets: [
        {
          label: 'Reference (training)',
          data: toPercent(feature.reference_hist.counts),
          backgroundColor: chartTokens().series[4],
          borderRadius: 3,
        },
        {
          label: 'Current (live)',
          data: toPercent(feature.current_hist.counts),
          backgroundColor: chartTokens().series[6],
          borderRadius: 3,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        x: { ticks: { maxRotation: isCategorical ? 60 : 0, autoSkip: true } },
        y: { beginAtZero: true, ticks: { callback: (v) => tickLabel(v, '%', 0) } },
      },
      plugins: {
        legend: { display: true, position: 'top' },
        tooltip: { callbacks: { label: (ctx) => `${ctx.dataset.label}: ${ctx.parsed.y.toFixed(1)}%` } },
      },
    },
  });
}

function explainerMarkup() {
  return `
    <div class="card" style="margin-top:16px">
      <button type="button" class="btn btn--ghost btn--sm" data-expand-toggle="psi-explainer" aria-expanded="false">
        ${ICONS.info}<span>What is PSI?</span>${ICONS.chevronDown}
      </button>
      <div id="psi-explainer" class="text-secondary" style="font-size:13px;line-height:1.6;margin-top:10px" hidden>
        PSI (Population Stability Index) measures how much a feature's distribution has shifted between two
        windows — here, the data the model was trained on versus the most recent real predictions. It's a simple,
        widely-used heuristic, not a formal statistical test: below 0.1 is generally "stable," 0.1–0.25 is a
        "warning" worth a look, and 0.25+ suggests a "significant" shift. The 0.1/0.25 thresholds are common
        industry rules of thumb (most often cited from credit-risk scoring), not scientifically validated for
        irrigation/weather data specifically — see <span class="code">docs/DRIFT.md</span>.
      </div>
    </div>
  `;
}

// --- Model performance (live) — Phase 10 -----------------------------------
//
// Computed server-side ONLY from real recorded prediction+actual pairs
// (app/services/performance.py) — status="no_actuals_recorded" until at
// least one exists. Never a fabricated chart: the empty state below is
// instructive, not a demo curve.

function performanceEmptyMarkup() {
  return emptyState({
    icon: ICONS.history,
    title: 'No live performance data yet',
    desc: 'Record actual outcomes from the History page to unlock live performance tracking.',
  });
}

function performanceStatsMarkup(perf) {
  return `
    <div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:16px">
      <div class="card card--pad-sm">
        <div class="text-muted" style="font-size:11px;text-transform:uppercase;letter-spacing:.04em">Recorded outcomes</div>
        <div class="mono" style="font-size:22px;font-weight:600;margin-top:4px">${perf.count}</div>
      </div>
      <div class="card card--pad-sm">
        <div class="text-muted" style="font-size:11px;text-transform:uppercase;letter-spacing:.04em">Rolling MAE</div>
        <div class="mono" style="font-size:22px;font-weight:600;margin-top:4px">${perf.rolling_mae.toFixed(2)}mm</div>
      </div>
      <div class="card card--pad-sm">
        <div class="text-muted" style="font-size:11px;text-transform:uppercase;letter-spacing:.04em">Rolling RMSE</div>
        <div class="mono" style="font-size:22px;font-weight:600;margin-top:4px">${perf.rolling_rmse.toFixed(2)}mm</div>
      </div>
    </div>
  `;
}

function renderPerformanceChart(canvas, series) {
  return createChart(canvas, {
    type: 'line',
    data: {
      labels: series.map((p) => new Date(p.date).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })),
      datasets: [
        {
          label: 'Error (actual − recommended, mm)',
          data: series.map((p) => p.error),
          borderColor: seriesColor('performanceError'),
          backgroundColor: seriesColor('performanceError'),
          tension: 0.3,
          borderWidth: 2,
          pointRadius: 3,
        },
      ],
    },
    options: {
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { label: (ctx) => `Error: ${ctx.parsed.y.toFixed(1)}mm` } },
      },
      scales: { y: { ticks: { callback: (v) => tickLabel(v, 'mm') } } },
    },
  });
}

function performanceSectionMarkup(perf) {
  if (perf.status !== 'ok' || !perf.count) {
    return `
      <div class="card">
        <div class="card__header"><span class="card__title">${ICONS.history}Model performance (live)</span></div>
        <div id="performance-empty"></div>
      </div>
    `;
  }
  return `
    <div class="card">
      <div class="card__header"><span class="card__title">${ICONS.history}Model performance (live)</span></div>
      <p class="text-muted" style="font-size:12.5px;margin:-4px 0 12px">
        Computed only from real outcomes recorded on the History page — signed error is actual minus recommended
        irrigation, so positive means the model under-recommended.
      </p>
      ${performanceStatsMarkup(perf)}
      <div style="height:220px"><canvas id="performance-chart"></canvas></div>
    </div>
  `;
}

function infrastructureCardMarkup() {
  return `
    <div class="card">
      <div class="card__header"><span class="card__title">${ICONS.externalLink}Infrastructure</span></div>
      <div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px">
        <div>
          <a class="btn btn--sm" href="http://127.0.0.1:3000" target="_blank" rel="noopener">${ICONS.externalLink}<span>Open Grafana</span></a>
          <p class="text-muted" style="font-size:12px;margin-top:6px">
            The provisioned "LEHAR Overview" dashboard — request rate, latency, error rate, and prediction volume, live.
          </p>
        </div>
        <div>
          <a class="btn btn--sm" href="http://127.0.0.1:9090" target="_blank" rel="noopener">${ICONS.externalLink}<span>Open Prometheus</span></a>
          <p class="text-muted" style="font-size:12px;margin-top:6px">
            Raw metrics and scrape-target health for this API (GET /metrics), scraped every 15 seconds.
          </p>
        </div>
      </div>
    </div>
  `;
}

export function mountMonitoring(root) {
  root.innerHTML = `
    <div class="view-header">
      <div>
        <h1>Monitoring</h1>
        <p>Real-time data-drift and live model-performance monitoring — synthetic training data, real computed numbers.</p>
      </div>
    </div>
    <div id="drift-body">${skeleton.block(320)}</div>
    <div id="performance-body" style="margin-top:16px">${skeleton.block(180)}</div>
    <div id="infrastructure-body" style="margin-top:16px"></div>
  `;

  const bodyEl = root.querySelector('#drift-body');
  const performanceBodyEl = root.querySelector('#performance-body');
  const infrastructureBodyEl = root.querySelector('#infrastructure-body');
  infrastructureBodyEl.innerHTML = infrastructureCardMarkup();

  let driftCharts = [];
  let performanceCharts = [];

  function destroyCharts() {
    driftCharts.forEach((c) => c && c.destroy());
    driftCharts = [];
  }

  function destroyPerformanceCharts() {
    performanceCharts.forEach((c) => c && c.destroy());
    performanceCharts = [];
  }

  function renderFeatureDetail(container, features, selected) {
    container.innerHTML = `
      <div class="card__header"><span class="card__title">${ICONS.analytics}Reference vs current — ${escapeHtml(FEATURE_LABELS[selected.name] || selected.name)}</span></div>
      <div class="text-muted" style="font-size:12px;margin-bottom:8px">
        PSI ${selected.psi.toFixed(3)} (${escapeHtml(BAND_LABEL[selected.band] || selected.band)}) — click another bar above to switch features.
      </div>
      <div style="height:260px"><canvas></canvas></div>
    `;
    const chart = renderHistogramChart(container.querySelector('canvas'), selected);
    driftCharts.push(chart);
  }

  async function load() {
    try {
      const drift = await getDrift();
      destroyCharts();

      if (drift.status === 'insufficient_data' || !drift.features.length) {
        bodyEl.innerHTML = bannerMarkup(drift);
        bodyEl.appendChild(insufficientDataMarkup(drift));
        return;
      }

      bodyEl.innerHTML = `
        ${bannerMarkup(drift)}
        <div class="card">
          <div class="card__header"><span class="card__title">${ICONS.monitoring}Per-feature PSI</span></div>
          <div class="map-legend" style="flex-direction:row;gap:14px;margin-bottom:8px">
            <span class="map-legend__item"><span class="map-legend__swatch" style="background:var(--amber);border-style:dashed"></span>Warning threshold (${drift.psi_warn})</span>
            <span class="map-legend__item"><span class="map-legend__swatch" style="background:var(--red);border-style:dashed"></span>Alert threshold (${drift.psi_alert})</span>
          </div>
          <div style="height:${Math.max(220, drift.features.length * 40)}px"><canvas id="psi-chart"></canvas></div>
        </div>
        <div class="card" id="feature-detail"></div>
        ${explainerMarkup()}
      `;

      const sortedByPsi = [...drift.features].sort((a, b) => b.psi - a.psi);
      const detailEl = bodyEl.querySelector('#feature-detail');

      const psiChart = renderPsiChart(
        bodyEl.querySelector('#psi-chart'),
        drift.features,
        drift.psi_warn,
        drift.psi_alert,
        (feature) => renderFeatureDetail(detailEl, drift.features, feature)
      );
      driftCharts.push(psiChart);

      // Default to the worst-offending feature so the page opens on the
      // most informative view rather than an empty panel.
      renderFeatureDetail(detailEl, drift.features, sortedByPsi[0]);

      wireExpandToggles(bodyEl);
    } catch (err) {
      destroyCharts();
      bodyEl.innerHTML = '';
      bodyEl.appendChild(errorState({ message: err.message, onRetry: load }));
    }
  }

  async function loadPerformance() {
    try {
      const perf = await getPerformance();
      destroyPerformanceCharts();
      performanceBodyEl.innerHTML = performanceSectionMarkup(perf);

      if (perf.status !== 'ok' || !perf.count) {
        performanceBodyEl.querySelector('#performance-empty').appendChild(performanceEmptyMarkup());
        return;
      }

      const chart = renderPerformanceChart(performanceBodyEl.querySelector('#performance-chart'), perf.series);
      performanceCharts.push(chart);
    } catch (err) {
      destroyPerformanceCharts();
      performanceBodyEl.innerHTML = '';
      performanceBodyEl.appendChild(errorState({ message: err.message, onRetry: loadPerformance }));
    }
  }

  // Independent of the drift section above — one failing never blocks the
  // other, same per-section-failure-tolerance stance as the rest of the app
  // (e.g. FloodService/MapOverviewService's per-district degradation).
  load();
  loadPerformance();
}
