"use client";

import { AnimatePresence, m } from "framer-motion";
import { MousePointerClick } from "lucide-react";
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
import { useMediaQuery } from "@/lib/useMediaQuery";

// Leaflet needs `window`; load the map only in the browser.
const DistrictMap = dynamic(() => import("@/components/DistrictMap"), {
  ssr: false,
  loading: () => <div className="skeleton h-full w-full rounded-none" />,
});

// Districts known to have no polygon in the vendored geoBoundaries file
// (see lib/geo.ts); listed on the page instead of being silently missing.
const NO_POLYGON = ["Larkana", "Chiniot", "Nankana Sahib", "Sujawal", "Mirpur", "Kotli"];

function MapView() {
  const { t, pick, lang } = useI18n();
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
  const close = () => router.replace("/map", { scroll: false });
  const open = selected !== null && levelByDistrict[selected] !== undefined;
  const desktop = useMediaQuery("(min-width: 1024px)");
  // The panel slides in from the reading end: right in English, left in Urdu.
  const slide = lang === "ur" ? -48 : 48;

  return (
    <div className="page space-y-5 py-8">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="space-y-2">
          <h1 className="h1">{t("map.title")}</h1>
          <p className="flex items-center gap-2 text-sm text-muted">
            <MousePointerClick className="h-4 w-4" aria-hidden="true" />
            {t("map.hint")}
          </p>
        </div>
        <ul className="flex flex-wrap items-center gap-2" aria-label={t("map.legend")}>
          {[1, 2, 3, 4, 5].map((level) => (
            <li key={level}>
              <LevelBadge level={level} size="sm" />
            </li>
          ))}
        </ul>
      </div>

      {active.error !== null && !active.data && <ErrorNotice error={active.error} onRetry={active.reload} />}

      {/* `isolate` keeps Leaflet's internal z-indexes inside this box, so the
          panel, header and tab bar always sit above the map. */}
      <div className="glass relative isolate h-[62vh] min-h-[420px] overflow-hidden !p-0 lg:h-[calc(100dvh-var(--header-h)-230px)] lg:min-h-[560px]">
        {active.data ? (
          <DistrictMap
            levelByDistrict={levelByDistrict}
            districts={districts}
            selected={selected}
            onSelect={select}
            describe={describe}
            noDataLabel={t("common.noData")}
            padEnd={open && desktop ? 456 : 0}
            rtl={lang === "ur"}
          />
        ) : (
          !active.error && <div className="skeleton h-full w-full rounded-none" />
        )}

        {/* Desktop: the district panel floats over the map's reading end. */}
        <AnimatePresence>
          {open && desktop && (
            <m.aside
              key={selected}
              aria-live="polite"
              aria-label={selected ?? undefined}
              initial={{ opacity: 0, x: slide }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: slide }}
              transition={{ type: "spring", stiffness: 320, damping: 32 }}
              className="glass absolute inset-y-3 end-3 z-[1000] w-[440px] overflow-y-auto bg-[#0e1524]/90 p-5"
            >
              <DistrictPanel district={selected!} level={levelByDistrict[selected!]} onClose={close} />
            </m.aside>
          )}
        </AnimatePresence>
      </div>

      {/* Phones and tablets: the same panel below the map, rising into view. */}
      <AnimatePresence>
        {open && !desktop && (
          <m.section
            key={selected}
            aria-live="polite"
            initial={{ opacity: 0, y: 24 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            transition={{ type: "spring", stiffness: 320, damping: 32 }}
            className="glass p-5"
          >
            <DistrictPanel district={selected!} level={levelByDistrict[selected!]} onClose={close} />
          </m.section>
        )}
      </AnimatePresence>

      <div className="grid gap-4 md:grid-cols-[minmax(0,420px)_1fr] md:items-end">
        {/* Keyboard/screen-reader alternative to clicking polygons. */}
        <label className="block">
          <span className="field-label">{t("common.district")}</span>
          <select className="field-input" value={selected ?? ""} onChange={(e) => (e.target.value ? select(e.target.value) : close())}>
            <option value="">{t("map.select")}</option>
            {districts.map((d) => (
              <option key={d} value={d}>
                {describe(d)}
              </option>
            ))}
          </select>
        </label>
        <p className="text-xs text-muted md:pb-3">
          {t("map.noPolygon", { list: NO_POLYGON.filter((d) => shapeNameFor(d) === d).join(", ") })}
        </p>
      </div>
    </div>
  );
}

export default function MapPage() {
  // useSearchParams needs a Suspense boundary for static prerendering.
  return (
    <Suspense
      fallback={
        // Tall like the real page, so the footer does not jump when it renders.
        <div className="page min-h-[calc(100dvh-var(--header-h))] py-8">
          <Loading />
        </div>
      }
    >
      <MapView />
    </Suspense>
  );
}
