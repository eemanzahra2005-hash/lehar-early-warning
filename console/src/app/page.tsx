"use client";

import { CircleCheck, MapPin } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { LevelBadge, LevelIcon, useLevelLabel } from "@/components/Level";
import { useLevels } from "@/components/LevelsProvider";
import { EmptyState, ErrorNotice, Loading } from "@/components/Status";
import { Takeover, readLocalAcks } from "@/components/Takeover";
import { useI18n } from "@/i18n/LanguageProvider";
import { api } from "@/lib/api";
import { formatDateTime, humanType } from "@/lib/format";
import { byLevelDesc, isTakeoverLevel, levelToken } from "@/lib/levels";
import type { AlertHealthSummaryResponse } from "@/lib/types";
import { useApi } from "@/lib/useApi";

// Matches the backend's health-summary cache TTL (60 s): polling faster
// would only return the cached answer again.
const REFRESH_MS = 60_000;
const ALL_CLEAR_WINDOW_MS = 48 * 3600 * 1000;

function NationalBanner({ summary }: { summary: AlertHealthSummaryResponse }) {
  const { t, pick, lang } = useI18n();
  const { levels } = useLevels();
  const level = summary.highest_level;
  const token = levelToken(level);
  const label = useLevelLabel(level);
  const meta = levels[level];
  const firstAction = meta ? (lang === "ur" ? meta.actions_ur[0] : meta.actions_en[0]) : null;
  const urgent = level >= 4;

  return (
    <section
      aria-labelledby="banner-title"
      aria-live={urgent ? "assertive" : "polite"}
      className={`${token.className} level-outline rounded-2xl p-5 sm:p-6`}
    >
      <p className="text-sm font-semibold opacity-90">{t("board.nationalHighest")}</p>
      <div className="mt-2 flex items-center gap-4">
        <span className="text-6xl font-black leading-none sm:text-7xl" aria-hidden="true">
          {level}
        </span>
        <LevelIcon level={level} className="h-12 w-12 shrink-0" />
        <div>
          <h1 id="banner-title" className="text-2xl font-bold sm:text-3xl">
            {label}
          </h1>
          <p className="mt-1 text-base font-medium">
            {summary.alerting_districts === 0
              ? t("board.allCalm", { total: summary.total_districts })
              : t("board.alertingDistricts", { n: summary.alerting_districts, total: summary.total_districts })}
          </p>
        </div>
      </div>
      {firstAction && (
        <p className="mt-4 text-lg font-semibold">
          {t("board.whatToDo")}: {firstAction}
        </p>
      )}
      {!meta && <p className="mt-3 text-sm">{pick(summary.highest_level_name_en, summary.highest_level_name_ur)}</p>}
      <p className="mt-3 text-xs opacity-90">
        {t("common.updated", { time: formatDateTime(summary.generated_at, lang) })}
      </p>
    </section>
  );
}

function CountsStrip({ counts }: { counts: Record<string, number> }) {
  return (
    <ul className="grid grid-cols-5 gap-2" aria-label="Districts per level">
      {[5, 4, 3, 2, 1].map((level) => (
        <li key={level} className={`${levelToken(level).className} level-outline rounded-lg p-2 text-center`}>
          <div className="flex items-center justify-center gap-1 text-xs font-semibold">
            <LevelIcon level={level} className="h-3.5 w-3.5" />
            <span>{level}</span>
          </div>
          <div className="text-2xl font-bold">{counts[String(level)] ?? 0}</div>
        </li>
      ))}
    </ul>
  );
}

export default function AlertBoardPage() {
  const { t, pick, lang } = useI18n();
  const { levels, error: levelsError, reload: reloadLevels } = useLevels();
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

  const takeover = alerting.filter(
    (row) => row.alert_id !== null && isTakeoverLevel(row.level, levels[row.level]) && !acked.includes(row.alert_id),
  );

  const recentAllClear = allClear.data ?? [];

  return (
    <div className="space-y-8">
      {takeover.length > 0 && <Takeover alerts={takeover} onAcknowledge={(id) => setAcked((a) => [...a, id])} />}

      <div className="space-y-3">
        {summary.data ? (
          <>
            <NationalBanner summary={summary.data} />
            <CountsStrip counts={summary.data.counts_by_level} />
          </>
        ) : summary.error ? (
          <ErrorNotice error={summary.error} onRetry={summary.reload} />
        ) : (
          <Loading />
        )}
      </div>

      <section aria-labelledby="active-title" className="space-y-3">
        <h2 id="active-title" className="h2">
          {t("board.activeAlerts")}
        </h2>
        {active.error && !active.data ? (
          <ErrorNotice error={active.error} onRetry={active.reload} />
        ) : !active.data ? (
          <Loading />
        ) : alerting.length === 0 ? (
          <EmptyState>{t("board.noActive")}</EmptyState>
        ) : (
          <ul className="grid gap-3 sm:grid-cols-2">
            {alerting.map((row) => (
              <li key={`${row.district}-${row.alert_id}`} className={`card border-s-8 ${borderFor(row.level)}`}>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <h3 className="text-lg font-bold">{row.district}</h3>
                  <LevelBadge level={row.level} size="sm" />
                </div>
                <p className="mt-2 font-medium">{pick(row.title_en, row.title_ur)}</p>
                <p className="mt-1 text-sm text-slate-600">
                  {humanType(row.type)} · {formatDateTime(row.created_at, lang)}
                </p>
                <div className="mt-3 flex gap-2">
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
              </li>
            ))}
          </ul>
        )}
      </section>

      <section aria-labelledby="allclear-title" className="space-y-3">
        <h2 id="allclear-title" className="h2 flex items-center gap-2">
          <CircleCheck className="h-5 w-5 text-green-700" aria-hidden="true" />
          {t("board.allClear")}
        </h2>
        {allClear.error && !allClear.data ? (
          <ErrorNotice error={allClear.error} onRetry={allClear.reload} />
        ) : !allClear.data ? (
          <Loading />
        ) : recentAllClear.length === 0 ? (
          <EmptyState>{t("board.allClearNone")}</EmptyState>
        ) : (
          <ul className="space-y-2">
            {recentAllClear.map((alert) => (
              <li key={alert.id} className="card flex flex-wrap items-center gap-3 border-green-300 bg-green-50">
                <CircleCheck className="h-5 w-5 text-green-800" aria-hidden="true" />
                <div className="flex-1">
                  <p className="font-semibold text-green-950">
                    {alert.district_code}: {pick(alert.title_en, alert.title_ur)}
                  </p>
                  <p className="text-sm text-green-900">{formatDateTime(alert.created_at, lang)}</p>
                </div>
                <Link href={`/alerts/${alert.id}`} className="btn-secondary">
                  {t("board.details")}
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section aria-labelledby="legend-title" className="space-y-3">
        <h2 id="legend-title" className="h2">
          {t("board.levelsLegend")}
        </h2>
        {levelsError && Object.keys(levels).length === 0 ? (
          <ErrorNotice error={levelsError} onRetry={reloadLevels} />
        ) : (
          <ul className="space-y-2">
            {[1, 2, 3, 4, 5].map((level) => (
              <li key={level} className="flex flex-wrap items-center gap-3">
                <LevelBadge level={level} />
                <span className="text-sm text-slate-700">
                  {levels[level] ? pick(levels[level].summary_en, levels[level].summary_ur) : ""}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

// Tailwind needs literal class names, so the card accent is a lookup.
function borderFor(level: number): string {
  return (
    { 1: "border-s-slate-300", 2: "border-s-lvl-2", 3: "border-s-lvl-3", 4: "border-s-lvl-4", 5: "border-s-lvl-5" }[level] ??
    "border-s-lvl-ops"
  );
}
