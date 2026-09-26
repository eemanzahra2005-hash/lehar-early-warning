"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import { useI18n } from "@/i18n/LanguageProvider";
import { ApiError, api } from "@/lib/api";
import { OBSERVED_DAYS, forecastPoints, observedPointsFromDetail } from "@/lib/flood";
import { formatDateTime, humanType } from "@/lib/format";
import type { FloodDistrictDetail, FloodForecastResponse } from "@/lib/types";
import { useApi } from "@/lib/useApi";
import { LevelBadge } from "./Level";
import { useLevels } from "./LevelsProvider";
import { EmptyState, ErrorNotice, Loading } from "./Status";

// recharts is the heaviest dependency; load it only once a district is opened.
const FloodChart = dynamic(() => import("./FloodChart").then((m) => m.FloodChart), {
  ssr: false,
  loading: () => <div className="h-56 w-full animate-pulse rounded bg-slate-100" />,
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

export function DistrictPanel({ district, level }: { district: string; level: number }) {
  const { t, pick, lang } = useI18n();
  const { levels } = useLevels();
  const flood = useApi(() => loadFlood(district), [district]);
  const latest = useApi(() => api.alerts({ district, limit: 5 }), [district]);
  const meta = levels[level];
  const actions = meta ? (lang === "ur" ? meta.actions_ur : meta.actions_en) : [];
  const today = new Date().toISOString().slice(0, 10);

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-xl font-bold">{district}</h2>
        <LevelBadge level={level} />
      </div>

      {actions.length > 0 && (
        <section>
          <h3 className="mb-1 font-semibold">{t("map.actions")}</h3>
          <ul className="list-disc space-y-1 ps-5 text-sm">
            {actions.map((a) => (
              <li key={a}>{a}</li>
            ))}
          </ul>
        </section>
      )}

      <section className="space-y-2">
        <h3 className="font-semibold">
          {t("map.discharge")} ({t("map.unit")})
        </h3>
        {flood.loading && !flood.data ? (
          <Loading />
        ) : flood.error ? (
          <ErrorNotice error={flood.error} onRetry={flood.reload} />
        ) : flood.data?.kind === "forecast" ? (
          <>
            <FloodChart
              points={forecastPoints(flood.data.forecast)}
              observedLabel={`${t("map.observed")} (${OBSERVED_DAYS}d)`}
              forecastLabel={`${t("map.forecast")} D+1..D+3`}
              baseline={flood.data.forecast.observed.baseline_median}
              unit={t("map.unit")}
            />
            <p className="text-xs text-slate-600">{t("map.forecastNote", { version: flood.data.forecast.model_version })}</p>
            <p className="text-xs text-slate-600">{flood.data.forecast.attribution}</p>
          </>
        ) : flood.data?.kind === "observed" ? (
          <>
            <p className="rounded-md bg-slate-100 p-2 text-sm text-slate-800">
              {t("map.forecastUnavailable", { detail: flood.data.reason })} {t("map.observedOnly")}
            </p>
            {flood.data.detailError ? (
              <ErrorNotice error={flood.data.detailError} onRetry={flood.reload} />
            ) : flood.data.detail && observedPointsFromDetail(flood.data.detail, today).length > 0 ? (
              <FloodChart
                points={observedPointsFromDetail(flood.data.detail, today)}
                observedLabel={`${t("map.observed")} (${OBSERVED_DAYS}d)`}
                forecastLabel={t("map.forecast")}
                baseline={flood.data.detail.discharge?.baseline_median}
                unit={t("map.unit")}
              />
            ) : (
              <EmptyState>{t("map.noDischarge")}</EmptyState>
            )}
          </>
        ) : null}
      </section>

      <section className="space-y-2">
        <h3 className="font-semibold">{t("map.latestAlerts")}</h3>
        {latest.error ? (
          <ErrorNotice error={latest.error} onRetry={latest.reload} />
        ) : !latest.data ? (
          <Loading />
        ) : latest.data.alerts.length === 0 ? (
          <EmptyState>{t("map.noAlerts")}</EmptyState>
        ) : (
          <ul className="space-y-2">
            {latest.data.alerts.map((alert) => (
              <li key={alert.id} className="rounded-lg border border-slate-200 p-2">
                <div className="flex flex-wrap items-center gap-2">
                  <LevelBadge level={alert.level} size="sm" />
                  <span className="text-xs text-slate-600">
                    {humanType(alert.type)} · {t(`status.${alert.status}` as "status.active")} · {formatDateTime(alert.created_at, lang)}
                  </span>
                </div>
                <Link href={`/alerts/${alert.id}`} className="mt-1 block text-sm font-medium text-blue-800 underline">
                  {pick(alert.title_en, alert.title_ur)}
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
