/**
 * Small count-up number animation for KPI tiles. Respects
 * prefers-reduced-motion by snapping straight to the final value.
 */

const easeOutCubic = (t) => 1 - Math.pow(1 - t, 3);

function prefersReducedMotion() {
  return window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

/** Animates `el`'s text content from 0 to `target`, formatted to `decimals`. */
export function countUp(el, target, { duration = 300, decimals = 1, from = 0 } = {}) {
  if (!el || !Number.isFinite(target)) return;

  if (prefersReducedMotion()) {
    el.textContent = target.toFixed(decimals);
    return;
  }

  const start = performance.now();
  function frame(now) {
    const t = Math.min(1, (now - start) / duration);
    const value = from + (target - from) * easeOutCubic(t);
    el.textContent = value.toFixed(decimals);
    if (t < 1) requestAnimationFrame(frame);
    else el.textContent = target.toFixed(decimals);
  }
  requestAnimationFrame(frame);
}
