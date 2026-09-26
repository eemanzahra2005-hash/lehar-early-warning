import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { DISTRICT_NAME_UR } from "../districtNames";
import {
  BORDER_DOT,
  buildMarkers,
  CALM_DOT,
  decayFling,
  filterDistricts,
  hexToRgb01,
  locationToAngles,
  MARKER_SIZE,
  rimColor,
  shortestTurn,
  SPIN_RAD_PER_S,
  type GlobePoint,
} from "../globe";
import { contrastRatio, LEVEL_TOKENS } from "../levels";

// The backend's district list, read from this same repo (like levels.test.ts
// reads levels.py), so the console tables can never silently drift from it.
const DISTRICTS_PY = resolve(__dirname, "../../../../backend/ml/districts.py");
const POINTS_JSON = resolve(__dirname, "../../../public/geo/globe-points.json");
const BORDER_JSON = resolve(__dirname, "../../../public/geo/globe-border.json");
const CSS = resolve(__dirname, "../../app/globals.css");

function backendDistricts(): string[] {
  const source = readFileSync(DISTRICTS_PY, "utf8");
  return [...source.matchAll(/^\s+"([^"]+)": \{"province": /gm)].map((m) => m[1]);
}

describe("district tables", () => {
  const districts = backendDistricts();

  it("reads the backend's 107 districts", () => {
    expect(districts).toHaveLength(107);
  });

  it("has an Urdu name for exactly the backend's districts", () => {
    expect(Object.keys(DISTRICT_NAME_UR).sort()).toEqual([...districts].sort());
    for (const [en, ur] of Object.entries(DISTRICT_NAME_UR)) {
      // Arabic-script letters only (plus spaces), never an empty or Latin placeholder.
      expect(ur, en).toMatch(/^[؀-ۿ ]+$/);
    }
  });

  it("has one globe point per backend district, inside Pakistan", () => {
    const points: GlobePoint[] = JSON.parse(readFileSync(POINTS_JSON, "utf8"));
    expect(points.map((p) => p.n).sort()).toEqual([...districts].sort());
    for (const p of points) {
      expect(p.lat, p.n).toBeGreaterThan(23);
      expect(p.lat, p.n).toBeLessThan(37.5);
      expect(p.lon, p.n).toBeGreaterThan(60);
      expect(p.lon, p.n).toBeLessThan(78);
    }
  });
});

describe("globe border", () => {
  const border: [number, number][] = JSON.parse(readFileSync(BORDER_JSON, "utf8"));

  it("has a few hundred [lat, lon] dots, all around Pakistan", () => {
    // Pakistan's land border + coast is ~7,300 km: about 65 degrees of arc,
    // so ~200 dots at the 0.3 degree step in scripts/build-globe-border.mjs.
    expect(border.length).toBeGreaterThan(150);
    expect(border.length).toBeLessThan(400);
    for (const [lat, lon] of border) {
      expect(lat).toBeGreaterThan(23);
      expect(lat).toBeLessThan(37.5);
      expect(lon).toBeGreaterThan(60);
      expect(lon).toBeLessThan(78);
    }
  });

  it("reaches the country's far corners, so it is the whole outline", () => {
    const lats = border.map(([lat]) => lat);
    const lons = border.map(([, lon]) => lon);
    expect(Math.min(...lats)).toBeLessThan(25); // Sindh coast
    expect(Math.max(...lats)).toBeGreaterThan(36); // Gilgit-Baltistan
    expect(Math.min(...lons)).toBeLessThan(62); // Balochistan-Iran border
    expect(Math.max(...lons)).toBeGreaterThan(75); // Punjab/GB east
  });
});

describe("globe view", () => {
  it("turns the short way round", () => {
    expect(shortestTurn(0, 0.5)).toBeCloseTo(0.5);
    expect(shortestTurn(0.1, 2 * Math.PI - 0.1)).toBeCloseTo(-0.2);
    expect(shortestTurn(2 * Math.PI - 0.1, 0.1)).toBeCloseTo(0.2);
    expect(Math.abs(shortestTurn(-7, 7))).toBeLessThanOrEqual(Math.PI);
  });

  it("tilts towards the location's latitude, and a degree east is a small turn", () => {
    const [phiA, theta] = locationToAngles(30, 69.5);
    const [phiB] = locationToAngles(30, 70.5);
    expect(theta).toBeCloseTo((30 * Math.PI) / 180);
    expect(Math.abs(shortestTurn(phiA, phiB))).toBeCloseTo(Math.PI / 180);
  });

  it("spins at 0.002 rad a frame at 60 fps", () => {
    expect(SPIN_RAD_PER_S / 60).toBeCloseTo(0.002, 6);
  });

  it("lets a fling die away within about a second, at any frame rate", () => {
    expect(decayFling(4, 1)).toBeLessThan(0.1);
    // Two 30 fps frames decay exactly as far as four 60 fps frames.
    const at30 = decayFling(decayFling(4, 1 / 30), 1 / 30);
    const at60 = [1, 2, 3, 4].reduce((v) => decayFling(v, 1 / 60), 4);
    expect(at30).toBeCloseTo(at60, 9);
  });

  it("tints the rim with a dimmed copy of the level's colour", () => {
    const ink = hexToRgb01(LEVEL_TOKENS[3].ink);
    const rim = rimColor(3);
    rim.forEach((c, i) => {
      expect(c).toBeLessThan(ink[i] + 1e-9);
      expect(c).toBeGreaterThanOrEqual(0);
    });
    expect(rimColor(3)).not.toEqual(rimColor(4));
    // Calm is teal (more green/blue than red), not L1's near-white ink.
    const [r, g, b] = rimColor(1);
    expect(g).toBeGreaterThan(r);
    expect(b).toBeGreaterThan(r);
  });

  it("converts hex colours to 0..1 channels", () => {
    expect(hexToRgb01("#FF6B6B")).toEqual([1, 107 / 255, 107 / 255]);
  });
});

describe("globe markers", () => {
  const points: GlobePoint[] = [
    { n: "Lahore", lat: 31.4, lon: 74.3 },
    { n: "Karachi", lat: 24.9, lon: 67.1 },
    { n: "Quetta", lat: 30.2, lon: 67.0 },
  ];

  it("draws calm and unknown districts as faint small dots", () => {
    const markers = buildMarkers(points, { Lahore: 1 });
    expect(markers).toHaveLength(3);
    for (const marker of markers) {
      expect(marker.color).toEqual(CALM_DOT);
      expect(marker.size).toBe(MARKER_SIZE[1]);
    }
  });

  it("draws alerting districts larger, in the level's ink, over a halo", () => {
    const markers = buildMarkers(points, { Lahore: 1, Karachi: 3, Quetta: 5 }, 1);
    // Two halos first (drawn underneath), then the three dots.
    expect(markers).toHaveLength(5);
    const [haloA, haloB, ...dots] = markers;
    const karachi = dots.find((m) => m.location[0] === 24.9)!;
    expect(karachi.color).toEqual(hexToRgb01(LEVEL_TOKENS[3].ink));
    expect(karachi.size).toBe(MARKER_SIZE[3]);
    expect(haloA.size).toBeGreaterThan(MARKER_SIZE[3]);
    expect(haloB.size).toBeGreaterThan(MARKER_SIZE[5]);
  });

  it("keeps every district a small dot with a tight halo, so 107 never fuse into one blob", () => {
    for (const size of Object.values(MARKER_SIZE)) {
      expect(size).toBeLessThanOrEqual(0.012);
    }
    // Alerting dots are at most ~1.8x a calm one: bigger, not a blob.
    expect(MARKER_SIZE[5] / MARKER_SIZE[1]).toBeLessThanOrEqual(1.8);
    const [halo] = buildMarkers(points, { Karachi: 5 }, 1);
    expect(halo.size).toBeLessThan(2 * MARKER_SIZE[5]);
  });

  it("draws the border outline first, under everything, smaller than any district", () => {
    const border: [number, number][] = [
      [24, 67],
      [25, 62],
    ];
    const markers = buildMarkers(points, { Karachi: 3 }, 0, border);
    expect(markers).toHaveLength(2 + 1 + 3);
    expect(markers.slice(0, 2).map((m) => m.location)).toEqual(border);
    for (const m of markers.slice(0, 2)) {
      expect(m.color).toEqual(BORDER_DOT);
      expect(m.size).toBeLessThan(MARKER_SIZE[1]);
    }
  });

  it("grows the marker with every level, so size alone ranks them", () => {
    for (let level = 2; level <= 5; level += 1) {
      expect(MARKER_SIZE[level]).toBeGreaterThan(MARKER_SIZE[level - 1]);
    }
  });
});

describe("district search", () => {
  const districts = ["Dera Ghazi Khan", "Dera Ismail Khan", "Lahore", "Hyderabad", "Faisalabad"];

  it("returns every district for an empty query", () => {
    expect(filterDistricts("  ", districts)).toEqual(districts);
  });

  it("matches word starts before substrings, in any case", () => {
    // "Hyderabad" contains "dera" too, but after the names that start with it.
    expect(filterDistricts("dera", districts)).toEqual(["Dera Ghazi Khan", "Dera Ismail Khan", "Hyderabad"]);
    expect(filterDistricts("ABAD", districts)).toEqual(["Hyderabad", "Faisalabad"]);
    expect(filterDistricts("isma", districts)).toEqual(["Dera Ismail Khan"]);
  });

  it("matches the Urdu name too", () => {
    expect(filterDistricts("لاہور", districts)).toEqual(["Lahore"]);
  });
});

describe("hero vignette", () => {
  // The darkest the vignette gets, from globals.css.
  function vignetteFor(scope: string): number {
    const css = readFileSync(CSS, "utf8");
    const rule = [...css.matchAll(/([^{}]+)\{\s*--hero-vignette:\s*([\d.]+);\s*\}/g)].find((m) =>
      // The last line before "{" is the selector list (earlier lines may be a comment).
      m[1].trim().split(/\r?\n/).pop()!.split(",").map((s) => s.trim()).includes(`.lvl-scope-${scope}`),
    );
    expect(rule, scope).toBeDefined();
    return Number(rule![2]);
  }

  function darken(hex: string, alpha: number): string {
    const [r, g, b] = hexToRgb01(hex).map((c) => Math.round(c * 255 * (1 - alpha)));
    return `#${[r, g, b].map((v) => v.toString(16).padStart(2, "0")).join("")}`;
  }

  it("keeps the hero text AA even at the vignette's darkest point", () => {
    for (const token of Object.values(LEVEL_TOKENS)) {
      const alpha = vignetteFor(token.key === "OPS" ? "0" : String(token.number));
      for (const stop of token.band) {
        expect(contrastRatio(token.bandFg, darken(stop, alpha)), `${token.key} ${stop}`).toBeGreaterThanOrEqual(4.5);
      }
    }
  });
});
