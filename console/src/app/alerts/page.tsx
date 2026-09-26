"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { LevelBadge } from "@/components/Level";
import { EmptyState, ErrorNotice, Loading } from "@/components/Status";
import { useI18n } from "@/i18n/LanguageProvider";
import { api } from "@/lib/api";
import { formatDateTime, humanType } from "@/lib/format";
import { ALERT_STATUSES, ALERT_TYPES, type AlertResponse } from "@/lib/types";
import { useApi } from "@/lib/useApi";
import { useIsAdmin } from "@/lib/useIsAdmin";

const PAGE_SIZE = 50;

interface Filters {
  district: string;
  level: string;
  type: string;
  status: string;
}

export default function AlertFeedPage() {
  const { t, pick, lang } = useI18n();
  const isAdmin = useIsAdmin();
  const meta = useApi(api.meta);
  const [filters, setFilters] = useState<Filters>({ district: "", level: "", type: "", status: "" });
  const [rows, setRows] = useState<AlertResponse[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [page, setPage] = useState(0);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- marks the start of the fetch this effect runs
    setLoading(true);
    api
      .alerts({
        district: filters.district,
        level: filters.level === "" ? "" : Number(filters.level),
        type: filters.type,
        status: filters.status,
        limit: PAGE_SIZE,
        offset: page * PAGE_SIZE,
      })
      .then((result) => {
        if (cancelled) return;
        setRows((prev) => (page === 0 ? result.alerts : [...prev, ...result.alerts]));
        setTotal(result.count);
        setError(null);
      })
      .catch((err) => !cancelled && setError(err))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [filters, page, attempt]);

  const update = (key: keyof Filters, value: string) => {
    setPage(0);
    setFilters((f) => ({ ...f, [key]: value }));
  };

  // OPS (level 0) notices are admin-only by design (ALERT_LEVELS.md); the
  // list API has no way to exclude them server-side, so hide them here and
  // say so rather than pretend they do not exist.
  const visible = isAdmin ? rows : rows.filter((a) => a.level !== 0 && a.type !== "OPS");
  const hiddenOps = rows.length - visible.length;
  const types = isAdmin ? ALERT_TYPES : ALERT_TYPES.filter((type) => type !== "OPS");
  const levelOptions = isAdmin ? [0, 1, 2, 3, 4, 5] : [1, 2, 3, 4, 5];

  return (
    <div className="space-y-4">
      <h1 className="h1">{t("feed.title")}</h1>

      <form className="grid grid-cols-2 gap-3 sm:grid-cols-4" onSubmit={(e) => e.preventDefault()}>
        <label>
          <span className="field-label">{t("common.district")}</span>
          <select className="field-input" value={filters.district} onChange={(e) => update("district", e.target.value)}>
            <option value="">{t("common.any")}</option>
            {isAdmin && <option value="SYSTEM">SYSTEM (OPS)</option>}
            {(meta.data?.districts ?? []).map((d) => (
              <option key={d} value={d}>
                {d}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span className="field-label">{t("common.levelWord")}</span>
          <select className="field-input" value={filters.level} onChange={(e) => update("level", e.target.value)}>
            <option value="">{t("common.any")}</option>
            {levelOptions.map((n) => (
              <option key={n} value={n}>
                {n === 0 ? "OPS (0)" : t("common.level", { n })}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span className="field-label">{t("common.type")}</span>
          <select className="field-input" value={filters.type} onChange={(e) => update("type", e.target.value)}>
            <option value="">{t("common.any")}</option>
            {types.map((type) => (
              <option key={type} value={type}>
                {humanType(type)}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span className="field-label">{t("common.status")}</span>
          <select className="field-input" value={filters.status} onChange={(e) => update("status", e.target.value)}>
            <option value="">{t("common.any")}</option>
            {ALERT_STATUSES.map((s) => (
              <option key={s} value={s}>
                {t(`status.${s}`)}
              </option>
            ))}
          </select>
        </label>
      </form>

      <div aria-live="polite" className="space-y-1 text-sm text-slate-700">
        {!loading && !error && <p>{t("feed.results", { n: total })}</p>}
        {hiddenOps > 0 && <p>{t("feed.opsHidden")}</p>}
      </div>

      {error !== null && <ErrorNotice error={error} onRetry={() => setAttempt((n) => n + 1)} />}

      {!error && !loading && visible.length === 0 ? (
        <EmptyState>{t("feed.empty")}</EmptyState>
      ) : (
        <ul className="space-y-2">
          {visible.map((alert) => (
            <li key={alert.id} className="card">
              <div className="flex flex-wrap items-center gap-2">
                <LevelBadge level={alert.level} size="sm" />
                <span className="font-semibold">{alert.district_code}</span>
                <span className="text-sm text-slate-600">
                  {humanType(alert.type)} · {t(`status.${alert.status}` as "status.active")} · {formatDateTime(alert.created_at, lang)}
                </span>
              </div>
              <Link href={`/alerts/${alert.id}`} className="mt-1 block font-medium text-blue-800 underline">
                {pick(alert.title_en, alert.title_ur)}
              </Link>
            </li>
          ))}
        </ul>
      )}

      {loading && <Loading />}
      {!loading && !error && rows.length < total && (
        <button type="button" className="btn-secondary" onClick={() => setPage((p) => p + 1)}>
          {t("feed.loadMore")}
        </button>
      )}
    </div>
  );
}
