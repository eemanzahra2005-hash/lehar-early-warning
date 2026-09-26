"use client";

import { m } from "framer-motion";
import { SPRING } from "./Motion";

export interface ChipOption {
  value: string;
  label: React.ReactNode;
}

/**
 * Single-choice filter chips. A radio group underneath (arrow keys are not
 * needed: each chip is its own button with aria-checked), with the selection
 * highlight sliding between chips.
 */
export function ChipGroup({
  id,
  label,
  options,
  value,
  onChange,
}: {
  id: string;
  label: string;
  options: ChipOption[];
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <div role="radiogroup" aria-label={label} className="flex flex-wrap gap-2">
      {options.map((option) => {
        const selected = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-checked={selected}
            onClick={() => onChange(option.value)}
            className={`press relative isolate inline-flex min-h-11 items-center transition-[transform,background-color,color] md:min-h-9 gap-1.5 rounded-full border px-3 py-1.5 text-sm font-medium ${
              selected ? "border-accent/60 text-white" : "border-line bg-white/[0.03] text-ink hover:bg-white/[0.08]"
            }`}
          >
            {selected && (
              <m.span
                layoutId={`chip-${id}`}
                transition={SPRING}
                className="absolute inset-0 -z-10 rounded-full bg-accent/15 shadow-[0_0_16px_-4px_rgb(94_234_212/0.6)]"
                aria-hidden="true"
              />
            )}
            {option.label}
          </button>
        );
      })}
    </div>
  );
}
