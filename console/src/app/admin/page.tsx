"use client";

import { m } from "framer-motion";
import { Activity, BellRing, CheckCheck, CircleCheck, Database, FlaskConical, Gauge, LogIn, LogOut, ShieldOff, Users } from "lucide-react";
import { useEffect, useState } from "react";
import { LevelBadge, levelScope } from "@/components/Level";
import { CountUp, EASE_OUT, StaggerItem, StaggerList } from "@/components/Motion";
import { ErrorNotice, Skeleton } from "@/components/Status";
import { useI18n } from "@/i18n/LanguageProvider";
import { ApiError, api, clearSession, getToken, getUsername, saveSession } from "@/lib/api";
import { formatDateTime, formatNumber, humanType } from "@/lib/format";
import type { DriftResponse } from "@/lib/types";
import { useApi } from "@/lib/useApi";

function Kpi({ label, value, icon: Icon, tone = "#5eead4" }: { label: string; value: number; icon: typeof Activity; tone?: string }) {
  return (
    <StaggerItem as="div" className="glass lift relative overflow-hidden p-4">
      <span
        aria-hidden="true"
        className="absolute -end-6 -top-6 h-20 w-20 rounded-full opacity-25 blur-2xl"
        style={{ background: tone }}
      />
      <p className="flex items-center gap-2 text-xs font-medium text-muted">
        <Icon className="h-4 w-4" style={{ color: tone }} aria-hidden="true" />
        {label}
      </p>
      <CountUp value={value} className="num mt-2 block text-3xl font-semibold text-white" />
    </StaggerItem>
  );
}

/** A labelled horizontal bar: the number is always printed next to it. */
function BarRow({ label, value, max, color = "#5eead4", glow = "rgb(94 234 212 / 0.5)" }: { label: React.ReactNode; value: number; max: number; color?: string; glow?: string }) {
  return (
    <li className="space-y-1">
      <div className="flex items-center justify-between gap-3 text-sm">
        <span className="min-w-0 text-ink">{label}</span>
        <span className="num text-white">{value}</span>
      </div>
      <div className="h-1.5 rounded-full bg-white/[0.06]" aria-hidden="true">
        <m.div
          className="h-full rounded-full"
          style={{ width: `${max > 0 ? Math.max((value / max) * 100, value > 0 ? 2 : 0) : 0}%`, background: color, boxShadow: `0 0 10px ${glow}`, transformOrigin: "var(--origin, left)" }}
          initial={{ scaleX: 0 }}
          animate={{ scaleX: 1 }}
          transition={{ duration: 0.8, ease: EASE_OUT }}
        />
      </div>
    </li>
  );
}

function KeyCounts({ data }: { data: Record<string, number> }) {
  const entries = Object.entries(data);
  if (entries.length === 0) return <p className="text-sm text-muted">—</p>;
  const max = Math.max(...entries.map(([, n]) => n));
  return (
    <ul className="space-y-3">
      {entries.map(([key, n]) => (
        <BarRow key={key} label={humanType(key)} value={n} max={max} />
      ))}
    </ul>
  );
}

function Panel({ title, children, className = "" }: { title: string; children: React.ReactNode; className?: string }) {
  return (
    <StaggerItem as="div" className={`card space-y-4 ${className}`}>
      <h3 className="eyebrow">{title}</h3>
      {children}
    </StaggerItem>
  );
}

function LoginForm({ onLoggedIn, expired }: { onLoggedIn: () => void; expired: boolean }) {
  const { t } = useI18n();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    try {
      saveSession(await api.login({ username, password }));
      setError(null);
      onLoggedIn();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} className="card max-w-sm space-y-4">
      {expired && <p className="text-sm text-amber-100">{t("admin.sessionExpired")}</p>}
      <label className="block">
        <span className="field-label">{t("admin.username")}</span>
        <input className="field-input" autoComplete="username" required value={username} onChange={(e) => setUsername(e.target.value)} dir="ltr" />
      </label>
      <label className="block">
        <span className="field-label">{t("admin.password")}</span>
        <input
          className="field-input"
          type="password"
          autoComplete="current-password"
          required
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          dir="ltr"
        />
      </label>
      <button type="submit" className="btn-primary w-full" disabled={busy}>
        <LogIn className="h-4 w-4" aria-hidden="true" />
        {t("admin.login")}
      </button>
      {error !== null &&
        (error instanceof ApiError && error.status === 401 ? (
          <p role="alert" className="text-sm font-medium text-danger">
            {t("admin.badLogin")}
          </p>
        ) : (
          <ErrorNotice error={error} />
        ))}
    </form>
  );
}

function Dashboard({ onSessionLost }: { onSessionLost: () => void }) {
  const { t, lang } = useI18n();
  const stats = useApi(api.stats);
  const models = useApi(api.models);
  const drift = useApi(api.drift);

  useEffect(() => {
    if (stats.error instanceof ApiError && stats.error.status === 401) onSessionLost();
  }, [stats.error, onSessionLost]);

  const s = stats.data;
  const production = models.data?.versions.find((v) => v.is_production);
  const byLevel = s ? Object.entries(s.by_level).sort(([a], [b]) => Number(b) - Number(a)) : [];
  const levelMax = Math.max(0, ...byLevel.map(([, n]) => n));
  // Share of all alerts by status, as one stacked bar (numbers in the legend).
  const statusParts = s
    ? [
        { key: "status.active" as const, n: s.active_alerts, color: "#ff6b6b" },
        { key: "status.acknowledged" as const, n: s.acknowledged_alerts, color: "#fbbf24" },
        { key: "status.resolved" as const, n: s.resolved_alerts, color: "#4ade80" },
      ]
    : [];
  const statusTotal = statusParts.reduce((sum, p) => sum + p.n, 0);

  return (
    <div className="space-y-8">
      <section className="space-y-4" aria-labelledby="stats-title">
        <h2 id="stats-title" className="h2">
          {t("admin.alertStats")}
        </h2>
        {stats.error ? (
          <ErrorNotice error={stats.error} onRetry={stats.reload} />
        ) : !s ? (
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
            {Array.from({ length: 6 }, (_, i) => (
              <div key={i} className="skeleton h-24" aria-hidden="true" />
            ))}
          </div>
        ) : (
          <>
            <StaggerList as="div" className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
              <Kpi label={t("admin.total")} value={s.total_alerts} icon={Database} tone="#818cf8" />
              <Kpi label={t("status.active")} value={s.active_alerts} icon={BellRing} tone="#ff6b6b" />
              <Kpi label={t("status.acknowledged")} value={s.acknowledged_alerts} icon={CheckCheck} tone="#fbbf24" />
              <Kpi label={t("status.resolved")} value={s.resolved_alerts} icon={CircleCheck} tone="#4ade80" />
              <Kpi label={t("admin.suppressed")} value={s.suppressed_total} icon={ShieldOff} tone="#94a0b2" />
              <Kpi label={t("admin.subscriptions")} value={s.active_subscriptions} icon={Users} tone="#5eead4" />
            </StaggerList>

            {statusTotal > 0 && (
              <div className="glass space-y-3 p-4">
                <div className="flex h-2.5 overflow-hidden rounded-full bg-white/[0.06]" aria-hidden="true">
                  {statusParts.map((p) => (
                    <m.div
                      key={p.key}
                      style={{ background: p.color, boxShadow: `0 0 10px ${p.color}` }}
                      initial={{ width: 0 }}
                      animate={{ width: `${(p.n / statusTotal) * 100}%` }}
                      transition={{ duration: 0.9, ease: EASE_OUT }}
                    />
                  ))}
                </div>
                <ul className="flex flex-wrap gap-x-5 gap-y-1 text-sm text-muted">
                  {statusParts.map((p) => (
                    <li key={p.key} className="flex items-center gap-2">
                      <span className="h-2 w-2 rounded-full" style={{ background: p.color }} aria-hidden="true" />
                      {t(p.key)} <span className="num text-white">{p.n}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            <StaggerList as="div" className="grid gap-4 md:grid-cols-2">
              <Panel title={t("admin.byLevel")}>
                {byLevel.length === 0 ? (
                  <p className="text-sm text-muted">—</p>
                ) : (
                  <ul className="space-y-3">
                    {byLevel.map(([level, n]) => (
                      <BarRow
                        key={level}
                        label={<LevelBadge level={Number(level)} size="sm" />}
                        value={n}
                        max={levelMax}
                        color={`var(--lvl-${Number(level) === 0 ? "ops" : level}-ink)`}
                        glow={`var(--lvl-${Number(level) === 0 ? "ops" : level}-glow)`}
                      />
                    ))}
                  </ul>
                )}
              </Panel>
              <Panel title={t("admin.byType")}>
                <KeyCounts data={s.by_type} />
              </Panel>
              <Panel title={t("admin.deliveries")}>
                {Object.keys(s.deliveries_by_channel).length === 0 ? (
                  <p className="text-sm text-muted">—</p>
                ) : (
                  Object.entries(s.deliveries_by_channel).map(([channel, counts]) => (
                    <div key={channel} className="space-y-2">
                      <p className="text-sm font-semibold text-white">{channel}</p>
                      <KeyCounts data={counts} />
                    </div>
                  ))
                )}
              </Panel>
              <Panel title={t("admin.latency")}>
                {Object.keys(s.delivery_latency).length === 0 ? (
                  <p className="text-sm text-muted">—</p>
                ) : (
                  <ul className="grid gap-3 sm:grid-cols-2">
                    {Object.entries(s.delivery_latency).map(([channel, l]) => (
                      <li key={channel} className="rounded-xl border border-line bg-white/[0.03] p-3 text-sm">
                        <p className="flex items-center gap-2 font-semibold text-white">
                          <Gauge className="h-4 w-4 text-accent" aria-hidden="true" />
                          {channel}
                        </p>
                        <p className="num mt-1 text-muted">
                          median <span className="text-white">{formatNumber(l.median_ms, 0)} ms</span> · p95{" "}
                          <span className="text-white">{l.p95_ms} ms</span> · n={l.sample_size}
                        </p>
                      </li>
                    ))}
                  </ul>
                )}
              </Panel>
            </StaggerList>

            <div className="card space-y-2 text-sm">
              <h3 className="eyebrow flex items-center gap-2">
                <Activity className="h-4 w-4" aria-hidden="true" />
                {t("admin.lastRun")}
              </h3>
              {s.last_run ? (
                <p className="text-ink">
                  <span className="num">{formatDateTime(s.last_run.started_at, lang)}</span> · {s.last_run.trigger} ·{" "}
                  <span className="num">{s.last_run.districts_checked}</span> districts · raised <span className="num">{s.last_run.alerts_raised}</span> ·
                  suppressed <span className="num">{s.last_run.alerts_suppressed}</span> · resolved <span className="num">{s.last_run.alerts_resolved}</span>
                  {s.last_run.duration_seconds !== null && (
                    <>
                      {" "}
                      · <span className="num">{formatNumber(s.last_run.duration_seconds, 1)} s</span>
                    </>
                  )}
                </p>
              ) : (
                <p className="text-muted">{t("admin.noRun")}</p>
              )}
              <p className="text-xs text-muted">
                suppressed_by_type_and_level scope: <code className="num">{s.suppressed_breakdown_scope}</code>
              </p>
            </div>
          </>
        )}
      </section>

      <section className="grid gap-4 md:grid-cols-2">
        <div className="card space-y-3">
          <h2 className="h2">{t("admin.models")}</h2>
          {models.error ? (
            <ErrorNotice error={models.error} onRetry={models.reload} />
          ) : !models.data ? (
            <Skeleton className="h-6" lines={4} />
          ) : (
            <div className="space-y-3 text-sm">
              <p className="text-ink">
                {t("admin.production")}: <code className="num text-accent">{production?.version ?? models.data.latest ?? "—"}</code> ·{" "}
                {t("admin.versions", { n: models.data.versions.length })}
              </p>
              {production && (
                <dl className="grid grid-cols-2 gap-2">
                  {Object.entries(production.metrics)
                    .filter(([, v]) => typeof v === "number")
                    .slice(0, 6)
                    .map(([k, v]) => (
                      <div key={k} className="rounded-xl border border-line bg-white/[0.03] p-2.5">
                        <dt className="num truncate text-xs text-muted">{k}</dt>
                        <dd className="num text-base text-white">{formatNumber(v as number, 3)}</dd>
                      </div>
                    ))}
                </dl>
              )}
              <p className="flex items-center gap-2 text-xs font-medium text-amber-100">
                <FlaskConical className="h-3.5 w-3.5" aria-hidden="true" />
                {t("common.synthetic")}
              </p>
            </div>
          )}
        </div>
        <div className="card space-y-3">
          <h2 className="h2">{t("admin.drift")}</h2>
          {drift.error ? (
            <ErrorNotice error={drift.error} onRetry={drift.reload} />
          ) : !drift.data ? (
            <Skeleton className="h-6" lines={4} />
          ) : (
            <DriftPanel drift={drift.data} />
          )}
        </div>
      </section>
    </div>
  );
}

/** PSI per feature as bars, with the warn/alert thresholds drawn as ticks. */
function DriftPanel({ drift }: { drift: DriftResponse }) {
  const features = [...drift.features].sort((a, b) => b.psi - a.psi).slice(0, 5);
  // Scale so the alert threshold always sits inside the track.
  const scale = Math.max(drift.psi_alert * 1.25, ...features.map((f) => f.psi), 0.0001);
  // Bands from backend/app/services/drift.py, drawn with the matching level ink.
  const bandLevel = (band: string) => (band === "significant_drift" ? 3 : band === "warning" ? 2 : 1);
  return (
    <div className="space-y-4 text-sm">
      <p className="text-ink">
        status: <strong className="text-white">{drift.status}</strong> · window <span className="num">{drift.window_used}</span> /{" "}
        <span className="num">{drift.samples_available}</span>
      </p>
      <p className="num text-xs text-muted">
        PSI warn {drift.psi_warn} · alert {drift.psi_alert}
      </p>
      {features.length > 0 && (
        <ul className="space-y-3" dir="ltr">
          {features.map((f) => (
            <li key={f.name} className={`${levelScope(bandLevel(f.band))} space-y-1`}>
              <div className="flex justify-between gap-3">
                <span className="num truncate text-ink">{f.name}</span>
                <span className="num shrink-0 text-white">
                  {formatNumber(f.psi, 3)} <span className="text-muted">({f.band})</span>
                </span>
              </div>
              <div className="relative h-1.5 rounded-full bg-white/[0.06]" aria-hidden="true">
                <m.div
                  className="h-full origin-left rounded-full"
                  style={{ width: `${(f.psi / scale) * 100}%`, background: "var(--lvl-ink)", boxShadow: "0 0 10px var(--lvl-glow)" }}
                  initial={{ scaleX: 0 }}
                  animate={{ scaleX: 1 }}
                  transition={{ duration: 0.8, ease: EASE_OUT }}
                />
                <span className="absolute -top-1 h-3.5 w-px bg-warn" style={{ left: `${(drift.psi_warn / scale) * 100}%` }} />
                <span className="absolute -top-1 h-3.5 w-px bg-danger" style={{ left: `${(drift.psi_alert / scale) * 100}%` }} />
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default function AdminPage() {
  const { t } = useI18n();
  // undefined = not yet read from localStorage (avoids a login-form flash); null = logged out.
  const [user, setUser] = useState<string | null | undefined>(undefined);
  const [expired, setExpired] = useState(false);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- localStorage is only readable after hydration
    setUser(getToken() ? (getUsername() ?? "admin") : null);
  }, []);

  const logout = () => {
    clearSession();
    setUser(null);
  };

  return (
    <div className="page space-y-6 py-8">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="h1">{t("admin.title")}</h1>
        {user && (
          <div className="flex items-center gap-3 text-sm text-muted">
            <span>{t("admin.loggedInAs", { user })}</span>
            <button type="button" className="btn-secondary" onClick={logout}>
              <LogOut className="h-4 w-4" aria-hidden="true" />
              {t("admin.logout")}
            </button>
          </div>
        )}
      </div>
      {user === undefined ? (
        <Skeleton className="h-40 max-w-sm" />
      ) : user === null ? (
        <LoginForm
          expired={expired}
          onLoggedIn={() => {
            setExpired(false);
            setUser(getUsername() ?? "admin");
          }}
        />
      ) : (
        <Dashboard
          onSessionLost={() => {
            clearSession();
            setExpired(true);
            setUser(null);
          }}
        />
      )}
    </div>
  );
}
