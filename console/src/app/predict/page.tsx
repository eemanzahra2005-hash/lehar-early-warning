"use client";

import { m } from "framer-motion";
import { ArrowUpRight, CloudSun, Droplets, FlaskConical } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { CountUp, EASE_OUT } from "@/components/Motion";
import { ShapBars } from "@/components/ShapBars";
import { ErrorNotice, Skeleton } from "@/components/Status";
import { useI18n } from "@/i18n/LanguageProvider";
import { api } from "@/lib/api";
import { formatNumber } from "@/lib/format";
import type { PredictRequest, PredictResponse } from "@/lib/types";
import { useApi } from "@/lib/useApi";

const TOP_REASONS = 5;

function NumberField({
  label,
  value,
  onChange,
  min,
  max,
  step = 0.1,
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
  min: number;
  max: number;
  step?: number;
}) {
  return (
    <label className="block">
      <span className="field-label">{label}</span>
      <input
        type="number"
        className="field-input num"
        dir="ltr"
        required
        min={min}
        max={max}
        step={step}
        value={Number.isNaN(value) ? "" : value}
        onChange={(e) => onChange(e.target.valueAsNumber)}
      />
    </label>
  );
}

/** An on/off switch that is still a real checkbox underneath (keyboard + forms work as before). */
function Switch({ label, checked, onChange }: { label: string; checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <label className="flex min-h-11 cursor-pointer items-center justify-between gap-4 rounded-xl border border-line bg-white/[0.03] px-3.5 py-2 has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-accent">
      <span className="text-sm text-ink">{label}</span>
      <input type="checkbox" role="switch" checked={checked} onChange={(e) => onChange(e.target.checked)} className="peer sr-only" />
      <span
        aria-hidden="true"
        className={`relative h-6 w-11 shrink-0 rounded-full transition-colors ${checked ? "bg-accent shadow-[0_0_14px_-2px_rgb(94_234_212/0.7)]" : "bg-white/15"}`}
      >
        <span
          className={`absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition-[inset-inline-start] duration-200 ${checked ? "start-[22px]" : "start-0.5"}`}
        />
      </span>
    </label>
  );
}

function Result({ result }: { result: PredictResponse }) {
  const { t } = useI18n();
  // Largest absolute SHAP contributions first: the "top reasons".
  const reasons = [...(result.explanation?.contributions ?? [])]
    .sort((a, b) => Math.abs(b.contribution_mm) - Math.abs(a.contribution_mm))
    .slice(0, TOP_REASONS);

  return (
    <m.section
      className="card space-y-6"
      aria-live="polite"
      aria-labelledby="result-title"
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, ease: EASE_OUT }}
    >
      <div>
        <h2 id="result-title" className="eyebrow">
          {t("predict.result")}
        </h2>
        <p className="mt-2 flex items-baseline gap-2 text-white">
          <Droplets className="h-8 w-8 self-center text-accent" aria-hidden="true" />
          <CountUp value={result.irrigation_recommendation_mm} decimals={1} className="num font-display text-6xl font-semibold tracking-tight" />
          <span className="text-xl font-medium text-muted">mm</span>
        </p>
        <p className="mt-2 text-sm text-muted">
          {t("predict.source")}: <code className="num text-ink">{result.source}</code>
          {result.model_version && (
            <>
              {" "}
              · model <span className="num text-ink">{result.model_version}</span>
            </>
          )}
        </p>
        {result.reason && <p className="mt-3 rounded-xl border border-amber-300/25 bg-amber-400/10 p-3 text-sm text-amber-100">{result.reason}</p>}
        <div className="mt-3 space-y-1 text-sm text-muted">
          {result.confidence && (
            <p className="num">
              {t("predict.interval", {
                lo: formatNumber(result.confidence.interval_mm[0]),
                hi: formatNumber(result.confidence.interval_mm[1]),
              })}
            </p>
          )}
          {result.risk && <p>{t("predict.risk", { band: result.risk.band, score: formatNumber(result.risk.score, 0) })}</p>}
          {result.soil_moisture_note && <p>{result.soil_moisture_note}</p>}
        </div>
      </div>

      <div>
        <h3 className="eyebrow mb-3">{t("predict.reasons")}</h3>
        {reasons.length === 0 ? (
          <p className="text-sm text-muted">{t("predict.noExplanation")}</p>
        ) : (
          <ShapBars
            rows={reasons.map((r) => {
              const up = r.contribution_mm >= 0;
              return {
                label: (
                  <>
                    {r.feature} = <span dir="ltr">{String(r.value)}</span>
                  </>
                ),
                valueText: `${up ? "+" : ""}${formatNumber(r.contribution_mm, 2)} mm (${up ? t("predict.increases") : t("predict.decreases")})`,
                magnitude: r.contribution_mm,
                direction: up ? "up" : "down",
              };
            })}
          />
        )}
      </div>

      <div className="rounded-xl border border-line bg-white/[0.03] p-4 text-sm">
        <h3 className="mb-1 flex items-center gap-2 font-semibold text-white">
          <CloudSun className="h-4 w-4 text-accent" aria-hidden="true" />
          {t("predict.weather")}
        </h3>
        <p className="num text-muted" dir="ltr">
          {formatNumber(result.weather_used.temperature_c)} °C · {formatNumber(result.weather_used.humidity_pct, 0)}% ·{" "}
          {formatNumber(result.weather_used.rainfall_mm)} mm rain · ET0 {formatNumber(result.weather_used.evapotranspiration_mm)} mm ({result.weather_used.source})
        </p>
      </div>
      <p className="text-sm font-semibold text-amber-100">{t("common.synthetic")}</p>
      <Link href="/explain" className="link inline-flex items-center gap-1 text-sm">
        {t("predict.seeExplain")}
        <ArrowUpRight className="h-4 w-4 rtl:-scale-x-100" aria-hidden="true" />
      </Link>
    </m.section>
  );
}

export default function PredictPage() {
  const { t } = useI18n();
  const meta = useApi(api.meta);
  const [form, setForm] = useState<PredictRequest>({
    district: "",
    crop_type: "",
    soil_moisture_pct: 25,
    canal_flow_cusecs: 100,
    use_live_weather: true,
    use_live_soil: false,
    manual_temperature_c: 30,
    manual_humidity_pct: 50,
    manual_rainfall_mm: 0,
    manual_evapotranspiration_mm: 5,
  });
  const [result, setResult] = useState<PredictResponse | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const set = <K extends keyof PredictRequest>(key: K, value: PredictRequest[K]) => setForm((f) => ({ ...f, [key]: value }));

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setResult(null);
    try {
      // With live weather on, the manual values are not sent at all.
      const body: PredictRequest = form.use_live_weather
        ? { ...form, manual_temperature_c: null, manual_humidity_pct: null, manual_rainfall_mm: null, manual_evapotranspiration_mm: null }
        : form;
      setResult(await api.predict(body));
      setError(null);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="page space-y-6 py-8">
      <div className="space-y-3">
        <h1 className="h1">{t("predict.title")}</h1>
        <p className="inline-flex items-center gap-2 rounded-full border border-amber-300/25 bg-amber-400/10 px-3 py-1 text-sm font-medium text-amber-100">
          <FlaskConical className="h-4 w-4" aria-hidden="true" />
          {t("common.synthetic")}
        </p>
      </div>
      {meta.error ? (
        <ErrorNotice error={meta.error} onRetry={meta.reload} />
      ) : !meta.data ? (
        <div className="grid gap-6 md:grid-cols-2">
          <Skeleton className="h-96" />
        </div>
      ) : (
        <div className="grid items-start gap-6 md:grid-cols-2">
          <form onSubmit={submit} className="card space-y-4">
            <div className="grid gap-4 sm:grid-cols-2 md:grid-cols-1 lg:grid-cols-2">
              <label className="block">
                <span className="field-label">{t("common.district")}</span>
                <select className="field-input" required value={form.district} onChange={(e) => set("district", e.target.value)}>
                  <option value="">—</option>
                  {meta.data.districts.map((d) => (
                    <option key={d} value={d}>
                      {d}
                    </option>
                  ))}
                </select>
              </label>
              <label className="block">
                <span className="field-label">{t("predict.crop")}</span>
                <select className="field-input" required value={form.crop_type} onChange={(e) => set("crop_type", e.target.value)}>
                  <option value="">—</option>
                  {meta.data.crops.map((c) => (
                    <option key={c} value={c}>
                      {c}
                    </option>
                  ))}
                </select>
              </label>
              {/* Bounds mirror PredictRequest's Field(ge, le) in schemas.py. */}
              <NumberField label={t("predict.soil")} value={form.soil_moisture_pct} onChange={(v) => set("soil_moisture_pct", v)} min={0} max={100} />
              <NumberField label={t("predict.canal")} value={form.canal_flow_cusecs} onChange={(v) => set("canal_flow_cusecs", v)} min={0} max={2000} step={1} />
            </div>
            <Switch label={t("predict.liveSoil")} checked={!!form.use_live_soil} onChange={(v) => set("use_live_soil", v)} />
            <Switch label={t("predict.liveWeather")} checked={form.use_live_weather} onChange={(v) => set("use_live_weather", v)} />
            {!form.use_live_weather && (
              <m.div
                className="grid grid-cols-2 gap-4"
                initial={{ opacity: 0, height: 0 }}
                animate={{ opacity: 1, height: "auto" }}
                transition={{ duration: 0.25, ease: EASE_OUT }}
              >
                <NumberField label={t("predict.temp")} value={form.manual_temperature_c ?? NaN} onChange={(v) => set("manual_temperature_c", v)} min={-10} max={55} />
                <NumberField label={t("predict.humidity")} value={form.manual_humidity_pct ?? NaN} onChange={(v) => set("manual_humidity_pct", v)} min={0} max={100} />
                <NumberField label={t("predict.rain")} value={form.manual_rainfall_mm ?? NaN} onChange={(v) => set("manual_rainfall_mm", v)} min={0} max={400} />
                <NumberField label={t("predict.et")} value={form.manual_evapotranspiration_mm ?? NaN} onChange={(v) => set("manual_evapotranspiration_mm", v)} min={0} max={20} />
              </m.div>
            )}
            <button type="submit" className="btn-primary w-full" disabled={busy}>
              <Droplets className="h-4 w-4" aria-hidden="true" />
              {t("predict.run")}
            </button>
          </form>
          <div className="space-y-4">
            {busy && <Skeleton className="h-72" />}
            {error !== null && <ErrorNotice error={error} />}
            {result && <Result result={result} />}
          </div>
        </div>
      )}
    </div>
  );
}
