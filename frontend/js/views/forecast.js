/** Forecast view — 7-day daily cards + a combined temp/rain/ET0 chart for
 * the currently selected district, with an optional "Expected irrigation
 * demand" ML-estimate series (GET /forecast?include_demand=true), rendered
 * in a visually distinct (dashed) style with an explicit assumption label —
 * never confused with the real forecast series. */

import { getForecast } from '../api.js';
import { state, subscribe } from '../state.js';
import { skeleton, errorState, emptyState, escapeHtml } from '../ui.js';
import { ICONS } from '../icons.js';
import { createChart, tickLabel, seriesColor } from '../charts.js';

const DEFAULT_DEMAND_SOIL_MOISTURE = 25;

function weatherIcon(rainfallMm) {
  if (rainfallMm >= 5) return ICONS.rain;
  if (rainfallMm >= 0.2) return ICONS.forecast;
  return ICONS.sun;
}

function dayCard(day) {
  const date = new Date(day.date);
  const weekday = Number.isNaN(date.getTime()) ? day.date : date.toLocaleDateString(undefined, { weekday: 'short' });
  const dateLabel = Number.isNaN(date.getTime()) ? '' : date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
  return `
    <div class="card card--pad-sm forecast-day-card">
      <div class="text-muted" style="font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:0.04em">${escapeHtml(weekday)}</div>
      <div class="text-muted" style="font-size:11px;margin-bottom:8px">${escapeHtml(dateLabel)}</div>
      <div style="width:26px;height:26px;color:var(--sky);margin-bottom:8px">${weatherIcon(day.rainfall_mm)}</div>
      <div class="kpi__value" style="font-size:20px">${day.temperature_c.toFixed(1)}<small>°C</small></div>
      <div class="flex flex-col gap-1" style="margin-top:8px;font-size:12px;color:var(--text-secondary)">
        <div>Rain: <span class="mono">${day.rainfall_mm.toFixed(1)}mm</span></div>
        <div>Humidity: <span class="mono">${day.humidity_pct !== null && day.humidity_pct !== undefined ? day.humidity_pct.toFixed(0) + '%' : '—'}</span></div>
        <div>ET0: <span class="mono">${day.evapotranspiration_mm.toFixed(1)}mm</span></div>
      </div>
      ${
        day.irrigation_estimate_mm !== null && day.irrigation_estimate_mm !== undefined
          ? `<div class="chip chip--sky" style="margin-top:8px">${ICONS.predict}${day.irrigation_estimate_mm.toFixed(1)}mm est.</div>`
          : ''
      }
    </div>
  `;
}

export function mountForecast(root) {
  root.innerHTML = `
    <div class="view-header">
      <div>
        <h1>Forecast</h1>
        <p>7-day outlook for the selected district, plus an optional ML-estimated irrigation demand series.</p>
      </div>
    </div>

    <div class="card">
      <div class="card__header">
        <span class="card__title">${ICONS.forecast}Daily forecast</span>
        <label class="switch">
          <input type="checkbox" id="demand-toggle" />
          <span class="switch__track"><span class="switch__thumb"></span></span>
          <span>Show expected irrigation demand</span>
        </label>
      </div>
      <div id="forecast-cards" class="forecast-cards">${skeleton.kpiRow(7)}</div>
    </div>

    <div class="card">
      <div class="card__header"><span class="card__title">${ICONS.analytics}Temperature · Rainfall · ET0</span></div>
      <p class="text-muted" id="demand-note" style="font-size:11.5px;margin-bottom:8px" hidden></p>
      <div id="forecast-chart-body">${skeleton.block(280)}</div>
    </div>
  `;

  const cardsEl = root.querySelector('#forecast-cards');
  const chartBodyEl = root.querySelector('#forecast-chart-body');
  const demandToggle = root.querySelector('#demand-toggle');
  const demandNoteEl = root.querySelector('#demand-note');

  let chart = null;

  function renderCards(days) {
    cardsEl.innerHTML = days.map(dayCard).join('');
  }

  function renderChart(days, includeDemand) {
    if (chart) {
      chart.destroy();
      chart = null;
    }
    chartBodyEl.innerHTML = '<div style="height:280px"><canvas id="forecast-combo-chart"></canvas></div>';
    const canvas = chartBodyEl.querySelector('#forecast-combo-chart');

    const labels = days.map((day) => {
      const date = new Date(day.date);
      return Number.isNaN(date.getTime()) ? day.date : date.toLocaleDateString(undefined, { weekday: 'short' });
    });

    const datasets = [
      {
        type: 'line',
        label: 'Temperature (°C)',
        data: days.map((d) => d.temperature_c),
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
        data: days.map((d) => d.rainfall_mm),
        backgroundColor: seriesColor('rainfall'),
        yAxisID: 'y1',
        borderRadius: 4,
        maxBarThickness: 22,
      },
      {
        type: 'line',
        label: 'ET0 (mm)',
        data: days.map((d) => d.evapotranspiration_mm),
        borderColor: seriesColor('et0'),
        backgroundColor: seriesColor('et0'),
        yAxisID: 'y1',
        tension: 0.35,
        borderWidth: 2,
        pointRadius: 2,
        borderDash: [],
      },
    ];

    if (includeDemand) {
      datasets.push({
        type: 'line',
        label: 'ML estimate — irrigation demand (mm)',
        data: days.map((d) => d.irrigation_estimate_mm),
        borderColor: seriesColor('demandEstimate'),
        backgroundColor: seriesColor('demandEstimate'),
        yAxisID: 'y1',
        tension: 0.2,
        borderWidth: 2,
        borderDash: [6, 4],
        pointRadius: 3,
        pointStyle: 'triangle',
      });
    }

    chart = createChart(canvas, {
      data: { labels, datasets },
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

  async function load() {
    const district = state.district;
    if (!district) {
      cardsEl.innerHTML = '';
      cardsEl.appendChild(emptyState({ icon: ICONS.forecast, title: 'Select a district', desc: 'Choose a district in the topbar to see its 7-day forecast.' }));
      chartBodyEl.innerHTML = '';
      return;
    }

    cardsEl.innerHTML = skeleton.kpiRow(7);
    chartBodyEl.innerHTML = skeleton.block(280);
    demandNoteEl.hidden = true;

    const includeDemand = demandToggle.checked;
    try {
      const opts = includeDemand ? { include_demand: true, soil_moisture_pct: DEFAULT_DEMAND_SOIL_MOISTURE } : {};
      const forecast = await getForecast(district, 7, opts);
      renderCards(forecast.days);
      renderChart(forecast.days, includeDemand);
      if (includeDemand && forecast.demand_note) {
        demandNoteEl.textContent = forecast.demand_note;
        demandNoteEl.hidden = false;
      }
    } catch (err) {
      cardsEl.innerHTML = '';
      cardsEl.appendChild(errorState({ message: err.message, onRetry: load }));
      chartBodyEl.innerHTML = '';
    }
  }

  demandToggle.addEventListener('change', load);

  let lastDistrict = state.district;
  function onStateChange() {
    if (state.district !== lastDistrict) {
      lastDistrict = state.district;
      load();
    }
  }
  load();
  const unsubscribe = subscribe(onStateChange);

  return () => {
    unsubscribe();
    if (chart) chart.destroy();
  };
}
