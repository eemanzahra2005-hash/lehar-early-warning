/**
 * TypeScript mirrors of the FastAPI response/request models in
 * backend/app/schemas.py. Only the models the console actually uses are
 * mirrored; field names and optionality follow schemas.py exactly so a
 * backend change shows up here as a type error rather than a silent `undefined`.
 */

// --- Alert engine (schemas.py: "Alert engine (LEHAR Phase 2)") -------------

export interface AlertLevelInfo {
  number: number; // 0 = OPS (admin only), 1-5 = farmer-facing
  key: string; // "OPS" | "L1" ... "L5"
  color_hex: string;
  text_color_hex: string;
  name_en: string;
  name_ur: string;
  audience: string; // "farmer" | "admin"
  summary_en: string;
  summary_ur: string;
  channels: string[];
  full_screen_takeover: boolean;
  actions_en: string[];
  actions_ur: string[];
  disclaimer_en: string;
  disclaimer_ur: string;
}

export interface AlertLevelsResponse {
  levels: AlertLevelInfo[];
  disclaimer: string;
  note: string;
}

export type AlertType =
  | "FLOOD"
  | "FLOOD_FORECAST"
  | "HEAVY_RAIN"
  | "HEAT_STRESS"
  | "IRRIGATION_DUE"
  | "OPS"
  | "ALL_CLEAR";

export const ALERT_TYPES: AlertType[] = [
  "FLOOD",
  "FLOOD_FORECAST",
  "HEAVY_RAIN",
  "HEAT_STRESS",
  "IRRIGATION_DUE",
  "OPS",
  "ALL_CLEAR",
];

export type AlertStatus = "active" | "acknowledged" | "resolved";
export const ALERT_STATUSES: AlertStatus[] = ["active", "acknowledged", "resolved"];

export interface AlertResponse {
  id: number;
  district_code: string;
  type: string;
  level: number;
  title_en: string;
  title_ur: string;
  body_en: string;
  body_ur: string;
  payload: Record<string, unknown>;
  status: string;
  dedupe_key: string;
  created_at: string;
  resolved_at: string | null;
}

export interface AlertListResponse {
  count: number;
  alerts: AlertResponse[];
  disclaimer: string;
}

export interface ActiveAlertSummary {
  district: string;
  level: number;
  source: "alert" | "default" | string;
  type: string | null;
  alert_id: number | null;
  title_en: string;
  title_ur: string;
  created_at: string | null;
}

export interface ActiveAlertsResponse {
  generated_at: string;
  count: number;
  alerting_count: number;
  default_level: number;
  districts: ActiveAlertSummary[];
  disclaimer: string;
}

export interface AlertHealthSummaryResponse {
  generated_at: string;
  highest_level: number;
  highest_level_key: string;
  highest_level_name_en: string;
  highest_level_name_ur: string;
  highest_level_color_hex: string;
  highest_level_text_color_hex: string;
  counts_by_level: Record<string, number>;
  total_districts: number;
  alerting_districts: number;
  cached: boolean;
  cache_ttl_seconds: number;
  disclaimer: string;
  disclaimer_ur: string;
}

export interface AlertRunResponse {
  run_id: number | null;
  trigger: string;
  started_at: string;
  finished_at: string;
  districts_checked: number;
  alerts_raised: number;
  alerts_suppressed: number;
  alerts_resolved: number;
  raised_alert_ids: number[];
  all_clear_alert_ids: number[];
  suppressed: { district_code: string; type: string; level: number; reason: string }[];
  disclaimer: string;
  duration_seconds: number | null;
}

export interface DeliveryLatencySummary {
  sample_size: number;
  median_ms: number;
  p95_ms: number;
}

export interface AlertStatsResponse {
  total_alerts: number;
  active_alerts: number;
  acknowledged_alerts: number;
  resolved_alerts: number;
  by_level: Record<string, number>;
  by_type: Record<string, number>;
  by_status: Record<string, number>;
  deliveries_by_status: Record<string, number>;
  subscriptions: number;
  total_runs: number;
  last_run: AlertRunResponse | null;
  disclaimer: string;
  raised_by_type_and_level: Record<string, Record<string, number>>;
  resolved_by_type_and_level: Record<string, Record<string, number>>;
  suppressed_total: number;
  suppressed_by_type_and_level: Record<string, Record<string, number>>;
  suppressed_breakdown_scope: string;
  deliveries_by_channel: Record<string, Record<string, number>>;
  delivery_latency: Record<string, DeliveryLatencySummary>;
  active_subscriptions: number;
  active_subscriptions_by_channel: Record<string, number>;
}

// --- Subscriptions (Phase 3/4) ---------------------------------------------

export interface EmailSubscribeRequest {
  email: string;
  districts: string[];
  min_level: number; // 2-5
  language: "en" | "ur";
}

export interface EmailSubscribeResponse {
  status: string;
  detail: string;
  disclaimer: string;
  message_en: string;
  message_ur: string;
  disclaimer_ur: string;
}

export interface TelegramLinkResponse {
  district: string;
  district_code: string;
  url: string;
  bot_username: string;
  start_command: string;
  instructions_en: string;
  instructions_ur: string;
  disclaimer: string;
  disclaimer_ur: string;
}

// --- Flood ------------------------------------------------------------------

export interface FloodDischargeSeries {
  unit: string;
  dates: string[];
  values: number[];
  baseline_median: number;
  forecast_max: number;
  anomaly_ratio: number;
}

export interface FloodDistrictDetail {
  district: string;
  province: string;
  status: string;
  score: number | null;
  band: string | null;
  components: Record<string, number> | null;
  discharge: FloodDischargeSeries | null;
  rain: { dates: string[]; values_mm: number[]; cumulative_3day_mm: number; max_day_mm: number } | null;
  disclaimer: string;
}

export interface FloodForecastResponse {
  district: string;
  province: string;
  status: string;
  model_version: string;
  issued_for_date: string;
  lead_time_hours: number;
  horizons_days: number[];
  observed: { unit: string; dates: string[]; values: number[]; baseline_median: number };
  predicted: { unit: string; dates: string[]; values: number[]; peak: number; anomaly_ratio: number };
  rain_forecast_mm: number[];
  score: number;
  band: string;
  components: Record<string, number>;
  level: number | null;
  alert_type: string | null;
  reason: string;
  generated_at: string;
  training_data: string;
  attribution: string;
  disclaimer: string;
}

// --- Meta / auth ------------------------------------------------------------

export interface MetaResponse {
  crops: string[];
  districts: string[];
  districts_by_province: Record<string, string[]>;
  note: string;
}

export interface LoginRequest {
  username: string;
  password: string;
}

export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  username: string;
}

export interface RefreshResponse {
  access_token: string;
  token_type: string;
  username: string;
}

// --- Predict / explain --------------------------------------------------------

export interface PredictRequest {
  district: string;
  crop_type: string;
  soil_moisture_pct: number;
  canal_flow_cusecs: number;
  use_live_weather: boolean;
  manual_temperature_c?: number | null;
  manual_humidity_pct?: number | null;
  manual_rainfall_mm?: number | null;
  manual_evapotranspiration_mm?: number | null;
  simulate_sensor_fault?: boolean;
  use_live_soil?: boolean;
}

export interface ContributionItem {
  feature: string;
  value: unknown;
  contribution_mm: number;
  direction: "increases" | "decreases" | string;
}

export interface PredictResponse {
  irrigation_recommendation_mm: number;
  source: string;
  model_version: string | null;
  weather_used: {
    temperature_c: number;
    humidity_pct: number;
    rainfall_mm: number;
    evapotranspiration_mm: number;
    source: string;
  };
  inputs_used: Record<string, unknown>;
  model_metrics: Record<string, unknown> | null;
  reason: string | null;
  model_raw_mm: number | null;
  explanation: { base_value_mm: number; contributions: ContributionItem[]; top_factors: string[] } | null;
  confidence: { tree_std_mm: number; interval_mm: number[] } | null;
  risk: { score: number; band: string; components: Record<string, number> } | null;
  soil_moisture_used: number | null;
  soil_moisture_source: string | null;
  soil_moisture_note: string | null;
}

export interface GlobalExplainResponse {
  available: boolean;
  model_version: string | null;
  sample_size: number | null;
  mean_abs_shap_mm: Record<string, number> | null;
  note: string;
}

// --- Models / monitoring (admin summary) -------------------------------------

export interface ModelVersionSummary {
  version: string;
  created_at: string | null;
  metrics: Record<string, unknown>;
  source: string;
  is_production: boolean;
  gate: Record<string, unknown> | null;
}

export interface ModelListResponse {
  latest: string | null;
  versions: ModelVersionSummary[];
  history: string[];
  mlflow_url: string;
}

export interface DriftResponse {
  status: string;
  window_used: number;
  samples_available: number;
  reference_model_version: string | null;
  psi_warn: number;
  psi_alert: number;
  features: { name: string; psi: number; band: string }[];
}

/** Uniform error body from backend/app/middleware.py. */
export interface ErrorResponse {
  error: string;
  detail: unknown;
  status_code: number;
}
