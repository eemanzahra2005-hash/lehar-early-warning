/**
 * The console's only door to the LEHAR FastAPI backend.
 *
 * Why the "waking up" logic exists: the backend runs on Render's free tier,
 * which puts the service to sleep after ~15 minutes idle. The first request
 * after that fails (network error, or a 502/503 from Render's proxy) for the
 * 30-60 s the container needs to boot. Instead of showing a scary error, we
 * retry with backoff for up to WAKE_BUDGET_MS and tell the user what is
 * happening.
 *
 * A 503 is NOT always "asleep": LEHAR itself answers 503 on purpose (e.g.
 * GET /flood/forecast when the model is disabled, or /email/subscribe when
 * email is not configured). Those carry LEHAR's JSON error body
 * ({"error", "detail", "status_code"} from backend/app/middleware.py), so we
 * only treat a 502/503/504 as "waking" when that body is absent.
 *
 * No fake data anywhere: every failure surfaces as an ApiError the page
 * renders honestly.
 */

import type {
  ActiveAlertsResponse,
  AlertHealthSummaryResponse,
  AlertLevelsResponse,
  AlertListResponse,
  AlertResponse,
  AlertStatsResponse,
  DriftResponse,
  EmailSubscribeRequest,
  EmailSubscribeResponse,
  FloodDistrictDetail,
  FloodForecastResponse,
  GlobalExplainResponse,
  LoginRequest,
  MetaResponse,
  ModelListResponse,
  PredictRequest,
  PredictResponse,
  RefreshResponse,
  TelegramLinkResponse,
  TokenResponse,
} from "./types";

export const DEFAULT_API_URL = "http://localhost:8000";
export const API_PREFIX = "/api/v1";
/** How long we keep retrying a sleeping server before giving up. */
export const WAKE_BUDGET_MS = 60_000;
const WAKE_STATUSES = new Set([502, 503, 504]);

export function apiBaseUrl(): string {
  const raw = process.env.NEXT_PUBLIC_API_URL || DEFAULT_API_URL;
  return raw.replace(/\/+$/, "");
}

export type ApiErrorKind = "network" | "http" | "wake_timeout";

export class ApiError extends Error {
  constructor(
    public kind: ApiErrorKind,
    public status: number | null,
    public detail: string,
  ) {
    super(detail);
    this.name = "ApiError";
  }
}

// --- "server waking up" state, shared by every request ------------------------
// A tiny pub/sub instead of a state library: the header banner subscribes,
// and any request that is currently retrying flips it on.

type WakeListener = (waking: boolean) => void;
const wakeListeners = new Set<WakeListener>();
let wakingRequests = 0;

export function onWakeStateChange(listener: WakeListener): () => void {
  wakeListeners.add(listener);
  listener(wakingRequests > 0);
  return () => {
    wakeListeners.delete(listener);
  };
}

function setWaking(delta: number) {
  const before = wakingRequests > 0;
  wakingRequests = Math.max(0, wakingRequests + delta);
  const after = wakingRequests > 0;
  if (before !== after) wakeListeners.forEach((listener) => listener(after));
}

/** Backoff schedule: 1 s, 2 s, 4 s, 8 s, then every 10 s. */
export function backoffDelayMs(attempt: number): number {
  return Math.min(1000 * 2 ** attempt, 10_000);
}

/** Pull a readable message out of LEHAR's error body (string or 422 list). */
export function errorDetail(body: unknown, fallback: string): string {
  if (body && typeof body === "object" && "detail" in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      return detail
        .map((item) => {
          const loc = Array.isArray(item?.loc) ? item.loc.filter((p: unknown) => p !== "body").join(".") : "";
          return loc ? `${loc}: ${item?.msg ?? ""}` : String(item?.msg ?? item);
        })
        .join("; ");
    }
  }
  return fallback;
}

function isLeharErrorBody(body: unknown): boolean {
  return !!body && typeof body === "object" && "error" in body && "detail" in body;
}

async function readBody(response: Response): Promise<unknown> {
  const text = await response.text();
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

export interface RequestOptions {
  fetchImpl?: typeof fetch;
  sleep?: (ms: number) => Promise<void>;
  now?: () => number;
  budgetMs?: number;
}

const defaultSleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

/**
 * fetch + JSON parse, retrying while the server looks asleep.
 * Exported (with injectable fetch/sleep/clock) so the retry rules are unit-tested.
 */
export async function requestJson<T>(url: string, init: RequestInit = {}, options: RequestOptions = {}): Promise<T> {
  const fetchImpl = options.fetchImpl ?? fetch;
  const sleep = options.sleep ?? defaultSleep;
  const now = options.now ?? Date.now;
  const budget = options.budgetMs ?? WAKE_BUDGET_MS;
  const started = now();
  let attempt = 0;
  let markedWaking = false;

  try {
    for (;;) {
      let retryReason: string | null = null;
      try {
        const response = await fetchImpl(url, init);
        const body = await readBody(response);
        if (response.ok) return body as T;
        if (WAKE_STATUSES.has(response.status) && !isLeharErrorBody(body)) {
          retryReason = `HTTP ${response.status}`;
        } else {
          throw new ApiError("http", response.status, errorDetail(body, `HTTP ${response.status}`));
        }
      } catch (error) {
        if (error instanceof ApiError) throw error;
        // fetch() rejects with a TypeError on DNS/connection/CORS failure —
        // exactly what a cold Render container looks like from a browser.
        retryReason = error instanceof Error ? error.message : "network error";
      }

      const elapsed = now() - started;
      const delay = backoffDelayMs(attempt);
      if (elapsed + delay > budget) {
        throw new ApiError("wake_timeout", null, `Server did not respond within ${Math.round(budget / 1000)} s (${retryReason}).`);
      }
      if (!markedWaking) {
        markedWaking = true;
        setWaking(1);
      }
      await sleep(delay);
      attempt += 1;
    }
  } finally {
    if (markedWaking) setWaking(-1);
  }
}

// --- auth token (admin only) ------------------------------------------------------

const TOKEN_KEY = "lehar.console.token";
const REFRESH_KEY = "lehar.console.refresh";
const USER_KEY = "lehar.console.user";

function storage(): Storage | null {
  try {
    return typeof window === "undefined" ? null : window.localStorage;
  } catch {
    return null;
  }
}

export function getToken(): string | null {
  return storage()?.getItem(TOKEN_KEY) ?? null;
}

export function getUsername(): string | null {
  return storage()?.getItem(USER_KEY) ?? null;
}

export function saveSession(token: TokenResponse): void {
  const s = storage();
  s?.setItem(TOKEN_KEY, token.access_token);
  s?.setItem(REFRESH_KEY, token.refresh_token);
  s?.setItem(USER_KEY, token.username);
}

export function clearSession(): void {
  const s = storage();
  s?.removeItem(TOKEN_KEY);
  s?.removeItem(REFRESH_KEY);
  s?.removeItem(USER_KEY);
}

// --- endpoint helpers ------------------------------------------------------------------

function url(path: string, query?: Record<string, string | number | undefined | null>): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value !== undefined && value !== null && value !== "") params.set(key, String(value));
  }
  const qs = params.toString();
  return `${apiBaseUrl()}${API_PREFIX}${path}${qs ? `?${qs}` : ""}`;
}

function get<T>(path: string, query?: Record<string, string | number | undefined | null>): Promise<T> {
  return requestJson<T>(url(path, query), { headers: { Accept: "application/json" } });
}

function post<T>(path: string, body: unknown, headers: Record<string, string> = {}): Promise<T> {
  return requestJson<T>(url(path), {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json", ...headers },
    body: JSON.stringify(body),
  });
}

/** Admin GET with the stored bearer token; refreshes the token once on 401. */
async function adminGet<T>(path: string): Promise<T> {
  const call = (token: string | null) =>
    requestJson<T>(url(path), {
      headers: { Accept: "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    });
  try {
    return await call(getToken());
  } catch (error) {
    const refresh = storage()?.getItem(REFRESH_KEY);
    if (!(error instanceof ApiError) || error.status !== 401 || !refresh) throw error;
    try {
      const renewed = await post<RefreshResponse>("/auth/refresh", { refresh_token: refresh });
      storage()?.setItem(TOKEN_KEY, renewed.access_token);
      return await call(renewed.access_token);
    } catch (refreshError) {
      clearSession();
      throw refreshError;
    }
  }
}

export const api = {
  levels: () => get<AlertLevelsResponse>("/alerts/levels"),
  healthSummary: () => get<AlertHealthSummaryResponse>("/alerts/health-summary"),
  active: () => get<ActiveAlertsResponse>("/alerts/active"),
  alerts: (filters: { district?: string; level?: number | ""; type?: string; status?: string; limit?: number; offset?: number } = {}) =>
    get<AlertListResponse>("/alerts", filters),
  ack: (id: number) => post<AlertResponse>(`/alerts/${id}/ack`, {}),
  stats: () => adminGet<AlertStatsResponse>("/alerts/stats"),
  telegramLink: (district: string) => get<TelegramLinkResponse>("/alerts/telegram/link", { district }),
  emailSubscribe: (body: EmailSubscribeRequest) => post<EmailSubscribeResponse>("/alerts/email/subscribe", body),
  floodForecast: (district: string) => get<FloodForecastResponse>(`/flood/forecast/${encodeURIComponent(district)}`),
  floodDistrict: (district: string) => get<FloodDistrictDetail>(`/flood/district/${encodeURIComponent(district)}`),
  meta: () => get<MetaResponse>("/meta"),
  predict: (body: PredictRequest) => post<PredictResponse>("/predict", body),
  explainGlobal: () => get<GlobalExplainResponse>("/explain/global"),
  login: (body: LoginRequest) => post<TokenResponse>("/auth/login", body),
  models: () => get<ModelListResponse>("/models"),
  drift: () => get<DriftResponse>("/monitoring/drift"),
};

/**
 * There is no GET /alerts/{id} in the API (listed as a backend gap in
 * console/README.md). Until there is, the detail page pages through
 * GET /alerts (newest first) looking for the id, bounded so a missing id can
 * never turn into an unbounded crawl.
 */
export async function findAlertById(id: number, pageSize = 500, maxPages = 10): Promise<AlertResponse | null> {
  for (let page = 0; page < maxPages; page += 1) {
    const result = await api.alerts({ limit: pageSize, offset: page * pageSize });
    const hit = result.alerts.find((alert) => alert.id === id);
    if (hit) return hit;
    // Ids only grow and the list is newest first: once we are past it, stop.
    const oldest = result.alerts[result.alerts.length - 1];
    if (!oldest || oldest.id < id || (page + 1) * pageSize >= result.count) return null;
  }
  return null;
}
