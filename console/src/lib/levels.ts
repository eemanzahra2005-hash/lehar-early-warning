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
}

export const LEVEL_TOKENS: Record<number, LevelToken> = {
  0: { number: 0, key: "OPS", bg: "#6B7280", fg: "#FFFFFF", className: "lvl-ops", icon: "Wrench" },
  1: { number: 1, key: "L1", bg: "#FFFFFF", fg: "#111827", className: "lvl-1", icon: "Info" },
  2: { number: 2, key: "L2", bg: "#FFD400", fg: "#111827", className: "lvl-2", icon: "TriangleAlert" },
  3: { number: 3, key: "L3", bg: "#E03131", fg: "#FFFFFF", className: "lvl-3", icon: "OctagonAlert" },
  4: { number: 4, key: "L4", bg: "#7B2FBF", fg: "#FFFFFF", className: "lvl-4", icon: "Siren" },
  5: { number: 5, key: "L5", bg: "#0B0B0B", fg: "#FFFFFF", className: "lvl-5", icon: "ShieldAlert" },
};

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
