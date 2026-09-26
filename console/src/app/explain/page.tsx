"use client";

import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { EmptyState, ErrorNotice, Loading } from "@/components/Status";
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
    <div className="space-y-4">
      <h1 className="h1">{t("explain.title")}</h1>
      <p className="text-sm font-medium text-slate-700">{t("common.synthetic")}</p>
      {global.error ? (
        <ErrorNotice error={global.error} onRetry={global.reload} />
      ) : !data ? (
        <Loading />
      ) : !data.available ? (
        // available=false is the backend saying "not computed" — never fill it in.
        <EmptyState>
          {t("explain.unavailable")} {data.note}
        </EmptyState>
      ) : (
        <section className="card space-y-3">
          <p className="text-sm text-slate-700">
            {t("explain.sample", { n: data.sample_size ?? "—", version: data.model_version ?? "—" })}
          </p>
          <div style={{ height: Math.max(240, rows.length * 34) }} dir="ltr">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={rows} layout="vertical" margin={{ left: 8, right: 16 }}>
                <CartesianGrid stroke="#e2e8f0" horizontal={false} />
                <XAxis type="number" tick={{ fontSize: 11 }} unit=" mm" />
                <YAxis type="category" dataKey="feature" width={170} tick={{ fontSize: 12 }} />
                <Tooltip formatter={(v) => `${Number(v).toFixed(3)} mm`} />
                <Bar dataKey="value" name="mean |SHAP|" fill="#1d4ed8" />
              </BarChart>
            </ResponsiveContainer>
          </div>
          {/* Text version of the chart for screen readers and copy-paste. */}
          <table className="w-full text-sm" dir="ltr">
            <caption className="sr-only">Mean absolute SHAP contribution per feature</caption>
            <tbody>
              {rows.map((r) => (
                <tr key={r.feature} className="border-b border-slate-100">
                  <th scope="row" className="py-1 text-left font-medium">
                    {r.feature}
                  </th>
                  <td className="py-1 text-right font-mono">{r.value.toFixed(3)} mm</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="text-xs text-slate-600">{data.note}</p>
        </section>
      )}
    </div>
  );
}
