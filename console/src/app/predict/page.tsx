"use client";

import { ArrowDown, ArrowUp } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { ErrorNotice, Loading } from "@/components/Status";
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
        className="field-input"
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

function Result({ result }: { result: PredictResponse }) {
  const { t } = useI18n();
  // Largest absolute SHAP contributions first: the "top reasons".
  const reasons = [...(result.explanation?.contributions ?? [])]
    .sort((a, b) => Math.abs(b.contribution_mm) - Math.abs(a.contribution_mm))
    .slice(0, TOP_REASONS);
  const maxAbs = Math.max(...reasons.map((r) => Math.abs(r.contribution_mm)), 0.0001);

  return (
    <section className="card space-y-4" aria-live="polite" aria-labelledby="result-title">
      <div>
        <h2 id="result-title" className="text-sm font-semibold text-slate-600">
          {t("predict.result")}
        </h2>
        <p className="text-4xl font-black">
          {formatNumber(result.irrigation_recommendation_mm)} <span className="text-xl font-semibold">mm</span>
        </p>
        <p className="text-sm text-slate-700">
          {t("predict.source")}: <code>{result.source}</code>
          {result.model_version && <> · model {result.model_version}</>}
        </p>
        {result.reason && <p className="mt-2 rounded-md bg-amber-50 p-2 text-sm text-amber-950">{result.reason}</p>}
        {result.confidence && (
          <p className="text-sm text-slate-700">
            {t("predict.interval", {
              lo: formatNumber(result.confidence.interval_mm[0]),
              hi: formatNumber(result.confidence.interval_mm[1]),
            })}
          </p>
        )}
        {result.risk && (
          <p className="text-sm text-slate-700">
            {t("predict.risk", { band: result.risk.band, score: formatNumber(result.risk.score, 0) })}
          </p>
        )}
        {result.soil_moisture_note && <p className="text-sm text-slate-700">{result.soil_moisture_note}</p>}
      </div>

      <div>
        <h3 className="mb-2 font-semibold">{t("predict.reasons")}</h3>
        {reasons.length === 0 ? (
          <p className="text-sm text-slate-600">{t("predict.noExplanation")}</p>
        ) : (
          <ul className="space-y-2">
            {reasons.map((r) => {
              const up = r.contribution_mm >= 0;
              return (
                <li key={r.feature} className="text-sm">
                  <div className="flex items-center justify-between gap-2">
                    <span className="flex items-center gap-1 font-medium">
                      {up ? <ArrowUp className="h-4 w-4" aria-hidden="true" /> : <ArrowDown className="h-4 w-4" aria-hidden="true" />}
                      {r.feature} = <span dir="ltr">{String(r.value)}</span>
                    </span>
                    <span dir="ltr">
                      {up ? "+" : ""}
                      {formatNumber(r.contribution_mm, 2)} mm ({up ? t("predict.increases") : t("predict.decreases")})
                    </span>
                  </div>
                  <div className="mt-1 h-2 rounded bg-slate-100" aria-hidden="true">
                    <div
                      className={`h-2 rounded ${up ? "bg-blue-700" : "bg-orange-600"}`}
                      style={{ width: `${(Math.abs(r.contribution_mm) / maxAbs) * 100}%` }}
                    />
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </div>

      <div className="text-sm text-slate-700">
        <h3 className="font-semibold">{t("predict.weather")}</h3>
        <p dir="ltr">
          {formatNumber(result.weather_used.temperature_c)} °C · {formatNumber(result.weather_used.humidity_pct, 0)}% ·{" "}
          {formatNumber(result.weather_used.rainfall_mm)} mm rain · ET0 {formatNumber(result.weather_used.evapotranspiration_mm)} mm ({result.weather_used.source})
        </p>
      </div>
      <p className="text-sm font-semibold text-slate-800">{t("common.synthetic")}</p>
      <Link href="/explain" className="text-sm text-blue-800 underline">
        {t("predict.seeExplain")}
      </Link>
    </section>
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

  if (meta.error) return <ErrorNotice error={meta.error} onRetry={meta.reload} />;
  if (!meta.data) return <Loading />;

  return (
    <div className="space-y-5">
      <h1 className="h1">{t("predict.title")}</h1>
      <p className="text-sm font-medium text-slate-700">{t("common.synthetic")}</p>
      <div className="grid gap-5 lg:grid-cols-2">
        <form onSubmit={submit} className="card space-y-3">
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
          <label className="flex items-center gap-2">
            <input type="checkbox" checked={form.use_live_soil} onChange={(e) => set("use_live_soil", e.target.checked)} className="h-4 w-4" />
            {t("predict.liveSoil")}
          </label>
          <label className="flex items-center gap-2">
            <input type="checkbox" checked={form.use_live_weather} onChange={(e) => set("use_live_weather", e.target.checked)} className="h-4 w-4" />
            {t("predict.liveWeather")}
          </label>
          {!form.use_live_weather && (
            <div className="grid grid-cols-2 gap-3">
              <NumberField label={t("predict.temp")} value={form.manual_temperature_c ?? NaN} onChange={(v) => set("manual_temperature_c", v)} min={-10} max={55} />
              <NumberField label={t("predict.humidity")} value={form.manual_humidity_pct ?? NaN} onChange={(v) => set("manual_humidity_pct", v)} min={0} max={100} />
              <NumberField label={t("predict.rain")} value={form.manual_rainfall_mm ?? NaN} onChange={(v) => set("manual_rainfall_mm", v)} min={0} max={400} />
              <NumberField label={t("predict.et")} value={form.manual_evapotranspiration_mm ?? NaN} onChange={(v) => set("manual_evapotranspiration_mm", v)} min={0} max={20} />
            </div>
          )}
          <button type="submit" className="btn-primary w-full" disabled={busy}>
            {t("predict.run")}
          </button>
        </form>
        <div className="space-y-3">
          {busy && <Loading />}
          {error !== null && <ErrorNotice error={error} />}
          {result && <Result result={result} />}
        </div>
      </div>
    </div>
  );
}
