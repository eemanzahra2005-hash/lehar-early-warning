"""Custom Prometheus metrics (Phase 10).

Exposed at GET /metrics alongside prometheus-fastapi-instrumentator's
automatic per-request HTTP metrics (wired in app/main.py). Every metric
here is incremented ONLY from real code paths that actually ran — never
synthetic/demo data, per CLAUDE.md rule 4. See docs/MONITORING.md for what
each metric means and how the Grafana panels use it.
"""

from prometheus_client import Counter, Gauge, Histogram

predictions_total = Counter(
    "predictions_total",
    "Total POST /api/v1/predict calls that produced a recommendation.",
    ["source", "district", "model_version"],
)

prediction_latency_seconds = Histogram(
    "prediction_latency_seconds",
    "Wall-clock time to compute one irrigation recommendation "
    "(weather resolution + model inference + SHAP explanation + risk score).",
)

weather_api_failures_total = Counter(
    "weather_api_failures_total",
    "Total failed calls to the Open-Meteo weather API "
    "(timeout, network error, 4xx/5xx after retries, or an unparseable response).",
)

flood_api_failures_total = Counter(
    "flood_api_failures_total",
    "Total failed calls to the Open-Meteo Flood API / GloFAS discharge data "
    "(timeout, network error, 4xx/5xx after retries, or an unparseable response).",
)

assistant_requests_total = Counter(
    "assistant_requests_total",
    "Total AI assistant chat replies successfully returned, by provider actually used.",
    ["provider"],
)

alerts_raised_total = Counter(
    "lehar_alerts_raised_total",
    "Total alerts actually written to the alerts table by the alert engine, "
    "by alert type and level (see app/services/alerts/engine.py).",
    ["type", "level"],
)

alerts_suppressed_total = Counter(
    "lehar_alerts_suppressed_total",
    "Total rule outcomes the alert engine deliberately did NOT raise — "
    "same-day duplicates, an identical alert already active, or a re-fire "
    "inside the ALERT_COOLDOWN_HOURS window.",
)

alert_run_duration_seconds = Histogram(
    "lehar_alert_run_duration_seconds",
    "Wall-clock time for one full alert evaluation run over every district "
    "(rule evaluation + dedupe + persistence + delivery).",
)

model_info = Gauge(
    "model_info",
    "Always 1 for the currently-served model version; labeled by version, "
    "so the exposed label set changes on every load/promote/rollback.",
    ["version"],
)
