"use client";

import { m } from "framer-motion";
import { ArrowDown, ArrowUp } from "lucide-react";
import { EASE_OUT } from "./Motion";

export interface ShapRow {
  /** Row label, e.g. "soil_moisture_pct = 12.5". */
  label: React.ReactNode;
  /** Text shown at the end of the row, e.g. "+3.20 mm (increases)". */
  valueText: string;
  /** Bar length driver; only its absolute value is used. */
  magnitude: number;
  /** Signed rows get an up/down arrow and a colour; unsigned rows (global importance) get neither. */
  direction?: "up" | "down";
}

const COLORS = {
  up: { from: "#38bdf8", to: "#5eead4", glow: "rgb(94 234 212 / 0.55)" },
  down: { from: "#f59e0b", to: "#fbbf24", glow: "rgb(251 191 36 / 0.5)" },
  none: { from: "#818cf8", to: "#5eead4", glow: "rgb(129 140 248 / 0.5)" },
};

/**
 * Horizontal glowing bars for SHAP values. Every bar carries its number as
 * text (and signed ones an arrow), so the chart never relies on colour or
 * bar length alone and needs no charting library.
 */
export function ShapBars({ rows }: { rows: ShapRow[] }) {
  const max = Math.max(...rows.map((r) => Math.abs(r.magnitude)), 0.0001);
  return (
    <ul className="space-y-3.5">
      {rows.map((row, i) => {
        const c = COLORS[row.direction ?? "none"];
        const share = Math.abs(row.magnitude) / max;
        return (
          <li key={i} className="text-sm">
            <div className="flex items-baseline justify-between gap-3">
              <span className="flex min-w-0 items-center gap-1.5 font-medium text-ink">
                {row.direction === "up" && <ArrowUp className="h-4 w-4 shrink-0 text-accent" aria-hidden="true" />}
                {row.direction === "down" && <ArrowDown className="h-4 w-4 shrink-0 text-warn" aria-hidden="true" />}
                <span className="truncate">{row.label}</span>
              </span>
              <span className="num shrink-0 text-muted" dir="ltr">
                {row.valueText}
              </span>
            </div>
            <div className="mt-1.5 h-2 rounded-full bg-white/[0.06]" aria-hidden="true">
              <m.div
                className="glow-bar"
                style={
                  {
                    width: `${Math.max(share * 100, 1.5)}%`,
                    transformOrigin: "var(--origin, left)",
                    "--bar-from": c.from,
                    "--bar-to": c.to,
                    "--bar-glow": c.glow,
                  } as React.CSSProperties
                }
                initial={{ scaleX: 0 }}
                animate={{ scaleX: 1 }}
                transition={{ duration: 0.8, ease: EASE_OUT, delay: i * 0.04 }}
              />
            </div>
          </li>
        );
      })}
    </ul>
  );
}
