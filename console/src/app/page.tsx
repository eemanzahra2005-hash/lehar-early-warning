"use client";

import { m } from "framer-motion";
import { ArrowUpRight, CircleCheck, MapPin } from "lucide-react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { LevelBackdrop, PulsingIcon } from "@/components/LevelBand";
import { LevelBadge, LevelIcon, levelScope, useLevelLabel } from "@/components/Level";
import { useLevels } from "@/components/LevelsProvider";
import { CountUp, EASE_OUT, StaggerItem, StaggerList } from "@/components/Motion";
import { EmptyState, ErrorNotice, Skeleton } from "@/components/Status";
import { Takeover, readLocalAcks } from "@/components/Takeover";
import { useI18n } from "@/i18n/LanguageProvider";
import { api } from "@/lib/api";
import { formatDateTime, humanType } from "@/lib/format";
import { byLevelDesc, isTakeoverLevel } from "@/lib/levels";
import type { AlertHealthSummaryResponse } from "@/lib/types";
import { useApi } from "@/lib/useApi";

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
// below does not jump when the national level arrives (layout shift).
const HERO_MIN_H = "min-h-[470px] sm:min-h-[480px] md:min-h-[400px] lg:min-h-[432px]";

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

  return (
    <section
      aria-labelledby="banner-title"
      aria-live={urgent ? "assertive" : "polite"}
      className={`band ${levelScope(level)} ${HERO_MIN_H} border-b border-white/10`}
    >
      <LevelBackdrop level={level} />
      <div className="page py-10 sm:py-14 lg:py-16">
        <p className="text-sm font-semibold uppercase tracking-[0.14em] rtl:tracking-normal">{t("board.nationalHighest")}</p>
        <div className="mt-4 flex flex-wrap items-end gap-x-8 gap-y-4">
          <div className="flex items-center gap-5">
            <m.span
              key={level}
              className="hero-numeral"
              aria-hidden="true"
              initial={{ opacity: 0, y: 16, scale: 0.96 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              transition={{ duration: 0.5, ease: EASE_OUT }}
            >
              {level}
            </m.span>
            <PulsingIcon level={level} className="h-12 w-12 sm:h-16 sm:w-16" ringClass="p-3 sm:p-4" />
          </div>
          <div className="min-w-0 pb-2">
            <h1 id="banner-title" className="text-3xl font-semibold sm:text-4xl lg:text-5xl">
              {label}
            </h1>
            {otherName && (
              <p lang={lang === "ur" ? "en" : "ur"} dir={lang === "ur" ? "ltr" : "rtl"} className={`mt-1 text-lg font-medium sm:text-xl ${lang === "ur" ? "" : "urdu"}`}>
                {otherName}
              </p>
            )}
          </div>
        </div>

        <p className="mt-6 max-w-3xl text-lg font-medium sm:text-xl">
          {level <= 1 && <CircleCheck className="me-2 inline h-6 w-6 -translate-y-0.5 text-emerald-300" aria-hidden="true" />}
          {summary.alerting_districts === 0
            ? t("board.allCalm", { total: summary.total_districts })
            : t("board.alertingDistricts", { n: summary.alerting_districts, total: summary.total_districts })}
        </p>
        {firstAction && (
          <p className="mt-2 max-w-3xl text-base font-semibold sm:text-lg">
            {t("board.whatToDo")}: {firstAction}
          </p>
        )}
        <p className="mt-6 flex flex-wrap items-center gap-x-2 text-sm font-medium">
          <span className="num">{t("common.updated", { time: formatDateTime(summary.generated_at, lang) })}</span>
          <span aria-hidden="true">·</span>
          <span className="inline-flex items-center gap-2">
            <span className="live-dot" aria-hidden="true" />
            {t("board.live")}
          </span>
        </p>
      </div>
    </section>
  );
}

function HeroSkeleton() {
  return (
    <div className={`${HERO_MIN_H} border-b border-white/10 bg-white/[0.02]`}>
      <div className="page space-y-4 py-12">
        <Skeleton className="h-4 w-56" />
        <div className="skeleton h-32 w-72 max-w-full" aria-hidden="true" />
        <div className="skeleton h-5 w-96 max-w-full" aria-hidden="true" />
      </div>
    </div>
  );
}

/** Five pills, L1..L5, each with an animated count and a bar of its share. */
function LevelStrip({ counts, total }: { counts: Record<string, number>; total: number }) {
  const { t, pick } = useI18n();
  const { levels } = useLevels();
  return (
    <section aria-labelledby="strip-title">
      <h2 id="strip-title" className="eyebrow mb-3">
        {t("board.levelStrip")}
      </h2>
      <StaggerList className="grid grid-cols-2 gap-3 sm:grid-cols-5">
        {[1, 2, 3, 4, 5].map((level) => {
          const n = counts[String(level)] ?? 0;
          const share = total > 0 ? n / total : 0;
          const meta = levels[level];
          return (
            <StaggerItem key={level} className={`glass lift ${levelScope(level)} relative overflow-hidden p-4 ${level === 5 ? "col-span-2 sm:col-span-1" : ""}`}>
              <div className="flex items-center gap-2 text-sm font-semibold" style={{ color: "var(--lvl-ink)" }}>
                <LevelIcon level={level} className="h-4 w-4" />
                <span className="num">L{level}</span>
                <span className="truncate font-medium text-ink">{meta ? pick(meta.name_en, meta.name_ur) : t("common.level", { n: level })}</span>
              </div>
              <CountUp value={n} className="num mt-2 block text-3xl font-semibold text-white" />
              <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-white/10" aria-hidden="true">
                <m.div
                  className="h-full rounded-full"
                  style={{ background: "var(--lvl-ink)", boxShadow: "0 0 12px var(--lvl-glow)", transformOrigin: "var(--origin, left)" }}
                  initial={{ scaleX: 0 }}
                  animate={{ scaleX: share === 0 ? 0 : Math.max(share, 0.04) }}
                  transition={{ duration: 0.9, ease: EASE_OUT, delay: 0.1 }}
                />
              </div>
            </StaggerItem>
          );
        })}
      </StaggerList>
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
          <LevelStrip counts={summary.data.counts_by_level} total={summary.data.total_districts} />
        ) : (
          !summary.error && (
            <div className="grid grid-cols-2 gap-3 pt-7 sm:grid-cols-5" aria-hidden="true">
              {[1, 2, 3, 4, 5].map((n) => (
                <div key={n} className={`skeleton h-[116px] ${n === 5 ? "col-span-2 sm:col-span-1" : ""}`} />
              ))}
            </div>
          )
        )}

        <div className="grid gap-6 lg:grid-cols-[5fr_7fr]">
          <section aria-labelledby="minimap-title" className="card flex flex-col gap-4">
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
              <MiniMap levelByDistrict={levelByDistrict} />
            )}
            <p className="text-xs text-muted">{t("board.mapCaption")}</p>
          </section>

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

        <section aria-labelledby="allclear-title" className="space-y-4">
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
        </section>

        <section aria-labelledby="legend-title" className="space-y-6">
          <h2 id="legend-title" className="h2">
            {t("board.levelsLegend")}
          </h2>
          <LevelStepper />
        </section>
      </div>
    </div>
  );
}
