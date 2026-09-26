"use client";

import { AnimatePresence, m } from "framer-motion";
import { ExternalLink, Mail, MailCheck, Search, Send, X } from "lucide-react";
import { useMemo, useState } from "react";
import { ChipGroup } from "@/components/Chips";
import { LevelBadge, levelScope } from "@/components/Level";
import { EASE_OUT } from "@/components/Motion";
import { QrCode } from "@/components/QrCode";
import { ErrorNotice, Notice, Skeleton } from "@/components/Status";
import { Steps } from "@/components/Steps";
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
    <section className="card lift flex flex-col gap-5" aria-labelledby="tg-title">
      <div className="flex items-center gap-3">
        <span className="grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-sky-400/15 text-sky-300 shadow-[0_0_20px_-4px_rgb(56_189_248/0.6)]">
          <Send className="h-5 w-5" aria-hidden="true" />
        </span>
        <div>
          <h2 id="tg-title" className="h2">
            {t("sub.telegram")}
          </h2>
          <p className="text-sm text-muted">{t("sub.telegramHelp")}</p>
        </div>
      </div>

      {/* Step 3 (pressing Start) happens inside Telegram: it is never marked done here. */}
      <Steps label={t("sub.steps")} current={link ? 1 : 0} steps={[t("sub.tgStep1"), t("sub.tgStep2"), t("sub.tgStep3")]} />

      <form onSubmit={getLink} className="flex flex-wrap items-end gap-3">
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
        {error !== null && (isNotConfigured(error) ? <Notice>{t("sub.telegramOff")}</Notice> : <ErrorNotice error={error} />)}
        <AnimatePresence>
          {link && (
            <m.div
              key={link.url}
              initial={{ opacity: 0, y: 12, scale: 0.98 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              transition={{ duration: 0.35, ease: EASE_OUT }}
              className="flex flex-col gap-5 rounded-2xl border border-sky-300/20 bg-sky-400/[0.06] p-5 sm:flex-row sm:items-center md:flex-col md:items-stretch xl:flex-row xl:items-center"
            >
              <div className="flex flex-col items-center gap-2">
                <QrCode value={link.url} label={`${t("sub.openTelegram")} — ${link.district}`} />
                <p className="max-w-44 text-center text-xs text-muted">{t("sub.scanQr")}</p>
              </div>
              <div className="min-w-0 flex-1 space-y-3">
                <a href={link.url} target="_blank" rel="noopener noreferrer" className="btn-primary">
                  <ExternalLink className="h-4 w-4" aria-hidden="true" />
                  {t("sub.openTelegram")} — {link.district}
                </a>
                <p className="text-sm text-ink">{pick(link.instructions_en, link.instructions_ur)}</p>
                <p className="text-sm text-muted">
                  {t("sub.orType", { bot: link.bot_username })}{" "}
                  <code className="num rounded-md bg-black/40 px-1.5 py-0.5 text-ink" dir="ltr">
                    {link.start_command}
                  </code>
                </p>
                <p className="text-xs text-muted">{pick(link.disclaimer, link.disclaimer_ur)}</p>
              </div>
            </m.div>
          )}
        </AnimatePresence>
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

  // Double opt-in: the console can only see step 1 -> 2. Step 3 (clicking
  // the link in the email) happens outside it, so it is never shown as done.
  const steps = [t("sub.emailStep1"), t("sub.emailStep2"), t("sub.emailStep3")];

  if (result) {
    return (
      <section className="card flex flex-col gap-5 border-emerald-300/25 bg-emerald-400/[0.05]" aria-live="polite" aria-labelledby="email-done">
        <Steps label={t("sub.steps")} current={1} steps={steps} />
        <m.div
          className="flex items-center gap-4"
          initial={{ opacity: 0, scale: 0.9 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ type: "spring", stiffness: 260, damping: 20 }}
        >
          <span className="grid h-14 w-14 shrink-0 place-items-center rounded-full bg-emerald-400/15 text-ok shadow-[0_0_28px_-4px_rgb(74_222_128/0.6)]">
            <MailCheck className="h-7 w-7" aria-hidden="true" />
          </span>
          <h2 id="email-done" className="h2">
            {t("sub.sent")}
          </h2>
        </m.div>
        <p className="text-ink">{pick(result.message_en, result.message_ur)}</p>
        <Notice tone="warn">{t("sub.confirmPending")}</Notice>
        <p className="text-sm text-muted">{pick(result.disclaimer, result.disclaimer_ur)}</p>
      </section>
    );
  }

  return (
    <section className="card lift flex flex-col gap-5" aria-labelledby="email-title">
      <div className="flex items-center gap-3">
        <span className="grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-accent/15 text-accent shadow-[0_0_20px_-4px_rgb(94_234_212/0.6)]">
          <Mail className="h-5 w-5" aria-hidden="true" />
        </span>
        <h2 id="email-title" className="h2">
          {t("sub.email")}
        </h2>
      </div>

      <Steps label={t("sub.steps")} current={0} steps={steps} />

      <form onSubmit={submit} className="space-y-5">
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

        <fieldset className="space-y-2.5">
          <legend className="field-label">
            {t("sub.chooseDistricts")} — <span className="num">{t("sub.selectedCount", { n: selected.length })}</span>
          </legend>
          {selected.length > 0 && (
            <ul className="flex flex-wrap gap-1.5">
              <AnimatePresence initial={false}>
                {selected.map((d) => (
                  <m.li key={d} layout initial={{ opacity: 0, scale: 0.8 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0, scale: 0.8 }}>
                    <button
                      type="button"
                      onClick={() => toggle(d)}
                      className="press inline-flex min-h-11 items-center gap-1 rounded-full border border-accent/50 bg-accent/15 px-3 text-xs font-medium text-white transition-transform md:min-h-8 md:px-2.5"
                    >
                      {d}
                      <X className="h-3.5 w-3.5" aria-hidden="true" />
                      <span className="sr-only">({t("common.close")})</span>
                    </button>
                  </m.li>
                ))}
              </AnimatePresence>
            </ul>
          )}
          <div className="relative">
            <Search className="pointer-events-none absolute start-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" aria-hidden="true" />
            <input
              type="search"
              className="field-input ps-10"
              placeholder={t("sub.searchDistricts")}
              aria-label={t("sub.searchDistricts")}
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>
          <div className="max-h-64 space-y-4 overflow-y-auto rounded-xl border border-line bg-black/20 p-3">
            {filtered.map(([province, list]) => (
              <div key={province}>
                <p className="eyebrow mb-1.5">{province}</p>
                <div className="grid grid-cols-2 gap-1 sm:grid-cols-3 md:grid-cols-2 xl:grid-cols-3">
                  {list.map((d) => {
                    const on = selected.includes(d);
                    return (
                      <label
                        key={d}
                        className={`flex min-h-11 cursor-pointer items-center gap-2 rounded-lg px-2 py-1 text-sm transition-colors md:min-h-9 ${
                          on ? "bg-accent/10 text-white" : "text-ink hover:bg-white/5"
                        }`}
                      >
                        <input type="checkbox" checked={on} onChange={() => toggle(d)} className="h-4 w-4 shrink-0 accent-[#5eead4]" />
                        {d}
                      </label>
                    );
                  })}
                </div>
              </div>
            ))}
          </div>
          {pickError && (
            <p role="alert" className="text-sm font-medium text-danger">
              {t("sub.pickDistrict")}
            </p>
          )}
        </fieldset>

        <fieldset className="space-y-2">
          <legend className="field-label">{t("sub.minLevel")}</legend>
          {/* Level 1 is in-app only, so email starts at level 2 (schemas.py). */}
          <p className="text-xs text-muted">{t("sub.minLevelHelp")}</p>
          <div className="grid gap-2 sm:grid-cols-2 md:grid-cols-1 lg:grid-cols-2">
            {[2, 3, 4, 5].map((n) => (
              <label
                key={n}
                className={`${levelScope(n)} flex min-h-12 cursor-pointer items-center rounded-xl border p-2.5 transition-colors has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-accent ${
                  minLevel === n ? "border-[color:var(--lvl-ink)] bg-white/[0.06] shadow-[0_0_20px_-6px_var(--lvl-glow)]" : "border-line hover:bg-white/[0.04]"
                }`}
              >
                <input type="radio" name="min-level" value={n} checked={minLevel === n} onChange={() => setMinLevel(n)} className="sr-only" />
                <LevelBadge level={n} size="sm" />
              </label>
            ))}
          </div>
        </fieldset>

        <div className="space-y-2">
          <p className="field-label">{t("common.language")}</p>
          <ChipGroup
            id="email-lang"
            label={t("common.language")}
            value={language}
            onChange={(v) => setLanguage(v as "en" | "ur")}
            options={[
              { value: "en", label: t("common.english") },
              { value: "ur", label: t("common.urdu") },
            ]}
          />
        </div>

        <button type="submit" className="btn-primary w-full sm:w-auto" disabled={busy}>
          <Mail className="h-4 w-4" aria-hidden="true" />
          {t("sub.subscribe")}
        </button>
      </form>

      <div aria-live="polite">
        {error !== null &&
          (isNotConfigured(error) ? (
            <Notice>{t("sub.emailOff")}</Notice>
          ) : error instanceof ApiError && error.status === 429 ? (
            <Notice tone="warn">{t("sub.rateLimited")}</Notice>
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
    <div className="page space-y-6 py-8">
      <h1 className="h1">{t("sub.title")}</h1>
      {meta.error ? (
        <ErrorNotice error={meta.error} onRetry={meta.reload} />
      ) : !meta.data ? (
        <div className="grid gap-6 md:grid-cols-2">
          <Skeleton className="h-80" />
          <Skeleton className="h-80" />
        </div>
      ) : (
        <div className="grid items-start gap-6 md:grid-cols-2">
          <TelegramCard districts={meta.data.districts} />
          <EmailCard byProvince={meta.data.districts_by_province} />
        </div>
      )}
    </div>
  );
}
