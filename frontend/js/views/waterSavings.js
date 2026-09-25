/** Water Savings view — pure client-side unit conversion + arithmetic, no
 * backend call except an optional prefill of "recommended" from the user's
 * most recent prediction. Formula: 1mm of water depth over 1m² = 1 litre,
 * so (current_mm - recommended_mm) x area_m2 = litres saved per 24h. */

import { getHistory } from '../api.js';
import { isLoggedIn } from '../state.js';
import { escapeHtml } from '../ui.js';
import { ICONS } from '../icons.js';

const UNIT_TO_M2 = {
  acres: 4046.86,
  hectares: 10000,
  kanals: 505.857,
};

function formatNumber(n, decimals = 0) {
  return n.toLocaleString(undefined, { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
}

export function mountWaterSavings(root) {
  root.innerHTML = `
    <div class="view-header">
      <div>
        <h1>Water Savings</h1>
        <p>Estimate the water saved by irrigating to the model's recommendation instead of your current practice.</p>
      </div>
    </div>

    <div class="grid grid--2col">
      <div class="card">
        <div class="card__header"><span class="card__title">${ICONS.waterSavings}Field &amp; irrigation inputs</span></div>
        <div class="flex flex-col gap-4">
          <div class="field">
            <label for="ws-area">Field area</label>
            <div class="flex gap-2">
              <input class="input" type="number" id="ws-area" min="0" step="0.1" value="5" />
              <select class="select" id="ws-unit" style="max-width:130px">
                <option value="acres">Acres</option>
                <option value="hectares">Hectares</option>
                <option value="kanals">Kanals</option>
              </select>
            </div>
          </div>
          <div class="field">
            <label for="ws-current">Current irrigation practice (mm / 24h)</label>
            <input class="input" type="number" id="ws-current" min="0" step="0.1" value="40" />
          </div>
          <div class="field">
            <label for="ws-recommended">Recommended irrigation (mm / 24h)</label>
            <input class="input" type="number" id="ws-recommended" min="0" step="0.1" value="0" />
            <span class="field-hint" id="ws-prefill-hint"></span>
          </div>
        </div>
      </div>

      <div class="card">
        <div class="card__header"><span class="card__title">${ICONS.checkCircle}Estimated savings</span></div>
        <div id="ws-result"></div>
      </div>
    </div>

    <div class="card">
      <div class="card__header"><span class="card__title">${ICONS.info}How this is calculated</span></div>
      <div class="flex flex-col gap-4">
        <div class="table-wrap">
          <table class="table">
            <tbody>
              <tr><td>Formula</td><td class="code">(current_mm − recommended_mm) × area_m² = litres saved / 24h</td></tr>
              <tr><td>Water-depth identity</td><td class="code">1mm over 1m² = 1 litre</td></tr>
              <tr><td>1 acre</td><td class="code">4,046.86 m²</td></tr>
              <tr><td>1 hectare</td><td class="code">10,000 m²</td></tr>
              <tr><td>1 kanal</td><td class="code">505.857 m²</td></tr>
            </tbody>
          </table>
        </div>
        <p class="text-muted" style="font-size:11.5px;line-height:1.5">
          Estimate for a 24h window, assumes uniform application; synthetic-data research prototype — not agronomic advice.
        </p>
      </div>
    </div>
  `;

  const areaInput = root.querySelector('#ws-area');
  const unitSelect = root.querySelector('#ws-unit');
  const currentInput = root.querySelector('#ws-current');
  const recommendedInput = root.querySelector('#ws-recommended');
  const prefillHint = root.querySelector('#ws-prefill-hint');
  const resultEl = root.querySelector('#ws-result');

  function render() {
    const area = Number(areaInput.value) || 0;
    const unit = unitSelect.value;
    const current = Number(currentInput.value) || 0;
    const recommended = Number(recommendedInput.value) || 0;
    const areaM2 = area * UNIT_TO_M2[unit];
    const differenceMm = current - recommended;
    const litres = differenceMm * areaM2;
    const cubicMetres = litres / 1000;

    if (differenceMm <= 0) {
      resultEl.innerHTML = `
        <div class="state-block">
          ${ICONS.info}
          <div class="state-block__title">No savings from this comparison</div>
          <div class="state-block__desc">Recommended irrigation (${formatNumber(recommended, 1)}mm) is at or above your current practice (${formatNumber(current, 1)}mm), so switching wouldn't reduce water use here.</div>
        </div>
      `;
      return;
    }

    resultEl.innerHTML = `
      <div class="flex flex-col gap-4">
        <div>
          <div class="text-muted" style="font-size:11px;text-transform:uppercase;letter-spacing:0.04em">Water saved per 24h</div>
          <div class="kpi__value" style="font-size:32px">${formatNumber(litres)}<small> litres</small></div>
          <div class="text-secondary" style="font-size:13px">= ${formatNumber(cubicMetres, 1)} m³</div>
        </div>
        <div class="table-wrap">
          <table class="table">
            <tbody>
              <tr><td>Field area</td><td class="mono">${formatNumber(area, 2)} ${escapeHtml(unit)} = ${formatNumber(areaM2, 1)} m²</td></tr>
              <tr><td>Depth difference</td><td class="mono">${formatNumber(current, 1)} − ${formatNumber(recommended, 1)} = ${formatNumber(differenceMm, 1)}mm</td></tr>
            </tbody>
          </table>
        </div>
      </div>
    `;
  }

  [areaInput, unitSelect, currentInput, recommendedInput].forEach((el) => el.addEventListener('input', render));

  async function prefillRecommended() {
    if (!isLoggedIn()) return;
    try {
      const history = await getHistory({ limit: 1 });
      if (history.length) {
        recommendedInput.value = history[0].recommendation_mm;
        prefillHint.textContent = `Prefilled from your latest prediction (${escapeHtml(history[0].district)}, ${new Date(history[0].created_at).toLocaleDateString()}).`;
        render();
      }
    } catch {
      // Prefill is a convenience only — silently leave the field as-is on failure.
    }
  }

  render();
  prefillRecommended();
}
