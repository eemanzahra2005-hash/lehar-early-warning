"use client";

import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { LevelBadge, levelScope } from "@/components/Level";
import { LevelBackdrop, PulsingIcon } from "@/components/LevelBand";
import { EmptyState, ErrorNotice, Skeleton } from "@/components/Status";
import { useI18n } from "@/i18n/LanguageProvider";
import { api, findAlertById } from "@/lib/api";
import { formatDateTime, humanType } from "@/lib/format";
import type { AlertResponse } from "@/lib/types";
import { useApi } from "@/lib/useApi";
import { useIsAdmin } from "@/lib/useIsAdmin";

function PayloadTable({ payload }: { payload: Record<string, unknown> }) {
  const entries = Object.entries(payload);
  if (entries.length === 0) return null;
  return (
    <div className="overflow-x-auto" dir="ltr">
      <table className="w-full text-left text-sm">
        <tbody>
          {entries.map(([key, value]) => (
            <tr key={key} className="border-b border-white/5 align-top last:border-0">
              <th scope="row" className="num py-2 pe-4 font-medium text-muted">
                {key}
              </th>
              <td className="num py-2 break-all text-ink">
                {typeof value === "object" ? JSON.stringify(value) : String(value)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function AlertDetail({ initial }: { initial: AlertResponse }) {
  const { t, pick, lang } = useI18n();
  const isAdmin = useIsAdmin();
  const [alert, setAlert] = useState(initial);
  const [ackError, setAckError] = useState<unknown>(null);
  const [acking, setAcking] = useState(false);

  const acknowledge = async () => {
    setAcking(true);
    try {
      setAlert(await api.ack(alert.id));
      setAckError(null);
    } catch (error) {
      setAckError(error);
    } finally {
      setAcking(false);
    }
  };

  return (
    <article className="space-y-6">
      <header className={`band ${levelScope(alert.level)} overflow-hidden rounded-3xl border border-white/10`}>
        <LevelBackdrop level={alert.level} />
        <div className="flex flex-wrap items-center gap-6 p-6 sm:p-8">
          <div className="flex items-center gap-4">
            <span className="hero-numeral !text-[clamp(64px,12vw,112px)]" aria-hidden="true">
              {alert.level}
            </span>
            <PulsingIcon level={alert.level} className="h-10 w-10 sm:h-12 sm:w-12" ringClass="p-3" />
          </div>
          <div className="min-w-0 flex-1 space-y-3">
            <LevelBadge level={alert.level} size="lg" />
            <h1 className="text-2xl font-semibold sm:text-3xl">{pick(alert.title_en, alert.title_ur)}</h1>
            <p className="text-sm font-medium">
              {alert.district_code} · {humanType(alert.type)} · {t(`status.${alert.status}` as "status.active")}
            </p>
          </div>
        </div>
      </header>

      {/* The body is the rule's fixed template text, shown verbatim (never generated). */}
      <p className="max-w-3xl whitespace-pre-line text-lg leading-relaxed text-ink">{pick(alert.body_en, alert.body_ur)}</p>

      <dl className="glass grid grid-cols-[auto_1fr] gap-x-6 gap-y-2 p-5 text-sm">
        <dt className="text-muted">{t("detail.created")}</dt>
        <dd className="num text-ink">{formatDateTime(alert.created_at, lang)}</dd>
        {alert.resolved_at && (
          <>
            <dt className="text-muted">{t("detail.resolved")}</dt>
            <dd className="num text-ink">{formatDateTime(alert.resolved_at, lang)}</dd>
          </>
        )}
        <dt className="text-muted">{t("detail.dedupe")}</dt>
        <dd className="num break-all text-ink" dir="ltr">
          {alert.dedupe_key}
        </dd>
      </dl>

      <section className="card space-y-3">
        <h2 className="h2">{t("detail.payload")}</h2>
        <PayloadTable payload={alert.payload} />
      </section>

      {isAdmin && alert.status === "active" && (
        <div className="space-y-2">
          <button type="button" className="btn-primary" onClick={acknowledge} disabled={acking}>
            {t("detail.adminAck")}
          </button>
          {ackError !== null && <ErrorNotice error={ackError} />}
        </div>
      )}
      {isAdmin && alert.status === "acknowledged" && <p className="text-sm text-ok">{t("detail.adminAckDone")}</p>}
      <p className="text-sm font-medium text-muted">{t("disclaimer")}</p>
    </article>
  );
}

export default function AlertDetailPage() {
  const { t } = useI18n();
  const params = useParams<{ id: string }>();
  const id = Number(params.id);
  const result = useApi(() => (Number.isInteger(id) && id > 0 ? findAlertById(id) : Promise.resolve(null)), [id]);

  return (
    <div className="page space-y-5 py-8">
      <Link href="/alerts" className="btn-secondary">
        <ArrowLeft className="h-4 w-4 rtl:rotate-180" aria-hidden="true" />
        {t("common.back")}
      </Link>
      {result.error ? (
        <ErrorNotice error={result.error} onRetry={result.reload} />
      ) : result.loading ? (
        <Skeleton className="h-48" lines={2} />
      ) : result.data ? (
        <AlertDetail key={result.data.id} initial={result.data} />
      ) : (
        <EmptyState>{t("detail.notFound", { id: params.id })}</EmptyState>
      )}
    </div>
  );
}
