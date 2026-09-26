"use client";

import { AnimatePresence, m, useDragControls, type PanInfo } from "framer-motion";
import { MousePointerClick } from "lucide-react";
import dynamic from "next/dynamic";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useRef, useState } from "react";
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

const PANEL_SPRING = { type: "spring", stiffness: 320, damping: 32 } as const;

/**
 * Phones: the district panel as a bottom sheet above the tab bar. It springs
 * up from the bottom edge; dragging its handle down far or fast enough
 * dismisses it (the close button still does the same, for everyone who
 * cannot or does not want to drag). Only the handle starts a drag, so the
 * sheet's own content scrolls normally.
 */
function BottomSheet({ label, onClose, children }: { label: string; onClose: () => void; children: React.ReactNode }) {
  const controls = useDragControls();
  const onDragEnd = (_: unknown, info: PanInfo) => {
    if (info.offset.y > 120 || info.velocity.y > 600) onClose();
  };
  return (
    <m.section
      aria-label={label}
      aria-live="polite"
      initial={{ y: "100%" }}
      animate={{ y: 0 }}
      exit={{ y: "100%" }}
      transition={PANEL_SPRING}
      drag="y"
      dragListener={false}
      dragControls={controls}
      dragConstraints={{ top: 0, bottom: 0 }}
      dragElastic={{ top: 0, bottom: 0.7 }}
      onDragEnd={onDragEnd}
      className="fixed inset-x-0 z-[1090] flex max-h-[72dvh] flex-col rounded-t-3xl border border-b-0 border-line bg-[#0e1524]/95 shadow-[0_-24px_48px_-12px_rgb(0_0_0/0.7)] backdrop-blur-xl"
      style={{ bottom: "calc(var(--tabbar-h) + env(safe-area-inset-bottom))" }}
    >
      {/* Drag handle: a 44 px tall grab area around the visible pill. */}
      <div
        aria-hidden="true"
        onPointerDown={(e) => controls.start(e)}
        className="flex h-11 shrink-0 cursor-grab touch-none items-center justify-center active:cursor-grabbing"
      >
        <span className="h-1.5 w-12 rounded-full bg-white/30" />
      </div>
      <div className="overflow-y-auto overscroll-contain px-5 pt-5 pb-5">{children}</div>
    </m.section>
  );
}

/**
 * Width of an element in px, kept current as it resizes (0 until measured).
 * Only observes while `enabled`: every width update re-renders the whole
 * map view, so it is skipped where the width is not needed.
 */
function useWidth(ref: React.RefObject<HTMLElement | null>, enabled: boolean): number {
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const el = ref.current;
    if (!el || !enabled) return;
    const observer = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width));
    observer.observe(el);
    return () => observer.disconnect();
  }, [ref, enabled]);
  return width;
}

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
  // Tablets and up: the panel floats over the map (45% wide on tablets,
  // 440 px on desktop). Phones: it is a bottom sheet instead.
  const overlay = useMediaQuery("(min-width: 768px)");
  const desktop = useMediaQuery("(min-width: 1024px)");
  const mapBox = useRef<HTMLDivElement>(null);
  // Only a tablet with the panel open needs the map's width (for the 45% panel).
  const mapWidth = useWidth(mapBox, open && overlay && !desktop);
  const panelWidth = desktop ? 440 : Math.round(mapWidth * 0.45);
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
      <div ref={mapBox} className="glass relative isolate h-[62vh] min-h-[420px] overflow-hidden !p-0 lg:h-[calc(100dvh-var(--header-h)-230px)] lg:min-h-[560px]">
        {active.data ? (
          <DistrictMap
            levelByDistrict={levelByDistrict}
            districts={districts}
            selected={selected}
            onSelect={select}
            describe={describe}
            noDataLabel={t("common.noData")}
            padEnd={open && overlay ? panelWidth + 16 : 0}
            rtl={lang === "ur"}
          />
        ) : (
          !active.error && <div className="skeleton h-full w-full rounded-none" />
        )}

        {/* Tablet and desktop: the district panel floats over the map's reading end. */}
        <AnimatePresence>
          {open && overlay && (
            <m.aside
              key={selected}
              aria-live="polite"
              aria-label={selected ?? undefined}
              initial={{ opacity: 0, x: slide }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: slide }}
              transition={PANEL_SPRING}
              className="glass absolute inset-y-3 end-3 z-[1000] w-[45%] overflow-y-auto overscroll-contain bg-[#0e1524]/90 p-5 lg:w-[440px]"
            >
              <DistrictPanel district={selected!} level={levelByDistrict[selected!]} onClose={close} />
            </m.aside>
          )}
        </AnimatePresence>
      </div>

      {/* Phones: the same panel as a draggable bottom sheet. */}
      <AnimatePresence>
        {open && !overlay && (
          <BottomSheet key={selected} label={selected!} onClose={close}>
            <DistrictPanel district={selected!} level={levelByDistrict[selected!]} onClose={close} />
          </BottomSheet>
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
