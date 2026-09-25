/**
 * Shared rendering for real per-prediction explainability (Phase 6):
 * the "Why this prediction?" signed contribution bar chart, top-factor
 * sentences, and the model-agreement confidence line. Backed entirely by
 * POST /api/v1/predict's `explanation`/`confidence` fields (see
 * backend/app/services/explain.py) — every number here came from a real
 * SHAP computation on the trained model, never invented. When the backend
 * couldn't compute an explanation (explanation: null), these render an
 * honest "unavailable" note instead of guessing.
 */

import { escapeHtml } from './ui.js';

export const FEATURE_LABELS = {
  soil_moisture_pct: 'Soil moisture',
  evapotranspiration_mm: 'Evapotranspiration (ET0)',
  rainfall_mm: 'Rainfall',
  temperature_c: 'Temperature',
  humidity_pct: 'Humidity',
  canal_flow_cusecs: 'Canal flow',
  district: 'District',
  crop_type: 'Crop type',
  month: 'Month',
  day_of_year: 'Day of year',
  was_imputed: 'Imputed weather flag',
};

function formatFeatureValue(feature, value) {
  switch (feature) {
    case 'soil_moisture_pct':
    case 'humidity_pct':
      return `${Number(value).toFixed(0)}%`;
    case 'evapotranspiration_mm':
    case 'rainfall_mm':
      return `${Number(value).toFixed(1)}mm`;
    case 'temperature_c':
      return `${Number(value).toFixed(1)}°C`;
    case 'canal_flow_cusecs':
      return `${Number(value).toFixed(0)} cusecs`;
    case 'was_imputed':
      return value ? 'yes' : 'no';
    default:
      return String(value);
  }
}

/** Horizontal signed bar chart: green bars push the recommendation UP,
 * blue bars push it DOWN, each labeled with its real mm contribution.
 * Bar width is relative to the largest |contribution| in this set, so the
 * dominant factor(s) always reach the edge of the track. */
export function contributionBarsMarkup(contributions, { limit = 8 } = {}) {
  const rows = contributions.slice(0, limit);
  const maxAbs = Math.max(...rows.map((c) => Math.abs(c.contribution_mm)), 0.01);
  return `
    <div class="contrib-bars">
      ${rows
        .map((c) => {
          const pct = Math.min(100, (Math.abs(c.contribution_mm) / maxAbs) * 50);
          const isUp = c.contribution_mm >= 0;
          const sign = c.contribution_mm >= 0 ? '+' : '−';
          const label = FEATURE_LABELS[c.feature] || c.feature;
          const valueStr = formatFeatureValue(c.feature, c.value);
          return `
            <div class="contrib-bar-row" title="${escapeHtml(label)} = ${escapeHtml(valueStr)}">
              <span class="contrib-bar-row__label">${escapeHtml(label)}</span>
              <span class="contrib-bar-row__track">
                <span class="contrib-bar-row__fill contrib-bar-row__fill--${isUp ? 'up' : 'down'}" style="width:${pct.toFixed(1)}%"></span>
              </span>
              <span class="contrib-bar-row__value mono contrib-bar-row__value--${isUp ? 'up' : 'down'}">${sign}${Math.abs(c.contribution_mm).toFixed(1)}mm</span>
            </div>
          `;
        })
        .join('')}
    </div>
    <div class="contrib-bars__legend">
      <span><span class="contrib-bars__swatch contrib-bars__swatch--up"></span>Pushes irrigation up</span>
      <span><span class="contrib-bars__swatch contrib-bars__swatch--down"></span>Pushes irrigation down</span>
    </div>
  `;
}

export function topFactorsMarkup(topFactors) {
  if (!topFactors || !topFactors.length) return '';
  return `<ul class="factor-list">${topFactors.map((s) => `<li>${escapeHtml(s)}</li>`).join('')}</ul>`;
}

/** "18.0 mm — trees agree within ±2.1 mm" — the RandomForest's individual
 * trees' spread for this one row. Explicitly NOT a calibrated statistical
 * confidence interval (see backend/app/services/explain.py), so it's
 * labeled "model agreement" everywhere it appears. */
export function confidenceLineMarkup(value, confidence) {
  if (!confidence) return '';
  const [p10, p90] = confidence.interval_mm;
  return `${Number(value).toFixed(1)} mm — trees agree within ±${confidence.tree_std_mm.toFixed(1)} mm <span class="text-muted">(model agreement interval ${p10.toFixed(1)}–${p90.toFixed(1)} mm)</span>`;
}

/** Full "Why this prediction?" card body: contribution bars + top-factor
 * sentences, or an honest unavailable note if explanation is null (the
 * explainer failed — see explain.py's never-fabricate contract). */
export function explainPanelMarkup(explanation) {
  if (!explanation) {
    return `
      <div class="text-muted" style="font-size:12px">
        Explanation unavailable for this prediction (the SHAP explainer could not run) —
        the recommendation itself is unaffected.
      </div>
    `;
  }
  return `
    ${contributionBarsMarkup(explanation.contributions)}
    ${topFactorsMarkup(explanation.top_factors)}
  `;
}
