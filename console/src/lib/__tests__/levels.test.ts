import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { byLevelDesc, contrastRatio, DARK_SURFACES, isTakeoverLevel, LEVEL_TOKENS, levelToken } from "../levels";

// The backend's single source of truth, read from this same repo so the
// console's colour tokens can never silently drift from the engine's.
const LEVELS_PY = resolve(__dirname, "../../../../backend/app/services/alerts/levels.py");
const CSS = resolve(__dirname, "../../app/globals.css");

function backendLevels(): { key: string; color: string; text: string }[] {
  const source = readFileSync(LEVELS_PY, "utf8");
  const pattern = /key="(\w+)",\s*color_hex="(#[0-9A-Fa-f]{6})",\s*text_color_hex="(#[0-9A-Fa-f]{6})"/g;
  return [...source.matchAll(pattern)].map((m) => ({ key: m[1], color: m[2], text: m[3] }));
}

describe("level tokens", () => {
  it("cover OPS and levels 1-5 exactly", () => {
    expect(Object.keys(LEVEL_TOKENS).map(Number)).toEqual([0, 1, 2, 3, 4, 5]);
    expect(Object.values(LEVEL_TOKENS).map((t) => t.key)).toEqual(["OPS", "L1", "L2", "L3", "L4", "L5"]);
  });

  it("match backend/app/services/alerts/levels.py", () => {
    const backend = backendLevels();
    expect(backend).toHaveLength(6);
    for (const level of backend) {
      const token = Object.values(LEVEL_TOKENS).find((t) => t.key === level.key);
      expect(token, level.key).toBeDefined();
      expect(token!.bg.toUpperCase()).toBe(level.color.toUpperCase());
      expect(token!.fg.toUpperCase()).toBe(level.text.toUpperCase());
    }
  });

  it("match the CSS custom properties in globals.css", () => {
    const css = readFileSync(CSS, "utf8").toLowerCase();
    for (const token of Object.values(LEVEL_TOKENS)) {
      const name = token.key === "OPS" ? "ops" : String(token.number);
      expect(css).toContain(`--lvl-${name}-bg: ${token.bg.toLowerCase()};`);
      expect(css).toContain(`--lvl-${name}-fg: ${token.fg.toLowerCase()};`);
    }
  });

  it("meet WCAG AA contrast (4.5:1) for every level", () => {
    for (const token of Object.values(LEVEL_TOKENS)) {
      expect(contrastRatio(token.bg, token.fg), token.key).toBeGreaterThanOrEqual(4.5);
    }
  });

  it("keep level-coloured ink readable (AA) on every dark surface", () => {
    for (const token of Object.values(LEVEL_TOKENS)) {
      for (const surface of DARK_SURFACES) {
        expect(contrastRatio(token.ink, surface), `${token.key} ink on ${surface}`).toBeGreaterThanOrEqual(4.5);
      }
    }
  });

  it("keep hero band text AA across the whole gradient", () => {
    for (const token of Object.values(LEVEL_TOKENS)) {
      for (const stop of token.band) {
        expect(contrastRatio(token.bandFg, stop), `${token.key} band ${stop}`).toBeGreaterThanOrEqual(4.5);
      }
    }
  });

  it("keep hero band text AA under the drifting blobs and the light sweep", () => {
    // Worst case: a blob at full strength, then the sweep at its peak on top.
    const over = (base: string, [top, alpha]: [string, number]) => {
      const rgb = (hex: string) => [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));
      const [b, t] = [rgb(base), rgb(top)];
      return "#" + b.map((v, i) => Math.round(v + (t[i] - v) * alpha).toString(16).padStart(2, "0")).join("");
    };
    for (const token of Object.values(LEVEL_TOKENS)) {
      for (const stop of [...token.band, ...token.blob]) {
        expect(contrastRatio(token.bandFg, stop), `${token.key} blob ${stop}`).toBeGreaterThanOrEqual(4.5);
        const swept = over(stop, token.sweep);
        expect(contrastRatio(token.bandFg, swept), `${token.key} sweep over ${stop}`).toBeGreaterThanOrEqual(4.5);
      }
    }
  });

  it("mirror the hero motion tokens in globals.css", () => {
    const css = readFileSync(CSS, "utf8").toLowerCase();
    for (const token of Object.values(LEVEL_TOKENS)) {
      const name = token.key === "OPS" ? "ops" : String(token.number);
      expect(css).toContain(`--lvl-${name}-blob-a: ${token.blob[0].toLowerCase()};`);
      expect(css).toContain(`--lvl-${name}-blob-b: ${token.blob[1].toLowerCase()};`);
      const [hex, alpha] = token.sweep;
      const rgb = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16)).join(" ");
      expect(css).toContain(`--lvl-${name}-sweep: rgb(${rgb} / ${alpha});`);
    }
  });

  it("mirror the dark-theme tokens in globals.css", () => {
    const css = readFileSync(CSS, "utf8").toLowerCase();
    for (const token of Object.values(LEVEL_TOKENS)) {
      const name = token.key === "OPS" ? "ops" : String(token.number);
      expect(css).toContain(`--lvl-${name}-ink: ${token.ink.toLowerCase()};`);
      expect(css).toContain(`--lvl-${name}-band-fg: ${token.bandFg.toLowerCase()};`);
      expect(css).toContain(`--lvl-${name}-gradient: linear-gradient(135deg, ${token.band[0].toLowerCase()}, ${token.band[1].toLowerCase()});`);
    }
    for (const surface of DARK_SURFACES) expect(css).toContain(surface.toLowerCase());
  });

  it("give every level a distinct icon (never colour alone)", () => {
    const icons = Object.values(LEVEL_TOKENS).map((t) => t.icon);
    expect(new Set(icons).size).toBe(icons.length);
  });
});

describe("level mapping", () => {
  it("clamps out-of-range numbers and defaults missing ones to calm level 1", () => {
    expect(levelToken(7).key).toBe("L5");
    expect(levelToken(-2).key).toBe("OPS");
    expect(levelToken(null).key).toBe("L1");
    expect(levelToken(undefined).key).toBe("L1");
    expect(levelToken(3).key).toBe("L3");
  });

  it("takes over the screen only at levels 4 and 5 without metadata", () => {
    expect([0, 1, 2, 3, 4, 5].map((n) => isTakeoverLevel(n))).toEqual([false, false, false, false, true, true]);
  });

  it("prefers the backend's full_screen_takeover flag when metadata is loaded", () => {
    const meta = { full_screen_takeover: false } as Parameters<typeof isTakeoverLevel>[1];
    expect(isTakeoverLevel(5, meta)).toBe(false);
  });

  it("sorts most urgent first, OPS below every farmer level, newest first on ties", () => {
    const rows = [
      { level: 0, created_at: "2026-09-01T00:00:00Z" },
      { level: 2, created_at: "2026-09-01T00:00:00Z" },
      { level: 5, created_at: "2026-09-01T00:00:00Z" },
      { level: 2, created_at: "2026-09-02T00:00:00Z" },
    ];
    expect([...rows].sort(byLevelDesc)).toEqual([rows[2], rows[3], rows[1], rows[0]]);
  });
});
