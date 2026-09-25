/**
 * Shared rendering for the Farm Risk Score (Phase 6, docs/RISK_SCORE.md) —
 * an IRRIGATION-STRESS (dryness) heuristic, distinct from the Flood Risk
 * Index shown elsewhere (frontend/js/views/map.js's Flood Watch mode).
 * Always labeled "Irrigation stress" in the UI so the two are never
 * confused. Every number here comes straight from the `risk` field on
 * POST /api/v1/predict / GET /api/v1/map/overview / POST /api/v1/compare —
 * a transparent arithmetic formula, never a black-box score.
 */

import { escapeHtml } from './ui.js';
import { ICONS } from './icons.js';

export const RISK_BAND_CHIP = { LOW: 'chip--emerald', MODERATE: 'chip--amber', HIGH: 'chip--red' };
export const RISK_BAND_TONE = { LOW: 'emerald', MODERATE: 'amber', HIGH: 'red' };

export const RISK_COMPONENT_LABELS = {
  moisture_deficit: 'Moisture deficit',
  et0_demand: 'ET0 demand',
  heat_stress: 'Heat stress',
  water_scarcity: 'Water scarcity',
  rain_relief: 'Rain relief (reduces risk)',
};

const DISCLAIMER = 'Transparent decision-support heuristic, not a validated agronomic index — see docs/RISK_SCORE.md.';

/** Small badge: "Irrigation stress: MODERATE · 46". Renders a neutral
 * "not available" chip if risk is null (never fabricated placeholder). */
export function riskChip(risk, { label = 'Irrigation stress' } = {}) {
  if (!risk) return `<span class="chip">${escapeHtml(label)}: n/a</span>`;
  const cls = RISK_BAND_CHIP[risk.band] || '';
  return `<span class="chip ${cls}" title="${escapeHtml(DISCLAIMER)}">${escapeHtml(label)}: ${risk.band} · ${risk.score.toFixed(0)}</span>`;
}

/** Component breakdown as five 0-1 mini bars, tinted to the overall band. */
export function riskComponentsMarkup(risk) {
  if (!risk) return '';
  const tone = RISK_BAND_TONE[risk.band] || 'amber';
  return `
    <div class="risk-bars">
      ${Object.entries(risk.components)
        .map(([key, value]) => {
          const pct = Math.max(0, Math.min(1, value)) * 100;
          return `
            <div class="risk-bar-row">
              <span class="risk-bar-row__label">${escapeHtml(RISK_COMPONENT_LABELS[key] || key)}</span>
              <span class="risk-bar-row__track"><span class="risk-bar-row__fill" style="width:${pct.toFixed(0)}%;background:var(--${tone})"></span></span>
              <span class="risk-bar-row__value mono">${value.toFixed(2)}</span>
            </div>
          `;
        })
        .join('')}
    </div>
    <p class="text-muted" style="font-size:10.5px;margin-top:8px">${escapeHtml(DISCLAIMER)}</p>
  `;
}

/** Click-to-expand: chip trigger + a floating component-breakdown popover
 * (positioned like the topbar's user-menu dropdown, so it overlays content
 * instead of pushing layout — important inside a KPI tile grid, where an
 * inline expansion would stretch the whole tile row). `id` must be unique
 * in the document (caller's responsibility) — wire with
 * wireExpandToggles() from frontend/js/ui.js after inserting this markup. */
export function riskExpandableMarkup(risk, { id, label = 'Irrigation stress' } = {}) {
  if (!risk) return riskChip(risk, { label });
  return `
    <span class="risk-expandable">
      <button type="button" class="risk-expandable__trigger" data-expand-toggle="${escapeHtml(id)}" aria-expanded="false">
        ${riskChip(risk, { label })}
        <span data-expand-caret class="risk-expandable__caret">${ICONS.chevronDown}</span>
      </button>
      <div class="risk-breakdown" id="${escapeHtml(id)}" hidden>
        ${riskComponentsMarkup(risk)}
      </div>
    </span>
  `;
}
