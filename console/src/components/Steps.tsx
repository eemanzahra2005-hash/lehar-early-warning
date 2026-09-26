"use client";

import { m } from "framer-motion";
import { Check } from "lucide-react";
import { EASE_OUT } from "./Motion";

/**
 * A small step indicator ("1 — 2 — 3"). `current` is the 0-based step the
 * user is on; earlier steps show a check. Steps that happen outside the
 * console (e.g. clicking the email link) simply stay "upcoming" — the
 * console never claims they happened.
 */
export function Steps({ steps, current, label }: { steps: string[]; current: number; label: string }) {
  return (
    <ol aria-label={label} className="flex items-start gap-2">
      {steps.map((step, i) => {
        const done = i < current;
        const active = i === current;
        return (
          <li key={step} className="flex min-w-0 flex-1 flex-col gap-2" aria-current={active ? "step" : undefined}>
            <div className="flex items-center gap-2">
              <m.span
                className={`grid h-8 w-8 shrink-0 place-items-center rounded-full border text-sm font-semibold ${
                  done
                    ? "border-accent bg-accent text-[#04201f]"
                    : active
                      ? "border-accent text-white shadow-[0_0_16px_-2px_rgb(94_234_212/0.7)]"
                      : "border-white/20 text-muted"
                }`}
                initial={false}
                animate={{ scale: active ? 1.08 : 1 }}
                transition={{ duration: 0.25, ease: EASE_OUT }}
              >
                {done ? <Check className="h-4 w-4" aria-hidden="true" /> : <span className="num">{i + 1}</span>}
              </m.span>
              {i < steps.length - 1 && (
                <span className="relative h-px flex-1 overflow-hidden bg-white/15" aria-hidden="true">
                  <m.span
                    className="absolute inset-0 bg-accent"
                    style={{ transformOrigin: "var(--origin, left)" }}
                    initial={false}
                    animate={{ scaleX: done ? 1 : 0 }}
                    transition={{ duration: 0.5, ease: EASE_OUT }}
                  />
                </span>
              )}
            </div>
            <span className={`text-xs leading-snug ${active ? "font-semibold text-white" : "text-muted"}`}>
              {step}
              {done && <span className="sr-only"> ✓</span>}
            </span>
          </li>
        );
      })}
    </ol>
  );
}
