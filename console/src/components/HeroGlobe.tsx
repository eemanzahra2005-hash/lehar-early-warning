"use client";

import type { Globe } from "cobe";
import { useEffect, useRef } from "react";
import { buildMarkers, locationToAngles, PAKISTAN_CENTER, shortestTurn, type GlobePoint } from "@/lib/globe";
import { usePrefersReducedMotion } from "./Motion";

// The resting view sways gently either side of Pakistan instead of spinning
// all the way round, so the alerting districts never spend half the time on
// the far side of the planet.
const SWAY_RAD = 0.45; // ~26 degrees each way
const SWAY_MS = 36_000; // one full sway, there and back
const PULSE_MS = 2_400; // halo pulse under alerting districts
const EASE = 0.06; // share of the remaining turn covered each frame when focusing

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

/**
 * The dotted globe in the home hero, drawn with `cobe` (a ~13 KB WebGL
 * library, loaded only when this mounts). One marker per district: calm ones
 * faint, alerting ones in their level's colour with a pulsing halo.
 *
 * cobe v2 draws exactly one frame per update() call, so the animation loop
 * is ours and it only runs while the globe is on screen AND the tab is
 * visible. Under prefers-reduced-motion there is no loop at all: one still
 * frame, redrawn only when the data or the focused district changes.
 *
 * If WebGL is missing (or cobe fails to load) it calls `onUnavailable` and
 * the hero shows the SVG mini-map instead.
 */
export function HeroGlobe({
  points,
  levelByDistrict,
  focus,
  label,
  onUnavailable,
}: {
  points: GlobePoint[];
  levelByDistrict: Record<string, number>;
  /** District to turn to, or null to rest on Pakistan. */
  focus: GlobePoint | null;
  label: string;
  onUnavailable: () => void;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const reduce = usePrefersReducedMotion();

  // The loop reads the latest props through refs, so new data or a new
  // focus never tears down the WebGL context.
  const dataRef = useRef({ points, levelByDistrict });
  const focusRef = useRef(focus);
  const failRef = useRef(onUnavailable);
  const kickRef = useRef<() => void>(() => {});
  useEffect(() => {
    dataRef.current = { points, levelByDistrict };
    focusRef.current = focus;
    failRef.current = onUnavailable;
    kickRef.current(); // redraw now (the only way a still frame updates)
  }, [points, levelByDistrict, focus, onUnavailable]);

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
    const started = performance.now();
    const running = () => !reduce && onScreen && !document.hidden;

    const tick = (now: number) => {
      frame = 0;
      if (!globe) return;
      const f = focusRef.current;
      const sway = reduce ? 0 : Math.sin(((now - started) / SWAY_MS) * 2 * Math.PI) * SWAY_RAD;
      const [toPhi, toTheta] = f ? locationToAngles(f.lat, f.lon) : [homePhi + sway, homeTheta];
      if (reduce) {
        // No motion: jump straight to the view.
        phi = toPhi;
        theta = toTheta;
      } else {
        phi += shortestTurn(phi, toPhi) * EASE;
        theta += (toTheta - theta) * EASE;
      }
      const pulse = reduce ? 0 : 0.5 - 0.5 * Math.cos(((now - started) / PULSE_MS) * 2 * Math.PI);
      const { points: pts, levelByDistrict: levels } = dataRef.current;
      globe.update({ phi, theta, markers: buildMarkers(pts, levels, pulse) });
      if (running()) frame = requestAnimationFrame(tick);
    };
    // Draw a frame soon, unless one is already queued.
    const kick = () => {
      if (!frame && globe) frame = requestAnimationFrame(tick);
    };
    const pause = () => {
      cancelAnimationFrame(frame);
      frame = 0;
    };
    kickRef.current = kick;

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
          dark: 1,
          diffuse: 1.4,
          mapSamples: 14_000,
          mapBrightness: 5,
          mapBaseBrightness: 0.02,
          baseColor: [0.2, 0.25, 0.32],
          markerColor: [1, 1, 1],
          glowColor: [0.28, 0.36, 0.45],
          markerElevation: 0.01,
          markers: buildMarkers(dataRef.current.points, dataRef.current.levelByDistrict),
        });
        kick();
      })
      .catch(() => !cancelled && failRef.current());

    return () => {
      cancelled = true;
      pause();
      kickRef.current = () => {};
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
