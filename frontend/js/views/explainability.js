/** Explainability page (#/explainability) — global feature importance
 * (mean |SHAP contribution| in mm, from GET /api/v1/explain/global), a
 * model card (real registry/metrics data from GET /api/v1/models/info),
 * and an honest "how to read this" section. Every number here is real,
 * computed data — nothing generated or invented (see
 * backend/app/services/explain.py, backend/ml/train_model.py's
 * compute_global_shap). */

import { getGlobalExplain, getModelInfo } from '../api.js';
import { skeleton, errorState, escapeHtml } from '../ui.js';
import { ICONS } from '../icons.js';
import { createChart, tickLabel, seriesColor } from '../charts.js';
import { FEATURE_LABELS } from '../explainUi.js';

function modelCardMarkup(info) {
  const m = info.metrics || {};
  const trainedAt = info.created_at ? new Date(info.created_at).toLocaleString() : 'unknown';
  const featureChips = info.feature_list
    .map((f) => `<span class="chip" style="margin:2px 4px 2px 0">${escapeHtml(FEATURE_LABELS[f] || f)}</span>`)
    .join('');
  return `
    <div class="table-wrap">
      <table class="table">
        <tbody>
          <tr><td>Model version</td><td class="code">${escapeHtml(info.version)}</td></tr>
          <tr><td>Algorithm</td><td>RandomForestRegressor (scikit-learn)</td></tr>
          <tr><td>Trained</td><td>${escapeHtml(trainedAt)}</td></tr>
          <tr><td>Dataset rows</td><td class="mono">${info.dataset_rows.toLocaleString()}</td></tr>
          <tr><td>Train / test split</td><td class="mono">${(m.n_train ?? 0).toLocaleString()} / ${(m.n_test ?? 0).toLocaleString()}</td></tr>
          <tr><td>Trees (n_estimators)</td><td class="mono">${m.n_estimators ?? '—'}</td></tr>
          <tr><td>Max depth</td><td class="mono">${m.max_depth ?? '—'}</td></tr>
          <tr><td>MAE</td><td class="mono">${typeof m.mae === 'number' ? m.mae.toFixed(4) : '—'} mm</td></tr>
          <tr><td>RMSE</td><td class="mono">${typeof m.rmse === 'number' ? m.rmse.toFixed(4) : '—'} mm</td></tr>
          <tr><td>R²</td><td class="mono">${typeof m.r2 === 'number' ? m.r2.toFixed(4) : '—'}</td></tr>
          <tr><td>Feature list</td><td style="white-space:normal">${featureChips}</td></tr>
        </tbody>
      </table>
    </div>
  `;
}

export function mountExplainability(root) {
  root.innerHTML = `
    <div class="view-header">
      <div>
        <h1>Explainability</h1>
        <p>How the irrigation recommendation model behaves overall, and how to read its numbers.</p>
      </div>
    </div>

    <div class="card">
      <div class="card__header"><span class="card__title">${ICONS.explainability}Global feature importance</span></div>
      <p class="text-muted" id="global-note" style="font-size:11.5px;margin-bottom:10px"></p>
      <div id="global-chart-body">${skeleton.block(280)}</div>
    </div>

    <div class="card">
      <div class="card__header"><span class="card__title">${ICONS.models}Model card</span></div>
      <div id="model-card-body">${skeleton.block(240)}</div>
    </div>

    <div class="card">
      <div class="card__header"><span class="card__title">${ICONS.info}How to read this</span></div>
      <div class="flex flex-col gap-2" style="font-size:13px;line-height:1.6;color:var(--text-secondary)">
        <p>This is a <strong>RandomForest regressor</strong> — a statistical model trained on synthetic data (see the footer disclaimer on every page). It is <strong>not an LLM</strong> and does not generate text: every sentence shown elsewhere in this app (e.g. the "Why this prediction?" panel) is template text filled in with real numbers from the model, never model-written prose.</p>
        <p>It is <strong>not an agronomist</strong>. The recommendations, risk score, and explanations are decision-support signals for a research/demo platform — not professional agronomic advice.</p>
        <p><strong>Global feature importance</strong> (above) shows, on average across a 500-row training sample, which inputs move the model's output the most — computed with SHAP (SHapley Additive exPlanations), a standard, real explainability technique for tree-based models, not an invented weighting.</p>
        <p>For any <em>single</em> prediction, see the "Why this prediction?" panel on the Predict page or Dashboard — it shows that specific row's real SHAP contributions, which can differ from the global ranking above (a feature that matters a lot on average may matter little for one particular field, and vice versa).</p>
      </div>
    </div>
  `;

  let chart = null;

  async function loadGlobal() {
    const bodyEl = root.querySelector('#global-chart-body');
    const noteEl = root.querySelector('#global-note');
    try {
      const data = await getGlobalExplain();
      if (!data.available) {
        bodyEl.innerHTML = '';
        bodyEl.appendChild(
          errorState({
            message: data.note || 'Global SHAP importance is not available for the currently loaded model version.',
          })
        );
        noteEl.textContent = '';
        return;
      }
      noteEl.textContent = `${data.note} (sample size: ${data.sample_size} rows, model ${data.model_version})`;
      const entries = Object.entries(data.mean_abs_shap_mm);
      bodyEl.innerHTML = `<div style="height:${Math.max(220, entries.length * 34)}px"><canvas id="global-shap-chart"></canvas></div>`;
      const canvas = bodyEl.querySelector('#global-shap-chart');
      chart = createChart(canvas, {
        data: {
          labels: entries.map(([f]) => FEATURE_LABELS[f] || f),
          datasets: [
            {
              type: 'bar',
              label: 'Mean |SHAP contribution| (mm)',
              data: entries.map(([, v]) => Number(v.toFixed(3))),
              backgroundColor: seriesColor('recommendation'),
              borderRadius: 4,
              maxBarThickness: 22,
            },
          ],
        },
        options: {
          indexAxis: 'y',
          maintainAspectRatio: false,
          plugins: { legend: { display: false } },
          scales: { x: { ticks: { callback: (v) => tickLabel(v, 'mm') } } },
        },
      });
    } catch (err) {
      bodyEl.innerHTML = '';
      bodyEl.appendChild(errorState({ message: err.message, onRetry: loadGlobal }));
    }
  }

  async function loadModelCard() {
    const bodyEl = root.querySelector('#model-card-body');
    try {
      const info = await getModelInfo();
      bodyEl.innerHTML = modelCardMarkup(info);
    } catch (err) {
      bodyEl.innerHTML = '';
      bodyEl.appendChild(errorState({ message: err.message, onRetry: loadModelCard }));
    }
  }

  loadGlobal();
  loadModelCard();

  return () => {
    if (chart) chart.destroy();
  };
}
