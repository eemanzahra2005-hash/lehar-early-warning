"use client";

import { AnimatePresence, m } from "framer-motion";
import { ArrowUpRight, ChevronsUpDown, Search, X } from "lucide-react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useEffect, useId, useMemo, useRef, useState } from "react";
import { useI18n } from "@/i18n/LanguageProvider";
import { api } from "@/lib/api";
import { districtNameUr } from "@/lib/districtNames";
import { formatDateTime } from "@/lib/format";
import { filterDistricts, type GlobePoint } from "@/lib/globe";
import type { AlertResponse } from "@/lib/types";
import { useApi } from "@/lib/useApi";
import { EASE_OUT, SPRING } from "./Motion";
import { LevelBadge, levelScope } from "./Level";

// Both are only needed once the hero is on screen, and the mini-map only
// if WebGL is missing: keep them out of the first bundle.
const HeroGlobe = dynamic(() => import("./HeroGlobe").then((mod) => mod.HeroGlobe), {
  ssr: false,
  loading: () => <div className="aspect-square w-full" aria-hidden="true" />,
});
const MiniMap = dynamic(() => import("./MiniMap").then((mod) => mod.MiniMap), {
  ssr: false,
  loading: () => <div className="skeleton aspect-[1000/870] w-full" aria-hidden="true" />,
});

/**
 * The glass "find a district" pill: an ARIA 1.2 combobox (a text box that
 * filters a listbox popup). Typing, ArrowDown or the chevron opens the list;
 * Up/Down move through it, Enter picks, Escape closes (and a second Escape
 * clears). The list opens upwards, over the globe, so the hero's bottom
 * edge never clips it.
 */
function DistrictCombobox({
  districts,
  levelByDistrict,
  selected,
  onSelect,
}: {
  districts: string[];
  levelByDistrict: Record<string, number>;
  selected: string | null;
  onSelect: (district: string | null) => void;
}) {
  const { t } = useI18n();
  const id = useId();
  const listId = `${id}-list`;
  const optionId = (i: number) => `${id}-opt-${i}`;
  const input = useRef<HTMLInputElement>(null);
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const options = useMemo(() => filterDistricts(query, districts), [query, districts]);
  const disabled = districts.length === 0;

  // Keep the highlighted option in view while arrowing through a long list.
  useEffect(() => {
    if (open) document.getElementById(optionId(active))?.scrollIntoView({ block: "nearest" });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- optionId is derived from the stable useId
  }, [active, open]);

  const choose = (district: string) => {
    setQuery(district);
    setOpen(false);
    onSelect(district);
  };
  const move = (delta: number) => {
    if (!open) setOpen(true);
    if (options.length) setActive((i) => (i + delta + options.length) % options.length);
  };

  return (
    <div className="relative">
      <label htmlFor={`${id}-input`} className="sr-only">
        {t("hero.pickLabel")}
      </label>
      <div className="hero-pill flex items-center gap-2 ps-4 pe-1.5">
        {selected ? (
          <span className={`${levelScope(levelByDistrict[selected])} dot h-2.5 w-2.5 shrink-0`} aria-hidden="true" />
        ) : (
          <Search className="h-4 w-4 shrink-0 text-[#b4bfcd]" aria-hidden="true" />
        )}
        <input
          ref={input}
          id={`${id}-input`}
          type="text"
          role="combobox"
          aria-expanded={open}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-activedescendant={open && options[active] ? optionId(active) : undefined}
          autoComplete="off"
          spellCheck={false}
          disabled={disabled}
          value={query}
          placeholder={disabled ? t("common.loading") : t("hero.pickPlaceholder", { n: districts.length })}
          onChange={(e) => {
            setQuery(e.target.value);
            setActive(0);
            setOpen(true);
          }}
          onClick={() => setOpen(true)}
          onBlur={() => setOpen(false)}
          onKeyDown={(e) => {
            if (e.key === "ArrowDown") {
              e.preventDefault();
              move(1);
            } else if (e.key === "ArrowUp") {
              e.preventDefault();
              move(-1);
            } else if (e.key === "Enter" && open && options[active]) {
              e.preventDefault();
              choose(options[active]);
            } else if (e.key === "Escape") {
              if (open) setOpen(false);
              else if (query || selected) {
                setQuery("");
                onSelect(null);
              }
            }
          }}
          className="hero-pill-input min-w-0 flex-1 bg-transparent py-3 text-base font-medium outline-none sm:text-lg"
        />
        {(query || selected) && (
          <button
            type="button"
            className="hero-pill-btn"
            aria-label={t("hero.pickClear")}
            onClick={() => {
              setQuery("");
              onSelect(null);
              input.current?.focus();
            }}
          >
            <X className="h-4 w-4" aria-hidden="true" />
          </button>
        )}
        {/* Mouse/touch shortcut to the full list; keyboard users have ArrowDown. */}
        <button
          type="button"
          tabIndex={-1}
          className="hero-pill-btn"
          aria-label={t("hero.pickAll")}
          disabled={disabled}
          onMouseDown={(e) => e.preventDefault()}
          onClick={() => {
            setOpen((o) => !o);
            input.current?.focus();
          }}
        >
          <ChevronsUpDown className="h-4 w-4" aria-hidden="true" />
        </button>
      </div>

      <AnimatePresence>
        {open && (
          <m.ul
            id={listId}
            role="listbox"
            aria-label={t("hero.pickLabel")}
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 4, transition: { duration: 0.12 } }}
            transition={{ duration: 0.18, ease: EASE_OUT }}
            className="hero-listbox absolute inset-x-0 bottom-[calc(100%+8px)] z-30 max-h-60 overflow-y-auto p-1.5"
          >
            {options.length === 0 ? (
              <li className="px-3 py-2 text-sm text-muted">{t("hero.pickNone")}</li>
            ) : (
              options.map((d, i) => {
                const level = levelByDistrict[d];
                const ur = districtNameUr(d);
                return (
                  <li
                    key={d}
                    id={optionId(i)}
                    role="option"
                    aria-selected={i === active}
                    // Keep focus in the text box, so the blur does not close the list first.
                    onMouseDown={(e) => e.preventDefault()}
                    onMouseMove={() => setActive(i)}
                    onClick={() => choose(d)}
                    className={`${levelScope(level)} flex cursor-pointer items-center gap-2.5 rounded-lg px-3 py-2 text-sm text-ink ${
                      i === active ? "bg-white/10" : ""
                    }`}
                  >
                    <span className={`dot h-2 w-2 shrink-0 ${level > 1 ? "" : "opacity-40"}`} aria-hidden="true" />
                    <span className="min-w-0 flex-1 truncate">{d}</span>
                    {ur && (
                      <span lang="ur" dir="rtl" className="urdu truncate text-muted" style={{ lineHeight: 1.4 }}>
                        {ur}
                      </span>
                    )}
                    {level !== undefined && <span className="num text-xs text-muted">L{level}</span>}
                  </li>
                );
              })
            )}
          </m.ul>
        )}
      </AnimatePresence>
      {/* Screen readers hear how many districts match as the user types. */}
      <p className="sr-only" aria-live="polite">
        {open ? t("hero.pickCount", { n: options.length }) : ""}
      </p>
    </div>
  );
}

/** The compact readout for the chosen district: level, names, last alert. */
function DistrictCard({ district, level, onClose }: { district: string; level: number | undefined; onClose: () => void }) {
  const { t, pick, lang } = useI18n();
  // Newest alert of any status (active, acknowledged or resolved).
  const last = useApi<AlertResponse | null>(() => api.alerts({ district, limit: 1 }).then((r) => r.alerts[0] ?? null), [district]);
  const ur = districtNameUr(district);

  return (
    <m.section
      aria-label={district}
      initial={{ opacity: 0, y: 10, scale: 0.98 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, y: 6, transition: { duration: 0.12 } }}
      transition={SPRING}
      className={`hero-card rail ${levelScope(level)} mt-3 p-4 ps-6 text-start`}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-lg font-semibold text-white" lang="en" dir="ltr">
            {district}
          </h2>
          {ur && (
            <p lang="ur" dir="rtl" className="urdu text-base text-ink" style={{ lineHeight: 1.6 }}>
              {ur}
            </p>
          )}
        </div>
        <button type="button" className="hero-pill-btn -me-1.5 -mt-1" aria-label={t("common.close")} onClick={onClose}>
          <X className="h-4 w-4" aria-hidden="true" />
        </button>
      </div>
      <div className="mt-2">{level !== undefined ? <LevelBadge level={level} size="sm" /> : <span className="text-sm text-muted">{t("common.noData")}</span>}</div>

      <p className="eyebrow mt-3">{t("hero.lastAlert")}</p>
      <div className="mt-1 min-h-10 text-sm">
        {last.error ? (
          <p className="text-muted">{t("common.noData")}</p>
        ) : last.loading ? (
          <p className="text-muted">{t("common.loading")}</p>
        ) : last.data === null ? (
          <p className="text-muted">{t("map.noAlerts")}</p>
        ) : (
          <>
            <p className="font-medium text-ink">{pick(last.data.title_en, last.data.title_ur)}</p>
            <p className="text-muted">
              <span className="num">L{last.data.level}</span> · {t(`status.${last.data.status}` as "status.active")} ·{" "}
              <span className="num">{formatDateTime(last.data.created_at, lang)}</span>
            </p>
          </>
        )}
      </div>

      <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
        <Link href={`/map?district=${encodeURIComponent(district)}`} className="btn-secondary">
          {t("hero.viewDistrict")}
          <ArrowUpRight className="h-4 w-4 rtl:-scale-x-100" aria-hidden="true" />
        </Link>
      </div>
      {/* Rule 12: every surface that shows an alert carries the disclaimer. */}
      <p className="mt-3 text-xs text-muted">{t("disclaimer")}</p>
    </m.section>
  );
}

/**
 * The hero's right-hand column: the dotted globe (or the SVG mini-map when
 * WebGL is unavailable), the glass district pill overlapping its lower edge,
 * and the chosen district's card. Under 360 px wide the globe is hidden and
 * only the pill remains (globals.css).
 */
export function HeroGlobePanel({ levelByDistrict }: { levelByDistrict: Record<string, number> | null }) {
  const { t } = useI18n();
  const [points, setPoints] = useState<GlobePoint[]>([]);
  const [noWebgl, setNoWebgl] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const levels = useMemo(() => levelByDistrict ?? {}, [levelByDistrict]);
  const districts = useMemo(() => Object.keys(levels).sort((a, b) => a.localeCompare(b)), [levels]);
  const focus = useMemo(() => points.find((p) => p.n === selected) ?? null, [points, selected]);

  useEffect(() => {
    // 5 KB of centroids built by scripts/build-globe-points.mjs.
    let cancelled = false;
    fetch("/geo/globe-points.json")
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((json: GlobePoint[]) => !cancelled && setPoints(json))
      // No points: the globe still turns, just without markers; the pill works regardless.
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="hero-globe mx-auto w-full max-w-[300px] sm:max-w-[380px] lg:max-w-[460px]">
      <p className="hero-hud-caption num mb-2 flex items-center justify-center gap-2 text-xs uppercase">
        <span className="live-dot" aria-hidden="true" />
        {t("hero.hudCaption", { n: districts.length || 107 })}
      </p>
      <div className="hero-globe-stage relative">
        {noWebgl ? (
          levelByDistrict ? (
            <div className="hero-card p-3">
              <MiniMap levelByDistrict={levelByDistrict} />
            </div>
          ) : (
            <div className="skeleton aspect-[1000/870] w-full" aria-hidden="true" />
          )
        ) : (
          <HeroGlobe
            points={points}
            levelByDistrict={levels}
            focus={focus}
            label={t("hero.globeLabel")}
            onUnavailable={() => setNoWebgl(true)}
          />
        )}
      </div>
      <div className={`relative z-10 mx-auto w-[92%] ${noWebgl ? "mt-3" : "hero-pill-overlap"}`}>
        <DistrictCombobox districts={districts} levelByDistrict={levels} selected={selected} onSelect={setSelected} />
      </div>
      <AnimatePresence mode="wait">
        {selected && <DistrictCard key={selected} district={selected} level={levels[selected]} onClose={() => setSelected(null)} />}
      </AnimatePresence>
    </div>
  );
}
