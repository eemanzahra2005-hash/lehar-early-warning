/**
 * Pure helpers for the home hero's dotted globe (components/HeroGlobe.tsx),
 * kept apart from the WebGL code so they are unit-tested.
 *
 * The globe is drawn by `cobe`, which takes colours as [r, g, b] in 0..1,
 * positions as [lat, lon] and the view as two angles: phi (spin around the
 * poles) and theta (tilt towards a pole).
 */

import { DISTRICT_NAME_UR } from "./districtNames";
import { levelToken } from "./levels";

export interface GlobePoint {
  /** LEHAR district name (the key used everywhere else). */
  n: string;
  lat: number;
  lon: number;
}

export interface GlobeMarker {
  location: [number, number];
  size: number;
  color: [number, number, number];
}

/** Roughly the middle of Pakistan: the globe's resting view. */
export const PAKISTAN_CENTER: [number, number] = [30.0, 69.5];

/**
 * Marker radius by level, in cobe's units (fractions of the globe radius).
 * Calm districts are small faint dots; each level up is a clearly larger
 * dot, so size says "how bad" without relying on colour alone.
 */
export const MARKER_SIZE: Record<number, number> = { 0: 0.009, 1: 0.009, 2: 0.03, 3: 0.038, 4: 0.046, 5: 0.055 };

/** The faint grey-blue of a calm (Level 1) or unknown district. */
export const CALM_DOT: [number, number, number] = [0.36, 0.43, 0.52];

export function hexToRgb01(hex: string): [number, number, number] {
  const clean = hex.replace("#", "");
  return [0, 2, 4].map((i) => parseInt(clean.slice(i, i + 2), 16) / 255) as [number, number, number];
}

/**
 * The view angles that put [lat, lon] in the middle of the globe. This is
 * cobe's own "focus on a location" formula from its examples.
 */
export function locationToAngles(lat: number, lon: number): [number, number] {
  return [Math.PI - ((lon * Math.PI) / 180 - Math.PI / 2), (lat * Math.PI) / 180];
}

/**
 * The signed turn from angle `from` to angle `to` the short way round,
 * in -PI..PI, so rotating to a district never spins the long way.
 */
export function shortestTurn(from: number, to: number): number {
  const turn = (to - from) % (2 * Math.PI);
  if (turn > Math.PI) return turn - 2 * Math.PI;
  if (turn < -Math.PI) return turn + 2 * Math.PI;
  return turn;
}

/**
 * One marker per district: a faint dot when calm, the level's colour and a
 * bigger size when alerting. `pulse` (0..1) grows a dim halo drawn under
 * every alerting district, which is what makes them "glow"; with pulse 0
 * (reduced motion) the halo is still there, just still. Halos come first in
 * the list so the solid dots are drawn over them.
 */
export function buildMarkers(points: GlobePoint[], levelByDistrict: Record<string, number>, pulse = 0): GlobeMarker[] {
  const halos: GlobeMarker[] = [];
  const dots: GlobeMarker[] = [];
  for (const p of points) {
    const level = levelByDistrict[p.n];
    const location: [number, number] = [p.lat, p.lon];
    if (level === undefined || level <= 1) {
      dots.push({ location, size: MARKER_SIZE[1], color: CALM_DOT });
      continue;
    }
    const token = levelToken(level);
    const color = hexToRgb01(token.ink);
    const size = MARKER_SIZE[token.number];
    // A darker copy of the colour reads as a translucent glow on the dark sphere.
    halos.push({ location, size: size * (1.8 + 0.7 * pulse), color: color.map((c) => c * 0.32) as [number, number, number] });
    dots.push({ location, size, color });
  }
  return [...halos, ...dots];
}

/**
 * Districts matching what the user typed: English (any case) or Urdu,
 * matching the start of any word first, then anywhere in the name.
 */
export function filterDistricts(query: string, districts: string[]): string[] {
  const q = query.trim().toLowerCase();
  if (!q) return districts;
  const starts: string[] = [];
  const contains: string[] = [];
  for (const d of districts) {
    const en = d.toLowerCase();
    const ur = DISTRICT_NAME_UR[d] ?? "";
    const words = [...en.split(/\s+/), ...ur.split(/\s+/)];
    if (words.some((w) => w.startsWith(q))) starts.push(d);
    else if (en.includes(q) || ur.includes(q)) contains.push(d);
  }
  return [...starts, ...contains];
}
