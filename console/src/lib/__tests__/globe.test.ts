import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { DISTRICT_NAME_UR } from "../districtNames";
import {
  buildMarkers,
  CALM_DOT,
  filterDistricts,
  hexToRgb01,
  locationToAngles,
  MARKER_SIZE,
  shortestTurn,
  type GlobePoint,
} from "../globe";
import { contrastRatio, LEVEL_TOKENS } from "../levels";

// The backend's district list, read from this same repo (like levels.test.ts
// reads levels.py), so the console tables can never silently drift from it.
const DISTRICTS_PY = resolve(__dirname, "../../../../backend/ml/districts.py");
const POINTS_JSON = resolve(__dirname, "../../../public/geo/globe-points.json");
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
