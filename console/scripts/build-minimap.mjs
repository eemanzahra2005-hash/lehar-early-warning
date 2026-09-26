// Builds public/geo/minimap.json: the district polygons from
// public/geo/pakistan_districts.geojson, projected to SVG coordinates and
// simplified, for the home page's mini-map.
//
// Why: the full GeoJSON is ~900 KB. The home page only needs a small
// overview picture, so shipping pre-simplified SVG path strings keeps the
// first screen fast on a phone. The full file is still used by /map (Leaflet).
//
// Run from console/:  node scripts/build-minimap.mjs
// The output is committed; re-run only if the source GeoJSON changes.

import { readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const SRC = resolve(here, "../public/geo/pakistan_districts.geojson");
const OUT = resolve(here, "../public/geo/minimap.json");
const WIDTH = 1000; // SVG units; height follows the country's aspect ratio
const TOLERANCE = 1.1; // Douglas-Peucker tolerance in SVG units (~0.1 % of width)

const geo = JSON.parse(readFileSync(SRC, "utf8"));

// Every ring of every feature, as [lon, lat] arrays.
const ringsOf = (geometry) =>
  geometry.type === "Polygon" ? geometry.coordinates : geometry.type === "MultiPolygon" ? geometry.coordinates.flat() : [];

let minLon = Infinity, maxLon = -Infinity, minLat = Infinity, maxLat = -Infinity;
for (const f of geo.features) {
  for (const ring of ringsOf(f.geometry)) {
    for (const [lon, lat] of ring) {
      minLon = Math.min(minLon, lon); maxLon = Math.max(maxLon, lon);
      minLat = Math.min(minLat, lat); maxLat = Math.max(maxLat, lat);
    }
  }
}

// Equirectangular projection, with longitude shrunk by cos(mid-latitude) so
// the country is not stretched sideways. Good enough for an overview map.
const kx = Math.cos((((minLat + maxLat) / 2) * Math.PI) / 180);
const scale = WIDTH / ((maxLon - minLon) * kx);
const HEIGHT = Math.ceil((maxLat - minLat) * scale);
const project = ([lon, lat]) => [(lon - minLon) * kx * scale, (maxLat - lat) * scale];

function perpDistance([x, y], [x1, y1], [x2, y2]) {
  const dx = x2 - x1, dy = y2 - y1;
  const len = Math.hypot(dx, dy);
  if (len === 0) return Math.hypot(x - x1, y - y1);
  return Math.abs(dy * x - dx * y + x2 * y1 - y2 * x1) / len;
}

// Classic Douglas-Peucker, iterative so long rings cannot overflow the stack.
function simplify(points, tolerance) {
  if (points.length < 4) return points;
  const keep = new Uint8Array(points.length);
  keep[0] = keep[points.length - 1] = 1;
  const stack = [[0, points.length - 1]];
  while (stack.length) {
    const [a, b] = stack.pop();
    let maxD = 0, index = -1;
    for (let i = a + 1; i < b; i++) {
      const d = perpDistance(points[i], points[a], points[b]);
      if (d > maxD) { maxD = d; index = i; }
    }
    if (maxD > tolerance && index > 0) {
      keep[index] = 1;
      stack.push([a, index], [index, b]);
    }
  }
  return points.filter((_, i) => keep[i]);
}

const r = (n) => Math.round(n * 10) / 10;
const features = [];
for (const f of geo.features) {
  const parts = [];
  for (const ring of ringsOf(f.geometry)) {
    const pts = simplify(ring.map(project), TOLERANCE);
    if (pts.length < 4) continue; // slivers vanish at this scale
    parts.push("M" + pts.map(([x, y]) => `${r(x)} ${r(y)}`).join("L") + "Z");
  }
  if (parts.length) features.push({ n: f.properties.shapeName, d: parts.join("") });
}

const out = { source: "geoBoundaries PAK ADM2 (simplified by scripts/build-minimap.mjs)", viewBox: `0 0 ${WIDTH} ${HEIGHT}`, features };
writeFileSync(OUT, JSON.stringify(out));
console.log(`${features.length} districts -> ${OUT} (${(JSON.stringify(out).length / 1024).toFixed(1)} KB)`);
