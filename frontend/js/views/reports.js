/** Reports view (Phase 12) — lets a logged-in user pick a scope (a saved
 * field, or a district) and a date range, then download a branded Excel or
 * PDF report from GET /api/v1/report. The download itself is a real file
 * (not JSON) — see api.js's downloadReport(), which returns a Blob + the
 * server-chosen filename that this view saves via a throwaway object URL. */

import { downloadReport, getFields, getMeta } from '../api.js';
import { isLoggedIn } from '../state.js';
import { emptyState, escapeHtml, toastError, toastSuccess } from '../ui.js';
import { ICONS } from '../icons.js';

const RANGES = [
  { id: '30', label: '30 days', days: 30 },
  { id: '90', label: '90 days', days: 90 },
  { id: 'custom', label: 'Custom', days: null },
];

function isoDate(date) {
  return date.toISOString().slice(0, 10);
}

function saveBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  // Revoke on a delay, not immediately — some browsers need the object URL
  // to still resolve for the download to actually start.
  setTimeout(() => URL.revokeObjectURL(url), 4000);
}

export function mountReports(root) {
  if (!isLoggedIn()) {
    root.innerHTML = `
      <div class="view-header"><div><h1>Reports</h1><p>Branded Excel and PDF exports of your irrigation data.</p></div></div>
      <div class="card"></div>
    `;
    root.querySelector('.card').appendChild(
      emptyState({
        icon: ICONS.reports,
        title: 'Log in to generate reports',
        desc: 'Reports are built from your own saved fields and prediction history.',
      })
    );
    return;
  }

  root.innerHTML = `
    <div class="view-header">
      <div>
        <h1>Reports</h1>
        <p>Generate a branded Excel or PDF report of your irrigation data.</p>
      </div>
    </div>

    <div class="grid grid--2col">
      <div class="flex flex-col gap-4">
        <div class="card">
          <div class="card__header"><span class="card__title">${ICONS.filter}Scope</span></div>
          <div class="flex flex-col gap-4">
            <div class="tabs" id="scope-tabs">
              <button type="button" class="tabs__btn is-active" data-scope="district">By district</button>
              <button type="button" class="tabs__btn" data-scope="field" id="scope-field-btn">By field</button>
            </div>
            <div class="field" id="district-scope-row">
              <label for="report-district">District</label>
              <select class="select" id="report-district"><option>Loading districts…</option></select>
            </div>
            <div class="field" id="field-scope-row" hidden>
              <label for="report-field">Saved field</label>
              <select class="select" id="report-field"></select>
            </div>
          </div>
        </div>

        <div class="card">
          <div class="card__header"><span class="card__title">${ICONS.history}Date range</span></div>
          <div class="flex flex-col gap-4">
            <div class="tabs" id="range-tabs">
              ${RANGES.map((r, i) => `<button type="button" class="tabs__btn${i === 0 ? ' is-active' : ''}" data-range="${r.id}">${r.label}</button>`).join('')}
            </div>
            <div class="flex gap-2" id="custom-range-row" hidden>
              <input class="input" type="date" id="report-from" />
              <input class="input" type="date" id="report-to" />
            </div>
          </div>
        </div>

        <div class="card">
          <div class="card__header"><span class="card__title">${ICONS.download}Download</span></div>
          <div class="flex flex-col gap-3">
            <button type="button" class="btn btn--primary btn--block" id="download-xlsx-btn">
              ${ICONS.download}<span>Download Excel</span>
            </button>
            <button type="button" class="btn btn--block" id="download-pdf-btn">
              ${ICONS.download}<span>Download PDF</span>
            </button>
          </div>
        </div>
      </div>

      <div class="card">
        <div class="card__header"><span class="card__title">${ICONS.info}What's in this report</span></div>
        <div class="flex flex-col gap-4">
          <p class="text-secondary" style="font-size:13px">
            Every report is built fresh from your real data at the moment you download it — nothing is
            pre-computed or cached.
          </p>
          <ul class="flex flex-col gap-2" style="font-size:13px;padding-left:18px;list-style:disc;color:var(--text-secondary)">
            <li>Branded header — generation time, current model version, and its real accuracy metrics</li>
            <li>Field details, if a saved field is selected</li>
            <li>Your latest matching prediction — inputs, weather, recommendation, risk band, and top SHAP factors</li>
            <li>Current live weather and the 7-day forecast for the chosen district</li>
            <li>Your prediction history for the selected range, as a table</li>
            <li>A recommendation-over-time chart</li>
          </ul>
          <p class="text-muted" style="font-size:11.5px;line-height:1.5">
            No predictions yet? The report still generates — with weather/forecast sections and an honest
            "no predictions recorded yet" note. Synthetic-data research prototype — not agronomic advice.
          </p>
        </div>
      </div>
    </div>
  `;

  const scopeTabs = root.querySelector('#scope-tabs');
  const districtRow = root.querySelector('#district-scope-row');
  const fieldRow = root.querySelector('#field-scope-row');
  const districtSelect = root.querySelector('#report-district');
  const fieldSelect = root.querySelector('#report-field');
  const scopeFieldBtn = root.querySelector('#scope-field-btn');

  const rangeTabs = root.querySelector('#range-tabs');
  const customRow = root.querySelector('#custom-range-row');
  const fromInput = root.querySelector('#report-from');
  const toInput = root.querySelector('#report-to');

  const xlsxBtn = root.querySelector('#download-xlsx-btn');
  const pdfBtn = root.querySelector('#download-pdf-btn');

  let scope = 'district';
  let selectedRange = '30';
  let fields = [];

  scopeTabs.querySelectorAll('.tabs__btn').forEach((btn) => {
    btn.addEventListener('click', () => {
      if (btn.disabled) return;
      scopeTabs.querySelectorAll('.tabs__btn').forEach((b) => b.classList.remove('is-active'));
      btn.classList.add('is-active');
      scope = btn.dataset.scope;
      districtRow.hidden = scope !== 'district';
      fieldRow.hidden = scope !== 'field';
    });
  });

  rangeTabs.querySelectorAll('.tabs__btn').forEach((btn) => {
    btn.addEventListener('click', () => {
      rangeTabs.querySelectorAll('.tabs__btn').forEach((b) => b.classList.remove('is-active'));
      btn.classList.add('is-active');
      selectedRange = btn.dataset.range;
      customRow.hidden = selectedRange !== 'custom';
    });
  });

  async function loadDistricts() {
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
    } catch {
      districtSelect.innerHTML = '<option value="">Districts unavailable</option>';
    }
  }

  async function loadFields() {
    try {
      fields = await getFields();
    } catch {
      fields = [];
    }
    if (!fields.length) {
      scopeFieldBtn.disabled = true;
      scopeFieldBtn.title = 'You have no saved fields yet — add one from the Predict page.';
      fieldSelect.innerHTML = '<option value="">No saved fields</option>';
      return;
    }
    fieldSelect.innerHTML = fields
      .map((f) => `<option value="${f.id}">${escapeHtml(f.name)} — ${escapeHtml(f.district)}</option>`)
      .join('');
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

  function buildParams(format) {
    const params = { format, ...computeRangeParams() };
    if (scope === 'field') {
      params.fieldId = fieldSelect.value || undefined;
    } else {
      params.district = districtSelect.value || undefined;
    }
    return params;
  }

  async function handleDownload(format, btn) {
    if (scope === 'field' && !fieldSelect.value) {
      toastError('Select a saved field first.');
      return;
    }
    const originalHtml = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = `<span class="is-spinning">${ICONS.refresh}</span><span>Generating…</span>`;
    try {
      const { blob, filename } = await downloadReport(buildParams(format));
      saveBlob(blob, filename);
      toastSuccess(`${format.toUpperCase()} report downloaded.`);
    } catch (err) {
      toastError(err.message || 'Report generation failed.');
    } finally {
      btn.disabled = false;
      btn.innerHTML = originalHtml;
    }
  }

  xlsxBtn.addEventListener('click', () => handleDownload('xlsx', xlsxBtn));
  pdfBtn.addEventListener('click', () => handleDownload('pdf', pdfBtn));

  loadDistricts();
  loadFields();
}
