// Builds public/geo/globe-points.json: one [lat, lon] marker position per
// LEHAR district, for the dotted globe in the home hero.
//
// Where each point comes from:
//   1. the area-weighted centroid of the district's polygon(s) in
//      public/geo/pakistan_districts.geojson (name matched with the same
//      mapping the maps use, src/lib/geo.ts), or
//   2. for the few districts with no polygon in that dataset (see geo.ts),
//      the main-city coordinates in backend/ml/districts.py.
// The district list itself is read from districts.py, so the file always has
// exactly the backend's 107 districts.
//
// Run from console/:  node scripts/build-globe-points.mjs
// The output is committed; re-run only if the GeoJSON or district list changes.
// (Node 24 runs the .ts import below directly: geo.ts has only erasable types.)

import { readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { shapeNameFor } from "../src/lib/geo.ts";

const here = dirname(fileURLToPath(import.meta.url));
const GEOJSON = resolve(here, "../public/geo/pakistan_districts.geojson");
const DISTRICTS_PY = resolve(here, "../../backend/ml/districts.py");
const OUT = resolve(here, "../public/geo/globe-points.json");

// '    "Lahore": {"province": "Punjab", "lat": 31.5497, "lon": 74.3436, ...'
const pattern = /^\s+"([^"]+)": \{"province": "[^"]+", "lat": ([\d.]+), "lon": ([\d.]+)/gm;
const districts = [...readFileSync(DISTRICTS_PY, "utf8").matchAll(pattern)].map((m) => ({
  name: m[1],
  lat: Number(m[2]),
  lon: Number(m[3]),
}));

const geo = JSON.parse(readFileSync(GEOJSON, "utf8"));
const byShape = new Map(geo.features.map((f) => [f.properties.shapeName, f.geometry]));

/** Area-weighted centroid of a (Multi)Polygon's outer rings, in degrees. */
function centroid(geometry) {
  const polygons = geometry.type === "Polygon" ? [geometry.coordinates] : geometry.coordinates;
  let area = 0, cx = 0, cy = 0;
  for (const [outer] of polygons) {
    // Shoelace formula. Degrees are fine at this scale: we only need a dot
    // that lands inside the district on a globe a few hundred pixels wide.
    for (let i = 0; i < outer.length - 1; i += 1) {
      const [x0, y0] = outer[i];
      const [x1, y1] = outer[i + 1];
      const cross = x0 * y1 - x1 * y0;
      area += cross;
      cx += (x0 + x1) * cross;
      cy += (y0 + y1) * cross;
    }
  }
  area /= 2;
  return { lon: cx / (6 * area), lat: cy / (6 * area) };
}

const round = (v) => Math.round(v * 1000) / 1000;
const fromCity = [];
const points = districts.map((d) => {
  const geometry = byShape.get(shapeNameFor(d.name));
  if (!geometry) fromCity.push(d.name);
  const { lat, lon } = geometry ? centroid(geometry) : d;
  return { n: d.name, lat: round(lat), lon: round(lon) };
});

writeFileSync(OUT, JSON.stringify(points) + "\n");
console.log(`wrote ${points.length} points to ${OUT}`);
console.log(`from districts.py city coordinates (no polygon): ${fromCity.join(", ") || "none"}`);
