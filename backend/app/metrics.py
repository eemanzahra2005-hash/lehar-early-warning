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

# LEHAR Phase 4: the same suppressions, broken down. A separate metric
# rather than labels on lehar_alerts_suppressed_total, so that existing
# series (and any query already written against it) is left unchanged.
# The alert_runs table only stores a per-run suppressed COUNT, so this is
# also where GET /api/v1/alerts/stats reads its per-level/type breakdown
# from — which is why that part of /stats is scoped to the process lifetime.
alerts_suppressed_detail_total = Counter(
    "lehar_alerts_suppressed_detail_total",
    "Rule outcomes the alert engine deliberately did NOT raise, by alert "
    "type, level and reason (duplicate | cooldown).",
    ["type", "level", "reason"],
)

# LEHAR Phase 4: what the most recent alert run did, for the Grafana "last
# run" panel. Gauges, not counters: each run overwrites them.
alert_last_run_timestamp_seconds = Gauge(
    "lehar_alert_last_run_timestamp_seconds",
    "Unix time the most recent alert run finished in this process "
    "(0 = no run yet since the process started).",
)
alert_last_run_outcomes = Gauge(
    "lehar_alert_last_run_outcomes",
    "What the most recent alert run did: districts checked and alerts "
    "raised / suppressed / resolved.",
    ["outcome"],
)

alert_run_duration_seconds = Histogram(
    "lehar_alert_run_duration_seconds",
    "Wall-clock time for one full alert evaluation run over every district "
    "(rule evaluation + dedupe + persistence + delivery).",
)

deliveries_total = Counter(
    "lehar_deliveries_total",
    "Total alert_deliveries rows written, by channel (in_app | telegram | email) "
    "and status (sent | failed | skipped) — see app/services/alerts/channels/.",
    ["channel", "status"],
)

delivery_latency_seconds = Histogram(
    "lehar_delivery_latency_seconds",
    "Time from an alert being raised (its created_at) to the provider accepting "
    "the Telegram/email message; for a level 4/5 re-send, from the start of the "
    "run that re-sent it. Successful external sends only.",
    ["channel"],
    # Seconds to an hour: a healthy run lands in the first few buckets, a
    # budget-deferred alert delivered on the next run in the last ones.
    buckets=(0.5, 1, 2.5, 5, 10, 30, 60, 300, 900, 1800, 3600, 7200, 21600),
)

model_info = Gauge(
    "model_info",
    "Always 1 for the currently-served model version; labeled by version, "
    "so the exposed label set changes on every load/promote/rollback.",
    ["version"],
)
