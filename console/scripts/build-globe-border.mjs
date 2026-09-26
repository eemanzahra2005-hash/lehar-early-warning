// Builds public/geo/globe-border.json: evenly spaced [lat, lon] points along
// Pakistan's national border, drawn as a faint dotted outline on the home
// hero's globe so the country reads clearly between the district dots.
//
// How: the source GeoJSON has only district polygons, no national outline.
// An edge shared by two districts is inside the country; an edge that
// belongs to exactly one district is on the border. So we count every edge
// (vertices rounded, so tiny float differences still match), keep the ones
// seen once, and walk along them dropping a point every STEP degrees.
//
// Run from console/:  node scripts/build-globe-border.mjs
// The output is committed; re-run only if the GeoJSON changes.

import { readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const GEOJSON = resolve(here, "../public/geo/pakistan_districts.geojson");
const OUT = resolve(here, "../public/geo/globe-border.json");
const STEP = 0.3; // degrees between border dots (~33 km)

const geo = JSON.parse(readFileSync(GEOJSON, "utf8"));
const key = ([x, y]) => `${x.toFixed(4)},${y.toFixed(4)}`;
const edgeKey = (a, b) => [key(a), key(b)].sort().join("|");

// Every ring edge, counted in both directions under one key.
const edges = new Map();
for (const f of geo.features) {
  const g = f.geometry;
  const polygons = g.type === "Polygon" ? [g.coordinates] : g.coordinates;
  for (const polygon of polygons) {
    for (const ring of polygon) {
      for (let i = 0; i < ring.length - 1; i += 1) {
        const k = edgeKey(ring[i], ring[i + 1]);
        const e = edges.get(k);
        if (e) e.count += 1;
        else edges.set(k, { a: ring[i], b: ring[i + 1], count: 1 });
      }
    }
  }
}

// Walk the outer edges, carrying the leftover distance from one edge to the
// next so the spacing stays even. Edges come in ring order, so "carry" is
// right almost everywhere; a stray gap only shifts one dot.
const points = [];
let carry = 0;
for (const { a, b, count } of edges.values()) {
  if (count !== 1) continue;
  const len = Math.hypot(b[0] - a[0], b[1] - a[1]);
  let d = STEP - carry;
  while (d <= len) {
    const t = d / len;
    points.push([a[1] + (b[1] - a[1]) * t, a[0] + (b[0] - a[0]) * t]);
    d += STEP;
  }
  carry = len - (d - STEP);
}

// Drop dots that land almost on top of each other (where two border
// stretches run side by side, or the carry reset at a gap).
const kept = [];
for (const p of points) {
  if (!kept.some((q) => Math.hypot(p[0] - q[0], p[1] - q[1]) < STEP * 0.6)) kept.push(p);
}

const round = (v) => Math.round(v * 100) / 100;
writeFileSync(OUT, JSON.stringify(kept.map(([lat, lon]) => [round(lat), round(lon)])) + "\n");
console.log(`wrote ${kept.length} border points to ${OUT}`);
