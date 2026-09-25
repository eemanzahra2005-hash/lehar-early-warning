"""Append-only log of platform-health events that the OPS rule reads.

Why a file and not a table: the two events that matter most — a quality-gate
FAIL and a rollback — are produced by *different processes*. The training
pipeline (`python backend/ml/pipeline.py`) runs standalone and never has the
API's database session; the rollback endpoint runs inside the API. A tiny
JSON-lines file under DB_PATH's directory is reachable from both, needs no
schema migration for what is fundamentally a diagnostic breadcrumb, and
works identically whether the app is on SQLite or Postgres.

Events older than ALERT_OPS_EVENT_MAX_AGE_HOURS are ignored on read and
pruned on write, so the file cannot grow without bound and a gate failure
from last month never re-raises an OPS alert today.

Every write is best-effort: recording an event must never be able to fail a
training run or a rollback. A failed write is logged and swallowed.
"""

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.config import get_settings

logger = logging.getLogger("app.alerts.ops_events")

PROJECT_ROOT = Path(__file__).resolve().parents[4]

# Hard cap on retained lines, independent of age — a runaway writer can
# still only ever cost this many lines of disk.
MAX_RETAINED_EVENTS = 500


def resolve_ops_events_path() -> Path:
    """ALERT_OPS_EVENTS_PATH, resolved against the project root if relative
    (same convention as app/db.py's resolve_db_path)."""
    raw = get_settings().alert_ops_events_path
    path = Path(raw)
    return path if path.is_absolute() else PROJECT_ROOT / path


def _parse_recorded_at(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def read_recent_events(now: datetime | None = None) -> list[dict]:
    """Every recorded event newer than ALERT_OPS_EVENT_MAX_AGE_HOURS,
    oldest first. Returns [] when the file is missing or unreadable — an
    unreadable breadcrumb file must not break an alert run."""
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=get_settings().alert_ops_event_max_age_hours)
    path = resolve_ops_events_path()
    if not path.exists():
        return []

    events: list[dict] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue  # a torn line from a crashed write — skip it, don't fail the run
            recorded_at = _parse_recorded_at(event.get("recorded_at"))
            if recorded_at is None or recorded_at < cutoff:
                continue
            events.append(event)
    except OSError:
        logger.warning("Could not read OPS events file at %s", path, exc_info=True)
        return []
    return events


def record_ops_event(kind: str, detail: str, now: datetime | None = None) -> None:
    """Append one event. Best-effort: never raises.

    `kind` is one of rules.OPS_TRIGGERS; `detail` is a short human-readable
    line that ends up verbatim in the OPS alert's payload."""
    now = now or datetime.now(timezone.utc)
    event = {"kind": kind, "detail": detail, "recorded_at": now.isoformat()}
    path = resolve_ops_events_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        existing = read_recent_events(now=now)
        lines = [json.dumps(e) for e in existing[-(MAX_RETAINED_EVENTS - 1) :]] + [json.dumps(event)]
        # Rewrite rather than append, so pruning happens on the same pass.
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except OSError:
        logger.warning("Could not record OPS event %s at %s", kind, path, exc_info=True)


def clear_ops_events() -> None:
    """Delete the events file. Used by the engine after an OPS alert has
    consumed the events (so one rollback raises one alert, not one per run)
    and by tests. Best-effort: never raises."""
    path = resolve_ops_events_path()
    try:
        if path.exists():
            os.remove(path)
    except OSError:
        logger.warning("Could not clear OPS events file at %s", path, exc_info=True)
