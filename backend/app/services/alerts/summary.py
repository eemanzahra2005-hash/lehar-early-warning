"""Read-only alert summaries (LEHAR Phase 4).

Two consumers, with very different audiences and costs:

  - GET /api/v1/alerts/stats (admin, JWT): the operational breakdown —
    what was raised, suppressed and resolved, what was delivered on which
    channel, and how fast.
  - GET /api/v1/alerts/health-summary (public, no auth): the one line the
    console banner needs — the national highest active level and how many
    districts sit at each level. Every console page load hits it, so its
    answer is cached (see HealthSummaryCache below).

Nothing here decides anything about an alert (CLAUDE.md rule 10): these are
COUNT(*)s and percentiles over rows the engine already wrote, and nothing
is estimated (rule 4).
"""

import math
import statistics
import threading
import time
from collections.abc import Callable
from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db import Alert, AlertDelivery, AlertRun, AlertSubscription
from app.metrics import alerts_suppressed_detail_total
from app.services.alerts.engine import STATUS_RESOLVED, highest_active_by_district
from app.services.alerts.levels import (
    CHANNEL_IN_APP,
    DISCLAIMER_EN,
    DISCLAIMER_UR,
    FARMER_LEVELS,
    get_level,
)

# The latency percentiles are computed over at most this many of the most
# recent successful sends PER CHANNEL. Bounds both the query and the memory
# it needs on a 512 MB host (CLAUDE.md rule 11), however long the
# deployment has been running; `sample_size` in the response says how many
# were actually used.
LATENCY_SAMPLE_LIMIT = 5000

# Scope label for the per-level/type suppression breakdown. alert_runs only
# stores a suppressed COUNT per run, so the breakdown comes from the
# in-process Prometheus counter and restarts from zero with the process. The
# response says so rather than letting it pass for an all-time figure.
SUPPRESSED_BREAKDOWN_SCOPE = "since_process_start"


# --- /stats helpers ---------------------------------------------------------------

def nested_counts(rows) -> dict[str, dict[str, int]]:
    """[(outer, inner, count), ...] -> {outer: {inner: count}}, keys as str
    (JSON object keys are strings anyway; doing it here keeps level 3 and
    "3" from ever becoming two different keys)."""
    result: dict[str, dict[str, int]] = {}
    for outer, inner, count in rows:
        result.setdefault(str(outer), {})[str(inner)] = int(count)
    return result


def percentile_nearest_rank(sorted_values: list[int], pct: float) -> int:
    """Nearest-rank percentile: the smallest value with at least pct% of the
    sample at or below it. Always an observed value (never interpolated), so
    "p95 = 1840 ms" means a real send took 1840 ms."""
    if not sorted_values:
        raise ValueError("percentile of an empty sample")
    rank = max(1, math.ceil(pct / 100 * len(sorted_values)))
    return sorted_values[rank - 1]


def latency_summary(values_ms: list[int]) -> dict:
    """{sample_size, median_ms, p95_ms} for one channel's latencies."""
    ordered = sorted(values_ms)
    return {
        "sample_size": len(ordered),
        # statistics.median averages the middle two of an even sample, the
        # textbook median; p95 uses nearest-rank (above).
        "median_ms": float(statistics.median(ordered)),
        "p95_ms": percentile_nearest_rank(ordered, 95),
    }


def delivery_latency_by_channel(db: Session) -> dict[str, dict]:
    """Median/p95 of alert_deliveries.latency_ms for successful sends.

    Same definition as the lehar_delivery_latency_seconds histogram: sent
    rows on an external channel only (in-app "delivery" is a database row,
    not a send), measured from the alert being raised to the provider
    accepting it (app/services/alerts/channels/__init__.py)."""
    channels = [
        channel
        for (channel,) in db.query(AlertDelivery.channel)
        .filter(AlertDelivery.status == "sent", AlertDelivery.channel != CHANNEL_IN_APP)
        .distinct()
        .all()
    ]
    result: dict[str, dict] = {}
    for channel in sorted(channels):
        values = [
            latency
            for (latency,) in db.query(AlertDelivery.latency_ms)
            .filter(
                AlertDelivery.channel == channel,
                AlertDelivery.status == "sent",
                AlertDelivery.latency_ms.isnot(None),
            )
            .order_by(AlertDelivery.id.desc())
            .limit(LATENCY_SAMPLE_LIMIT)
            .all()
        ]
        if values:
            result[channel] = latency_summary(values)
    return result


def suppressed_breakdown() -> dict[str, dict[str, int]]:
    """{type: {level: count}} read from the in-process Prometheus counter
    (reasons summed). See SUPPRESSED_BREAKDOWN_SCOPE for why it is scoped."""
    result: dict[str, dict[str, int]] = {}
    for metric in alerts_suppressed_detail_total.collect():
        for sample in metric.samples:
            if not sample.name.endswith("_total") or sample.value <= 0:
                continue
            by_level = result.setdefault(sample.labels["type"], {})
            level = sample.labels["level"]
            by_level[level] = by_level.get(level, 0) + int(sample.value)
    return result


def operations_stats(db: Session) -> dict:
    """The Phase 4 additions to GET /api/v1/alerts/stats, as plain values
    ready for AlertStatsResponse."""
    raised = db.query(Alert.type, Alert.level, func.count(Alert.id)).group_by(Alert.type, Alert.level).all()
    resolved = (
        db.query(Alert.type, Alert.level, func.count(Alert.id))
        .filter(Alert.status == STATUS_RESOLVED)
        .group_by(Alert.type, Alert.level)
        .all()
    )
    deliveries = (
        db.query(AlertDelivery.channel, AlertDelivery.status, func.count(AlertDelivery.id))
        .group_by(AlertDelivery.channel, AlertDelivery.status)
        .all()
    )
    active_by_channel = dict(
        db.query(AlertSubscription.channel, func.count(AlertSubscription.id))
        .filter(AlertSubscription.verified.is_(True))
        .group_by(AlertSubscription.channel)
        .all()
    )
    return {
        # Every alerts row is a raised alert (a suppression writes nothing),
        # so "raised" is simply all rows, by type then level.
        "raised_by_type_and_level": nested_counts(raised),
        "resolved_by_type_and_level": nested_counts(resolved),
        # Durable: the sum of every alert_runs row's own suppressed count.
        "suppressed_total": int(db.query(func.coalesce(func.sum(AlertRun.alerts_suppressed), 0)).scalar() or 0),
        "suppressed_by_type_and_level": suppressed_breakdown(),
        "suppressed_breakdown_scope": SUPPRESSED_BREAKDOWN_SCOPE,
        "deliveries_by_channel": nested_counts(deliveries),
        "delivery_latency": delivery_latency_by_channel(db),
        "active_subscriptions": sum(active_by_channel.values()),
        "active_subscriptions_by_channel": {str(k): int(v) for k, v in active_by_channel.items()},
    }


# --- /health-summary ---------------------------------------------------------------

def build_health_summary(db: Session, now: datetime | None = None) -> dict:
    """The national banner: highest active level and districts per level.

    Built on highest_active_by_district — the exact rows GET /alerts/active
    serves — so the banner and the map can never disagree. A calm district
    counts at level 1 (the computed default); OPS notices never count."""
    districts = highest_active_by_district(db)
    counts = {str(level): 0 for level in FARMER_LEVELS}
    for row in districts:
        counts[str(row["level"])] = counts.get(str(row["level"]), 0) + 1
    highest = max((row["level"] for row in districts), default=FARMER_LEVELS[0])
    level = get_level(highest)
    return {
        "generated_at": now or datetime.now(timezone.utc),
        "highest_level": highest,
        "highest_level_key": level.key,
        "highest_level_name_en": level.name_en,
        "highest_level_name_ur": level.name_ur,
        "highest_level_color_hex": level.color_hex,
        "highest_level_text_color_hex": level.text_color_hex,
        "counts_by_level": counts,
        "total_districts": len(districts),
        "alerting_districts": sum(1 for row in districts if row["source"] == "alert"),
        "disclaimer": DISCLAIMER_EN,
        "disclaimer_ur": DISCLAIMER_UR,
    }


class HealthSummaryCache:
    """One cached answer, reused for `ttl_seconds`.

    Deliberately tiny: a single value, no per-key storage, so its memory
    cost is one small dict. The lock stops a burst of simultaneous page
    loads on an expired cache from each running the query. The alert
    endpoints that change what the banner shows (a run, an acknowledgement)
    call invalidate(), so a new alert is never hidden behind the TTL."""

    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self._lock = threading.Lock()
        self._value: dict | None = None
        self._expires_at = 0.0

    def get(self, ttl_seconds: float, build: Callable[[], dict]) -> tuple[dict, bool]:
        """(summary, served_from_cache)."""
        with self._lock:
            now = self._clock()
            if self._value is not None and now < self._expires_at:
                return self._value, True
            self._value = build()
            self._expires_at = now + ttl_seconds
            return self._value, False

    def invalidate(self) -> None:
        with self._lock:
            self._value = None
            self._expires_at = 0.0


health_summary_cache = HealthSummaryCache()
