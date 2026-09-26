"use client";

import dynamic from "next/dynamic";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useMemo } from "react";
import { DistrictPanel } from "@/components/DistrictPanel";
import { LevelBadge } from "@/components/Level";
import { useLevels } from "@/components/LevelsProvider";
import { ErrorNotice, Loading } from "@/components/Status";
import { useI18n } from "@/i18n/LanguageProvider";
import { api } from "@/lib/api";
import { shapeNameFor } from "@/lib/geo";
import { useApi } from "@/lib/useApi";

// Leaflet needs `window`; load the map only in the browser.
const DistrictMap = dynamic(() => import("@/components/DistrictMap"), {
  ssr: false,
  loading: () => <div className="h-full w-full animate-pulse bg-slate-100" />,
});

// Districts known to have no polygon in the vendored geoBoundaries file
// (see lib/geo.ts); listed on the page instead of being silently missing.
const NO_POLYGON = ["Larkana", "Chiniot", "Nankana Sahib", "Sujawal", "Mirpur", "Kotli"];

function MapView() {
  const { t, pick } = useI18n();
  const { levels } = useLevels();
  const router = useRouter();
  const selected = useSearchParams().get("district");
  const active = useApi(api.active, [], 60_000);

  const levelByDistrict = useMemo(() => {
    const out: Record<string, number> = {};
    for (const row of active.data?.districts ?? []) out[row.district] = row.level;
    return out;
  }, [active.data]);
  const districts = useMemo(() => Object.keys(levelByDistrict).sort(), [levelByDistrict]);

  const describe = (district: string) => {
    const level = levelByDistrict[district];
    const meta = levels[level];
    return `${district} — ${t("common.level", { n: level })}${meta ? ` · ${pick(meta.name_en, meta.name_ur)}` : ""}`;
  };

  const select = (district: string) => router.replace(`/map?district=${encodeURIComponent(district)}`, { scroll: false });

  return (
    <div className="space-y-4">
      <h1 className="h1">{t("map.title")}</h1>
      {active.error !== null && !active.data && <ErrorNotice error={active.error} onRetry={active.reload} />}

      <div className="flex flex-wrap items-center gap-2" aria-label={t("map.legend")}>
        {[1, 2, 3, 4, 5].map((level) => (
          <LevelBadge key={level} level={level} size="sm" />
        ))}
      </div>

      <div className="grid gap-4 lg:grid-cols-[3fr_2fr]">
        <div className="space-y-2">
          <div className="h-[60vh] min-h-80 overflow-hidden rounded-xl border border-slate-200">
            {active.data ? (
              <DistrictMap
                levelByDistrict={levelByDistrict}
                districts={districts}
                selected={selected}
                onSelect={select}
                describe={describe}
                noDataLabel={t("common.noData")}
              />
            ) : (
              !active.error && <Loading />
            )}
          </div>
          {/* Keyboard/screen-reader alternative to clicking polygons. */}
          <label className="block">
            <span className="field-label">{t("common.district")}</span>
            <select className="field-input" value={selected ?? ""} onChange={(e) => e.target.value && select(e.target.value)}>
              <option value="">{t("map.select")}</option>
              {districts.map((d) => (
                <option key={d} value={d}>
                  {describe(d)}
                </option>
              ))}
            </select>
          </label>
          <p className="text-xs text-slate-600">
            {t("map.noPolygon", { list: NO_POLYGON.filter((d) => shapeNameFor(d) === d).join(", ") })}
          </p>
        </div>

        <aside className="card" aria-live="polite">
          {selected && levelByDistrict[selected] !== undefined ? (
            <DistrictPanel key={selected} district={selected} level={levelByDistrict[selected]} />
          ) : (
            <p className="text-slate-600">{t("map.select")}</p>
          )}
        </aside>
      </div>
    </div>
  );
}

export default function MapPage() {
  // useSearchParams needs a Suspense boundary for static prerendering.
  return (
    <Suspense fallback={<Loading />}>
      <MapView />
    </Suspense>
  );
}
