import type { Lang } from "@/i18n/dictionary";

/** Local date-time in the reader's language; "—" for missing values. */
export function formatDateTime(iso: string | null | undefined, lang: Lang): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString(lang === "ur" ? "ur-PK" : "en-PK", { dateStyle: "medium", timeStyle: "short" });
}

export function formatNumber(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return value.toFixed(digits);
}

/** FLOOD_FORECAST -> "Flood forecast" (alert types are shown as-is in both languages). */
export function humanType(type: string | null | undefined): string {
  if (!type) return "—";
  const lower = type.toLowerCase().replace(/_/g, " ");
  return lower.charAt(0).toUpperCase() + lower.slice(1);
}
