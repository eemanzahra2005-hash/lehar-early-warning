"""
Application configuration.

All configuration is read from environment variables (via a local `.env` file in
`backend/`). Never hard-code secrets or environment-specific values here — add a new
field with a sensible default and document it in `backend/.env.example` instead.
"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/ directory — resolved from this file's location so `.env` is found
# regardless of the working directory the app is launched from.
BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Typed application settings, populated from environment variables / .env."""

    app_name: str = "LEHAR — Level-based Early-warning for Hydrological & Agricultural Risk"
    api_v1_prefix: str = "/api/v1"
    environment: str = "local"
    log_level: str = "INFO"

    # Comma-separated string in the environment, e.g. "http://a.com,http://b.com"
    cors_origins: str = "http://localhost:8000,http://127.0.0.1:8000"

    # --- Split-deployment CORS (LEHAR Phase 1) ---
    # Origins of the SEPARATE frontend(s) that call this API cross-origin —
    # the Next.js Early-Warning Console (LEHAR Phase 5), which runs on
    # localhost:3000 in dev and on a Vercel domain once deployed. Kept as a
    # second variable rather than folded into CORS_ORIGINS above (CLAUDE.md
    # rule 1 — additive): CORS_ORIGINS keeps meaning "origins this repo's
    # own same-host vanilla frontend is served from", and the two are merged
    # (de-duplicated, order preserved) by cors_origins_list below. Set this
    # to the deployed console origin on Render, e.g.
    # "https://lehar-console.vercel.app".
    frontend_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    # --- Memory diagnostics (LEHAR Phase 1) ---
    # True = log this process's resident set size (RSS, in MB) once at
    # startup, so a 512MB-constrained host's deploy log records what the
    # process actually costs at boot instead of leaving it to guesswork
    # (see docs/MEMORY.md). Off by default — it is a diagnostic, not part of
    # normal operation. GET /api/v1/health/deep reports the CURRENT RSS
    # regardless of this flag. Both report a real psutil measurement or
    # null; neither ever estimates a number (CLAUDE.md rule 4).
    log_memory: bool = False

    # --- Auth / JWT (Phase 11) ---
    # Placeholder default for local dev only — every real .env MUST set its own.
    jwt_secret: str = "dev-only-change-me-in-your-.env"
    # Access tokens are short-lived by design (previously 7 days, same as the
    # refresh token below) — a leaked/stolen access token now only works for
    # an hour. Long-lived sessions are carried by the refresh token instead
    # (see JWT_REFRESH_EXPIRE_MINUTES, POST /api/v1/auth/refresh).
    jwt_expire_minutes: int = 60
    jwt_refresh_expire_minutes: int = 10080  # 7 days

    # --- Database ---
    # Relative paths are resolved against the project root (see app/db.py).
    db_path: str = "backend/data/app.db"

    # Full SQLAlchemy connection URL (Phase 9). Empty (default) = build a
    # SQLite URL from db_path above, exactly as every phase before this one
    # did — the zero-setup dev/test default is unchanged. Set to a Postgres
    # URL to opt into the production-style database, e.g.
    # "postgresql+psycopg://user:pass@localhost:5432/smart_irrigation"
    # (psycopg v3 — see backend/requirements.txt for why not psycopg2).
    # When this points at Postgres, Alembic migrations are the source of
    # truth for schema — see docs/DATABASE.md — NOT create_all().
    database_url: str = ""

    # --- ML model ---
    # "latest" follows the registry's "latest" pointer; or pin an exact version string.
    model_version: str = "latest"

    # --- Weather (Open-Meteo, no API key required) ---
    weather_timeout_seconds: float = 8.0
    weather_cache_ttl_seconds: int = 300

    # --- Map overview (GET /api/v1/map/overview) ---
    # How long (seconds) the whole map overview response (all districts) is
    # cached in memory before the next request recomputes it.
    map_overview_ttl_seconds: int = 600

    # --- Flood watch (GET /api/v1/flood/*) ---
    # How long (seconds) the whole flood overview response (all districts'
    # GloFAS river-discharge risk) is cached in memory before the next
    # request recomputes it.
    flood_cache_ttl_seconds: int = 3600

    # --- Flood lead-time model (LEHAR Phase 2.5, GET /api/v1/flood/forecast) ---
    # OFF by default, and it stays off until a model is actually registered
    # under backend/ml/flood_dl/model/ — a fresh checkout has no trained
    # model, and a feature that is not there must report that it is not
    # there, never a fabricated forecast (CLAUDE.md rule 4). Turning this on
    # costs an onnxruntime import and one ~170 KB ONNX session, both of them
    # deferred to the first forecast actually served (CLAUDE.md rule 11 —
    # see app/services/flood_forecast.py).
    flood_dl_enabled: bool = False
    # "latest" follows the flood_dl registry's pointer; or pin an exact
    # version string, exactly like MODEL_VERSION does for the irrigation model.
    flood_dl_model_version: str = "latest"

    # Flood Risk Index component weights — see docs/FLOOD_RISK.md.
    flood_w_discharge: float = 0.30
    flood_w_rain_3day: float = 0.25
    flood_w_rain_intensity: float = 0.15
    flood_w_exposure: float = 0.20
    flood_w_monsoon: float = 0.10

    # --- Farm Risk Score (Phase 6) ---
    # Irrigation-stress (dryness) component weights — see docs/RISK_SCORE.md.
    # Distinct from the Flood Risk Index above, which measures the opposite
    # extreme (too much water).
    risk_w_moisture_deficit: float = 0.35
    risk_w_et0_demand: float = 0.20
    risk_w_heat_stress: float = 0.15
    risk_w_water_scarcity: float = 0.15
    risk_w_rain_relief: float = 0.15

    # --- MLOps: MLflow tracking + quality gate (Phase 7) ---
    # backend/ml/pipeline.py falls back to local file tracking (mlruns/) when
    # this server is unreachable, so training always works fully offline —
    # see docs/MLOPS.md.
    mlflow_tracking_uri: str = "http://127.0.0.1:5000"
    # Quality gate thresholds — pragmatic project defaults, not scientific
    # constants (see docs/MLOPS.md). QG_MAX_MAE is an absolute ceiling;
    # QG_MAE_TOLERANCE is how much worse than the CURRENT production model's
    # MAE a candidate is still allowed to be; QG_MIN_R2 is an absolute floor.
    qg_max_mae: float = 1.0
    qg_mae_tolerance: float = 0.05
    qg_min_r2: float = 0.90

    # --- AI Assistant (Phase 6.5 local-only, upgraded to hybrid in 6.6) ---
    # "hybrid" (default): try the cloud provider first when LLM_CLOUD_API_KEY
    # is set, automatically fall back to local Ollama on ANY cloud error/
    # timeout/rate-limit so the user still gets a reply; behaves exactly like
    # "ollama" when no cloud key is configured. "ollama": local only, never
    # calls the cloud provider. "cloud": cloud only, never falls back to
    # local. "none" disables the assistant entirely (status always reports
    # available=false, chat always 503).
    llm_provider: str = "hybrid"
    ollama_base_url: str = "http://127.0.0.1:11434"
    llm_model: str = "llama3.2:3b"
    # CPU inference is slow — default generously high so a real reply isn't
    # cut off mid-generation on a modest machine.
    llm_timeout_seconds: float = 90.0

    # Cloud LLM — any OpenAI-compatible chat-completions endpoint. Groq's
    # free tier is the reference provider (get a key at console.groq.com).
    # The key is read only from Settings and used solely in an outgoing
    # Authorization header — never logged, never returned by any endpoint.
    llm_cloud_base_url: str = "https://api.groq.com/openai/v1"
    # Groq retired llama-3.3-70b-versatile on 2026-08-16 (see
    # https://console.groq.com/docs/deprecations); openai/gpt-oss-120b is
    # Groq's recommended OpenAI-compatible replacement (see llm.py's
    # reasoning_effort/think-tag handling for this model family).
    llm_cloud_model: str = "openai/gpt-oss-120b"
    llm_cloud_api_key: str = ""  # empty = cloud disabled; hybrid behaves like "ollama"
    llm_cloud_timeout_seconds: float = 20.0

    # --- Data-drift monitoring (Phase 8) ---
    # PSI (Population Stability Index) between the production model's
    # training-time reference distribution (reference_distribution.json,
    # see ml/pipeline.py) and the last DRIFT_WINDOW real prediction inputs
    # logged to prediction_logs — see docs/DRIFT.md. DRIFT_PSI_WARN/ALERT
    # are common industry heuristics (credit-risk-scoring literature), NOT
    # scientifically validated for irrigation/weather data specifically.
    drift_window: int = 200
    drift_min_samples: int = 50
    drift_psi_warn: float = 0.1
    drift_psi_alert: float = 0.25

    # --- Rate limiting (Phase 11) ---
    # Per-client-IP sliding-window limits via slowapi (in-memory, single
    # process — fine for this local-first app). Auth endpoints get the
    # tightest limit (credential stuffing / brute force); assistant chat is
    # limited separately because each call is a real LLM request (cloud
    # cost or slow CPU inference). Disabled automatically during pytest
    # except one dedicated test — see backend/tests/conftest.py and
    # app/rate_limit.py.
    rate_limit_auth_per_minute: int = 5
    rate_limit_predict_per_minute: int = 30
    rate_limit_assistant_per_minute: int = 10
    # LEHAR Phase 4: the public subscription endpoints that are not the
    # subscribe call itself (email verify/unsubscribe links, the Telegram
    # deep-link lookup). Looser than auth — a person may click a link twice,
    # and the console looks up a link per district — but still bounded so
    # none of them can be used to hammer the database.
    rate_limit_subscription_per_minute: int = 20

    # --- Low-memory deployment mode (Phase 13, e.g. Render's free tier —
    # see render.yaml, docs/DEPLOY_RENDER.md) ---
    # False (default) = current behavior: the SHAP explainer is built eagerly
    # at startup (app/main.py's lifespan) so its one-time numba JIT warm-up
    # never delays a user's first prediction. True = skip that eager build;
    # ExplainService is instead constructed lazily on the first request that
    # actually needs it (app/dependencies.py's existing singleton pattern
    # already does this — no other code path changes). Trades a slower
    # first `/predict` call for a smaller memory footprint at boot on a
    # RAM-constrained host. The uvicorn entrypoint (backend/docker-
    # entrypoint.sh) already runs a single worker process with no --workers
    # flag, and explain()/confidence() already degrade to
    # explanation=null/confidence=null on ANY construction or inference
    # failure (Phase 6's never-fabricate contract) — both already hold
    # regardless of this flag, so nothing else needs to change for them.
    low_memory_mode: bool = False

    # Under LOW_MEMORY_MODE only: the SHAP TreeExplainer is skipped entirely
    # (explanation stays null, exactly like any other explainer-construction
    # failure — see app/services/explain.py) when the loaded model has MORE
    # estimators than this. SHAP's per-request cost scales with the number
    # of trees, and the one-time numba JIT warm-up measured ~53MB extra RSS
    # locally for the 120-tree production model (see PROGRESS.md Phase
    # 13.1's diagnosis) — too much to risk on a 512MB host. The compact
    # deployment model trained for LOW_MEMORY_MODE hosts (40 estimators)
    # stays comfortably under this default, so explanations keep working
    # there; a heavier model accidentally pointed at by MODEL_VERSION on a
    # low-memory host degrades to explanation=null instead of risking an
    # OOM kill. Has no effect when LOW_MEMORY_MODE is false (local dev keeps
    # building the real explainer for every model, as before).
    low_memory_shap_max_estimators: int = 60

    # --- Alert engine (LEHAR Phase 2) ---
    # Every threshold below is a DOCUMENTED DEFAULT, not a scientific
    # constant — docs/ALERT_LEVELS.md states each one and where it came
    # from. The rules that use them are pure functions in
    # app/services/alerts/rules.py; nothing else reads these.

    # Shared secret POST /api/v1/alerts/run requires in its
    # X-Alert-Run-Token header. Empty (the default) means the endpoint is
    # NOT configured and refuses every call with 503 — an unauthenticated
    # alert-run endpoint would let anyone drive the whole district sweep.
    # The Phase 6 cron-job.org scheduler sends this header.
    alert_run_token: str = ""
    # An unchanged condition may re-notify at most this often. Escalation to
    # a HIGHER level ignores the cooldown entirely — a farmer must never
    # wait out a cooldown to be told things got worse.
    alert_cooldown_hours: float = 12.0
    # Consecutive clear runs before an active alert resolves and an
    # ALL_CLEAR is emitted. 2 (not 1) so a single failed upstream fetch
    # can't declare a flood over.
    alert_clear_runs_to_resolve: int = 2
    # Days of Open-Meteo daily forecast each run pulls per district — the
    # window HEAVY_RAIN, HEAT_STRESS and IRRIGATION_DUE all read from.
    alert_forecast_days: int = 3

    # FLOOD: levels map from app/services/flood.py's band (LOW/WATCH/HIGH).
    # Within HIGH, a >= 5% rise in forecast river discharge over the next
    # 48 h escalates to level 4, and either an "extreme" Flood Risk Index
    # score or a >= 20-year return period escalates to level 5. GloFAS via
    # Open-Meteo publishes no return period, so ALERT_FLOOD_RETURN_PERIOD_RATIO
    # (forecast peak / 30-day baseline median) is a documented PROXY for
    # that rarity — never presented as a computed return period.
    alert_flood_rising_pct: float = 0.05
    alert_flood_extreme_score: float = 85.0
    alert_flood_return_period_ratio: float = 3.0
    alert_flood_return_period_years: int = 20

    # FLOOD_FORECAST (LEHAR Phase 2.5): the same band mapping applied to the
    # flood lead-time model's PREDICTED discharge 1-3 days ahead. The max
    # level deliberately stops at 3, one rung below the observed FLOOD rule's
    # ceiling — levels 4/5 take over the screen and say "evacuate", and a
    # small model forecasting three days out is not, on its own, evidence for
    # that. See docs/FLOOD_DL.md and app/services/alerts/rules.py.
    alert_flood_forecast_min_level: int = 2
    alert_flood_forecast_max_level: int = 3

    # HEAVY_RAIN: Open-Meteo daily precipitation_sum, mm, wettest single day.
    alert_heavy_rain_l2_mm: float = 30.0
    alert_heavy_rain_l3_mm: float = 80.0

    # HEAT_STRESS: Open-Meteo daily temperature_2m_max, Celsius. Level 2
    # needs the heat SUSTAINED (a single hot day is normal here); level 3
    # does not, because 45 C damages a crop on its own.
    alert_heat_l2_c: float = 40.0
    alert_heat_l3_c: float = 45.0
    alert_heat_consecutive_days: int = 2

    # IRRIGATION_DUE (level 1): fires for a saved field when the model
    # recommends at least the field's own irrigation_threshold_mm (app/db.py's
    # Field; this value is the fallback when the field has none) and less
    # than ALERT_IRRIGATION_DRY_MM of rain is forecast over the next
    # ALERT_IRRIGATION_DRY_DAYS days.
    alert_irrigation_threshold_mm: float = 10.0
    alert_irrigation_dry_mm: float = 1.0
    alert_irrigation_dry_days: int = 3

    # OPS: where the cross-process platform-health breadcrumbs live (a
    # quality-gate FAIL is written by the standalone training pipeline, a
    # rollback by the API) and how long one stays eligible to raise an OPS
    # alert. Relative paths resolve against the project root. The PSI
    # trigger has no threshold of its own — it reuses DRIFT_PSI_ALERT above
    # so the OPS alert and GET /api/v1/monitoring/drift can never disagree.
    alert_ops_events_path: str = "backend/data/ops_events.jsonl"
    alert_ops_event_max_age_hours: float = 24.0

    # --- Alert delivery channels (LEHAR Phase 3) ---
    # Every channel DISABLES ITSELF when its credentials are empty (the
    # default): a matching subscriber then gets an honest "skipped" delivery
    # row naming the missing variable, never a fabricated "sent" and never
    # an error. Nothing here is required to run LEHAR locally (CLAUDE.md
    # rule 5). See docs/ALERTS.md for how to obtain each value.

    # Telegram: the token @BotFather gives you, the bot's @username (without
    # the @, used to build t.me/<bot>?start=<district_code> deep links), and
    # a random secret Telegram echoes back in the
    # X-Telegram-Bot-Api-Secret-Token header on every webhook call — the
    # webhook refuses any request without it.
    telegram_bot_token: str = ""
    telegram_bot_username: str = ""
    telegram_webhook_secret: str = ""

    # Email via Brevo's transactional HTTPS API (never SMTP — Render's free
    # tier blocks outbound SMTP ports). ALERT_FROM_EMAIL must be a sender
    # verified in the Brevo dashboard.
    brevo_api_key: str = ""
    alert_from_email: str = ""
    alert_from_name: str = "LEHAR Alerts"

    # Public https:// origin of THIS API (e.g. https://lehar-api.onrender.com),
    # used to build the email verification/unsubscribe links and the
    # Telegram webhook URL. Email is disabled without it, because every
    # email must carry a working unsubscribe link.
    public_base_url: str = ""

    # Upper bound on Telegram + email sends in ONE alert run (re-sends
    # included), to stay inside the providers' free tiers (Brevo: 300
    # emails/day). Sends past the cap are recorded as deferred and retried
    # on the next run, highest level first.
    alert_max_sends_per_run: int = 200

    # LEHAR Phase 4: how long GET /api/v1/alerts/health-summary (the public
    # console banner) reuses one computed answer. Every console page load
    # hits it, so without a cache each visitor would be a database query —
    # and on Neon's free tier every query keeps the compute awake.
    alert_health_summary_ttl_seconds: int = 60

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def cors_origins_list(self) -> list[str]:
        """Every allowed CORS origin: CORS_ORIGINS (this repo's own frontend)
        plus FRONTEND_ORIGINS (the separate console — LEHAR Phase 1), merged
        and de-duplicated with first-seen order preserved. Parsing both the
        same way means a deployment can set either, or both, and neither
        silently overrides the other."""
        merged: list[str] = []
        for raw in (self.cors_origins, self.frontend_origins):
            for origin in raw.split(","):
                cleaned = origin.strip()
                if cleaned and cleaned not in merged:
                    merged.append(cleaned)
        return merged


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance (env is read once per process)."""
    return Settings()
