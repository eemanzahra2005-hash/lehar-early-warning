"use client";

import { LogIn, LogOut } from "lucide-react";
import { useEffect, useState } from "react";
import { LevelBadge } from "@/components/Level";
import { ErrorNotice, Loading } from "@/components/Status";
import { useI18n } from "@/i18n/LanguageProvider";
import { ApiError, api, clearSession, getToken, getUsername, saveSession } from "@/lib/api";
import { formatDateTime, formatNumber, humanType } from "@/lib/format";
import { useApi } from "@/lib/useApi";

function Stat({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-slate-200 p-3">
      <p className="text-xs font-medium text-slate-600">{label}</p>
      <p className="text-2xl font-bold">{value}</p>
    </div>
  );
}

function KeyCounts({ data }: { data: Record<string, number> }) {
  const entries = Object.entries(data);
  if (entries.length === 0) return <p className="text-sm text-slate-600">—</p>;
  return (
    <ul className="space-y-1 text-sm">
      {entries.map(([key, n]) => (
        <li key={key} className="flex justify-between gap-4 border-b border-slate-100 py-0.5">
          <span>{humanType(key)}</span>
          <span className="font-mono">{n}</span>
        </li>
      ))}
    </ul>
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
    <form onSubmit={submit} className="card max-w-sm space-y-3">
      {expired && <p className="text-sm text-amber-900">{t("admin.sessionExpired")}</p>}
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
          <p role="alert" className="text-sm font-medium text-red-800">
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

  return (
    <div className="space-y-6">
      <section className="space-y-3" aria-labelledby="stats-title">
        <h2 id="stats-title" className="h2">
          {t("admin.alertStats")}
        </h2>
        {stats.error ? (
          <ErrorNotice error={stats.error} onRetry={stats.reload} />
        ) : !s ? (
          <Loading />
        ) : (
          <>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <Stat label={t("admin.total")} value={s.total_alerts} />
              <Stat label={t("status.active")} value={s.active_alerts} />
              <Stat label={t("status.acknowledged")} value={s.acknowledged_alerts} />
              <Stat label={t("status.resolved")} value={s.resolved_alerts} />
              <Stat label={t("admin.suppressed")} value={s.suppressed_total} />
              <Stat label={t("admin.subscriptions")} value={s.active_subscriptions} />
            </div>

            <div className="grid gap-4 md:grid-cols-2">
              <div className="card space-y-2">
                <h3 className="font-semibold">{t("admin.byLevel")}</h3>
                <ul className="space-y-1">
                  {Object.entries(s.by_level)
                    .sort(([a], [b]) => Number(b) - Number(a))
                    .map(([level, n]) => (
                      <li key={level} className="flex items-center justify-between gap-3">
                        <LevelBadge level={Number(level)} size="sm" />
                        <span className="font-mono">{n}</span>
                      </li>
                    ))}
                </ul>
                {Object.keys(s.by_level).length === 0 && <p className="text-sm text-slate-600">—</p>}
              </div>
              <div className="card space-y-2">
                <h3 className="font-semibold">{t("admin.byType")}</h3>
                <KeyCounts data={s.by_type} />
              </div>
              <div className="card space-y-2">
                <h3 className="font-semibold">{t("admin.deliveries")}</h3>
                {Object.keys(s.deliveries_by_channel).length === 0 ? (
                  <p className="text-sm text-slate-600">—</p>
                ) : (
                  Object.entries(s.deliveries_by_channel).map(([channel, counts]) => (
                    <div key={channel}>
                      <p className="text-sm font-semibold">{channel}</p>
                      <KeyCounts data={counts} />
                    </div>
                  ))
                )}
              </div>
              <div className="card space-y-2">
                <h3 className="font-semibold">{t("admin.latency")}</h3>
                {Object.keys(s.delivery_latency).length === 0 ? (
                  <p className="text-sm text-slate-600">—</p>
                ) : (
                  <ul className="space-y-1 text-sm">
                    {Object.entries(s.delivery_latency).map(([channel, l]) => (
                      <li key={channel}>
                        <strong>{channel}</strong>: median {formatNumber(l.median_ms, 0)} ms · p95 {l.p95_ms} ms (n={l.sample_size})
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </div>

            <div className="card space-y-1 text-sm">
              <h3 className="font-semibold">{t("admin.lastRun")}</h3>
              {s.last_run ? (
                <p>
                  {formatDateTime(s.last_run.started_at, lang)} · {s.last_run.trigger} · {s.last_run.districts_checked} districts · raised{" "}
                  {s.last_run.alerts_raised} · suppressed {s.last_run.alerts_suppressed} · resolved {s.last_run.alerts_resolved}
                  {s.last_run.duration_seconds !== null && <> · {formatNumber(s.last_run.duration_seconds, 1)} s</>}
                </p>
              ) : (
                <p className="text-slate-600">{t("admin.noRun")}</p>
              )}
              <p className="text-xs text-slate-600">
                suppressed_by_type_and_level scope: <code>{s.suppressed_breakdown_scope}</code>
              </p>
            </div>
          </>
        )}
      </section>

      <section className="grid gap-4 md:grid-cols-2">
        <div className="card space-y-2">
          <h2 className="h2">{t("admin.models")}</h2>
          {models.error ? (
            <ErrorNotice error={models.error} onRetry={models.reload} />
          ) : !models.data ? (
            <Loading />
          ) : (
            <div className="space-y-1 text-sm">
              <p>
                {t("admin.production")}: <code>{production?.version ?? models.data.latest ?? "—"}</code> ·{" "}
                {t("admin.versions", { n: models.data.versions.length })}
              </p>
              {production && (
                <ul className="font-mono text-xs">
                  {Object.entries(production.metrics)
                    .filter(([, v]) => typeof v === "number")
                    .slice(0, 6)
                    .map(([k, v]) => (
                      <li key={k}>
                        {k}: {formatNumber(v as number, 3)}
                      </li>
                    ))}
                </ul>
              )}
              <p className="text-xs font-medium text-slate-700">{t("common.synthetic")}</p>
            </div>
          )}
        </div>
        <div className="card space-y-2">
          <h2 className="h2">{t("admin.drift")}</h2>
          {drift.error ? (
            <ErrorNotice error={drift.error} onRetry={drift.reload} />
          ) : !drift.data ? (
            <Loading />
          ) : (
            <div className="space-y-1 text-sm">
              <p>
                status: <strong>{drift.data.status}</strong> · window {drift.data.window_used} / {drift.data.samples_available}
              </p>
              <p className="text-xs text-slate-600">
                PSI warn {drift.data.psi_warn} · alert {drift.data.psi_alert}
              </p>
              {drift.data.features.length > 0 && (
                <ul className="font-mono text-xs">
                  {[...drift.data.features]
                    .sort((a, b) => b.psi - a.psi)
                    .slice(0, 5)
                    .map((f) => (
                      <li key={f.name}>
                        {f.name}: {formatNumber(f.psi, 3)} ({f.band})
                      </li>
                    ))}
                </ul>
              )}
            </div>
          )}
        </div>
      </section>
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
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="h1">{t("admin.title")}</h1>
        {user && (
          <div className="flex items-center gap-3 text-sm">
            <span>{t("admin.loggedInAs", { user })}</span>
            <button type="button" className="btn-secondary" onClick={logout}>
              <LogOut className="h-4 w-4" aria-hidden="true" />
              {t("admin.logout")}
            </button>
          </div>
        )}
      </div>
      {user === undefined ? (
        <Loading />
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
