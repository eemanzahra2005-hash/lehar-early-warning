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
 * Marker radius by level, in cobe v2's units. Every district is its own
 * small dot: Pakistan covers only ~1/500th of the sphere, so at 0.025 (the
 * size first tried) its 107 dots fused into one solid country-shaped blob.
 * At these sizes neighbouring Punjab districts stay separate points. Each
 * level up is a larger dot (L2 = 1.3x calm, L5 = 1.8x), so size still says "how bad"
 * without relying on colour alone.
 */
export const MARKER_SIZE: Record<number, number> = { 0: 0.0065, 1: 0.0065, 2: 0.0085, 3: 0.0095, 4: 0.0105, 5: 0.0115 };

/**
 * A calm (Level 1) or unknown district: soft teal-white at 35 % strength.
 * cobe markers have no alpha, so "35 % opacity" is the colour scaled
 * towards black, which on the dark sphere reads the same.
 */
export const CALM_DOT: [number, number, number] = [0.3, 0.35, 0.34];

/** The faint dotted outline of the national border (below the district dots). */
export const BORDER_DOT: [number, number, number] = [0.22, 0.3, 0.3];
export const BORDER_SIZE = 0.0028;

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
 * The globe's markers, back to front: the border outline, then a dim halo
 * under every alerting district (what makes it "glow"; `pulse` 0..1 breathes
 * it, and with pulse 0 under reduced motion it is still there, just still),
 * then one dot per district on top. Calm dots are faint and small; alerting
 * ones are brighter, a little larger and in their level's colour.
 */
export function buildMarkers(
  points: GlobePoint[],
  levelByDistrict: Record<string, number>,
  pulse = 0,
  border: [number, number][] = [],
): GlobeMarker[] {
  const outline: GlobeMarker[] = border.map((location) => ({ location, size: BORDER_SIZE, color: BORDER_DOT }));
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
    // A darker copy of the colour reads as a translucent glow on the dark
    // sphere. Kept tight (under 2x) so neighbouring halos do not fuse.
    halos.push({ location, size: size * (1.5 + 0.35 * pulse), color: color.map((c) => c * 0.3) as [number, number, number] });
    dots.push({ location, size, color });
  }
  return [...outline, ...halos, ...dots];
}

/** Calm levels' rim: the teal of the L1 band's glow (--lvl-1-glow), since L1's ink is near-white. */
const CALM_RIM = "#99F6E4";

/**
 * The atmosphere rim colour for the national level: the level's ink (teal
 * when calm), dimmed so the rim is a hint of colour, not a neon ring.
 */
export function rimColor(level: number): [number, number, number] {
  const token = levelToken(level);
  const hex = token.number <= 1 ? CALM_RIM : token.ink;
  return hexToRgb01(hex).map((c) => c * 0.4) as [number, number, number];
}

/** Auto-spin, in radians per second (0.002 rad a frame at 60 fps). */
export const SPIN_RAD_PER_S = 0.12;

/**
 * Drag inertia: how much of the fling speed survives one second. After a
 * mouse drag the globe keeps coasting and slows to the normal spin within
 * about a second.
 */
export const FLING_KEEP_PER_S = 0.02;

/** The fling speed `dt` seconds later (frame-rate independent decay). */
export function decayFling(velocity: number, dt: number): number {
  return velocity * FLING_KEEP_PER_S ** dt;
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
