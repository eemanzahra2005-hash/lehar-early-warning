"use client";

import { FlaskConical } from "lucide-react";
import { ShapBars } from "@/components/ShapBars";
import { EmptyState, ErrorNotice, Skeleton } from "@/components/Status";
import { useI18n } from "@/i18n/LanguageProvider";
import { api } from "@/lib/api";
import { useApi } from "@/lib/useApi";

export default function ExplainPage() {
  const { t } = useI18n();
  const global = useApi(api.explainGlobal);
  const data = global.data;
  const rows = Object.entries(data?.mean_abs_shap_mm ?? {})
    .map(([feature, value]) => ({ feature, value }))
    .sort((a, b) => b.value - a.value);

  return (
    <div className="page space-y-6 py-8">
      <div className="space-y-3">
        <h1 className="h1">{t("explain.title")}</h1>
        <p className="inline-flex items-center gap-2 rounded-full border border-amber-300/25 bg-amber-400/10 px-3 py-1 text-sm font-medium text-amber-100">
          <FlaskConical className="h-4 w-4" aria-hidden="true" />
          {t("common.synthetic")}
        </p>
      </div>
      {/* Reserve roughly the chart's height so the footer does not jump when it arrives. */}
      <div className="min-h-[60vh]">
        {global.error ? (
          <ErrorNotice error={global.error} onRetry={global.reload} />
        ) : !data ? (
          <Skeleton className="h-10" lines={6} />
        ) : !data.available ? (
          // available=false is the backend saying "not computed" — never fill it in.
          <EmptyState>
            {t("explain.unavailable")} {data.note}
          </EmptyState>
        ) : (
          <section className="card max-w-3xl space-y-5">
            <p className="text-sm text-muted">{t("explain.sample", { n: data.sample_size ?? "—", version: data.model_version ?? "—" })}</p>
            {/* Each bar prints its value, so the list doubles as the text table. */}
            <div dir="ltr">
              <ShapBars rows={rows.map((r) => ({ label: r.feature, valueText: `${r.value.toFixed(3)} mm`, magnitude: r.value }))} />
            </div>
            <p className="text-xs text-muted">{data.note}</p>
        </section>
      )}
      </div>
    </div>
  );
}
