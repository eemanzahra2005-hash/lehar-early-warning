"""Shared Pydantic request/response schemas."""

from datetime import date as date_cls
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class HealthResponse(BaseModel):
    """Response body for GET /api/v1/health."""

    status: str
    app: str
    version: str
    environment: str
    # Latest trained model version from backend/ml/model/registry.json, or
    # None if no model has been trained yet (never crashes when absent).
    model_version: str | None = None


class DeepHealthCheck(BaseModel):
    """One dependency's result inside DeepHealthResponse.checks."""

    status: str  # "ok" | "error" | "unavailable"
    detail: str | None = None


class DeepHealthResponse(BaseModel):
    """Response body for GET /api/v1/health/deep (LEHAR Phase 1).

    The *diagnostic* counterpart to GET /api/v1/health: it actually touches
    the database and resolves the model, so it is deliberately NOT the
    endpoint an uptime pinger should hit (see app/routers/health.py).
    """

    status: str  # "ok" when every check passed, "degraded" otherwise
    app: str
    version: str
    environment: str
    model_version: str | None = None
    # Real psutil resident-set-size reading in MB, or null when it could not
    # be measured — never an estimate (CLAUDE.md rule 4, app/services/memory.py).
    rss_mb: float | None = None
    checks: dict[str, DeepHealthCheck]


class MetaResponse(BaseModel):
    """Response body for GET /api/v1/meta."""

    crops: list[str]
    districts: list[str]
    districts_by_province: dict[str, list[str]]
    note: str


class ErrorResponse(BaseModel):
    """Uniform JSON error body returned by error handlers in middleware.py.

    `detail` is a string for most errors, or a list of field errors for
    request validation failures (FastAPI's RequestValidationError.errors()).
    """

    error: str
    detail: Any
    status_code: int


# --- Auth -------------------------------------------------------------

class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=6, max_length=128)
    # Plain optional string (not EmailStr) — email-validator isn't a pinned
    # dependency, and this field is informational only, not verified.
    email: str | None = None


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    username: str


class RefreshRequest(BaseModel):
    refresh_token: str


class RefreshResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str


# --- Fields -------------------------------------------------------------

class FieldCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    district: str
    crop_type: str
    default_soil_moisture_pct: float | None = Field(default=None, ge=0, le=100)
    default_canal_flow_cusecs: float | None = Field(default=None, ge=0, le=2000)
    # LEHAR Phase 2 (optional, additive): this field's own IRRIGATION_DUE
    # trigger in mm. Omitted/null keeps the previous behaviour and falls
    # back to ALERT_IRRIGATION_THRESHOLD_MM. Bounds mirror
    # ActualObservationRequest's mm range.
    irrigation_threshold_mm: float | None = Field(default=None, ge=0, le=200)


class FieldResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    district: str
    crop_type: str
    default_soil_moisture_pct: float | None
    default_canal_flow_cusecs: float | None
    # Null for every field saved before LEHAR Phase 2 — the alert rule falls
    # back to ALERT_IRRIGATION_THRESHOLD_MM for those.
    irrigation_threshold_mm: float | None = None
    created_at: datetime


# --- Weather -------------------------------------------------------------

class WeatherResponse(BaseModel):
    district: str
    temperature_c: float
    humidity_pct: float
    rainfall_mm: float
    evapotranspiration_mm: float
    source: str = "open-meteo"


class ForecastDay(BaseModel):
    date: str
    temperature_c: float
    # Open-Meteo has no daily relative-humidity aggregate; it's derived from
    # hourly values and may be unavailable for some days.
    humidity_pct: float | None
    rainfall_mm: float
    evapotranspiration_mm: float
    # Only populated when GET /forecast is called with include_demand=true.
    # An ML estimate of irrigation demand for that day, assuming soil
    # moisture stays fixed at soil_moisture_pct (default 25%) — never a
    # measurement, always clearly a model projection.
    irrigation_estimate_mm: float | None = None


class ForecastResponse(BaseModel):
    district: str
    days: list[ForecastDay]
    # Only set when include_demand=true was requested.
    demand_note: str | None = None


# --- Explainability (Phase 6) ----------------------------------------------

class ContributionItem(BaseModel):
    feature: str
    value: Any
    contribution_mm: float
    direction: str  # "increases" | "decreases"


class Explanation(BaseModel):
    base_value_mm: float
    contributions: list[ContributionItem]
    top_factors: list[str]


class ConfidenceInterval(BaseModel):
    # "Model agreement interval" across the RandomForest's individual trees'
    # predictions for this row — NOT a calibrated statistical probability.
    tree_std_mm: float
    interval_mm: list[float]  # [p10, p90]


class GlobalExplainResponse(BaseModel):
    available: bool
    model_version: str | None = None
    sample_size: int | None = None
    mean_abs_shap_mm: dict[str, float] | None = None
    note: str


# --- Farm Risk Score (Phase 6) ----------------------------------------------

class RiskScore(BaseModel):
    score: float
    band: str  # "LOW" | "MODERATE" | "HIGH"
    components: dict[str, float]


# --- Predict -------------------------------------------------------------
#
# Physical bounds (Phase 8) match backend/ml/validation.py's training-data
# schema exactly — see docs/DATA_VALIDATION.md for the reasoning behind
# each range. Pydantic's Field(ge=, le=) rejects impossible values (e.g.
# temperature_c=80) with a 422 whose message names the field and the
# violated bound — never silently accepted or clamped.

class PredictRequest(BaseModel):
    district: str
    crop_type: str
    soil_moisture_pct: float = Field(ge=0, le=100, description="Soil moisture, percent (0-100).")
    canal_flow_cusecs: float = Field(ge=0, le=2000, description="Canal flow, cusecs (0-2000).")
    use_live_weather: bool
    manual_temperature_c: float | None = Field(
        default=None, ge=-10, le=55, description="Air temperature, Celsius (-10 to 55)."
    )
    manual_humidity_pct: float | None = Field(
        default=None, ge=0, le=100, description="Relative humidity, percent (0-100)."
    )
    manual_rainfall_mm: float | None = Field(
        default=None, ge=0, le=400, description="Rainfall, millimeters (0-400)."
    )
    manual_evapotranspiration_mm: float | None = Field(
        default=None, ge=0, le=20, description="Reference evapotranspiration (ET0), millimeters (0-20)."
    )
    simulate_sensor_fault: bool = False
    field_id: int | None = None
    # Phase 16 (additive, default off): use Open-Meteo's live, model-estimated
    # soil moisture instead of soil_moisture_pct. soil_moisture_pct stays
    # required either way — it is the manual fallback whenever the live fetch
    # fails, so a prediction is never blocked (see docs/SOIL_MOISTURE.md).
    use_live_soil: bool = False


class WeatherUsed(BaseModel):
    temperature_c: float
    humidity_pct: float
    rainfall_mm: float
    evapotranspiration_mm: float
    source: str  # "open-meteo" | "manual"


class SoilMoistureLayers(BaseModel):
    """Raw Open-Meteo values behind a live soil moisture value (Phase 16),
    exposed for transparency — see docs/SOIL_MOISTURE.md."""

    soil_moisture_1_to_3cm: float
    soil_moisture_3_to_9cm: float
    soil_moisture_9_to_27cm: float
    # Thickness-weighted mean of the three layers (2/6/18 cm), same unit.
    root_zone: float
    unit: str  # "m³/m³"
    # The hour these values are for, in the district's local time.
    observed_at: str


class SoilMoistureResponse(BaseModel):
    """GET /api/v1/soil-moisture — a model estimate, never a field sensor reading."""

    district: str
    soil_moisture_pct: float
    source: str  # always "live (Open-Meteo model estimate)"
    label: str
    layers: SoilMoistureLayers


class PredictResponse(BaseModel):
    irrigation_recommendation_mm: float
    source: str  # "model_prediction" | "fallback_rule_based" | "rule_flood_override"
    model_version: str | None
    weather_used: WeatherUsed
    inputs_used: dict[str, Any]
    model_metrics: dict[str, Any] | None
    reason: str | None = None
    # Only set when source == "rule_flood_override" (see docs/FLOOD_RISK.md):
    # the model's original, un-overridden recommendation, preserved so the
    # override is transparent rather than silently discarding information.
    model_raw_mm: float | None = None
    # Phase 6 — all three are null-safe: never fabricated, never break the
    # response if unavailable (see app/services/explain.py, risk.py).
    explanation: Explanation | None = None
    confidence: ConfidenceInterval | None = None
    risk: RiskScore | None = None
    # Phase 16 — the soil moisture the model, risk score, and fallback rule
    # actually used, and where it came from. Always set by POST /predict;
    # defaulted here only so the response model stays backward compatible.
    soil_moisture_used: float | None = None
    soil_moisture_source: str | None = None  # "live (Open-Meteo model estimate)" | "manual"
    # Only set when soil_moisture_source is live.
    soil_moisture_layers: SoilMoistureLayers | None = None
    # Only set when use_live_soil was requested but the live fetch failed and
    # the manual value was used instead — says so rather than hiding it.
    soil_moisture_note: str | None = None


# --- History -------------------------------------------------------------

class ActualObservationResponse(BaseModel):
    """A real-world irrigation outcome recorded against one prediction
    (Phase 10 — see app/db.py's ActualObservation, POST
    /api/v1/history/{id}/actual)."""

    model_config = ConfigDict(from_attributes=True)

    actual_irrigation_mm: float
    observed_at: datetime
    note: str | None = None


class PredictionLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    field_id: int | None
    district: str
    crop_type: str
    soil_moisture_pct: float
    canal_flow_cusecs: float
    temperature_c: float
    humidity_pct: float
    rainfall_mm: float
    evapotranspiration_mm: float
    recommendation_mm: float
    source: str
    model_version: str | None
    risk_score: float | None = None
    risk_band: str | None = None
    created_at: datetime
    # None until the user records a real outcome (Phase 10) — never a
    # fabricated/estimated value.
    actual: ActualObservationResponse | None = None


class ActualObservationRequest(BaseModel):
    """Request body for POST /api/v1/history/{id}/actual. Bounds mirror
    irrigation_recommendation_mm's realistic physical range (see
    docs/DATA_VALIDATION.md's rationale for similar mm-valued fields) —
    generous enough for a real single-application depth, tight enough to
    catch an obvious typo (e.g. an extra digit)."""

    actual_irrigation_mm: float = Field(ge=0, le=200, description="Actual irrigation applied, millimeters (0-200).")
    note: str | None = Field(default=None, max_length=500)


# --- Model introspection --------------------------------------------------

class FeatureImportanceResponse(BaseModel):
    model_version: str
    feature_importance: dict[str, float]


class ModelInfoResponse(BaseModel):
    """Model card data for the Explainability page — version, real training
    metrics, training date, dataset size, and the feature list, all read
    straight from the registry/metrics.json (never fabricated)."""

    version: str
    created_at: str | None = None
    metrics: dict[str, Any]
    feature_list: list[str]
    dataset_rows: int


# --- MLOps: model registry / promote / rollback (Phase 7) -------------------

class ModelVersionSummary(BaseModel):
    version: str
    created_at: str | None = None
    metrics: dict[str, Any]
    # "pipeline" (trained via ml/pipeline.py, has gate/mlflow metadata) or
    # "legacy" (trained before Phase 7 — promotable all the same).
    source: str
    is_production: bool
    gate: dict[str, Any] | None = None
    mlflow_run_id: str | None = None
    mlflow_model_version: str | None = None


class ModelListResponse(BaseModel):
    latest: str | None
    versions: list[ModelVersionSummary]
    # Ordered stack of previously-production versions, most-recently-demoted
    # first — rollback always promotes history[0].
    history: list[str]
    mlflow_url: str


class PromoteResponse(BaseModel):
    version: str
    latest: str
    history: list[str]
    message: str


# --- Map overview ----------------------------------------------------------

class MapWeatherSummary(BaseModel):
    temperature_c: float
    humidity_pct: float
    rainfall_mm: float
    evapotranspiration_mm: float


class MapDistrictOverview(BaseModel):
    district: str
    province: str
    weather: MapWeatherSummary | None
    recommendation_mm: float | None
    # "ok" | "unavailable" (weather provider failed for this district — the
    # rest of the map overview still succeeds; see MapOverviewService).
    status: str
    # Irrigation-stress (dryness) Farm Risk Score computed on the same
    # default field conditions as recommendation_mm — see docs/RISK_SCORE.md.
    risk: RiskScore | None = None


class MapOverviewResponse(BaseModel):
    generated_at: datetime
    ttl_seconds: int
    default_conditions: dict[str, Any]
    note: str
    districts: list[MapDistrictOverview]


# --- Compare -----------------------------------------------------------

class CompareRequest(BaseModel):
    districts: list[str] = Field(min_length=2, max_length=6)
    crop_type: str
    soil_moisture_pct: float = Field(ge=0, le=100)
    canal_flow_cusecs: float = Field(ge=0, le=2000)


class CompareDistrictResult(BaseModel):
    district: str
    weather: WeatherUsed | None = None
    recommendation_mm: float | None = None
    model_version: str | None = None
    error: str | None = None
    risk: RiskScore | None = None


class CompareResponse(BaseModel):
    crop_type: str
    soil_moisture_pct: float
    canal_flow_cusecs: float
    results: list[CompareDistrictResult]


# --- Flood watch (Phase 5.5) -----------------------------------------------

class FloodDistrictOverview(BaseModel):
    district: str
    province: str
    status: str  # "ok" | "unavailable"
    score: float | None = None
    band: str | None = None  # "LOW" | "WATCH" | "HIGH"
    components: dict[str, float] | None = None
    anomaly_ratio: float | None = None
    rain_3day_mm: float | None = None


class FloodOverviewResponse(BaseModel):
    generated_at: datetime
    ttl_seconds: int
    weights: dict[str, float]
    bands: dict[str, float]
    disclaimer: str
    districts: list[FloodDistrictOverview]


class FloodDischargeSeries(BaseModel):
    unit: str
    dates: list[str]
    values: list[float]
    baseline_median: float
    forecast_max: float
    anomaly_ratio: float


class FloodRainSeries(BaseModel):
    dates: list[str]
    values_mm: list[float]
    cumulative_3day_mm: float
    max_day_mm: float


class FloodDistrictDetail(BaseModel):
    district: str
    province: str
    status: str  # "ok" | "unavailable"
    score: float | None = None
    band: str | None = None
    components: dict[str, float] | None = None
    discharge: FloodDischargeSeries | None = None
    rain: FloodRainSeries | None = None
    disclaimer: str


# --- Flood lead-time forecast (LEHAR Phase 2.5) ------------------------------


class FloodForecastObserved(BaseModel):
    """The 14 observed days the model read to make its prediction."""

    unit: str
    dates: list[str]
    values: list[float]
    baseline_median: float


class FloodForecastPredicted(BaseModel):
    """What the model says the river will do at D+1, D+2 and D+3."""

    unit: str
    dates: list[str]
    values: list[float]
    peak: float
    anomaly_ratio: float


class FloodForecastResponse(BaseModel):
    district: str
    province: str
    status: str
    model_version: str
    issued_for_date: str
    lead_time_hours: int
    horizons_days: list[int]
    observed: FloodForecastObserved
    predicted: FloodForecastPredicted
    rain_forecast_mm: list[float]
    score: float
    band: str
    components: dict[str, float]
    # None when the predicted band is LOW: level 1 is the calm default and is
    # computed rather than stored (see app/services/alerts/engine.py).
    level: int | None = None
    alert_type: str | None = None
    reason: str
    generated_at: datetime
    # Both carried on every response rather than left to the docs: this model
    # is the one trained on REAL data (CLAUDE.md rule 13), and Open-Meteo and
    # GloFAS both require attribution.
    training_data: str
    attribution: str
    disclaimer: str


# --- Data-drift monitoring (Phase 8) ----------------------------------------

class DriftHistogram(BaseModel):
    # Numeric feature: 21 bin-edge floats (20 bins). Categorical feature:
    # sorted category label strings, one per "bin".
    edges: list[Any]
    counts: list[int]


class DriftFeature(BaseModel):
    name: str
    psi: float
    band: str  # "stable" | "warning" | "significant_drift"
    reference_hist: DriftHistogram
    current_hist: DriftHistogram


class DriftResponse(BaseModel):
    status: str  # "stable" | "warning" | "significant_drift" | "insufficient_data"
    window_used: int
    samples_available: int
    reference_model_version: str | None
    # Real, currently-configured DRIFT_PSI_WARN/DRIFT_PSI_ALERT — so the UI's
    # threshold lines always reflect the actual config, never a hardcoded guess.
    psi_warn: float
    psi_alert: float
    features: list[DriftFeature]


# --- Model performance (Phase 10) -------------------------------------------
#
# Computed ONLY from real recorded pairs (prediction_logs joined to
# actual_observations, see app/services/performance.py) — never fabricated
# or estimated. status="no_actuals_recorded" until at least one exists.

class PerformancePoint(BaseModel):
    date: date_cls
    # actual_irrigation_mm - recommendation_mm for one recorded pair, mm.
    # Signed (not absolute): positive means the model under-recommended
    # relative to what was actually applied, negative means it over-recommended.
    error: float


class PerformanceResponse(BaseModel):
    status: str  # "ok" | "no_actuals_recorded"
    count: int
    rolling_mae: float | None = None
    rolling_rmse: float | None = None
    series: list[PerformancePoint] = Field(default_factory=list)


# --- AI Assistant (Phase 6.5 local-only, hybrid cloud+local in Phase 6.6) ---

class ProviderStatus(BaseModel):
    available: bool
    model: str


class AssistantStatusResponse(BaseModel):
    mode: str  # configured LLM_PROVIDER: "hybrid" | "ollama" | "cloud" | "none"
    available: bool  # whether the assistant can respond right now, given `mode`
    cloud: ProviderStatus
    local: ProviderStatus


class AssistantChatTurn(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    content: str


class AssistantChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    district: str | None = None
    # Last N turns of prior conversation (oldest first); the router keeps
    # only the most recent 6 regardless of how many are sent.
    history: list[AssistantChatTurn] | None = None
    # Optional: the exact POST /predict response JSON already shown to the
    # user (see the Predict page's "Explain in Urdu" button). Merged into
    # CONTEXT verbatim as "this_prediction" — real data the user is already
    # looking at, not re-derived from prediction_logs, so it also works for
    # anonymous (not-logged-in) predictions that were never saved to history.
    prediction_context: dict[str, Any] | None = None
    # Optional client preference (Settings > AI Assistant), honored only if
    # that provider is actually available right now — see
    # app/services/llm.py's LLMService._resolve_effective_provider.
    provider: str | None = Field(default=None, pattern="^(hybrid|local|cloud)$")


class AssistantChatResponse(BaseModel):
    reply: str
    # Which provider actually produced this reply ("cloud" | "local") and
    # its model name — may differ from the client's `provider` preference
    # above (e.g. hybrid falling back, or an unavailable override ignored).
    provider_used: str
    model: str
    # The exact CONTEXT JSON handed to the LLM — surfaced so the UI can show
    # a "Data used" card, and so this is auditable rather than a black box.
    context_used: dict[str, Any]


# --- Alert engine (LEHAR Phase 2) -------------------------------------------
#
# See app/services/alerts/ and docs/ALERT_LEVELS.md. Every alert body
# already ends with the mandated research-advisory disclaimer; it is ALSO
# returned as its own field on every alert-bearing response so a client can
# render it as a persistent footer without parsing the body (CLAUDE.md
# rule 12).


class AlertLevelInfo(BaseModel):
    """One level's metadata, served verbatim from
    app/services/alerts/levels.py — the single source of truth."""

    number: int  # 0 = OPS (admin only), 1-5 = farmer-facing
    key: str  # "OPS" | "L1" ... "L5"
    color_hex: str
    text_color_hex: str
    name_en: str
    name_ur: str
    audience: str  # "farmer" | "admin"
    summary_en: str
    summary_ur: str
    channels: list[str]  # "in_app" | "telegram" | "email"
    full_screen_takeover: bool
    actions_en: list[str]
    actions_ur: list[str]
    disclaimer_en: str
    disclaimer_ur: str


class AlertLevelsResponse(BaseModel):
    levels: list[AlertLevelInfo]
    disclaimer: str
    note: str


class AlertResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    district_code: str
    type: str  # FLOOD | HEAVY_RAIN | HEAT_STRESS | IRRIGATION_DUE | OPS | ALL_CLEAR
    level: int
    title_en: str
    title_ur: str
    body_en: str
    body_ur: str
    # The values, thresholds, source timestamps and reason the rule fired
    # on — enough to re-derive the level by hand years later.
    payload: dict[str, Any]
    status: str  # active | acknowledged | resolved
    dedupe_key: str
    created_at: datetime
    resolved_at: datetime | None = None


class AlertListResponse(BaseModel):
    count: int
    alerts: list[AlertResponse]
    disclaimer: str


class ActiveAlertSummary(BaseModel):
    """One district's current level — the map choropleth / banner shape.

    Two kinds of row, told apart by `source`:
      "alert"   — the district's highest ACTIVE alert; every field is set.
      "default" — no active alert, so level 1 (white) is COMPUTED, not
                  stored. `type`, `alert_id` and `created_at` are null
                  because there is no alert row behind it.
    OPS notices are never included in either kind.
    """

    district: str
    level: int
    source: str  # "alert" | "default"
    type: str | None = None
    alert_id: int | None = None
    title_en: str
    title_ur: str
    created_at: datetime | None = None


class ActiveAlertsResponse(BaseModel):
    generated_at: datetime
    # Rows returned — every known district, calm ones included.
    count: int
    # How many of those are backed by a real active alert row. The number
    # the banner cares about; count - alerting_count districts are calm.
    alerting_count: int
    # The computed level reported for a district with no active alert.
    default_level: int
    districts: list[ActiveAlertSummary]
    disclaimer: str


class AlertSuppressionSummary(BaseModel):
    district_code: str
    type: str
    level: int
    reason: str  # "duplicate" | "cooldown"


class AlertRunResponse(BaseModel):
    """What POST /api/v1/alerts/run reports back. Suppressions are listed,
    not just counted, so a scheduled run is auditable from its response
    alone."""

    run_id: int | None
    trigger: str  # "cron" | "manual"
    started_at: datetime
    finished_at: datetime
    districts_checked: int
    alerts_raised: int
    alerts_suppressed: int
    alerts_resolved: int
    raised_alert_ids: list[int]
    all_clear_alert_ids: list[int]
    suppressed: list[AlertSuppressionSummary]
    disclaimer: str


class AlertStatsResponse(BaseModel):
    """Admin counters for the console (JWT required). Every number is a
    real COUNT(*) over the alert tables — nothing estimated."""

    total_alerts: int
    active_alerts: int
    acknowledged_alerts: int
    resolved_alerts: int
    by_level: dict[str, int]
    by_type: dict[str, int]
    by_status: dict[str, int]
    deliveries_by_status: dict[str, int]
    subscriptions: int
    total_runs: int
    last_run: AlertRunResponse | None = None
    disclaimer: str


# --- LEHAR Phase 3: alert delivery channels ---------------------------------

class EmailSubscribeRequest(BaseModel):
    """POST /api/v1/alerts/email/subscribe. Nothing is sent to this address
    except a verification email until its owner clicks the link in it."""

    # A plain pattern rather than EmailStr — email-validator is not a pinned
    # dependency (see RegisterRequest above). Brevo rejects anything that is
    # not deliverable anyway; this only stops obvious typos early.
    email: str = Field(max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    # District codes ("dera_ghazi_khan") or names ("Dera Ghazi Khan").
    districts: list[str] = Field(min_length=1, max_length=107)
    # Level 1 is in-app only, so an email subscription starts at 2.
    min_level: int = Field(default=2, ge=2, le=5)
    language: str = Field(default="en", pattern="^(en|ur)$")


class EmailSubscribeResponse(BaseModel):
    status: str
    detail: str
    disclaimer: str


class TelegramWebhookResponse(BaseModel):
    ok: bool
    handled: str
