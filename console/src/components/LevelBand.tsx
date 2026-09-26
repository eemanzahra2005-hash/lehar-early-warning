"use client";

import { AnimatePresence, m } from "framer-motion";
import { levelToken } from "@/lib/levels";
import { LevelIcon, levelScope } from "./Level";

/**
 * The animated background of a level band: the level's gradient (cross-
 * fading when the level changes), a slow drifting mesh, film-grain noise,
 * and for Level 5 a thin pulsing white edge so black never disappears into
 * the dark page. Put it inside an element with the `band` class.
 *
 * `hero` (home page only) swaps the single mesh for three slower drifting
 * blobs plus a light sweep every 8 s; the wave edge is <HeroWaves>.
 */
export function LevelBackdrop({ level, hero = false }: { level: number; hero?: boolean }) {
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
        >
          {/* The home hero's blobs and sweep live inside the level's own
              layer, so a level change cross-fades them with the gradient
              (a white sweep never lands on the outgoing level's red). */}
          {hero && (
            <>
              <span className="hero-blob b1" />
              <span className="hero-blob b2" />
              <span className="hero-blob b3" />
              <span className="hero-sweep" />
            </>
          )}
        </m.div>
      </AnimatePresence>
      {!hero && <div className="band-mesh" aria-hidden="true" />}
      <div className="band-noise" aria-hidden="true" />
      {n === 5 && <div className="band-edge" aria-hidden="true" />}
    </>
  );
}

/**
 * Level icon with expanding pulse rings from Level 3 upwards. `radar` (home
 * hero) rings at every level instead: calm every 3 s, stronger and faster
 * from Level 3.
 */
export function PulsingIcon({
  level,
  className = "h-14 w-14",
  ringClass = "",
  radar = false,
}: {
  level: number;
  className?: string;
  ringClass?: string;
  radar?: boolean;
}) {
  return (
    <span className={`relative inline-grid shrink-0 place-items-center rounded-full ${ringClass}`}>
      {radar ? (
        level >= 3 ? (
          <>
            <span className="radar-ring strong" aria-hidden="true" />
            <span className="radar-ring strong delay" aria-hidden="true" />
          </>
        ) : (
          <span className="radar-ring" aria-hidden="true" />
        )
      ) : level >= 3 && (
        <>
          <span className="pulse-ring" aria-hidden="true" />
          <span className="pulse-ring delay" aria-hidden="true" />
        </>
      )}
      <LevelIcon level={level} className={className} />
    </span>
  );
}

/**
 * A smooth wave across 1440 units, filled down to the bottom (48). The SVG
 * is drawn at 200 % of the band's width; `period` must divide 720 so that
 * sliding it by -50 % lands on an identical shape and the loop is seamless.
 */
function wavePath(period: number, mid: number, amp: number): string {
  const half = period / 2;
  let d = `M0 ${mid} C${half / 3} ${mid - amp} ${(2 * half) / 3} ${mid - amp} ${half} ${mid}`;
  // Each "S" mirrors the previous curve, alternating crest and trough.
  for (let x = 2 * half, sign = 1; x <= 1440; x += half, sign = -sign) {
    d += ` S${x - half / 3} ${mid + sign * amp} ${x} ${mid}`;
  }
  return `${d} V48 H0 Z`;
}
const WAVE_BACK = wavePath(360, 22, 14); // 2 crests per band width
const WAVE_FRONT = wavePath(240, 31, 9); // 3 crests per band width

/** Two layered waves along the bottom of the home hero, level-tinted at the back. */
export function HeroWaves() {
  return (
    <div className="hero-waves" aria-hidden="true">
      <svg className="hero-wave back" viewBox="0 0 1440 48" preserveAspectRatio="none" focusable="false">
        <path d={WAVE_BACK} />
      </svg>
      <svg className="hero-wave front" viewBox="0 0 1440 48" preserveAspectRatio="none" focusable="false">
        <path d={WAVE_FRONT} />
      </svg>
    </div>
  );
}
