"use client";

import { X } from "lucide-react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useI18n } from "@/i18n/LanguageProvider";
import { ApiError, api } from "@/lib/api";
import { OBSERVED_DAYS, forecastPoints, observedPointsFromDetail } from "@/lib/flood";
import { formatDateTime, humanType } from "@/lib/format";
import type { FloodDistrictDetail, FloodForecastResponse } from "@/lib/types";
import { useApi } from "@/lib/useApi";
import { LevelBadge, levelScope } from "./Level";
import { useLevels } from "./LevelsProvider";
import { StaggerItem, StaggerList } from "./Motion";
import { EmptyState, ErrorNotice, Notice, Skeleton } from "./Status";

// recharts is the heaviest dependency; load it only once a district is opened.
const FloodChart = dynamic(() => import("./FloodChart").then((m) => m.FloodChart), {
  ssr: false,
  loading: () => <div className="skeleton h-60 w-full" aria-hidden="true" />,
});

type FloodResult =
  | { kind: "forecast"; forecast: FloodForecastResponse }
  | { kind: "observed"; reason: string; detail: FloodDistrictDetail | null; detailError: unknown };

/**
 * Try the DL lead-time forecast first. A 503 there is an honest "no
 * forecast" (disabled / no model / district not in the training set), not
 * an outage, so fall back to Flood Watch's observed discharge and say why.
 */
async function loadFlood(district: string): Promise<FloodResult> {
  try {
    return { kind: "forecast", forecast: await api.floodForecast(district) };
  } catch (error) {
    if (!(error instanceof ApiError) || error.status !== 503) throw error;
    try {
      return { kind: "observed", reason: error.detail, detail: await api.floodDistrict(district), detailError: null };
    } catch (detailError) {
      return { kind: "observed", reason: error.detail, detail: null, detailError };
    }
  }
}

export function DistrictPanel({ district, level, onClose }: { district: string; level: number; onClose?: () => void }) {
  const { t, pick, lang } = useI18n();
  const { levels } = useLevels();
  const flood = useApi(() => loadFlood(district), [district]);
  const latest = useApi(() => api.alerts({ district, limit: 5 }), [district]);
  const meta = levels[level];
  const actions = meta ? (lang === "ur" ? meta.actions_ur : meta.actions_en) : [];
  const today = new Date().toISOString().slice(0, 10);
  const chartLabels = {
    observedLabel: `${t("map.observed")} (${OBSERVED_DAYS}d)`,
    forecastPeriodLabel: t("map.forecastPeriod"),
    baselineLabel: t("map.baseline"),
    unit: t("map.unit"),
  };

  return (
    <div className="space-y-6">
      <div className={`${levelScope(level)} rail -mx-5 -mt-5 flex items-start justify-between gap-3 border-b border-line bg-white/[0.03] px-5 pb-4 pt-5 ps-7`}>
        <div className="min-w-0 space-y-2">
          <h2 className="font-display text-2xl font-semibold text-white">{district}</h2>
          <LevelBadge level={level} />
        </div>
        {onClose && (
          <button type="button" onClick={onClose} className="btn-secondary h-11 w-11 shrink-0 !p-0" aria-label={t("common.close")}>
            <X className="h-5 w-5" aria-hidden="true" />
          </button>
        )}
      </div>

      {actions.length > 0 && (
        <section>
          <h3 className="eyebrow mb-2">{t("map.actions")}</h3>
          <ul className="space-y-2 text-sm text-ink">
            {actions.map((a) => (
              <li key={a} className={`${levelScope(level)} flex gap-2.5`}>
                <span className="dot mt-2 shrink-0" aria-hidden="true" />
                <span>{a}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="space-y-3">
        <h3 className="eyebrow">
          {t("map.discharge")} ({t("map.unit")})
        </h3>
        {flood.loading && !flood.data ? (
          <Skeleton className="h-60" />
        ) : flood.error ? (
          <ErrorNotice error={flood.error} onRetry={flood.reload} />
        ) : flood.data?.kind === "forecast" ? (
          <>
            <FloodChart
              points={forecastPoints(flood.data.forecast)}
              forecastLabel={`${t("map.forecast")} D+1..D+3`}
              baseline={flood.data.forecast.observed.baseline_median}
              {...chartLabels}
            />
            <p className="text-xs text-muted">{t("map.forecastNote", { version: flood.data.forecast.model_version })}</p>
            <p className="text-xs text-muted">{flood.data.forecast.attribution}</p>
          </>
        ) : flood.data?.kind === "observed" ? (
          <>
            <Notice>
              {t("map.forecastUnavailable", { detail: flood.data.reason })} {t("map.observedOnly")}
            </Notice>
            {flood.data.detailError ? (
              <ErrorNotice error={flood.data.detailError} onRetry={flood.reload} />
            ) : flood.data.detail && observedPointsFromDetail(flood.data.detail, today).length > 0 ? (
              <FloodChart
                points={observedPointsFromDetail(flood.data.detail, today)}
                forecastLabel={t("map.forecast")}
                baseline={flood.data.detail.discharge?.baseline_median}
                {...chartLabels}
              />
            ) : (
              <EmptyState>{t("map.noDischarge")}</EmptyState>
            )}
          </>
        ) : null}
      </section>

      <section className="space-y-3">
        <h3 className="eyebrow">{t("map.latestAlerts")}</h3>
        {latest.error ? (
          <ErrorNotice error={latest.error} onRetry={latest.reload} />
        ) : !latest.data ? (
          <Skeleton className="h-14" lines={2} />
        ) : latest.data.alerts.length === 0 ? (
          <EmptyState illustration={false}>{t("map.noAlerts")}</EmptyState>
        ) : (
          <StaggerList className="space-y-2">
            {latest.data.alerts.map((alert) => (
              <StaggerItem key={alert.id} className={`${levelScope(alert.level)} lift rail rounded-xl border border-line bg-white/[0.03] p-3 ps-5`}>
                <div className="flex flex-wrap items-center gap-2">
                  <LevelBadge level={alert.level} size="sm" />
                  <span className="text-xs text-muted">
                    {humanType(alert.type)} · {t(`status.${alert.status}` as "status.active")} ·{" "}
                    <span className="num">{formatDateTime(alert.created_at, lang)}</span>
                  </span>
                </div>
                <Link href={`/alerts/${alert.id}`} className="link mt-1.5 block text-sm font-medium">
                  {pick(alert.title_en, alert.title_ur)}
                </Link>
              </StaggerItem>
            ))}
          </StaggerList>
        )}
      </section>
    </div>
  );
}
