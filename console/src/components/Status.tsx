"use client";

import { AnimatePresence, m } from "framer-motion";
import { LoaderCircle, RefreshCw, TriangleAlert } from "lucide-react";
import { useEffect, useState } from "react";
import { useI18n } from "@/i18n/LanguageProvider";
import { ApiError, onWakeStateChange } from "@/lib/api";

/** Global "server waking up" notice, shown while any request is retrying. It slides down in, and away, like a toast. */
export function WakeBanner() {
  const { t } = useI18n();
  const [waking, setWaking] = useState(false);
  useEffect(() => onWakeStateChange(setWaking), []);
  return (
    <div role="status" aria-live="polite">
      <AnimatePresence initial={false}>
      {waking && (
        <m.div
          key="wake"
          initial={{ opacity: 0, y: -12 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -12 }}
          transition={{ type: "spring", stiffness: 380, damping: 32 }}
          className="border-b border-amber-300/20 bg-amber-400/10 text-sm text-amber-100 backdrop-blur"
        >
          <div className="page flex items-center gap-2.5 py-2.5">
            <LoaderCircle className="h-4 w-4 shrink-0 animate-spin text-warn" aria-hidden="true" />
            <p>
              <strong className="text-white">{t("wake.title")}</strong> — {t("wake.body")}
            </p>
          </div>
        </m.div>
      )}
      </AnimatePresence>
    </div>
  );
}

/** Shimmering placeholder blocks while data loads; screen readers hear "Loading…". */
export function Skeleton({ className = "h-24", lines = 1 }: { className?: string; lines?: number }) {
  const { t } = useI18n();
  return (
    <div role="status" className="space-y-3">
      <span className="sr-only">{t("common.loading")}</span>
      {Array.from({ length: lines }, (_, i) => (
        <div key={i} className={`skeleton ${className}`} aria-hidden="true" />
      ))}
    </div>
  );
}

/** Compact inline loading row (for small panels and buttons). */
export function Loading() {
  const { t } = useI18n();
  return (
    <p className="flex items-center gap-2 py-6 text-muted" role="status">
      <LoaderCircle className="h-5 w-5 animate-spin text-accent" aria-hidden="true" />
      {t("common.loading")}
    </p>
  );
}

export function errorMessage(error: unknown, t: ReturnType<typeof useI18n>["t"]): string {
  if (error instanceof ApiError) {
    if (error.kind === "wake_timeout") return t("error.wakeTimeout");
    if (error.kind === "network") return t("error.network");
    return t("error.generic", { detail: error.detail });
  }
  return t("error.generic", { detail: error instanceof Error ? error.message : String(error) });
}

/** Honest error state: says what failed and offers a retry, never fake data. */
export function ErrorNotice({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const { t } = useI18n();
  return (
    <div
      role="alert"
      className="flex flex-wrap items-center gap-3 rounded-2xl border border-red-400/30 bg-red-500/10 p-4 text-sm text-red-100"
    >
      <TriangleAlert className="h-5 w-5 shrink-0 text-danger" aria-hidden="true" />
      <span className="min-w-0 flex-1 break-words">{errorMessage(error, t)}</span>
      {onRetry && (
        <button type="button" onClick={onRetry} className="btn-secondary">
          <RefreshCw className="h-4 w-4" aria-hidden="true" />
          {t("common.retry")}
        </button>
      )}
    </div>
  );
}

/** A small line drawing of calm water: used by empty states, purely decorative. */
function CalmWaves({ className = "h-12 w-20" }: { className?: string }) {
  return (
    <svg viewBox="0 0 80 48" className={className} aria-hidden="true" fill="none">
      <circle cx="58" cy="14" r="7" stroke="#5EEAD4" strokeOpacity="0.6" strokeWidth="1.5" />
      <path d="M4 28c6 0 6-5 12-5s6 5 12 5 6-5 12-5 6 5 12 5 6-5 12-5 6 5 12 5" stroke="#5EEAD4" strokeWidth="2" strokeLinecap="round" />
      <path d="M12 38c5 0 5-4 10-4s5 4 10 4 5-4 10-4 5 4 10 4 5-4 10-4" stroke="#38BDF8" strokeOpacity="0.5" strokeWidth="2" strokeLinecap="round" />
    </svg>
  );
}

export function EmptyState({ children, illustration = true }: { children: React.ReactNode; illustration?: boolean }) {
  return (
    <div className="flex items-center gap-4 rounded-2xl border border-dashed border-white/15 bg-white/[0.02] p-5 text-muted">
      {illustration && <CalmWaves className="h-12 w-20 shrink-0" />}
      <p className="min-w-0">{children}</p>
    </div>
  );
}

/** Neutral information box (e.g. "channel not configured on this server"). */
export function Notice({ children, tone = "info" }: { children: React.ReactNode; tone?: "info" | "warn" | "ok" }) {
  const tones = {
    info: "border-white/10 bg-white/5 text-ink",
    warn: "border-amber-300/25 bg-amber-400/10 text-amber-100",
    ok: "border-emerald-300/25 bg-emerald-400/10 text-emerald-100",
  };
  return <div className={`rounded-2xl border p-4 text-sm ${tones[tone]}`}>{children}</div>;
}
