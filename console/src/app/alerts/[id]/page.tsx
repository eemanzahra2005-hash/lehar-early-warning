"use client";

import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { LevelBadge } from "@/components/Level";
import { EmptyState, ErrorNotice, Loading } from "@/components/Status";
import { useI18n } from "@/i18n/LanguageProvider";
import { api, findAlertById } from "@/lib/api";
import { formatDateTime, humanType } from "@/lib/format";
import { levelToken } from "@/lib/levels";
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
            <tr key={key} className="border-b border-slate-100 align-top">
              <th scope="row" className="py-1.5 pe-4 font-mono font-medium text-slate-700">
                {key}
              </th>
              <td className="py-1.5 font-mono break-all text-slate-900">
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
  const token = levelToken(alert.level);

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
    <article className="space-y-5">
      <header className={`${token.className} level-outline space-y-2 rounded-2xl p-5`}>
        <LevelBadge level={alert.level} size="lg" />
        <h1 className="text-2xl font-bold">{pick(alert.title_en, alert.title_ur)}</h1>
        <p className="text-sm">
          {alert.district_code} · {humanType(alert.type)} · {t(`status.${alert.status}` as "status.active")}
        </p>
      </header>

      {/* The body is the rule's fixed template text, shown verbatim (never generated). */}
      <p className="whitespace-pre-line text-lg">{pick(alert.body_en, alert.body_ur)}</p>

      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
        <dt className="font-semibold">{t("detail.created")}</dt>
        <dd>{formatDateTime(alert.created_at, lang)}</dd>
        {alert.resolved_at && (
          <>
            <dt className="font-semibold">{t("detail.resolved")}</dt>
            <dd>{formatDateTime(alert.resolved_at, lang)}</dd>
          </>
        )}
        <dt className="font-semibold">{t("detail.dedupe")}</dt>
        <dd className="font-mono break-all" dir="ltr">
          {alert.dedupe_key}
        </dd>
      </dl>

      <section className="card space-y-2">
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
      {isAdmin && alert.status === "acknowledged" && <p className="text-sm text-green-800">{t("detail.adminAckDone")}</p>}
    </article>
  );
}

export default function AlertDetailPage() {
  const { t } = useI18n();
  const params = useParams<{ id: string }>();
  const id = Number(params.id);
  const result = useApi(() => (Number.isInteger(id) && id > 0 ? findAlertById(id) : Promise.resolve(null)), [id]);

  return (
    <div className="space-y-4">
      <Link href="/alerts" className="btn-secondary">
        <ArrowLeft className="h-4 w-4 rtl:rotate-180" aria-hidden="true" />
        {t("common.back")}
      </Link>
      {result.error ? (
        <ErrorNotice error={result.error} onRetry={result.reload} />
      ) : result.loading ? (
        <Loading />
      ) : result.data ? (
        <AlertDetail key={result.data.id} initial={result.data} />
      ) : (
        <EmptyState>{t("detail.notFound", { id: params.id })}</EmptyState>
      )}
    </div>
  );
}
