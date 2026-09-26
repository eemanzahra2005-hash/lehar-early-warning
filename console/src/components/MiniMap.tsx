"use client";

import { useInView } from "framer-motion";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { useI18n } from "@/i18n/LanguageProvider";
import { districtForShape } from "@/lib/geo";
import { levelToken } from "@/lib/levels";
import { useLevels } from "./LevelsProvider";

interface MiniMapData {
  viewBox: string;
  features: { n: string; d: string }[];
}

/**
 * Overview choropleth for the home page: plain SVG on the dark theme, no
 * tiles, no Leaflet. The geometry is the simplified public/geo/minimap.json
 * (see scripts/build-minimap.mjs), fetched only once the map scrolls into
 * view. Each district names its level in a <title> (never colour alone);
 * clicking opens it on the full map, and the page links there for keyboard
 * users.
 */
export function MiniMap({ levelByDistrict }: { levelByDistrict: Record<string, number> }) {
  const { t, pick } = useI18n();
  const { levels } = useLevels();
  const router = useRouter();
  const ref = useRef<HTMLDivElement>(null);
  const inView = useInView(ref, { once: true, margin: "200px" });
  const [data, setData] = useState<MiniMapData | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (!inView) return;
    let cancelled = false;
    fetch("/geo/minimap.json")
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((json: MiniMapData) => !cancelled && setData(json))
      .catch(() => !cancelled && setFailed(true));
    return () => {
      cancelled = true;
    };
  }, [inView]);

  const districts = useMemo(() => Object.keys(levelByDistrict), [levelByDistrict]);

  // Calm (L1) districts are a faint white wash; alerting ones glow.
  const shapes = useMemo(
    () =>
      (data?.features ?? []).map((f) => {
        const district = districtForShape(f.n, districts);
        const level = district ? levelByDistrict[district] : undefined;
        return { ...f, district, level };
      }),
    [data, districts, levelByDistrict],
  );

  const describe = (district: string | null, shape: string, level: number | undefined) => {
    if (!district || level === undefined) return `${shape} — ${t("common.noData")}`;
    const meta = levels[level];
    return `${district} — ${t("common.level", { n: level })}${meta ? ` · ${pick(meta.name_en, meta.name_ur)}` : ""}`;
  };

  return (
    <div ref={ref} className="relative aspect-[1000/870] w-full" dir="ltr">
      {failed ? (
        <p role="alert" className="grid h-full place-items-center text-sm text-muted">
          {t("common.noData")}
        </p>
      ) : !data ? (
        <div className="skeleton h-full w-full" aria-hidden="true" />
      ) : (
        <svg viewBox={data.viewBox} className="h-full w-full" role="img" aria-label={t("map.title")}>
          <defs>
            <filter id="mini-glow" x="-50%" y="-50%" width="200%" height="200%">
              <feGaussianBlur stdDeviation="4" result="blur" />
              <feMerge>
                <feMergeNode in="blur" />
                <feMergeNode in="SourceGraphic" />
              </feMerge>
            </filter>
          </defs>
          {/* Calm and unknown districts first, so alert outlines sit on top. */}
          {[...shapes]
            .sort((a, b) => (a.level ?? -1) - (b.level ?? -1))
            .map((s) => {
              const token = s.level !== undefined ? levelToken(s.level) : null;
              const alerting = s.level !== undefined && s.level >= 2;
              return (
                <path
                  key={s.n}
                  d={s.d}
                  fill={token ? token.bg : "transparent"}
                  fillOpacity={!token ? 0 : s.level === 1 ? 0.1 : 0.85}
                  stroke={token ? token.ink : "#94a0b2"}
                  strokeOpacity={alerting ? 1 : 0.35}
                  strokeWidth={alerting ? 1.6 : 0.8}
                  strokeDasharray={s.district ? undefined : "3 3"}
                  filter={alerting ? "url(#mini-glow)" : undefined}
                  className={s.district ? "mini-district" : undefined}
                  onClick={s.district ? () => router.push(`/map?district=${encodeURIComponent(s.district!)}`) : undefined}
                >
                  <title>{describe(s.district, s.n, s.level)}</title>
                </path>
              );
            })}
        </svg>
      )}
    </div>
  );
}
