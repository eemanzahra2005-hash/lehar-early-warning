/** Analytics view — six real charts built from the logged-in user's
 * prediction history (GET /history), over a selectable date range. Never
 * synthesizes data: an empty range renders an honest empty state instead of
 * a chart with invented numbers. */

import { getHistory } from '../api.js';
import { isLoggedIn } from '../state.js';
import { skeleton, errorState, emptyState } from '../ui.js';
import { ICONS } from '../icons.js';
import { createChart, tickLabel, seriesColor } from '../charts.js';

const RANGES = [
  { id: '7', label: '7 days', days: 7 },
  { id: '30', label: '30 days', days: 30 },
  { id: '90', label: '90 days', days: 90 },
  { id: 'custom', label: 'Custom', days: null },
];

function isoDate(date) {
  return date.toISOString().slice(0, 10);
}

function chartCard(id, title, icon) {
  return `
    <div class="card">
      <div class="card__header"><span class="card__title">${icon}${title}</span></div>
      <div id="${id}">${skeleton.block(220)}</div>
    </div>
  `;
}

export function mountAnalytics(root) {
  if (!isLoggedIn()) {
    root.innerHTML = `
      <div class="view-header"><div><h1>Analytics</h1><p>Trends across your prediction history.</p></div></div>
      <div class="card"></div>
    `;
    root.querySelector('.card').appendChild(
      emptyState({ icon: ICONS.user, title: 'Log in to see your analytics', desc: 'Analytics are built from your own prediction history.' })
    );
    return;
  }

  root.innerHTML = `
    <div class="view-header">
      <div>
        <h1>Analytics</h1>
        <p>Trends across your prediction history.</p>
      </div>
      <div class="flex gap-3" style="align-items:center;flex-wrap:wrap">
        <div class="tabs" id="range-tabs">
          ${RANGES.map((r, i) => `<button type="button" class="tabs__btn${i === 1 ? ' is-active' : ''}" data-range="${r.id}">${r.label}</button>`).join('')}
        </div>
        <div class="flex gap-2" id="custom-range-row" hidden>
          <input class="input" type="date" id="analytics-from" />
          <input class="input" type="date" id="analytics-to" />
        </div>
      </div>
    </div>

    <div id="analytics-body">
      <div class="grid grid--split">
        ${chartCard('chart-recommendation', 'Recommendation over time', ICONS.predict)}
        ${chartCard('chart-soil', 'Soil moisture trend', ICONS.wind)}
        ${chartCard('chart-rainfall-vs-rec', 'Rainfall vs recommendation', ICONS.forecast)}
        ${chartCard('chart-et0', 'ET0 trend', ICONS.wind)}
        ${chartCard('chart-temp', 'Temperature trend', ICONS.thermometer)}
        ${chartCard('chart-by-district', 'Average recommendation per district (top 10)', ICONS.map)}
      </div>
    </div>
  `;

  const tabsEl = root.querySelector('#range-tabs');
  const customRow = root.querySelector('#custom-range-row');
  const fromInput = root.querySelector('#analytics-from');
  const toInput = root.querySelector('#analytics-to');
  const bodyEl = root.querySelector('#analytics-body');

  let selectedRange = '30';
  const charts = [];

  function destroyCharts() {
    charts.forEach((c) => c && c.destroy());
    charts.length = 0;
  }

  function labelsFor(rows) {
    return rows.map((r) => new Date(r.created_at).toLocaleDateString(undefined, { month: 'short', day: 'numeric' }));
  }

  function renderLineChart(elId, rows, key, color, unit) {
    const el = root.querySelector(`#${elId}`);
    if (!rows.length) {
      el.innerHTML = '';
      el.appendChild(emptyState({ icon: ICONS.analytics, title: 'Not enough history yet — run some predictions' }));
      return;
    }
    el.innerHTML = '<div style="height:220px"><canvas></canvas></div>';
    const canvas = el.querySelector('canvas');
    const chart = createChart(canvas, {
      data: {
        labels: labelsFor(rows),
        datasets: [
          {
            type: 'line',
            data: rows.map((r) => r[key]),
            borderColor: color,
            backgroundColor: color,
            tension: 0.3,
            borderWidth: 2,
            pointRadius: rows.length > 40 ? 0 : 2,
          },
        ],
      },
      options: {
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: { y: { ticks: { callback: (v) => tickLabel(v, unit) } } },
      },
    });
    charts.push(chart);
  }

  function renderRainfallVsRecommendation(rows) {
    const el = root.querySelector('#chart-rainfall-vs-rec');
    if (!rows.length) {
      el.innerHTML = '';
      el.appendChild(emptyState({ icon: ICONS.analytics, title: 'Not enough history yet — run some predictions' }));
      return;
    }
    el.innerHTML = '<div style="height:220px"><canvas></canvas></div>';
    const canvas = el.querySelector('canvas');
    const chart = createChart(canvas, {
      data: {
        labels: labelsFor(rows),
        datasets: [
          { type: 'bar', label: 'Rainfall (mm)', data: rows.map((r) => r.rainfall_mm), backgroundColor: seriesColor('rainfall'), yAxisID: 'y', borderRadius: 3, maxBarThickness: 18 },
          { type: 'line', label: 'Recommendation (mm)', data: rows.map((r) => r.recommendation_mm), borderColor: seriesColor('recommendation'), backgroundColor: seriesColor('recommendation'), yAxisID: 'y1', tension: 0.3, borderWidth: 2, pointRadius: rows.length > 40 ? 0 : 2 },
        ],
      },
      options: {
        maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        scales: {
          y: { position: 'left', ticks: { callback: (v) => tickLabel(v, 'mm') } },
          y1: { position: 'right', grid: { drawOnChartArea: false }, ticks: { callback: (v) => tickLabel(v, 'mm') } },
        },
        plugins: { legend: { display: true, position: 'bottom', labels: { boxWidth: 10, font: { size: 11 } } } },
      },
    });
    charts.push(chart);
  }

  function renderByDistrict(rows) {
    const el = root.querySelector('#chart-by-district');
    if (!rows.length) {
      el.innerHTML = '';
      el.appendChild(emptyState({ icon: ICONS.analytics, title: 'Not enough history yet — run some predictions' }));
      return;
    }
    const sums = new Map();
    for (const r of rows) {
      const cur = sums.get(r.district) || { total: 0, count: 0 };
      cur.total += r.recommendation_mm;
      cur.count += 1;
      sums.set(r.district, cur);
    }
    const averages = [...sums.entries()]
      .map(([district, { total, count }]) => ({ district, avg: total / count }))
      .sort((a, b) => b.avg - a.avg)
      .slice(0, 10);

    el.innerHTML = `<div style="height:${Math.max(220, averages.length * 32)}px"><canvas></canvas></div>`;
    const canvas = el.querySelector('canvas');
    const chart = createChart(canvas, {
      data: {
        labels: averages.map((a) => a.district),
        datasets: [{ type: 'bar', data: averages.map((a) => Number(a.avg.toFixed(1))), backgroundColor: seriesColor('recommendation'), borderRadius: 4, maxBarThickness: 20 }],
      },
      options: {
        indexAxis: 'y',
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: { x: { ticks: { callback: (v) => tickLabel(v, 'mm') } } },
      },
    });
    charts.push(chart);
  }

  function renderAll(rows) {
    destroyCharts();
    renderLineChart('chart-recommendation', rows, 'recommendation_mm', seriesColor('recommendation'), 'mm');
    renderLineChart('chart-soil', rows, 'soil_moisture_pct', seriesColor('soilMoisture'), '%');
    renderRainfallVsRecommendation(rows);
    renderLineChart('chart-et0', rows, 'evapotranspiration_mm', seriesColor('et0'), 'mm');
    renderLineChart('chart-temp', rows, 'temperature_c', seriesColor('temperature'), '°C');
    renderByDistrict(rows);
  }

  function computeRangeParams() {
    if (selectedRange === 'custom') {
      const params = {};
      if (fromInput.value) params.from = fromInput.value;
      if (toInput.value) params.to = toInput.value;
      return params;
    }
    const range = RANGES.find((r) => r.id === selectedRange);
    const to = new Date();
    const from = new Date();
    from.setDate(from.getDate() - (range.days - 1));
    return { from: isoDate(from), to: isoDate(to) };
  }

  async function load() {
    bodyEl.querySelectorAll('[id^="chart-"]').forEach((el) => {
      el.innerHTML = skeleton.block(220);
    });

    try {
      // Rows come back newest-first — reverse to chronological order for charts.
      const rows = [...(await getHistory({ limit: 500, ...computeRangeParams() }))].reverse();
      renderAll(rows);
    } catch (err) {
      bodyEl.innerHTML = '';
      bodyEl.appendChild(errorState({ message: err.message, onRetry: load }));
    }
  }

  tabsEl.querySelectorAll('.tabs__btn').forEach((btn) => {
    btn.addEventListener('click', () => {
      tabsEl.querySelectorAll('.tabs__btn').forEach((b) => b.classList.remove('is-active'));
      btn.classList.add('is-active');
      selectedRange = btn.dataset.range;
      customRow.hidden = selectedRange !== 'custom';
      if (selectedRange !== 'custom' || (fromInput.value && toInput.value)) load();
    });
  });
  [fromInput, toInput].forEach((el) =>
    el.addEventListener('change', () => {
      if (selectedRange === 'custom' && fromInput.value && toInput.value) load();
    })
  );

  load();

  return () => destroyCharts();
}
