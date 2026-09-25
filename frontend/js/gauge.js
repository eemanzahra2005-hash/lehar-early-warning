/**
 * Semicircle SVG gauge (0-max mm) with a colored zone arc (Low/Moderate/High
 * demand bands) + a needle. gaugeMarkup() is a pure markup generator —
 * colors reference CSS custom properties so it re-themes free. The needle
 * is drawn at rest (fraction 0); call animateGaugeNeedle() right after
 * inserting the markup into the DOM to sweep it to the real value.
 */

const DEFAULT_ZONES = [
  { from: 0, to: 15, tone: 'var(--emerald)', label: 'Low' },
  { from: 15, to: 35, tone: 'var(--amber)', label: 'Moderate' },
  { from: 35, to: 60, tone: 'var(--red)', label: 'High' },
];

const CX = 100;
const CY = 100;
const ARC_R = 78;
const NEEDLE_R = 62;
const TICK_R = 92;

function pointAt(frac, radius) {
  const angle = (180 - frac * 180) * (Math.PI / 180);
  return { x: CX + radius * Math.cos(angle), y: CY - radius * Math.sin(angle) };
}

const easeOutCubic = (t) => 1 - Math.pow(1 - t, 3);

function prefersReducedMotion() {
  return window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

export function gaugeMarkup(value, { max = 60, size = 240, zones = DEFAULT_ZONES } = {}) {
  const clamped = Math.max(0, Math.min(Number(value) || 0, max));

  const zoneArcs = zones
    .map((z) => {
      const fFrom = Math.max(0, Math.min(z.from / max, 1));
      const fTo = Math.max(0, Math.min(z.to / max, 1));
      const start = pointAt(fFrom, ARC_R);
      const end = pointAt(fTo, ARC_R);
      const largeArc = fTo - fFrom > 0.5 ? 1 : 0;
      return `<path d="M ${start.x.toFixed(1)} ${start.y.toFixed(1)} A ${ARC_R} ${ARC_R} 0 ${largeArc} 1 ${end.x.toFixed(1)} ${end.y.toFixed(1)}" stroke="${z.tone}" stroke-width="14" fill="none" stroke-linecap="butt"/>`;
    })
    .join('');

  const tickLabels = zones
    .map((z) => {
      const fMid = (z.from + z.to) / 2 / max;
      const p = pointAt(fMid, TICK_R);
      return `<text x="${p.x.toFixed(1)}" y="${p.y.toFixed(1)}" font-size="8.5" fill="var(--text-muted)" text-anchor="middle" dominant-baseline="middle">${z.label}</text>`;
    })
    .join('');

  const restNeedle = pointAt(0, NEEDLE_R);

  return `
    <svg class="gauge__svg" viewBox="0 0 200 118" width="${size}" height="${Math.round(size * 0.59)}" role="img" aria-label="Irrigation gauge, ${clamped} of ${max} millimeters">
      ${zoneArcs}
      <line class="gauge__needle" data-frac="0" x1="${CX}" y1="${CY}" x2="${restNeedle.x.toFixed(1)}" y2="${restNeedle.y.toFixed(1)}" stroke="var(--text-primary)" stroke-width="3" stroke-linecap="round"/>
      <circle cx="${CX}" cy="${CY}" r="5.5" fill="var(--text-primary)"/>
      <text x="6" y="112" font-size="9" fill="var(--text-muted)" text-anchor="start">0</text>
      <text x="194" y="112" font-size="9" fill="var(--text-muted)" text-anchor="end">${max}mm</text>
      ${tickLabels}
    </svg>
  `;
}

/** Sweeps the needle from rest (0) to `value` with a 400ms ease-out. Call
 * once, right after the gaugeMarkup() HTML has been inserted into the DOM. */
export function animateGaugeNeedle(svgEl, value, { max = 60, duration = 400 } = {}) {
  const needle = svgEl && svgEl.querySelector('.gauge__needle');
  if (!needle) return;
  const clamped = Math.max(0, Math.min(Number(value) || 0, max));
  const targetFrac = max > 0 ? clamped / max : 0;

  if (prefersReducedMotion() || duration <= 0) {
    const p = pointAt(targetFrac, NEEDLE_R);
    needle.setAttribute('x2', p.x.toFixed(1));
    needle.setAttribute('y2', p.y.toFixed(1));
    return;
  }

  const start = performance.now();
  function frame(now) {
    const t = Math.min(1, (now - start) / duration);
    const frac = easeOutCubic(t) * targetFrac;
    const p = pointAt(frac, NEEDLE_R);
    needle.setAttribute('x2', p.x.toFixed(1));
    needle.setAttribute('y2', p.y.toFixed(1));
    if (t < 1) requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);
}
