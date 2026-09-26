"use client";

import { AnimatePresence, m } from "framer-motion";
import { ArrowUpRight, CircleCheck, MapPin } from "lucide-react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import { HeroWaves, LevelBackdrop, PulsingIcon } from "@/components/LevelBand";
import { LevelBadge, LevelIcon, levelScope, useLevelLabel } from "@/components/Level";
import { useLevels } from "@/components/LevelsProvider";
import { CountUp, EASE_OUT, FadeIn, Reveal, SPRING, StaggerItem, StaggerList, usePrefersReducedMotion } from "@/components/Motion";
import { EmptyState, ErrorNotice, Skeleton } from "@/components/Status";
import { Takeover, readLocalAcks } from "@/components/Takeover";
import { useI18n } from "@/i18n/LanguageProvider";
import { api } from "@/lib/api";
import { formatDateTime, humanType } from "@/lib/format";
import { byLevelDesc, isTakeoverLevel } from "@/lib/levels";
import type { AlertHealthSummaryResponse } from "@/lib/types";
import { useApi } from "@/lib/useApi";
import { useMediaQuery } from "@/lib/useMediaQuery";

// The mini-map sits below the fold on phones: keep it out of the first bundle.
const MiniMap = dynamic(() => import("@/components/MiniMap").then((mod) => mod.MiniMap), {
  ssr: false,
  loading: () => <div className="skeleton aspect-[1000/870] w-full" aria-hidden="true" />,
});

// Matches the backend's health-summary cache TTL (60 s): polling faster
// would only return the cached answer again.
const REFRESH_MS = 60_000;
const ALL_CLEAR_WINDOW_MS = 48 * 3600 * 1000;
// The hero and its loading skeleton share a minimum height, so the page
// below does not jump when the national level arrives (layout shift). The
// extra bottom padding is room for the wave edge.
const HERO_MIN_H = "min-h-[486px] sm:min-h-[496px] md:min-h-[416px] lg:min-h-[448px]";

// Load choreography: the numeral springs in first, then the text lines fade
// up one after another, 60 ms apart. Only on first appearance; a poll that
// returns the same data changes nothing.
const heroLines = {
  hidden: {},
  show: { transition: { delayChildren: 0.15, staggerChildren: 0.06 } },
};
const heroLine = {
  hidden: { opacity: 0, y: 12 },
  show: { opacity: 1, y: 0, transition: { duration: 0.45, ease: EASE_OUT } },
};

/**
 * The digits of the big numeral: a blurred copy that slowly "breathes" under
 * the solid digits. When `countUp` is set (first load only) both count from
 * 0 up to the level, written straight into the DOM so it costs no renders.
 */
function NumeralDigits({ value, countUp }: { value: number; countUp: boolean }) {
  const glow = useRef<HTMLSpanElement>(null);
  const solid = useRef<HTMLSpanElement>(null);
  const reduce = usePrefersReducedMotion();

  useEffect(() => {
    if (!countUp || reduce || value <= 0) return;
    const write = (n: number) => {
      if (glow.current) glow.current.textContent = String(n);
      if (solid.current) solid.current.textContent = String(n);
    };
    // 700 ms ease-out, stepping through whole numbers only (0, 1, 2, 3 ...).
    const began = performance.now();
    let frame = requestAnimationFrame(function tick(now) {
      const t = Math.min(1, (now - began) / 700);
      write(Math.round(value * (1 - (1 - t) ** 3)));
      if (t < 1) frame = requestAnimationFrame(tick);
    });
    return () => {
      cancelAnimationFrame(frame);
      write(value);
    };
  }, [countUp, reduce, value]);

  return (
    <span className="hero-digit">
      <span ref={glow} className="hero-digit-glow">
        {value}
      </span>
      <span ref={solid} className="hero-digit-solid">
        {value}
      </span>
    </span>
  );
}

/**
 * The big level numeral. First appearance: springs in from 80 % and counts
 * up. Later level changes (a poll or refresh): the old digit rolls up and
 * out while the new one rolls in from below.
 */
function HeroNumeral({ level }: { level: number }) {
  // "Has the level changed since this hero appeared?", tracked with the
  // render-time state update React recommends over an effect.
  const [shown, setShown] = useState(level);
  const [changed, setChanged] = useState(false);
  if (shown !== level) {
    setShown(level);
    setChanged(true);
  }

  return (
    <m.span
      className="hero-numeral hero-roll"
      aria-hidden="true"
      initial={{ opacity: 0, scale: 0.8 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={{ type: "spring", stiffness: 260, damping: 18 }}
    >
      <AnimatePresence initial={false}>
        <m.span
          key={level}
          initial={{ y: "70%", opacity: 0 }}
          animate={{ y: 0, opacity: 1 }}
          exit={{ y: "-70%", opacity: 0 }}
          transition={{ duration: 0.45, ease: EASE_OUT }}
        >
          <NumeralDigits value={level} countUp={!changed} />
        </m.span>
      </AnimatePresence>
    </m.span>
  );
}

function Hero({ summary }: { summary: AlertHealthSummaryResponse }) {
  const { t, lang } = useI18n();
  const { levels } = useLevels();
  const level = summary.highest_level;
  const label = useLevelLabel(level);
  const meta = levels[level];
  const firstAction = meta ? (lang === "ur" ? meta.actions_ur[0] : meta.actions_en[0]) : null;
  // The level name in the OTHER language too, so a mixed household reads it.
  const otherName = lang === "ur" ? summary.highest_level_name_en : summary.highest_level_name_ur;
  const urgent = level >= 4;

  // Screen readers hear a level CHANGE, once, not every poll's new
  // "updated" time. Empty on first load: the heading is read in page order.
  const [announcedFor, setAnnouncedFor] = useState(level);
  const [announcement, setAnnouncement] = useState("");
  if (announcedFor !== level) {
    setAnnouncedFor(level);
    setAnnouncement(t("board.levelChanged", { level: label }));
  }

  return (
    <section aria-labelledby="banner-title" className={`band ${levelScope(level)} ${HERO_MIN_H}`}>
      <LevelBackdrop level={level} hero />
      <p className="sr-only" aria-live={urgent ? "assertive" : "polite"} aria-atomic="true">
        {announcement}
      </p>
      <m.div
        className="page pb-14 pt-10 sm:pb-[4.5rem] sm:pt-14 lg:pb-20 lg:pt-16"
        variants={heroLines}
        initial="hidden"
        animate="show"
      >
        <p className="text-sm font-semibold uppercase tracking-[0.14em] rtl:tracking-normal">{t("board.nationalHighest")}</p>
        <div className="mt-4 flex flex-wrap items-end gap-x-8 gap-y-4">
          <div className="flex items-center gap-5">
            <HeroNumeral level={level} />
            <PulsingIcon level={level} radar className="h-12 w-12 sm:h-16 sm:w-16" ringClass="p-3 sm:p-4" />
          </div>
          <div className="min-w-0 pb-2">
            <m.h1 id="banner-title" variants={heroLine} className="text-3xl font-semibold sm:text-4xl lg:text-5xl">
              {label}
            </m.h1>
            {otherName && (
              <m.p
                variants={heroLine}
                lang={lang === "ur" ? "en" : "ur"}
                dir={lang === "ur" ? "ltr" : "rtl"}
                className={`mt-1 text-lg font-medium sm:text-xl ${lang === "ur" ? "" : "urdu"}`}
              >
                {otherName}
              </m.p>
            )}
          </div>
        </div>

        <m.p variants={heroLine} className="mt-6 max-w-3xl text-lg font-medium sm:text-xl">
          {level <= 1 && <CircleCheck className="me-2 inline h-6 w-6 -translate-y-0.5 text-emerald-300" aria-hidden="true" />}
          {summary.alerting_districts === 0
            ? t("board.allCalm", { total: summary.total_districts })
            : t("board.alertingDistricts", { n: summary.alerting_districts, total: summary.total_districts })}
        </m.p>
        {firstAction && (
          <m.p variants={heroLine} className="mt-2 max-w-3xl text-base font-semibold sm:text-lg">
            {t("board.whatToDo")}: {firstAction}
          </m.p>
        )}
        <m.p variants={heroLine} className="hero-live mt-6 flex flex-wrap items-center gap-x-2 text-sm font-medium">
          <span className="num">{t("common.updated", { time: formatDateTime(summary.generated_at, lang) })}</span>
          <span aria-hidden="true">·</span>
          <span className="inline-flex items-center gap-2">
            <span className="live-dot" aria-hidden="true" />
            {t("board.live")}
          </span>
        </m.p>
      </m.div>
      <HeroWaves />
    </section>
  );
}

function HeroSkeleton() {
  return (
    <div className={`${HERO_MIN_H} bg-white/[0.02]`}>
      <div className="page space-y-4 py-12">
        <Skeleton className="h-4 w-56" />
        <div className="skeleton h-32 w-72 max-w-full" aria-hidden="true" />
        <div className="skeleton h-5 w-96 max-w-full" aria-hidden="true" />
      </div>
    </div>
  );
}

// How many district names the level popover lists before "+N more".
const POPOVER_NAMES = 5;

/** The names in a level card's popover: the first five, then "+N more". */
function DistrictNames({ level, names }: { level: number; names: string[] | null }) {
  const { t } = useI18n();
  return (
    <>
      <p className="eyebrow mb-2">{t("board.levelDistricts", { n: level })}</p>
      {names === null ? (
        <p className="text-sm text-muted">{t("common.loading")}</p>
      ) : names.length === 0 ? (
        <p className="text-sm text-muted">{t("board.noDistricts")}</p>
      ) : (
        <ul className="space-y-1 text-sm text-ink">
          {names.slice(0, POPOVER_NAMES).map((name) => (
            <li key={name} className="flex items-center gap-2">
              <span className="dot h-1.5 w-1.5 shrink-0" aria-hidden="true" />
              {name}
            </li>
          ))}
          {names.length > POPOVER_NAMES && (
            <li className="num pt-0.5 text-muted">{t("board.moreDistricts", { n: names.length - POPOVER_NAMES })}</li>
          )}
        </ul>
      )}
    </>
  );
}

/**
 * Five level cards, L1..L5, each with an animated count and a bar of its
 * share. A card "pops" (scale + lift + a ring in its level colour) and shows
 * the districts at that level:
 *   - mouse: while hovered;  keyboard: while focused;  touch: tap toggles.
 * Tablets and desktops show the names in a popover above the card. Phones
 * scroll the cards sideways (a popover would be clipped by that row), so
 * the names open in a panel just below it instead.
 */
function LevelStrip({
  counts,
  total,
  namesByLevel,
}: {
  counts: Record<string, number>;
  total: number;
  namesByLevel: Record<number, string[]> | null;
}) {
  const { t, pick } = useI18n();
  const { levels } = useLevels();
  const [open, setOpen] = useState<number | null>(null);
  const lastPointer = useRef("mouse");
  const wide = useMediaQuery("(min-width: 768px)");
  const namesFor = (level: number) => (namesByLevel ? (namesByLevel[level] ?? []) : null);
  const closeIf = (level: number) => setOpen((current) => (current === level ? null : current));

  return (
    <section aria-labelledby="strip-title" onKeyDown={(e) => e.key === "Escape" && setOpen(null)}>
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h2 id="strip-title" className="eyebrow">
          {t("board.levelStrip")}
        </h2>
        <p className="text-xs text-muted">{t("board.stripHint")}</p>
      </div>
      {/* Phones: a swipeable snap row where the next card peeks in at the
          edge. Tablets: a 3 + 2 grid. Desktop: one row of five. */}
      <StaggerList className="snap-row -mx-4 flex snap-x snap-mandatory scroll-px-4 gap-3 overflow-x-auto px-4 py-3 sm:-mx-6 sm:scroll-px-6 sm:px-6 md:mx-0 md:grid md:grid-cols-6 md:overflow-visible md:px-0 md:py-0 lg:grid-cols-5">
        {[1, 2, 3, 4, 5].map((level) => {
          const n = counts[String(level)] ?? 0;
          const share = total > 0 ? n / total : 0;
          const meta = levels[level];
          const isOpen = open === level;
          return (
            <StaggerItem
              key={level}
              className={`${levelScope(level)} relative w-[64%] max-w-60 shrink-0 snap-start md:w-auto md:max-w-none ${
                level <= 3 ? "md:col-span-2" : "md:col-span-3"
              } lg:col-span-1 ${isOpen ? "z-20" : ""}`}
              onPointerEnter={(e) => e.pointerType === "mouse" && setOpen(level)}
              onPointerLeave={(e) => e.pointerType === "mouse" && closeIf(level)}
            >
              <m.button
                type="button"
                aria-expanded={isOpen}
                aria-controls={isOpen ? `strip-names-${level}` : undefined}
                onPointerDown={(e) => (lastPointer.current = e.pointerType)}
                // Keyboard focus opens it; a tap's focus does not (the click toggles instead).
                onFocus={(e) => e.currentTarget.matches(":focus-visible") && setOpen(level)}
                onBlur={() => closeIf(level)}
                onClick={(e) => {
                  // A mouse click on an already-hovered card changes nothing.
                  if (lastPointer.current === "mouse" && e.detail > 0) return;
                  setOpen(isOpen ? null : level);
                }}
                animate={isOpen ? { scale: 1.03, y: -4 } : { scale: 1, y: 0 }}
                transition={{ duration: 0.2, ease: EASE_OUT }}
                className="glass pop-card relative block w-full overflow-hidden p-4 text-start"
              >
                <span className="flex items-center gap-2 text-sm font-semibold" style={{ color: "var(--lvl-ink)" }}>
                  <LevelIcon level={level} className="h-4 w-4 shrink-0" />
                  <span className="num">L{level}</span>
                  <span className="truncate font-medium text-ink">{meta ? pick(meta.name_en, meta.name_ur) : t("common.level", { n: level })}</span>
                </span>
                <CountUp value={n} className="num mt-2 block text-3xl font-semibold text-white" />
                <span className="pop-bar mt-3 block h-1.5 rounded-full bg-white/10" aria-hidden="true">
                  <m.span
                    className="block h-full rounded-full"
                    style={{ background: "var(--lvl-ink)", boxShadow: "0 0 12px var(--lvl-glow)", transformOrigin: "var(--origin, left)" }}
                    initial={{ scaleX: 0 }}
                    animate={{ scaleX: share === 0 ? 0 : Math.max(share, 0.04) }}
                    transition={{ duration: 0.9, ease: EASE_OUT, delay: 0.1 }}
                  />
                </span>
              </m.button>

              <AnimatePresence>
                {isOpen && wide && (
                  <m.div
                    id={`strip-names-${level}`}
                    initial={{ opacity: 0, y: 8, scale: 0.94 }}
                    animate={{ opacity: 1, y: 0, scale: 1 }}
                    exit={{ opacity: 0, y: 6, scale: 0.96, transition: { duration: 0.12 } }}
                    transition={SPRING}
                    style={{ transformOrigin: "bottom center" }}
                    className="glass absolute bottom-[calc(100%+12px)] left-1/2 z-30 w-60 -translate-x-1/2 bg-[#0e1524]/95 p-4 shadow-[0_18px_40px_-12px_var(--lvl-glow)]"
                  >
                    <DistrictNames level={level} names={namesFor(level)} />
                    {/* The little arrow pointing down at the card. */}
                    <span
                      aria-hidden="true"
                      className="absolute -bottom-[7px] left-1/2 h-3 w-3 -translate-x-1/2 rotate-45 border-e border-b border-line bg-[#0e1524]"
                    />
                  </m.div>
                )}
              </AnimatePresence>
            </StaggerItem>
          );
        })}
      </StaggerList>

      <AnimatePresence mode="wait" initial={false}>
        {open !== null && !wide && (
          <m.div
            key={open}
            id={`strip-names-${open}`}
            initial={{ opacity: 0, y: -8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8, transition: { duration: 0.12 } }}
            transition={SPRING}
            className={`glass rail ${levelScope(open)} mt-1 p-4 ps-6`}
          >
            <DistrictNames level={open} names={namesFor(open)} />
          </m.div>
        )}
      </AnimatePresence>
    </section>
  );
}

/** "What the levels mean" as a stepper: horizontal on desktop, vertical on phones. */
function LevelStepper() {
  const { t, pick } = useI18n();
  const { levels, error, reload } = useLevels();
  if (error && Object.keys(levels).length === 0) return <ErrorNotice error={error} onRetry={reload} />;
  return (
    <ol className="relative grid gap-6 md:grid-cols-5 md:gap-4">
      {/* The connecting rail: a gradient through the five level inks. */}
      <span
        aria-hidden="true"
        className="absolute inset-y-4 start-[22px] w-px bg-gradient-to-b from-white/60 via-[#ff6b6b]/70 to-[#c39bf5]/70 md:inset-x-8 md:inset-y-auto md:top-[22px] md:h-px md:w-auto md:bg-gradient-to-r rtl:md:bg-gradient-to-l"
      />
      {[1, 2, 3, 4, 5].map((level) => {
        const meta = levels[level];
        return (
          <li key={level} className={`${levelScope(level)} relative flex gap-4 md:flex-col md:gap-3`}>
            <span
              className={`lvl-${level} level-outline relative z-10 grid h-11 w-11 shrink-0 place-items-center rounded-full`}
              style={{ boxShadow: "0 0 0 4px #0b1220, 0 0 18px var(--lvl-glow)" }}
            >
              <LevelIcon level={level} className="h-5 w-5" />
            </span>
            <div className="min-w-0">
              <p className="font-display font-semibold text-white">
                <span className="num" style={{ color: "var(--lvl-ink)" }}>
                  {level}
                </span>{" "}
                · {meta ? pick(meta.name_en, meta.name_ur) : t("common.level", { n: level })}
              </p>
              <p className="mt-1 text-sm text-muted">{meta ? pick(meta.summary_en, meta.summary_ur) : ""}</p>
            </div>
          </li>
        );
      })}
    </ol>
  );
}

export default function AlertBoardPage() {
  const { t, pick, lang } = useI18n();
  const { levels } = useLevels();
  const summary = useApi(api.healthSummary, [], REFRESH_MS);
  const active = useApi(api.active, [], REFRESH_MS);
  // The 48 h window is applied when the data arrives, not during render.
  const allClear = useApi(
    () =>
      api
        .alerts({ type: "ALL_CLEAR", limit: 10 })
        .then((r) => r.alerts.filter((a) => Date.now() - new Date(a.created_at).getTime() < ALL_CLEAR_WINDOW_MS)),
    [],
    REFRESH_MS,
  );
  const [acked, setAcked] = useState<number[]>([]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- localStorage is only readable after hydration
    setAcked(readLocalAcks());
  }, []);

  const alerting = useMemo(
    () => (active.data?.districts ?? []).filter((row) => row.source === "alert").sort(byLevelDesc),
    [active.data],
  );
  const levelByDistrict = useMemo(() => {
    const out: Record<string, number> = {};
    for (const row of active.data?.districts ?? []) out[row.district] = row.level;
    return out;
  }, [active.data]);

  // District names per level, for the level cards' popovers (null until loaded).
  const namesByLevel = useMemo(() => {
    if (!active.data) return null;
    const out: Record<number, string[]> = {};
    for (const row of active.data.districts) (out[row.level] ??= []).push(row.district);
    for (const list of Object.values(out)) list.sort((a, b) => a.localeCompare(b));
    return out;
  }, [active.data]);

  const takeover = alerting.filter(
    (row) => row.alert_id !== null && isTakeoverLevel(row.level, levels[row.level]) && !acked.includes(row.alert_id),
  );

  const recentAllClear = allClear.data ?? [];

  return (
    <div>
      {takeover.length > 0 && <Takeover alerts={takeover} onAcknowledge={(id) => setAcked((a) => [...a, id])} />}

      {summary.data ? (
        <Hero summary={summary.data} />
      ) : summary.error ? (
        <div className="page pt-8">
          <ErrorNotice error={summary.error} onRetry={summary.reload} />
        </div>
      ) : (
        <HeroSkeleton />
      )}

      <div className="page space-y-14 py-10">
        {summary.data ? (
          <LevelStrip counts={summary.data.counts_by_level} total={summary.data.total_districts} namesByLevel={namesByLevel} />
        ) : (
          !summary.error && (
            // Same shape as the strip (snap row / 3 + 2 / five), so nothing jumps.
            <div className="-mx-4 flex gap-3 overflow-hidden px-4 pt-11 pb-3 sm:-mx-6 sm:px-6 md:mx-0 md:grid md:grid-cols-6 md:px-0 md:pb-0 lg:grid-cols-5" aria-hidden="true">
              {[1, 2, 3, 4, 5].map((n) => (
                <div key={n} className={`skeleton h-[116px] w-[64%] max-w-60 shrink-0 md:w-auto md:max-w-none ${n <= 3 ? "md:col-span-2" : "md:col-span-3"} lg:col-span-1`} />
              ))}
            </div>
          )
        )}

        <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-[5fr_7fr]">
          <Reveal as="section" aria-labelledby="minimap-title" className="card flex h-fit flex-col gap-4">
            <div className="flex items-center justify-between gap-3">
              <h2 id="minimap-title" className="h2">
                {t("map.title")}
              </h2>
              <Link href="/map" className="btn-secondary">
                {t("board.openMap")}
                <ArrowUpRight className="h-4 w-4 rtl:-scale-x-100" aria-hidden="true" />
              </Link>
            </div>
            {active.error && !active.data ? (
              <ErrorNotice error={active.error} onRetry={active.reload} />
            ) : !active.data ? (
              <Skeleton className="aspect-[1000/870] w-full" />
            ) : (
              <FadeIn>
                <MiniMap levelByDistrict={levelByDistrict} />
              </FadeIn>
            )}
            <p className="text-xs text-muted">{t("board.mapCaption")}</p>
          </Reveal>

          <section aria-labelledby="active-title" className="space-y-4">
            <h2 id="active-title" className="h2">
              {t("board.activeAlerts")}
            </h2>
            {active.error && !active.data ? (
              <ErrorNotice error={active.error} onRetry={active.reload} />
            ) : !active.data ? (
              <Skeleton className="h-28" lines={3} />
            ) : alerting.length === 0 ? (
              <EmptyState>{t("board.noActive")}</EmptyState>
            ) : (
              <StaggerList className="grid gap-3">
                {alerting.map((row) => (
                  <StaggerItem key={`${row.district}-${row.alert_id}`} className={`glass lift rail ${levelScope(row.level)} p-4 ps-6`}>
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <h3 className="text-lg font-semibold text-white">{row.district}</h3>
                      <LevelBadge level={row.level} size="sm" />
                    </div>
                    <p className="mt-2 font-medium text-ink">{pick(row.title_en, row.title_ur)}</p>
                    <p className="mt-1 text-sm text-muted">
                      {humanType(row.type)} · <span className="num">{formatDateTime(row.created_at, lang)}</span>
                    </p>
                    <div className="mt-3 flex flex-wrap gap-2">
                      {row.alert_id !== null && (
                        <Link href={`/alerts/${row.alert_id}`} className="btn-secondary">
                          {t("board.details")}
                        </Link>
                      )}
                      <Link href={`/map?district=${encodeURIComponent(row.district)}`} className="btn-secondary">
                        <MapPin className="h-4 w-4" aria-hidden="true" />
                        {t("board.viewMap")}
                      </Link>
                    </div>
                  </StaggerItem>
                ))}
              </StaggerList>
            )}
          </section>
        </div>

        <Reveal as="section" aria-labelledby="allclear-title" className="space-y-4">
          <h2 id="allclear-title" className="h2 flex items-center gap-2">
            <CircleCheck className="h-5 w-5 text-ok" aria-hidden="true" />
            {t("board.allClear")}
          </h2>
          {allClear.error && !allClear.data ? (
            <ErrorNotice error={allClear.error} onRetry={allClear.reload} />
          ) : !allClear.data ? (
            <Skeleton className="h-16" />
          ) : recentAllClear.length === 0 ? (
            <EmptyState>{t("board.allClearNone")}</EmptyState>
          ) : (
            <StaggerList className="grid gap-3 md:grid-cols-2">
              {recentAllClear.map((alert) => (
                <StaggerItem
                  key={alert.id}
                  className="glass lift flex flex-wrap items-center gap-3 border-emerald-300/20 bg-emerald-400/[0.06] p-4"
                >
                  <span className="grid h-9 w-9 place-items-center rounded-full bg-emerald-400/15 shadow-[0_0_16px_rgb(74_222_128/0.35)]">
                    <CircleCheck className="h-5 w-5 text-ok" aria-hidden="true" />
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="font-semibold text-white">
                      {alert.district_code}: {pick(alert.title_en, alert.title_ur)}
                    </p>
                    <p className="num text-sm text-muted">{formatDateTime(alert.created_at, lang)}</p>
                  </div>
                  <Link href={`/alerts/${alert.id}`} className="btn-secondary">
                    {t("board.details")}
                  </Link>
                </StaggerItem>
              ))}
            </StaggerList>
          )}
        </Reveal>

        <Reveal as="section" aria-labelledby="legend-title" className="space-y-6">
          <h2 id="legend-title" className="h2">
            {t("board.levelsLegend")}
          </h2>
          <LevelStepper />
        </Reveal>
      </div>
    </div>
  );
}
