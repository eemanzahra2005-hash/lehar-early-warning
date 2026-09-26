"use client";

import { ExternalLink, Mail, Send } from "lucide-react";
import { useMemo, useState } from "react";
import { LevelBadge } from "@/components/Level";
import { ErrorNotice, Loading } from "@/components/Status";
import { useI18n } from "@/i18n/LanguageProvider";
import { ApiError, api } from "@/lib/api";
import type { EmailSubscribeResponse, TelegramLinkResponse } from "@/lib/types";
import { useApi } from "@/lib/useApi";

/** 503 = channel not configured on this server; say that plainly instead of an error. */
function isNotConfigured(error: unknown): boolean {
  return error instanceof ApiError && error.status === 503;
}

function TelegramCard({ districts }: { districts: string[] }) {
  const { t, pick } = useI18n();
  const [district, setDistrict] = useState("");
  const [link, setLink] = useState<TelegramLinkResponse | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  const getLink = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!district) return;
    setBusy(true);
    setLink(null);
    try {
      setLink(await api.telegramLink(district));
      setError(null);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="card space-y-3" aria-labelledby="tg-title">
      <h2 id="tg-title" className="h2 flex items-center gap-2">
        <Send className="h-5 w-5" aria-hidden="true" />
        {t("sub.telegram")}
      </h2>
      <p className="text-sm text-slate-700">{t("sub.telegramHelp")}</p>
      <form onSubmit={getLink} className="flex flex-wrap items-end gap-2">
        <label className="min-w-48 flex-1">
          <span className="field-label">{t("common.district")}</span>
          <select className="field-input" value={district} onChange={(e) => setDistrict(e.target.value)} required>
            <option value="">—</option>
            {districts.map((d) => (
              <option key={d} value={d}>
                {d}
              </option>
            ))}
          </select>
        </label>
        <button type="submit" className="btn-primary" disabled={!district || busy}>
          {t("sub.getLink")}
        </button>
      </form>

      <div aria-live="polite">
        {error !== null &&
          (isNotConfigured(error) ? (
            <p className="rounded-md bg-slate-100 p-3 text-sm">{t("sub.telegramOff")}</p>
          ) : (
            <ErrorNotice error={error} />
          ))}
        {link && (
          <div className="space-y-2 rounded-lg bg-sky-50 p-3">
            <a href={link.url} target="_blank" rel="noopener noreferrer" className="btn-primary">
              <ExternalLink className="h-4 w-4" aria-hidden="true" />
              {t("sub.openTelegram")} — {link.district}
            </a>
            <p className="text-sm">{pick(link.instructions_en, link.instructions_ur)}</p>
            <p className="text-sm">
              {t("sub.orType", { bot: link.bot_username })}{" "}
              <code className="rounded bg-white px-1.5 py-0.5" dir="ltr">
                {link.start_command}
              </code>
            </p>
          </div>
        )}
      </div>
    </section>
  );
}

function EmailCard({ byProvince }: { byProvince: Record<string, string[]> }) {
  const { t, pick, lang } = useI18n();
  const [email, setEmail] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const [minLevel, setMinLevel] = useState(3);
  const [language, setLanguage] = useState<"en" | "ur">(lang);
  const [search, setSearch] = useState("");
  const [result, setResult] = useState<EmailSubscribeResponse | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [pickError, setPickError] = useState(false);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return Object.entries(byProvince)
      .map(([province, list]) => [province, list.filter((d) => !q || d.toLowerCase().includes(q))] as const)
      .filter(([, list]) => list.length > 0);
  }, [byProvince, search]);

  const toggle = (district: string) =>
    setSelected((s) => (s.includes(district) ? s.filter((d) => d !== district) : [...s, district]));

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (selected.length === 0) {
      setPickError(true);
      return;
    }
    setPickError(false);
    setBusy(true);
    try {
      setResult(await api.emailSubscribe({ email, districts: selected, min_level: minLevel, language }));
      setError(null);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  };

  if (result) {
    return (
      <section className="card space-y-2 border-green-300 bg-green-50" aria-live="polite">
        <h2 className="h2 flex items-center gap-2 text-green-950">
          <Mail className="h-5 w-5" aria-hidden="true" />
          {t("sub.sent")}
        </h2>
        <p className="text-green-950">{pick(result.message_en, result.message_ur)}</p>
        <p className="text-sm text-green-900">{pick(result.disclaimer, result.disclaimer_ur)}</p>
      </section>
    );
  }

  return (
    <section className="card space-y-3" aria-labelledby="email-title">
      <h2 id="email-title" className="h2 flex items-center gap-2">
        <Mail className="h-5 w-5" aria-hidden="true" />
        {t("sub.email")}
      </h2>
      <form onSubmit={submit} className="space-y-4">
        <label className="block">
          <span className="field-label">{t("sub.emailLabel")}</span>
          <input
            type="email"
            required
            maxLength={254}
            autoComplete="email"
            dir="ltr"
            className="field-input"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </label>

        <fieldset className="space-y-2">
          <legend className="field-label">
            {t("sub.chooseDistricts")} — {t("sub.selectedCount", { n: selected.length })}
          </legend>
          <input
            type="search"
            className="field-input"
            placeholder={t("sub.searchDistricts")}
            aria-label={t("sub.searchDistricts")}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          <div className="max-h-64 space-y-3 overflow-y-auto rounded-md border border-slate-200 p-2">
            {filtered.map(([province, list]) => (
              <div key={province}>
                <p className="text-xs font-semibold uppercase text-slate-600">{province}</p>
                <div className="grid grid-cols-2 gap-1 sm:grid-cols-3">
                  {list.map((d) => (
                    <label key={d} className="flex items-center gap-2 rounded px-1 py-1 text-sm hover:bg-slate-50">
                      <input type="checkbox" checked={selected.includes(d)} onChange={() => toggle(d)} className="h-4 w-4" />
                      {d}
                    </label>
                  ))}
                </div>
              </div>
            ))}
          </div>
          {pickError && (
            <p role="alert" className="text-sm font-medium text-red-800">
              {t("sub.pickDistrict")}
            </p>
          )}
        </fieldset>

        <fieldset>
          <legend className="field-label">{t("sub.minLevel")}</legend>
          {/* Level 1 is in-app only, so email starts at level 2 (schemas.py). */}
          <div className="flex flex-wrap gap-3">
            {[2, 3, 4, 5].map((n) => (
              <label key={n} className="flex items-center gap-2">
                <input type="radio" name="min-level" value={n} checked={minLevel === n} onChange={() => setMinLevel(n)} />
                <LevelBadge level={n} size="sm" />
              </label>
            ))}
          </div>
        </fieldset>

        <fieldset>
          <legend className="field-label">{t("common.language")}</legend>
          <div className="flex gap-4">
            {(["en", "ur"] as const).map((code) => (
              <label key={code} className="flex items-center gap-2">
                <input type="radio" name="language" checked={language === code} onChange={() => setLanguage(code)} />
                {code === "en" ? t("common.english") : t("common.urdu")}
              </label>
            ))}
          </div>
        </fieldset>

        <button type="submit" className="btn-primary" disabled={busy}>
          {t("sub.subscribe")}
        </button>
      </form>

      <div aria-live="polite">
        {error !== null &&
          (isNotConfigured(error) ? (
            <p className="rounded-md bg-slate-100 p-3 text-sm">{t("sub.emailOff")}</p>
          ) : error instanceof ApiError && error.status === 429 ? (
            <p className="rounded-md bg-amber-50 p-3 text-sm">{t("sub.rateLimited")}</p>
          ) : (
            <ErrorNotice error={error} />
          ))}
      </div>
    </section>
  );
}

export default function SubscribePage() {
  const { t } = useI18n();
  const meta = useApi(api.meta);

  return (
    <div className="space-y-5">
      <h1 className="h1">{t("sub.title")}</h1>
      {meta.error ? (
        <ErrorNotice error={meta.error} onRetry={meta.reload} />
      ) : !meta.data ? (
        <Loading />
      ) : (
        <div className="grid gap-5 lg:grid-cols-2">
          <TelegramCard districts={meta.data.districts} />
          <EmailCard byProvince={meta.data.districts_by_province} />
        </div>
      )}
    </div>
  );
}
