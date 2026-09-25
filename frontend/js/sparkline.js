/**
 * Tiny inline SVG line sparkline — no Chart.js, no library. Pure markup
 * generator so it can be dropped straight into a KPI tile's innerHTML.
 * `color` is expected to be a CSS value (usually a var(--token) reference),
 * which SVG presentation attributes accept directly.
 */

export function sparklineSvg(values, { width = 96, height = 26, color = 'currentColor', strokeWidth = 1.5 } = {}) {
  const points = values
    .map((v, i) => (typeof v === 'number' && Number.isFinite(v) ? { i, v } : null))
    .filter(Boolean);
  if (points.length < 2) return '';

  const nums = points.map((p) => p.v);
  const min = Math.min(...nums);
  const max = Math.max(...nums);
  const range = max - min || 1;
  const stepX = width / (values.length - 1 || 1);
  const pad = 3;

  const coords = points.map((p) => ({
    x: p.i * stepX,
    y: height - pad - ((p.v - min) / range) * (height - pad * 2),
  }));

  const linePath = coords.map((c, i) => `${i === 0 ? 'M' : 'L'} ${c.x.toFixed(1)} ${c.y.toFixed(1)}`).join(' ');
  const last = coords[coords.length - 1];
  const first = coords[0];
  const areaPath = `${linePath} L ${last.x.toFixed(1)} ${height} L ${first.x.toFixed(1)} ${height} Z`;

  return `
    <svg viewBox="0 0 ${width} ${height}" width="${width}" height="${height}" preserveAspectRatio="none" aria-hidden="true" focusable="false">
      <path d="${areaPath}" fill="${color}" fill-opacity="0.12" stroke="none"/>
      <path d="${linePath}" fill="none" stroke="${color}" stroke-width="${strokeWidth}" stroke-linecap="round" stroke-linejoin="round"/>
      <circle cx="${last.x.toFixed(1)}" cy="${last.y.toFixed(1)}" r="2" fill="${color}"/>
    </svg>
  `;
}
