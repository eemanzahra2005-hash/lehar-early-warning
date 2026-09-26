"use client";

import { LoaderCircle, RefreshCw, TriangleAlert } from "lucide-react";
import { useEffect, useState } from "react";
import { useI18n } from "@/i18n/LanguageProvider";
import { ApiError, onWakeStateChange } from "@/lib/api";

/** Global "server waking up" notice, shown while any request is retrying. */
export function WakeBanner() {
  const { t } = useI18n();
  const [waking, setWaking] = useState(false);
  useEffect(() => onWakeStateChange(setWaking), []);
  return (
    <div role="status" aria-live="polite">
      {waking && (
        <div className="border-b border-amber-300 bg-amber-50 px-4 py-2 text-sm text-amber-950">
          <div className="mx-auto flex max-w-5xl items-center gap-2">
            <LoaderCircle className="h-4 w-4 shrink-0 animate-spin" aria-hidden="true" />
            <p>
              <strong>{t("wake.title")}</strong> — {t("wake.body")}
            </p>
          </div>
        </div>
      )}
    </div>
  );
}

export function Loading() {
  const { t } = useI18n();
  return (
    <p className="flex items-center gap-2 py-6 text-slate-600" role="status">
      <LoaderCircle className="h-5 w-5 animate-spin" aria-hidden="true" />
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
    <div role="alert" className="flex flex-wrap items-center gap-3 rounded-lg border border-red-300 bg-red-50 p-3 text-sm text-red-950">
      <TriangleAlert className="h-5 w-5 shrink-0" aria-hidden="true" />
      <span className="flex-1">{errorMessage(error, t)}</span>
      {onRetry && (
        <button type="button" onClick={onRetry} className="btn-secondary">
          <RefreshCw className="h-4 w-4" aria-hidden="true" />
          {t("common.retry")}
        </button>
      )}
    </div>
  );
}

export function EmptyState({ children }: { children: React.ReactNode }) {
  return <p className="rounded-lg border border-dashed border-slate-300 p-4 text-slate-600">{children}</p>;
}
