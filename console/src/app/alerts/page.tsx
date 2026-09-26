"use client";

import { SlidersHorizontal } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { ChipGroup } from "@/components/Chips";
import { LevelBadge, LevelIcon, levelScope } from "@/components/Level";
import { Reveal, StaggerItem, StaggerList } from "@/components/Motion";
import { EmptyState, ErrorNotice, Skeleton } from "@/components/Status";
import { useI18n } from "@/i18n/LanguageProvider";
import { api } from "@/lib/api";
import { formatDateTime, formatDay, humanType } from "@/lib/format";
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

  // Timeline groups: one heading per local calendar day, newest first
  // (the API already returns newest first, so order is preserved).
  const days = useMemo(() => {
    const groups: { day: string; alerts: AlertResponse[] }[] = [];
    for (const alert of visible) {
      const day = formatDay(alert.created_at, lang);
      const last = groups[groups.length - 1];
      if (last && last.day === day) last.alerts.push(alert);
      else groups.push({ day, alerts: [alert] });
    }
    return groups;
  }, [visible, lang]);

  const levelChips = [
    { value: "", label: t("common.any") },
    ...levelOptions.map((n) => ({
      value: String(n),
      label: (
        <span className={`${levelScope(n)} inline-flex items-center gap-1.5`}>
          <span className="dot h-2 w-2" aria-hidden="true" />
          <LevelIcon level={n} className="h-3.5 w-3.5" />
          {n === 0 ? "OPS" : t("common.level", { n })}
        </span>
      ),
    })),
  ];
  const statusChips = [{ value: "", label: t("common.any") }, ...ALERT_STATUSES.map((s) => ({ value: s, label: t(`status.${s}`) }))];

  return (
    <div className="page space-y-6 py-8">
      <h1 className="h1">{t("feed.title")}</h1>

      <form className="card space-y-5" onSubmit={(e) => e.preventDefault()} aria-label={t("feed.filters")}>
        <p className="eyebrow flex items-center gap-2">
          <SlidersHorizontal className="h-4 w-4" aria-hidden="true" />
          {t("feed.filters")}
        </p>
        <div className="space-y-2">
          <p className="field-label">
            {t("common.levelWord")}
          </p>
          <ChipGroup id="level" label={t("common.levelWord")} options={levelChips} value={filters.level} onChange={(v) => update("level", v)} />
        </div>
        <div className="space-y-2">
          <p className="field-label">{t("common.status")}</p>
          <ChipGroup id="status" label={t("common.status")} options={statusChips} value={filters.status} onChange={(v) => update("status", v)} />
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
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
        </div>
      </form>

      <div aria-live="polite" className="space-y-1 text-sm text-muted">
        {!loading && !error && <p className="num">{t("feed.results", { n: total })}</p>}
        {hiddenOps > 0 && <p>{t("feed.opsHidden")}</p>}
      </div>

      {error !== null && <ErrorNotice error={error} onRetry={() => setAttempt((n) => n + 1)} />}

      {!error && !loading && visible.length === 0 ? (
        <EmptyState>{t("feed.empty")}</EmptyState>
      ) : (
        <div className="space-y-8">
          {days.map(({ day, alerts }) => (
            <Reveal as="section" key={day} aria-label={day}>
              <h2 className="num mb-3 text-sm font-semibold text-muted">{day}</h2>
              {/* The timeline rail runs down the reading start; each dot is the level's ink. */}
              <StaggerList as="ol" className="relative space-y-3 ps-7 before:absolute before:inset-y-2 before:start-[9px] before:w-px before:bg-gradient-to-b before:from-white/25 before:to-white/5">
                {alerts.map((alert) => (
                  <StaggerItem key={alert.id} className={`${levelScope(alert.level)} relative`}>
                    <span
                      className="dot absolute top-5 -start-[23px] h-3 w-3 ring-4 ring-[#0b1220]"
                      aria-hidden="true"
                    />
                    <Link href={`/alerts/${alert.id}`} className="glass lift block p-4">
                      <div className="flex flex-wrap items-center gap-2">
                        <LevelBadge level={alert.level} size="sm" />
                        <span className="font-semibold text-white">{alert.district_code}</span>
                        <span className="text-sm text-muted">
                          {humanType(alert.type)} · {t(`status.${alert.status}` as "status.active")} ·{" "}
                          <span className="num">{formatDateTime(alert.created_at, lang)}</span>
                        </span>
                      </div>
                      <p className="mt-1.5 font-medium text-ink">{pick(alert.title_en, alert.title_ur)}</p>
                    </Link>
                  </StaggerItem>
                ))}
              </StaggerList>
            </Reveal>
          ))}
        </div>
      )}

      {loading && <Skeleton className="h-20" lines={rows.length === 0 ? 4 : 1} />}
      {!loading && !error && rows.length < total && (
        <button type="button" className="btn-secondary" onClick={() => setPage((p) => p + 1)}>
          {t("feed.loadMore")}
        </button>
      )}
    </div>
  );
}
