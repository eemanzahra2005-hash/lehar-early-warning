/**
 * The console's level design system.
 *
 * Names, summaries and actions always come live from GET /alerts/levels
 * (backend/app/services/alerts/levels.py is the single source of truth).
 * What lives here is only what the UI needs *before* that call returns, so a
 * level is never shown as colour alone: the CSS token, the icon and the
 * number. The hex values mirror levels.py and a unit test reads levels.py to
 * prove they have not drifted.
 */

import type { AlertLevelInfo } from "./types";

export type LevelKey = "OPS" | "L1" | "L2" | "L3" | "L4" | "L5";

export interface LevelToken {
  number: number;
  key: LevelKey;
  /** Background colour (mirrors color_hex in levels.py). */
  bg: string;
  /** Foreground colour with WCAG AA contrast on bg (mirrors text_color_hex). */
  fg: string;
  /** CSS class defined in globals.css. */
  className: string;
  /** Name of the lucide icon rendered by <LevelIcon>. */
  icon: "Wrench" | "Info" | "TriangleAlert" | "OctagonAlert" | "Siren" | "ShieldAlert";
  /**
   * Dark theme (Phase 5b). The official colours above are kept for badges;
   * these say how each level shows up on the navy "command center" surfaces.
   * `ink` is the level's colour for text, dots and rails ON a dark surface
   * (black and white cannot both work there, so L5 uses a white ink and
   * relies on icon + number + name). `band` is the hero gradient, and
   * `bandFg` the text on it. The tests hold every pair to WCAG AA.
   */
  ink: string;
  band: [string, string];
  bandFg: string;
  /**
   * Home hero motion (Phase 5c). `blob` are the two colours of the drifting
   * mesh blobs, and `sweep` is the colour + peak opacity of the light sweep.
   * Both are chosen so the text on the band stays AA wherever they drift:
   * darker same-hue blobs under white text, lighter ones under dark text.
   * L3's red is already at 4.51:1, so its "light" sweep is a dark sheen.
   */
  blob: [string, string];
  sweep: [string, number];
}

export const LEVEL_TOKENS: Record<number, LevelToken> = {
  0: {
    number: 0, key: "OPS", bg: "#6B7280", fg: "#FFFFFF", className: "lvl-ops", icon: "Wrench",
    ink: "#CBD5E1", band: ["#6B7280", "#374151"], bandFg: "#FFFFFF",
    blob: ["#4B5563", "#1F2937"], sweep: ["#FFFFFF", 0.03],
  },
  // L1 is the calm baseline: a deep teal band with a white glow, not a white slab.
  1: {
    number: 1, key: "L1", bg: "#FFFFFF", fg: "#111827", className: "lvl-1", icon: "Info",
    ink: "#F8FAFC", band: ["#115E59", "#0B1A24"], bandFg: "#FFFFFF",
    blob: ["#0F766E", "#134E4A"], sweep: ["#FFFFFF", 0.08],
  },
  2: {
    number: 2, key: "L2", bg: "#FFD400", fg: "#111827", className: "lvl-2", icon: "TriangleAlert",
    ink: "#FFD400", band: ["#FFD400", "#F2A900"], bandFg: "#111827",
    blob: ["#FFE45C", "#FFC21A"], sweep: ["#FFFFFF", 0.22],
  },
  3: {
    number: 3, key: "L3", bg: "#E03131", fg: "#FFFFFF", className: "lvl-3", icon: "OctagonAlert",
    ink: "#FF6B6B", band: ["#E03131", "#9F1D1D"], bandFg: "#FFFFFF",
    blob: ["#C92A2A", "#7F1D1D"], sweep: ["#000000", 0.14],
  },
  4: {
    number: 4, key: "L4", bg: "#7B2FBF", fg: "#FFFFFF", className: "lvl-4", icon: "Siren",
    ink: "#C39BF5", band: ["#7B2FBF", "#4A1A7A"], bandFg: "#FFFFFF",
    blob: ["#6A28A8", "#3B1263"], sweep: ["#FFFFFF", 0.14],
  },
  // L5 is black on a dark page: the band gets a pulsing white edge (globals.css).
  5: {
    number: 5, key: "L5", bg: "#0B0B0B", fg: "#FFFFFF", className: "lvl-5", icon: "ShieldAlert",
    ink: "#F1F5F9", band: ["#0B0B0B", "#000000"], bandFg: "#FFFFFF",
    blob: ["#27272A", "#18181B"], sweep: ["#FFFFFF", 0.1],
  },
};

/**
 * The dark surfaces a level's `ink` is drawn on: the page gradient's two ends
 * and a glass card (6 % white over the lighter end). Mirrors globals.css.
 */
export const DARK_SURFACES = ["#070B14", "#0E1524", "#1C2331"] as const;

/** Levels that interrupt the user with a full-screen takeover (ALERT_LEVELS.md). */
export const TAKEOVER_MIN_LEVEL = 4;

/** Token for any level number; unknown/out-of-range numbers clamp into 0..5. */
export function levelToken(level: number | null | undefined): LevelToken {
  if (level === null || level === undefined || Number.isNaN(level)) return LEVEL_TOKENS[1];
  const n = Math.max(0, Math.min(5, Math.round(level)));
  return LEVEL_TOKENS[n];
}

export function isTakeoverLevel(level: number, meta?: AlertLevelInfo): boolean {
  // Prefer the backend's own flag; fall back to the documented rule.
  if (meta) return meta.full_screen_takeover;
  return level >= TAKEOVER_MIN_LEVEL;
}

/**
 * Sort key for "most urgent first". OPS (0) is outside the farmer ladder and
 * must never sort above a farmer level (ALERT_LEVELS.md: "OPS is number 0,
 * not 6"), so plain numeric descending is exactly right.
 */
export function byLevelDesc<T extends { level: number; created_at?: string | null }>(a: T, b: T): number {
  if (b.level !== a.level) return b.level - a.level;
  return (b.created_at ?? "").localeCompare(a.created_at ?? "");
}

/** Level metadata by number, from the /alerts/levels response. */
export function indexLevels(levels: AlertLevelInfo[]): Record<number, AlertLevelInfo> {
  const out: Record<number, AlertLevelInfo> = {};
  for (const level of levels) out[level.number] = level;
  return out;
}

// --- WCAG contrast (used by the tests to hold the tokens to AA) --------------

function channel(value: number): number {
  const v = value / 255;
  return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
}

export function relativeLuminance(hex: string): number {
  const clean = hex.replace("#", "");
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(clean.slice(i, i + 2), 16));
  return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
}

export function contrastRatio(a: string, b: string): number {
  const [hi, lo] = [relativeLuminance(a), relativeLuminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}
