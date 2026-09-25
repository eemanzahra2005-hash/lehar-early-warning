/** History view — filterable, paginated table of the logged-in user's past
 * predictions, a small trend chart, and a client-side CSV export built from
 * whatever the current filters returned (never re-derived server data). */

import { getHistory, getFields, getMeta, recordActual, ApiError } from '../api.js';
import { isLoggedIn } from '../state.js';
import { skeleton, errorState, emptyState, escapeHtml, toastError, toastSuccess, openModal } from '../ui.js';
import { ICONS } from '../icons.js';
import { createChart, tickLabel, seriesColor } from '../charts.js';
import { riskChip } from '../riskUi.js';

const PAGE_SIZE = 25;
const FETCH_LIMIT = 500;

const CSV_COLUMNS = [
  ['created_at', 'Datetime'],
  ['field_name', 'Field'],
  ['district', 'District'],
  ['crop_type', 'Crop'],
  ['soil_moisture_pct', 'Soil moisture (%)'],
  ['canal_flow_cusecs', 'Canal flow (cusecs)'],
  ['source', 'Source'],
  ['model_version', 'Model version'],
  ['recommendation_mm', 'Recommendation (mm)'],
  ['risk_band', 'Irrigation stress band'],
  ['risk_score', 'Irrigation stress score'],
];

function sourceBadge(source) {
  return source === 'model_prediction'
    ? `<span class="chip chip--emerald">model</span>`
    : `<span class="chip chip--amber">fallback</span>`;
}

/** Phase 10 — either the real recorded outcome, or a "Record actual" action.
 * Feeds GET /api/v1/monitoring/performance's honest MAE/RMSE (see
 * monitoring.js) — never a fabricated value. */
function actualCell(row) {
  if (row.actual) {
    return `<span class="mono" title="Recorded ${new Date(row.actual.observed_at).toLocaleString()}${row.actual.note ? ` — ${escapeHtml(row.actual.note)}` : ''}">${row.actual.actual_irrigation_mm.toFixed(1)}mm</span>`;
  }
  return `<button type="button" class="btn btn--sm btn--ghost" data-record-actual="${row.id}">Record actual</button>`;
}

function recordActualModalTemplate() {
  return `
    <div class="modal__header"><h2>Record actual outcome</h2></div>
    <form class="modal__body" id="actual-form" novalidate>
      <p class="text-muted" style="font-size:12.5px;margin:-4px 0 4px">
        How much water was actually applied for this prediction? This feeds the real,
        honest model-performance tracking on the Monitoring page.
      </p>
      <div class="field">
        <label for="actual-mm">Actual irrigation applied (mm)</label>
        <input class="input" id="actual-mm" type="number" min="0" max="200" step="0.1" required />
        <div class="field-error" data-error-for="mm"></div>
      </div>
      <div class="field">
        <label for="actual-note">Note (optional)</label>
        <input class="input" id="actual-note" maxlength="500" placeholder="e.g. measured with a flow meter" />
      </div>
      <button type="submit" class="btn btn--primary btn--block">Save</button>
    </form>
  `;
}

/** Opens the "Record actual" modal for one history row. Calls
 * onRecorded(updatedRow) on success so the caller can patch its own table
 * state without a full reload. */
function openRecordActualModal(row, onRecorded) {
  const body = document.createElement('div');
  body.innerHTML = recordActualModalTemplate();
  const { close, modal } = openModal(body, { maxWidth: '380px' });

  const form = modal.querySelector('#actual-form');
  const mmInput = modal.querySelector('#actual-mm');
  const noteInput = modal.querySelector('#actual-note');
  const mmError = modal.querySelector('[data-error-for="mm"]');
  mmInput.focus();

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    mmError.textContent = '';
    const mm = Number(mmInput.value);
    if (!Number.isFinite(mm) || mm < 0 || mm > 200) {
      mmError.textContent = 'Enter a value between 0 and 200mm.';
      return;
    }

    const submitBtn = form.querySelector('button[type="submit"]');
    submitBtn.disabled = true;
    submitBtn.textContent = 'Saving…';

    try {
      const updated = await recordActual(row.id, {
        actual_irrigation_mm: mm,
        note: noteInput.value.trim() || null,
      });
      toastSuccess(`Recorded ${updated.actual.actual_irrigation_mm.toFixed(1)}mm for this prediction.`);
      close();
      onRecorded(updated);
    } catch (err) {
      submitBtn.disabled = false;
      submitBtn.textContent = 'Save';
      if (err instanceof ApiError && err.status === 409) {
        toastError('An actual outcome was already recorded for this prediction.');
        close();
      } else {
        toastError(err instanceof ApiError ? err.message : 'Something went wrong.');
      }
    }
  });
}

function toCsv(rows, fieldsById) {
  const lines = [CSV_COLUMNS.map(([, label]) => `"${label}"`).join(',')];
  for (const row of rows) {
    const field = row.field_id ? fieldsById.get(row.field_id) : null;
    const record = { ...row, field_name: field ? field.name : '' };
    lines.push(
      CSV_COLUMNS.map(([key]) => {
        const value = record[key] ?? '';
        return `"${String(value).replace(/"/g, '""')}"`;
      }).join(',')
    );
  }
  return lines.join('\r\n');
}

function downloadCsv(csv, filename) {
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

export function mountHistory(root) {
  if (!isLoggedIn()) {
    root.innerHTML = `
      <div class="view-header"><div><h1>History</h1><p>Your past predictions, filterable and exportable.</p></div></div>
      <div class="card"></div>
    `;
    root.querySelector('.card').appendChild(
      emptyState({ icon: ICONS.user, title: 'Log in to see your prediction history', desc: 'Your past predictions will appear here once you have an account.' })
    );
    return;
  }

  root.innerHTML = `
    <div class="view-header">
      <div>
        <h1>History</h1>
        <p>Filterable log of your past predictions.</p>
      </div>
      <button type="button" class="btn btn--sm" id="export-csv-btn">${ICONS.download}<span>Export CSV</span></button>
    </div>

    <div class="card">
      <div class="card__header"><span class="card__title">${ICONS.filter}Filters</span></div>
      <div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px">
        <div class="field"><label for="hist-district">District</label><select class="select" id="hist-district"><option value="">All districts</option></select></div>
        <div class="field"><label for="hist-crop">Crop</label><select class="select" id="hist-crop"><option value="">All crops</option></select></div>
        <div class="field"><label for="hist-field">Field</label><select class="select" id="hist-field"><option value="">All fields</option></select></div>
        <div class="field"><label for="hist-from">From</label><input class="input" type="date" id="hist-from" /></div>
        <div class="field"><label for="hist-to">To</label><input class="input" type="date" id="hist-to" /></div>
      </div>
    </div>

    <div class="card">
      <div class="card__header"><span class="card__title">${ICONS.analytics}Recommendation trend</span></div>
      <div id="trend-body">${skeleton.block(180)}</div>
    </div>

    <div class="card">
      <div class="card__header"><span class="card__title">${ICONS.history}Predictions</span></div>
      <div id="table-body">${skeleton.block(320)}</div>
      <div class="flex items-center justify-between" id="pagination-row" style="margin-top:12px" hidden>
        <span class="text-muted" style="font-size:12px" id="pagination-label"></span>
        <div class="flex gap-2">
          <button type="button" class="btn btn--sm" id="prev-page-btn">Previous</button>
          <button type="button" class="btn btn--sm" id="next-page-btn">Next</button>
        </div>
      </div>
    </div>
  `;

  const districtSelect = root.querySelector('#hist-district');
  const cropSelect = root.querySelector('#hist-crop');
  const fieldSelect = root.querySelector('#hist-field');
  const fromInput = root.querySelector('#hist-from');
  const toInput = root.querySelector('#hist-to');
  const trendBody = root.querySelector('#trend-body');
  const tableBody = root.querySelector('#table-body');
  const paginationRow = root.querySelector('#pagination-row');
  const paginationLabel = root.querySelector('#pagination-label');
  const prevBtn = root.querySelector('#prev-page-btn');
  const nextBtn = root.querySelector('#next-page-btn');
  const exportBtn = root.querySelector('#export-csv-btn');

  let trendChart = null;
  let currentRows = [];
  let fieldsById = new Map();
  let page = 0;

  async function loadFilters() {
    try {
      const [meta, fields] = await Promise.all([getMeta(), getFields()]);
      districtSelect.innerHTML =
        '<option value="">All districts</option>' +
        Object.entries(meta.districts_by_province)
          .map(([province, districts]) => `<optgroup label="${escapeHtml(province)}">${districts.map((d) => `<option value="${escapeHtml(d)}">${escapeHtml(d)}</option>`).join('')}</optgroup>`)
          .join('');
      cropSelect.innerHTML = '<option value="">All crops</option>' + meta.crops.map((c) => `<option value="${escapeHtml(c)}">${escapeHtml(c)}</option>`).join('');
      fieldsById = new Map(fields.map((f) => [f.id, f]));
      fieldSelect.innerHTML = '<option value="">All fields</option>' + fields.map((f) => `<option value="${f.id}">${escapeHtml(f.name)}</option>`).join('');
    } catch (err) {
      toastError(`Could not load filter options: ${err.message}`);
    }
  }

  function renderTablePage() {
    const start = page * PAGE_SIZE;
    const pageRows = currentRows.slice(start, start + PAGE_SIZE);
    const totalPages = Math.max(1, Math.ceil(currentRows.length / PAGE_SIZE));

    if (!currentRows.length) {
      tableBody.innerHTML = '';
      tableBody.appendChild(
        emptyState({
          icon: ICONS.history,
          title: 'No predictions match these filters',
          desc: 'Try widening the date range or clearing a filter.',
        })
      );
      paginationRow.hidden = true;
      return;
    }

    tableBody.innerHTML = `
      <div class="table-wrap">
        <table class="table">
          <thead>
            <tr>
              <th>Datetime</th><th>Field</th><th>District</th><th>Crop</th><th>Soil moisture</th>
              <th>Canal flow</th><th>Source</th><th>Model version</th><th>Recommendation</th><th>Irrigation stress</th><th>Actual</th>
            </tr>
          </thead>
          <tbody>
            ${pageRows
              .map((r) => {
                const field = r.field_id ? fieldsById.get(r.field_id) : null;
                return `
                  <tr>
                    <td>${new Date(r.created_at).toLocaleString()}</td>
                    <td>${field ? escapeHtml(field.name) : '<span class="text-muted">—</span>'}</td>
                    <td>${escapeHtml(r.district)}</td>
                    <td>${escapeHtml(r.crop_type)}</td>
                    <td class="mono">${r.soil_moisture_pct}%</td>
                    <td class="mono">${r.canal_flow_cusecs}</td>
                    <td>${sourceBadge(r.source)}</td>
                    <td class="code">${escapeHtml(r.model_version || '—')}</td>
                    <td class="mono">${r.recommendation_mm.toFixed(1)}mm</td>
                    <td>${r.risk_band ? riskChip({ score: r.risk_score, band: r.risk_band }) : '<span class="text-muted">—</span>'}</td>
                    <td>${actualCell(r)}</td>
                  </tr>
                `;
              })
              .join('')}
          </tbody>
        </table>
      </div>
    `;

    paginationRow.hidden = false;
    paginationLabel.textContent = `Page ${page + 1} of ${totalPages} · ${currentRows.length} record${currentRows.length === 1 ? '' : 's'}`;
    prevBtn.disabled = page === 0;
    nextBtn.disabled = page >= totalPages - 1;
  }

  function renderTrendChart() {
    if (trendChart) {
      trendChart.destroy();
      trendChart = null;
    }
    if (!currentRows.length) {
      trendBody.innerHTML = '';
      trendBody.appendChild(emptyState({ icon: ICONS.analytics, title: 'Not enough history yet — run some predictions', desc: 'The trend chart needs at least one prediction in the selected range.' }));
      return;
    }
    const chronological = [...currentRows].reverse();
    trendBody.innerHTML = '<div style="height:180px"><canvas id="hist-trend-chart"></canvas></div>';
    const canvas = trendBody.querySelector('#hist-trend-chart');
    trendChart = createChart(canvas, {
      data: {
        labels: chronological.map((r) => new Date(r.created_at).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })),
        datasets: [
          {
            type: 'line',
            label: 'Recommendation (mm)',
            data: chronological.map((r) => r.recommendation_mm),
            borderColor: seriesColor('recommendation'),
            backgroundColor: seriesColor('recommendation'),
            tension: 0.3,
            borderWidth: 2,
            pointRadius: 2,
          },
        ],
      },
      options: {
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: { y: { ticks: { callback: (v) => tickLabel(v, 'mm') } } },
      },
    });
  }

  async function load() {
    tableBody.innerHTML = skeleton.block(320);
    trendBody.innerHTML = skeleton.block(180);
    paginationRow.hidden = true;
    page = 0;

    const params = { limit: FETCH_LIMIT };
    if (districtSelect.value) params.district = districtSelect.value;
    if (cropSelect.value) params.crop = cropSelect.value;
    if (fieldSelect.value) params.field_id = fieldSelect.value;
    if (fromInput.value) params.from = fromInput.value;
    if (toInput.value) params.to = toInput.value;

    try {
      currentRows = await getHistory(params);
      renderTablePage();
      renderTrendChart();
    } catch (err) {
      tableBody.innerHTML = '';
      tableBody.appendChild(errorState({ message: err.message, onRetry: load }));
      trendBody.innerHTML = '';
    }
  }

  tableBody.addEventListener('click', (e) => {
    const btn = e.target.closest('[data-record-actual]');
    if (!btn) return;
    const id = Number(btn.dataset.recordActual);
    const row = currentRows.find((r) => r.id === id);
    if (!row) return;
    openRecordActualModal(row, (updated) => {
      row.actual = updated.actual;
      renderTablePage();
    });
  });

  [districtSelect, cropSelect, fieldSelect, fromInput, toInput].forEach((el) => el.addEventListener('change', load));
  prevBtn.addEventListener('click', () => {
    if (page > 0) {
      page -= 1;
      renderTablePage();
    }
  });
  nextBtn.addEventListener('click', () => {
    const totalPages = Math.max(1, Math.ceil(currentRows.length / PAGE_SIZE));
    if (page < totalPages - 1) {
      page += 1;
      renderTablePage();
    }
  });
  exportBtn.addEventListener('click', () => {
    if (!currentRows.length) {
      toastError('Nothing to export — no predictions match the current filters.');
      return;
    }
    downloadCsv(toCsv(currentRows, fieldsById), `lehar-history-${new Date().toISOString().slice(0, 10)}.csv`);
  });

  loadFilters().then(load);

  return () => {
    if (trendChart) trendChart.destroy();
  };
}
