/** Models page (#/models) — Phase 7 MLOps: every trained model version with
 * real evaluation metrics (GET /api/v1/models), which one is PRODUCTION, a
 * model-card detail panel (incl. the quality-gate reasons for pipeline-
 * trained versions), safe Promote/Rollback with a confirmation modal (auth
 * required — reuses the existing login), and a link out to the local MLflow
 * UI. Works read-only (no promote/rollback controls) without a login, and
 * degrades gracefully if MLflow itself is down (this page reads entirely
 * from registry.json via the backend, never from MLflow directly). */

import { getModels, promoteModel, rollbackModel } from '../api.js';
import { isLoggedIn } from '../state.js';
import { skeleton, errorState, emptyState, escapeHtml, openModal, toastSuccess, toastError } from '../ui.js';
import { ICONS } from '../icons.js';

function sourceChip(source) {
  return source === 'pipeline' ? `<span class="chip chip--sky">pipeline</span>` : `<span class="chip">legacy</span>`;
}

function gateChip(gate) {
  if (!gate) return '';
  return gate.passed
    ? `<span class="chip chip--emerald">${ICONS.checkCircle}<span>gate PASS</span></span>`
    : `<span class="chip chip--red">${ICONS.xCircle}<span>gate FAIL</span></span>`;
}

function fmt(v, digits = 4) {
  return typeof v === 'number' ? v.toFixed(digits) : '—';
}

function versionRowMarkup(v, loggedIn) {
  const m = v.metrics || {};
  return `
    <tr data-version="${escapeHtml(v.version)}" class="${v.is_production ? 'is-production' : ''}">
      <td class="code">${escapeHtml(v.version)}</td>
      <td>${v.created_at ? new Date(v.created_at).toLocaleString() : '—'}</td>
      <td class="mono">${fmt(m.mae)}</td>
      <td class="mono">${fmt(m.rmse)}</td>
      <td class="mono">${fmt(m.r2)}</td>
      <td>${sourceChip(v.source)}</td>
      <td>${v.is_production ? '<span class="chip chip--emerald">PRODUCTION</span>' : ''}</td>
      <td>
        <div class="flex gap-2" style="justify-content:flex-end">
          <button type="button" class="btn btn--icon btn--ghost" data-action="details" data-version="${escapeHtml(v.version)}" aria-label="Version details" title="Details">${ICONS.info}</button>
          ${
            !v.is_production && loggedIn
              ? `<button type="button" class="btn btn--sm btn--primary" data-action="promote" data-version="${escapeHtml(v.version)}">${ICONS.rocket}<span>Promote</span></button>`
              : ''
          }
        </div>
      </td>
    </tr>
  `;
}

function detailPanelMarkup(v) {
  const m = v.metrics || {};
  const gateReasons =
    v.gate && Array.isArray(v.gate.reasons)
      ? `
        <div>
          <div class="text-muted" style="font-size:11px;text-transform:uppercase;letter-spacing:.04em;margin-bottom:6px">Quality gate reasons</div>
          <ul style="font-size:13px;line-height:1.6;padding-left:18px;margin:0;color:var(--text-secondary)">
            ${v.gate.reasons.map((r) => `<li>${escapeHtml(r)}</li>`).join('')}
          </ul>
        </div>
      `
      : '';
  return `
    <div class="modal__header"><h2>${escapeHtml(v.version)}</h2></div>
    <div class="modal__body">
      <div class="flex gap-2" style="flex-wrap:wrap">
        ${v.is_production ? '<span class="chip chip--emerald">PRODUCTION</span>' : ''}
        ${sourceChip(v.source)}
        ${gateChip(v.gate)}
      </div>
      <div class="table-wrap">
        <table class="table">
          <tbody>
            <tr><td>Created</td><td>${v.created_at ? new Date(v.created_at).toLocaleString() : '—'}</td></tr>
            <tr><td>MAE</td><td class="mono">${fmt(m.mae)} mm</td></tr>
            <tr><td>RMSE</td><td class="mono">${fmt(m.rmse)} mm</td></tr>
            <tr><td>R²</td><td class="mono">${fmt(m.r2)}</td></tr>
            <tr><td>Train / test rows</td><td class="mono">${m.n_train ?? '—'} / ${m.n_test ?? '—'}</td></tr>
            <tr><td>Trees / max depth</td><td class="mono">${m.n_estimators ?? '—'} / ${m.max_depth ?? '—'}</td></tr>
            <tr><td>MLflow run</td><td class="code">${escapeHtml(v.mlflow_run_id || '—')}</td></tr>
            <tr><td>MLflow model version</td><td class="code">${escapeHtml(v.mlflow_model_version || '—')}</td></tr>
          </tbody>
        </table>
      </div>
      ${gateReasons}
    </div>
  `;
}

function confirmationMarkup({ title, body, confirmLabel, confirmIcon }) {
  return `
    <div class="modal__header"><h2>${escapeHtml(title)}</h2></div>
    <div class="modal__body">
      <p style="font-size:13.5px;line-height:1.6;color:var(--text-secondary)">${body}</p>
      <div class="flex gap-2" style="justify-content:flex-end;margin-top:16px">
        <button type="button" class="btn btn--ghost" data-close>Cancel</button>
        <button type="button" class="btn btn--primary" data-confirm>${confirmIcon}<span>${escapeHtml(confirmLabel)}</span></button>
      </div>
    </div>
  `;
}

export function mountModels(root) {
  root.innerHTML = `
    <div class="view-header">
      <div>
        <h1>Models</h1>
        <p>Every trained model version, real evaluation metrics, and safe promote/rollback (Phase 7 MLOps).</p>
      </div>
      <div class="flex gap-2">
        <button type="button" class="btn btn--sm" id="rollback-btn" hidden>${ICONS.undo}<span>Rollback</span></button>
        <a class="btn btn--sm btn--ghost" id="mlflow-link" href="http://127.0.0.1:5000" target="_blank" rel="noopener">${ICONS.externalLink}<span>Open MLflow</span></a>
      </div>
    </div>

    <div class="card">
      <div class="card__header"><span class="card__title">${ICONS.refresh}Train a new candidate</span></div>
      <p class="text-secondary" style="font-size:13px">Run <span class="code">scripts\\retrain.bat</span> (or <span class="code">scripts/retrain.sh</span> on macOS/Linux) from the project root. A candidate only becomes production automatically if it passes the quality gate — see <span class="code">docs/MLOPS.md</span> for the exact thresholds.</p>
    </div>

    <div class="card">
      <div class="card__header"><span class="card__title">${ICONS.models}Model versions</span></div>
      <div id="models-body">${skeleton.block(280)}</div>
    </div>
  `;

  let modelsData = null;
  const rollbackBtn = root.querySelector('#rollback-btn');
  const mlflowLink = root.querySelector('#mlflow-link');

  async function load() {
    const bodyEl = root.querySelector('#models-body');
    try {
      modelsData = await getModels();
      mlflowLink.href = modelsData.mlflow_url;

      if (!modelsData.versions.length) {
        bodyEl.innerHTML = '';
        bodyEl.appendChild(
          emptyState({
            icon: ICONS.models,
            title: 'No trained models yet',
            desc: 'Run scripts\\retrain.bat to train the first candidate.',
          })
        );
        rollbackBtn.hidden = true;
        return;
      }

      const loggedIn = isLoggedIn();
      const sorted = [...modelsData.versions].sort((a, b) => (b.created_at || '').localeCompare(a.created_at || ''));
      bodyEl.innerHTML = `
        <div class="table-wrap">
          <table class="table">
            <thead>
              <tr><th>Version</th><th>Created</th><th>MAE</th><th>RMSE</th><th>R²</th><th>Source</th><th>Status</th><th></th></tr>
            </thead>
            <tbody>${sorted.map((v) => versionRowMarkup(v, loggedIn)).join('')}</tbody>
          </table>
        </div>
      `;

      rollbackBtn.hidden = !(loggedIn && modelsData.history && modelsData.history.length > 0);

      bodyEl.querySelectorAll('[data-action="details"]').forEach((btn) => {
        btn.addEventListener('click', () => {
          const version = modelsData.versions.find((v) => v.version === btn.dataset.version);
          if (version) openModal(Object.assign(document.createElement('div'), { innerHTML: detailPanelMarkup(version) }), { maxWidth: '480px' });
        });
      });
      bodyEl.querySelectorAll('[data-action="promote"]').forEach((btn) => {
        btn.addEventListener('click', () => confirmPromote(btn.dataset.version));
      });
    } catch (err) {
      bodyEl.innerHTML = '';
      bodyEl.appendChild(errorState({ message: err.message, onRetry: load }));
    }
  }

  function openConfirmation(opts, onConfirm) {
    const body = document.createElement('div');
    body.innerHTML = confirmationMarkup(opts);
    const { close, modal } = openModal(body, { maxWidth: '440px' });
    modal.querySelector('[data-close]').addEventListener('click', close);
    modal.querySelector('[data-confirm]').addEventListener('click', async () => {
      const confirmBtn = modal.querySelector('[data-confirm]');
      confirmBtn.disabled = true;
      try {
        await onConfirm();
        close();
      } catch (err) {
        toastError(err.message);
        confirmBtn.disabled = false;
      }
    });
  }

  function confirmPromote(version) {
    if (!isLoggedIn()) {
      toastError('Log in to promote a model version.');
      return;
    }
    openConfirmation(
      {
        title: 'Promote this version?',
        body: `Version <span class="code">${escapeHtml(version)}</span> will become the production model immediately — every new prediction and the Explainability page will use it right away. The current production version is kept in history and can be rolled back to at any time.`,
        confirmLabel: 'Promote',
        confirmIcon: ICONS.rocket,
      },
      async () => {
        const result = await promoteModel(version);
        toastSuccess(result.message || `Promoted ${version}.`);
        load();
      }
    );
  }

  function confirmRollback() {
    if (!isLoggedIn() || !modelsData || !modelsData.history.length) return;
    const target = modelsData.history[0];
    openConfirmation(
      {
        title: 'Roll back?',
        body: `This promotes the previous production version (<span class="code">${escapeHtml(target)}</span>) back to production immediately.`,
        confirmLabel: 'Roll back',
        confirmIcon: ICONS.undo,
      },
      async () => {
        const result = await rollbackModel();
        toastSuccess(result.message || 'Rolled back.');
        load();
      }
    );
  }

  rollbackBtn.addEventListener('click', confirmRollback);

  load();
}
