"use client";

import { AnimatePresence, m } from "framer-motion";
import { levelToken } from "@/lib/levels";
import { LevelIcon, levelScope } from "./Level";

/**
 * The animated background of a level band: the level's gradient (cross-
 * fading when the level changes), a slow drifting mesh, film-grain noise,
 * and for Level 5 a thin pulsing white edge so black never disappears into
 * the dark page. Put it inside an element with the `band` class.
 */
export function LevelBackdrop({ level }: { level: number }) {
  const n = levelToken(level).number;
  return (
    <>
      <AnimatePresence initial={false}>
        <m.div
          key={n}
          className={`band-layer ${levelScope(n)}`}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.8, ease: "easeInOut" }}
          aria-hidden="true"
        />
      </AnimatePresence>
      <div className="band-mesh" aria-hidden="true" />
      <div className="band-noise" aria-hidden="true" />
      {n === 5 && <div className="band-edge" aria-hidden="true" />}
    </>
  );
}

/** Level icon with expanding pulse rings from Level 3 upwards. */
export function PulsingIcon({ level, className = "h-14 w-14", ringClass = "" }: { level: number; className?: string; ringClass?: string }) {
  return (
    <span className={`relative inline-grid shrink-0 place-items-center rounded-full ${ringClass}`}>
      {level >= 3 && (
        <>
          <span className="pulse-ring" aria-hidden="true" />
          <span className="pulse-ring delay" aria-hidden="true" />
        </>
      )}
      <LevelIcon level={level} className={className} />
    </span>
  );
}
