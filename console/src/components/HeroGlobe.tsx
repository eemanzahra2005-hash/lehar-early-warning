"use client";

import type { Globe } from "cobe";
import { useEffect, useRef } from "react";
import {
  buildMarkers,
  decayFling,
  locationToAngles,
  PAKISTAN_CENTER,
  rimColor,
  shortestTurn,
  SPIN_RAD_PER_S,
  type GlobePoint,
} from "@/lib/globe";
import { usePrefersReducedMotion } from "./Motion";

const PULSE_MS = 2_400; // halo pulse under alerting districts
const EASE = 0.06; // share of the remaining turn covered per 60 fps frame when focusing
const MAX_DT = 0.05; // s; a long gap (tab switch, jank) never jumps the globe

/** True if this browser can give us a WebGL context at all. */
function webglAvailable(): boolean {
  try {
    const probe = document.createElement("canvas");
    const gl = probe.getContext("webgl2") ?? probe.getContext("webgl");
    // Hand the probe context straight back; browsers cap how many exist.
    gl?.getExtension("WEBGL_lose_context")?.loseContext();
    return !!gl;
  } catch {
    return false;
  }
}

/** Share of the remaining distance to cover this frame, at any frame rate. */
const easeStep = (dt: number) => 1 - (1 - EASE) ** (dt * 60);

/**
 * The dotted globe in the home hero, drawn with `cobe` (a ~13 KB WebGL
 * library, loaded only when this mounts). It starts with Pakistan facing the
 * viewer and turns slowly; a mouse can drag it round and fling it (touch
 * scrolls the page instead). Markers: a faint dotted national border, then
 * one small dot per district, calm ones faint and alerting ones in their
 * level's colour over a pulsing halo. The atmosphere rim takes the national
 * level's colour.
 *
 * cobe v2 draws exactly one frame per update() call, so the animation loop
 * is ours and it only runs while the globe is on screen AND the tab is
 * visible. Under prefers-reduced-motion there is no loop at all: one still
 * frame, redrawn only when the data, the focused district or a drag changes
 * it (a drag still turns it, it just never coasts).
 *
 * If WebGL is missing (or cobe fails to load) it calls `onUnavailable` and
 * the hero shows the SVG mini-map instead.
 */
export function HeroGlobe({
  points,
  border,
  levelByDistrict,
  level,
  focus,
  label,
  onUnavailable,
}: {
  points: GlobePoint[];
  /** [lat, lon] dots along the national border. */
  border: [number, number][];
  levelByDistrict: Record<string, number>;
  /** National (highest) level: tints the atmosphere rim. */
  level: number;
  /** District to turn to, or null to keep spinning. */
  focus: GlobePoint | null;
  label: string;
  onUnavailable: () => void;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const reduce = usePrefersReducedMotion();

  // The loop reads the latest props through refs, so new data or a new
  // focus never tears down the WebGL context.
  const dataRef = useRef({ points, border, levelByDistrict, level });
  const focusRef = useRef(focus);
  const followRef = useRef(true); // false once the user drags away from the focus
  const failRef = useRef(onUnavailable);
  const kickRef = useRef<() => void>(() => {});
  useEffect(() => {
    dataRef.current = { points, border, levelByDistrict, level };
    failRef.current = onUnavailable;
    kickRef.current(); // redraw now (the only way a still frame updates)
  }, [points, border, levelByDistrict, level, onUnavailable]);
  useEffect(() => {
    // A newly picked district always turns into view, even after a drag.
    focusRef.current = focus;
    followRef.current = true;
    kickRef.current();
  }, [focus]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    if (!webglAvailable()) {
      failRef.current();
      return;
    }

    let globe: Globe | null = null;
    let frame = 0;
    let cancelled = false;
    let onScreen = true;
    const [homePhi, homeTheta] = locationToAngles(...PAKISTAN_CENTER);
    let phi = homePhi;
    let theta = homeTheta;
    let fling = 0; // extra spin left over from a mouse fling, rad/s
    let drag: { x: number; t: number } | null = null;
    let last = performance.now();
    const started = last;
    const redraws: number[] = [];
    const running = () => !reduce && onScreen && !document.hidden;

    const markers = (pulse: number) => {
      const d = dataRef.current;
      return buildMarkers(d.points, d.levelByDistrict, pulse, d.border);
    };

    const tick = (now: number) => {
      frame = 0;
      if (!globe) return;
      const dt = Math.min(MAX_DT, Math.max(0, now - last) / 1000);
      last = now;
      const f = followRef.current ? focusRef.current : null;
      if (drag) {
        // The pointer handlers turn phi; the loop only draws.
      } else if (f) {
        const [toPhi, toTheta] = locationToAngles(f.lat, f.lon);
        if (reduce) {
          phi = toPhi; // no motion: jump straight to the view
          theta = toTheta;
        } else {
          phi += shortestTurn(phi, toPhi) * easeStep(dt);
          theta += (toTheta - theta) * easeStep(dt);
        }
      } else if (!reduce) {
        phi += (SPIN_RAD_PER_S + fling) * dt;
        fling = decayFling(fling, dt);
        theta += (homeTheta - theta) * easeStep(dt);
      }
      const pulse = reduce ? 0 : 0.5 - 0.5 * Math.cos(((now - started) / PULSE_MS) * 2 * Math.PI);
      globe.update({ phi, theta, glowColor: rimColor(dataRef.current.level), markers: markers(pulse) });
      if (running()) frame = requestAnimationFrame(tick);
    };
    // Draw a frame soon, unless one is already queued.
    const kick = () => {
      if (!frame && globe) {
        last = performance.now();
        frame = requestAnimationFrame(tick);
      }
    };
    const pause = () => {
      cancelAnimationFrame(frame);
      frame = 0;
    };
    kickRef.current = kick;

    // Mouse/pen drag with inertia. Touch is left alone (touch-action: pan-y
    // in CSS) so a thumb on the globe still scrolls the page on phones.
    const onDown = (e: PointerEvent) => {
      if (e.pointerType === "touch" || e.button !== 0) return;
      canvas.setPointerCapture(e.pointerId);
      drag = { x: e.clientX, t: e.timeStamp };
      fling = 0;
      followRef.current = false;
      canvas.dataset.dragging = "true";
    };
    const onMove = (e: PointerEvent) => {
      if (!drag) return;
      // Dragging across the whole globe turns it half way round.
      const turn = ((e.clientX - drag.x) / Math.max(1, canvas.offsetWidth)) * Math.PI;
      const seconds = Math.max(1, e.timeStamp - drag.t) / 1000;
      phi += turn;
      // Smoothed pointer speed, so the release fling is not one jittery sample.
      fling = fling * 0.6 + (turn / seconds) * 0.4;
      drag = { x: e.clientX, t: e.timeStamp };
      kick();
    };
    const onUp = (e: PointerEvent) => {
      if (!drag) return;
      // Holding still before letting go means "stop here", not "fling".
      if (reduce || e.timeStamp - drag.t > 80) fling = 0;
      fling = Math.max(-6, Math.min(6, fling));
      drag = null;
      delete canvas.dataset.dragging;
      kick();
    };
    canvas.addEventListener("pointerdown", onDown);
    canvas.addEventListener("pointermove", onMove);
    canvas.addEventListener("pointerup", onUp);
    canvas.addEventListener("pointercancel", onUp);

    const onVisibility = () => (document.hidden ? pause() : kick());
    document.addEventListener("visibilitychange", onVisibility);
    const seen = new IntersectionObserver(([entry]) => {
      onScreen = entry.isIntersecting;
      if (onScreen) kick();
      else pause();
    });
    seen.observe(canvas);
    // The canvas is square and fills its box; follow that box's size.
    const resized = new ResizeObserver(() => {
      const size = canvas.offsetWidth;
      if (globe && size > 0) {
        globe.update({ width: size, height: size });
        kick();
      }
    });
    resized.observe(canvas);

    import("cobe")
      .then(({ default: createGlobe }) => {
        if (cancelled) return;
        const size = canvas.offsetWidth || 400;
        globe = createGlobe(canvas, {
          // Phones get 1.5x, not 3x: the dots stay crisp at a fraction of the fill cost.
          devicePixelRatio: Math.min(window.devicePixelRatio || 1, 2),
          width: size,
          height: size,
          phi,
          theta,
          // Land visible but quiet: a slightly lifted dark side, softer
          // light and dim fine dots, so the district markers are what the
          // eye finds first.
          dark: 0.85,
          diffuse: 1.2,
          mapSamples: 16_000,
          mapBrightness: 3.2,
          mapBaseBrightness: 0.02,
          baseColor: [0.16, 0.21, 0.25],
          markerColor: [1, 1, 1],
          glowColor: rimColor(dataRef.current.level),
          markerElevation: 0.005,
          markers: markers(0),
        });
        kick();
        // cobe loads its land-dot texture asynchronously and has no "loaded"
        // event. The live loop picks it up on its own; a reduced-motion still
        // frame would otherwise be drawn without land, so redraw it a few
        // times while the texture arrives.
        if (reduce) for (const ms of [150, 500, 1200]) redraws.push(window.setTimeout(kick, ms));
      })
      .catch(() => !cancelled && failRef.current());

    return () => {
      cancelled = true;
      redraws.forEach(clearTimeout);
      pause();
      kickRef.current = () => {};
      canvas.removeEventListener("pointerdown", onDown);
      canvas.removeEventListener("pointermove", onMove);
      canvas.removeEventListener("pointerup", onUp);
      canvas.removeEventListener("pointercancel", onUp);
      document.removeEventListener("visibilitychange", onVisibility);
      seen.disconnect();
      resized.disconnect();
      globe?.destroy();
    };
  }, [reduce]);

  return (
    <canvas
      ref={canvasRef}
      role="img"
      aria-label={label}
      className="hero-globe-canvas aspect-square h-auto w-full"
    />
  );
}
