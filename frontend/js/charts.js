/**
 * Thin wrapper around the vendored Chart.js UMD build (loaded as a classic
 * script in index.html, exposing window.Chart). Applies our design tokens
 * to every chart and re-skins all live charts when the theme toggles.
 */

import { subscribe } from './state.js';

function readTokens() {
  const css = getComputedStyle(document.documentElement);
  const v = (name) => css.getPropertyValue(name).trim();
  return {
    text: v('--text-secondary'),
    textPrimary: v('--text-primary'),
    grid: v('--border'),
    surface: v('--surface'),
    body: v('--font-body'),
    mono: v('--font-mono'),
    emerald: v('--emerald'),
    sky: v('--sky'),
    amber: v('--amber'),
    red: v('--red'),
    // Fixed categorical chart palette, slots 1-8, in order — never cycled.
    // See CHART_SERIES below for the app-wide metric -> slot assignment.
    series: [1, 2, 3, 4, 5, 6, 7, 8].map((i) => v(`--chart-${i}`)),
  };
}

/** App-wide, fixed metric -> categorical-slot assignment (0-based index into
 * chartTokens().series) so the same metric always renders in the same color
 * everywhere it appears, and no chart ever cycles/reuses a slot for two
 * different series within itself. Reserved slots (4, 6) are free for future
 * series. */
export const CHART_SERIES = {
  recommendation: 0, // blue — the headline irrigation metric
  temperature: 1, // orange
  rainfall: 2, // aqua
  soilMoisture: 2, // aqua (never combined with rainfall in the same chart)
  demandEstimate: 3, // yellow — ML estimate / projection lines
  et0: 5, // green
  district: null, // compare.js: one slot per selected district, in order
  driftReference: 4, // Monitoring page's reference (training) histogram bars
  driftCurrent: 6, // Monitoring page's current (live) histogram bars
  performanceError: 7, // Monitoring page's Phase 10 live-performance error-over-time line
};

/** Convenience accessor: the hex color for a named series or a raw slot
 * index (0-based), re-read live so it always matches the active theme. */
export function seriesColor(nameOrIndex) {
  const t = chartTokens();
  const index = typeof nameOrIndex === 'number' ? nameOrIndex : CHART_SERIES[nameOrIndex];
  return t.series[((index % 8) + 8) % 8];
}

// NOTE: only top-level scalar Chart.defaults are touched here. Chart.js
// resolves defaults.plugins.tooltip/legend through internal route/proxy
// getters-setters — assigning into those nested paths (even innocuous
// scalars like backgroundColor) recurses infinitely in this bundled version.
// Per-chart tooltip/legend colors are merged into each chart's own (plain)
// options object in createChart()/reskin() instead, which is safe.
function applyGlobalDefaults() {
  const Chart = window.Chart;
  if (!Chart) return;
  const t = readTokens();
  Chart.defaults.color = t.text;
  Chart.defaults.font.family = t.body;
  Chart.defaults.borderColor = t.grid;
}

function themedPluginDefaults(t) {
  return {
    tooltip: {
      backgroundColor: t.surface,
      titleColor: t.textPrimary,
      bodyColor: t.text,
      borderColor: t.grid,
      borderWidth: 1,
      padding: 10,
      cornerRadius: 8,
    },
    legend: {
      labels: { color: t.text },
    },
  };
}

/** Shallow-merges theme plugin defaults under whatever the caller already
 * specified, so caller options (e.g. legend position) always win. */
function mergePluginTheme(options, t) {
  const themed = themedPluginDefaults(t);
  options.plugins = options.plugins || {};

  options.plugins.tooltip = { ...themed.tooltip, ...(options.plugins.tooltip || {}) };

  const callerLegend = options.plugins.legend || {};
  options.plugins.legend = {
    ...themed.legend,
    ...callerLegend,
    labels: { ...themed.legend.labels, ...(callerLegend.labels || {}) },
  };
}

const liveCharts = new Set();

/** Creates a themed Chart.js instance and tracks it for live re-skinning. */
export function createChart(canvas, config) {
  const Chart = window.Chart;
  if (!Chart) {
    console.error('Chart.js failed to load from vendor/chartjs/chart.umd.js');
    return null;
  }
  applyGlobalDefaults();
  config.options = config.options || {};
  mergePluginTheme(config.options, readTokens());

  const chart = new Chart(canvas, config);
  liveCharts.add(chart);

  const originalDestroy = chart.destroy.bind(chart);
  chart.destroy = () => {
    liveCharts.delete(chart);
    originalDestroy();
  };
  return chart;
}

export function chartTokens() {
  return readTokens();
}

/** Axis tick label formatter: rounds to `decimals` first. Chart.js's
 * auto-generated tick values can carry float noise (e.g. 4.500000000000001)
 * when a chart's data range is tiny or degenerate (a single data point, or
 * all-equal values) — always round before display, never show raw floats. */
export function tickLabel(value, unit = '', decimals = 1) {
  return `${Number(value.toFixed(decimals))}${unit}`;
}

/** Re-applies theme colors to an existing chart's own (plain) options
 * object, forcibly overwriting the previous theme's colors — unlike
 * mergePluginTheme() used at creation time, this must NOT defer to
 * whatever is already there, since that's the stale theme. */
function reskin(chart) {
  const t = readTokens();
  const scales = chart.options.scales || {};
  Object.values(scales).forEach((scale) => {
    if (scale.grid) scale.grid.color = t.grid;
    if (scale.ticks) scale.ticks.color = t.text;
  });

  const plugins = chart.options.plugins || {};
  if (plugins.tooltip) {
    Object.assign(plugins.tooltip, themedPluginDefaults(t).tooltip);
  }
  if (plugins.legend && plugins.legend.labels) {
    plugins.legend.labels.color = t.text;
  }
  chart.update();
}

subscribe(() => {
  applyGlobalDefaults();
  liveCharts.forEach(reskin);
});
