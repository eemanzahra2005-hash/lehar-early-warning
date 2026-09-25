"""The alert engine: one evaluation pass over every district.

What a run does, in order:

  1. fetch, per district, the Flood Risk Index (app/services/flood.py), the
     daily weather outlook (app/services/weather.py) and — when it is turned
     on and a model is registered — the flood LEAD-TIME forecast
     (app/services/flood_forecast.py, LEHAR Phase 2.5), concurrently;
  2. evaluate the pure rules in rules.py against those values;
  3. evaluate IRRIGATION_DUE over every saved field, and OPS once;
  4. decide, per outcome, whether to RAISE or SUPPRESS it (dedupe,
     cooldown, escalation);
  5. resolve alerts whose condition has been gone for two runs and emit an
     ALL_CLEAR for each;
  6. deliver every raised alert through channels/ — and, since LEHAR
     Phase 3, re-send open level 4/5 alerts every 6 h and retry anything
     an earlier run deferred, all inside ALERT_MAX_SENDS_PER_RUN;
  7. record the run in alert_runs — always, even when nothing fired.

Alert rows are for things that are HAPPENING. A calm district writes
nothing: a LOW flood band raises no alert, and level 1 (white) is instead
the computed default GET /api/v1/alerts/active reports for any district
with no active alert (see highest_active_by_district at the bottom of this
file). The only level-1 rows the engine writes are IRRIGATION_DUE — one per
saved field per day — and ALL_CLEAR, which announces a past event and is
born resolved. On a calm day over all 107 districts, this run stores zero
alerts.

Determinism (CLAUDE.md rule 10): the only non-deterministic inputs are the
upstream measurements and the clock. Given the same measurements, the same
clock and the same database state, a run produces exactly the same alerts,
with exactly the same text, every time. `now` is injectable so tests can
pin the clock and drive cooldown/escalation deliberately.

Degradation: a district whose flood or weather fetch fails is skipped with
a warning, exactly like MapOverviewService and FloodService do — one broken
upstream district never fails the run for the other 106.
"""

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import Alert, AlertRun, AlertSubscription
from app.db import Field as FieldModel
from app.metrics import alert_run_duration_seconds, alerts_raised_total, alerts_suppressed_total
from app.services.alerts import ops_events
from app.services.alerts.channels import DeliveryDispatcher, SendBudget
from app.services.alerts.levels import OPS_LEVEL
from app.services.alerts.rules import (
    TYPE_ALL_CLEAR,
    TYPE_OPS,
    AlertThresholds,
    evaluate_flood,
    evaluate_flood_forecast,
    evaluate_heat_stress,
    evaluate_heavy_rain,
    evaluate_irrigation_due,
    evaluate_ops,
)
from app.services.alerts.templates import render
from app.services.flood import FORECAST_DAYS as FLOOD_FORECAST_DAYS
from ml.districts import DISTRICTS

logger = logging.getLogger("app.alerts.engine")

MAX_CONCURRENT_DISTRICT_FETCHES = 8

STATUS_ACTIVE = "active"
STATUS_ACKNOWLEDGED = "acknowledged"
STATUS_RESOLVED = "resolved"
OPEN_STATUSES = (STATUS_ACTIVE, STATUS_ACKNOWLEDGED)

TRIGGER_CRON = "cron"
TRIGGER_MANUAL = "manual"

# district_code for OPS alerts, which are about the platform rather than a
# place. Deliberately not a real district name so it can never collide.
SYSTEM_DISTRICT = "SYSTEM"

# Why an outcome was not raised — recorded in AlertRunResult.suppressed and
# surfaced by POST /api/v1/alerts/run, so a suppressed alert is as
# auditable as a raised one.
SUPPRESS_DUPLICATE = "duplicate"
SUPPRESS_COOLDOWN = "cooldown"

# Defaults mirroring MapOverviewService's documented map conditions, used
# for a saved field that recorded no soil moisture / canal flow of its own.
DEFAULT_SOIL_MOISTURE_PCT = 25.0

# Set by the engine on the payload of an alert superseded by an escalation
# (or a de-escalation after the cooldown), so a resolved row always says
# which of the two reasons closed it.
RESOLUTION_CLEARED = "cleared"
RESOLUTION_SUPERSEDED = "superseded"

# The calm baseline GET /api/v1/alerts/active reports for a district with no
# active alert. Level 1 (white) is a COMPUTED state, never a stored row —
# see highest_active_by_district. `source` tells a client which it is
# looking at, so a real level-1 IRRIGATION_DUE alert is distinguishable from
# "nothing is happening here".
CALM_LEVEL = 1
SOURCE_ALERT = "alert"
SOURCE_DEFAULT = "default"
CALM_TITLE_EN = "No active alert"
CALM_TITLE_UR = "کوئی فعال الرٹ نہیں"


def type_component(alert_type: str, subject: str | None = None) -> str:
    """The "type" half of a dedupe key. A rule outcome with a `subject`
    (currently only IRRIGATION_DUE's "field:<id>") widens the type so each
    subject gets its own key: two saved fields in one district each get
    their own daily alert instead of colliding on one row."""
    return f"{alert_type}:{subject}" if subject else alert_type


def dedupe_key_for(district_code: str, alert_type: str, level: int, moment: datetime) -> str:
    """district + type + level + day. Stored UNIQUE (app/db.py), so the
    same condition at the same level in the same district cannot produce two
    alerts on the same UTC day no matter how often the engine runs.

    `alert_type` is the composed component from type_component() above —
    "FLOOD", or "IRRIGATION_DUE:field:12", or "ALL_CLEAR:FLOOD" — so one
    day's flood all-clear and heat all-clear for the same district, and two
    fields' irrigation advisories, are all distinct keys."""
    return f"{district_code}|{alert_type}|{level}|{moment.strftime('%Y-%m-%d')}"


@dataclass
class SuppressedOutcome:
    district_code: str
    type: str
    level: int
    reason: str


@dataclass
class AlertRunResult:
    """Everything one run did. Mirrors the alert_runs row plus the detail
    the API returns to whoever triggered the run."""

    run_id: int | None
    started_at: datetime
    finished_at: datetime
    trigger: str
    districts_checked: int
    alerts_raised: int
    alerts_suppressed: int
    alerts_resolved: int
    raised_alert_ids: list[int] = field(default_factory=list)
    suppressed: list[SuppressedOutcome] = field(default_factory=list)
    all_clear_alert_ids: list[int] = field(default_factory=list)


@dataclass
class _DistrictSnapshot:
    """One district's fetched inputs. Any part may be missing — the rules
    that need the missing part simply don't run for that district."""

    district: str
    flood: dict | None = None
    outlook: list[dict] | None = None
    # LEHAR Phase 2.5: the flood lead-time model's prediction for this
    # district, or None when the feature is off, no model is registered, or
    # this district's inputs were incomplete. Always optional — a missing
    # forecast costs the FLOOD_FORECAST rule and nothing else.
    forecast: dict | None = None
    ok: bool = False


class AlertEngine:
    """Stateless across runs — everything it needs to remember (active
    alerts, consecutive clear runs, the last raise time) lives in the
    database, so a restarted process picks up exactly where it left off."""

    def __init__(
        self,
        flood_service,
        weather_service,
        model_service=None,
        drift_service=None,
        thresholds: AlertThresholds | None = None,
        dispatcher: DeliveryDispatcher | None = None,
        flood_forecast_service=None,
    ):
        settings = get_settings()
        self._flood_service = flood_service
        self._weather_service = weather_service
        # Optional: IRRIGATION_DUE needs a model, OPS needs drift. Either
        # being unavailable silently skips that rule rather than failing the
        # run or inventing a value (CLAUDE.md rule 4).
        self._model_service = model_service
        self._drift_service = drift_service
        # LEHAR Phase 2.5, and optional for the same reason: no service, no
        # registered model, or FLOOD_DL_ENABLED=false all mean the
        # FLOOD_FORECAST rule simply does not run. Every other rule is
        # untouched, so an alert run on a checkout with no flood lead-time
        # model behaves exactly as it did in Phase 2.
        self._flood_forecast_service = flood_forecast_service
        self._thresholds = thresholds or AlertThresholds.from_settings(settings)
        self._dispatcher = dispatcher or DeliveryDispatcher()
        self._forecast_days = settings.alert_forecast_days
        self._cooldown = timedelta(hours=settings.alert_cooldown_hours)
        self._clear_runs_to_resolve = settings.alert_clear_runs_to_resolve
        # LEHAR Phase 3: the cap on Telegram + email sends per run, so one
        # bad day across 107 districts cannot exhaust a free tier.
        self._max_sends_per_run = settings.alert_max_sends_per_run

    # --- fetching ------------------------------------------------------

    def _fetch_district(self, district: str) -> _DistrictSnapshot:
        snapshot = _DistrictSnapshot(district=district)
        try:
            entry = self._flood_service.get_district(district)
            snapshot.flood = entry if entry.get("status") == "ok" else None
        except Exception:
            logger.warning("Flood data unavailable for %s during alert run", district)

        try:
            snapshot.outlook = self._weather_service.fetch_daily_outlook(district, days=self._forecast_days)
        except Exception:
            logger.warning("Weather outlook unavailable for %s during alert run", district)

        if self._flood_forecast_service is not None:
            # forecast_quietly() never raises and returns None when the
            # feature is off or no model is registered, so this costs one
            # cheap `is_available()` check on a run with the feature off.
            snapshot.forecast = self._flood_forecast_service.forecast_quietly(district)

        snapshot.ok = snapshot.flood is not None or snapshot.outlook is not None
        return snapshot

    def _fetch_all(self, districts: list[str]) -> dict[str, _DistrictSnapshot]:
        """Bounded-concurrency fetch, same pattern (and the same worker cap)
        as MapOverviewService and FloodService use for the free Open-Meteo
        API."""
        snapshots: dict[str, _DistrictSnapshot] = {}
        with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_DISTRICT_FETCHES) as pool:
            futures = {pool.submit(self._fetch_district, name): name for name in districts}
            for future in as_completed(futures):
                name = futures[future]
                try:
                    snapshots[name] = future.result()
                except Exception:
                    logger.exception("Unexpected failure fetching alert inputs for %s", name)
                    snapshots[name] = _DistrictSnapshot(district=name)
        return snapshots

    # --- rule evaluation -----------------------------------------------

    def _evaluate_district(self, snapshot: _DistrictSnapshot) -> list:
        outcomes = []

        if snapshot.flood is not None:
            discharge = snapshot.flood.get("discharge") or {}
            all_values = discharge.get("values") or []
            # flood.py returns ONE combined past+forecast series; the last
            # FORECAST_DAYS entries are today onwards (see _split_series).
            forecast_values = all_values[-FLOOD_FORECAST_DAYS:]
            all_dates = discharge.get("dates") or []
            forecast_dates = all_dates[-FLOOD_FORECAST_DAYS:]
            outcome = evaluate_flood(
                band=snapshot.flood.get("band"),
                score=snapshot.flood.get("score"),
                forecast_discharge=forecast_values,
                anomaly_ratio=discharge.get("anomaly_ratio"),
                thresholds=self._thresholds,
                return_period_years=discharge.get("return_period_years"),
                forecast_dates=forecast_dates,
            )
            if outcome is not None:
                outcomes.append(outcome)

        if snapshot.forecast is not None:
            # LEHAR Phase 2.5. The rule is re-evaluated HERE from the
            # service's raw predicted numbers rather than trusting the level
            # the service already computed for its own endpoint: every alert
            # in this engine must trace input -> threshold -> level through
            # rules.py, with the thresholds this run is configured with
            # (CLAUDE.md rule 10).
            predicted_block = snapshot.forecast.get("predicted") or {}
            observed_block = snapshot.forecast.get("observed") or {}
            observed_values = observed_block.get("values") or []
            forecast_outcome = evaluate_flood_forecast(
                band=snapshot.forecast.get("band"),
                score=snapshot.forecast.get("score"),
                predicted_discharge=predicted_block.get("values") or [],
                anomaly_ratio=predicted_block.get("anomaly_ratio"),
                thresholds=self._thresholds,
                current_discharge=observed_values[-1] if observed_values else None,
                model_version=snapshot.forecast.get("model_version"),
                lead_time_hours=snapshot.forecast.get("lead_time_hours", 24),
                forecast_dates=predicted_block.get("dates"),
            )
            if forecast_outcome is not None:
                outcomes.append(forecast_outcome)

        if snapshot.outlook:
            dates = [day.get("date") for day in snapshot.outlook]
            rain = [day.get("rainfall_mm") for day in snapshot.outlook if day.get("rainfall_mm") is not None]
            tmax = [
                day.get("temperature_max_c")
                for day in snapshot.outlook
                if day.get("temperature_max_c") is not None
            ]
            rain_outcome = evaluate_heavy_rain(daily_rain_mm=rain, thresholds=self._thresholds, dates=dates)
            if rain_outcome is not None:
                outcomes.append(rain_outcome)
            heat_outcome = evaluate_heat_stress(daily_tmax_c=tmax, thresholds=self._thresholds, dates=dates)
            if heat_outcome is not None:
                outcomes.append(heat_outcome)

        return outcomes

    def _evaluate_irrigation(self, db: Session, snapshots: dict[str, _DistrictSnapshot]) -> list[tuple[str, object]]:
        """IRRIGATION_DUE over every saved field. Needs a model — without
        one the rule is skipped entirely rather than guessing a recommended
        depth."""
        if self._model_service is None:
            return []

        results: list[tuple[str, object]] = []
        for saved_field in db.query(FieldModel).order_by(FieldModel.id).all():
            snapshot = snapshots.get(saved_field.district)
            if snapshot is None or not snapshot.outlook:
                continue
            params = DISTRICTS.get(saved_field.district)
            if params is None:
                continue

            try:
                weather = self._weather_service.fetch(saved_field.district)
                predicted_mm = self._model_service.predict(
                    temperature_c=weather["temperature_c"],
                    humidity_pct=weather["humidity_pct"],
                    rainfall_mm=weather["rainfall_mm"],
                    evapotranspiration_mm=weather["evapotranspiration_mm"],
                    canal_flow_cusecs=(
                        saved_field.default_canal_flow_cusecs
                        if saved_field.default_canal_flow_cusecs is not None
                        else params["canal_flow_baseline_cusecs"]
                    ),
                    soil_moisture_pct=(
                        saved_field.default_soil_moisture_pct
                        if saved_field.default_soil_moisture_pct is not None
                        else DEFAULT_SOIL_MOISTURE_PCT
                    ),
                    district=saved_field.district,
                    crop_type=saved_field.crop_type,
                )
            except Exception:
                logger.warning(
                    "Irrigation prediction unavailable for field %s (%s)", saved_field.id, saved_field.district
                )
                continue

            outcome = evaluate_irrigation_due(
                predicted_mm=predicted_mm,
                field_threshold_mm=saved_field.irrigation_threshold_mm,
                daily_rain_mm=[
                    day.get("rainfall_mm") for day in snapshot.outlook if day.get("rainfall_mm") is not None
                ],
                thresholds=self._thresholds,
                # The field id scopes the alert to THIS field: two fields in
                # one district each get their own daily advisory rather than
                # colliding on a single district-wide dedupe key.
                field_id=saved_field.id,
                field_name=saved_field.name,
                crop_type=saved_field.crop_type,
                dates=[day.get("date") for day in snapshot.outlook],
            )
            if outcome is not None:
                results.append((saved_field.district, outcome))
        return results

    def _evaluate_ops(self, db: Session, now: datetime) -> tuple[object | None, bool]:
        """Returns (outcome, consumed_events). `consumed_events` is True when
        the outcome was driven by recorded events, which the caller then
        clears so one rollback raises one alert rather than one per run."""
        max_psi: float | None = None
        psi_feature: str | None = None
        drift_status: str | None = None
        model_version: str | None = None

        if self._drift_service is not None:
            try:
                report = self._drift_service.compute(db)
                drift_status = report.status
                model_version = report.reference_model_version
                # "insufficient_data" reports no features at all, so max_psi
                # correctly stays None — no data is not the same as no drift.
                for feature in report.features:
                    if max_psi is None or feature.psi > max_psi:
                        max_psi, psi_feature = feature.psi, feature.name
            except Exception:
                logger.warning("Drift report unavailable during alert run", exc_info=True)

        events = ops_events.read_recent_events(now=now)
        outcome = evaluate_ops(
            max_psi=max_psi,
            psi_feature=psi_feature,
            drift_status=drift_status,
            ops_events=events,
            thresholds=self._thresholds,
            model_version=model_version,
        )
        return outcome, bool(events)

    # --- persistence ---------------------------------------------------

    def _load_open_alerts(self, db: Session) -> tuple[list[Alert], dict[tuple, Alert]]:
        """Every currently-open alert, plus an index keyed by
        (district, type, subject) — the "one condition" identity the
        dedupe/escalation/resolution logic all reason about.

        Loaded ONCE per run rather than queried per outcome: the run already
        walks 107 districts x 5 rule families, and the subject key
        (IRRIGATION_DUE's per-field scoping) lives in the JSON payload,
        which is awkward to filter on portably across SQLite and Postgres.
        One query and a dict is both simpler and cheaper."""
        rows = (
            db.query(Alert)
            .filter(Alert.status.in_(OPEN_STATUSES), Alert.type != TYPE_ALL_CLEAR)
            .order_by(Alert.created_at.desc(), Alert.id.desc())
            .all()
        )
        index: dict[tuple, Alert] = {}
        for alert in rows:
            key = (alert.district_code, alert.type, (alert.payload or {}).get("subject"))
            # Rows arrive newest-first, so the first hit per key is the
            # current one; there should only ever be one open per key.
            index.setdefault(key, alert)
        return rows, index

    def _build_alert(self, district_code: str, outcome, now: datetime, dedupe_key: str) -> Alert:
        context = {
            "district": district_code,
            "reason": outcome.reason,
            **outcome.thresholds,
            **outcome.values,
        }
        message = render(outcome.type, outcome.level, context)
        return Alert(
            district_code=district_code,
            type=outcome.type,
            level=outcome.level,
            title_en=message.title_en,
            title_ur=message.title_ur,
            body_en=message.body_en,
            body_ur=message.body_ur,
            payload={
                "values": outcome.values,
                "thresholds": outcome.thresholds,
                "source_timestamps": outcome.source_timestamps,
                "reason": outcome.reason,
                # None for district-wide rules; "field:<id>" for
                # IRRIGATION_DUE. Part of this alert's identity, so it is
                # stored rather than re-derived from the dedupe key.
                "subject": outcome.subject,
                "consecutive_clear_runs": 0,
            },
            status=STATUS_ACTIVE,
            dedupe_key=dedupe_key,
            created_at=now,
        )

    def _resolve(self, alert: Alert, now: datetime, reason: str) -> None:
        alert.status = STATUS_RESOLVED
        alert.resolved_at = now
        # Reassign rather than mutate: SQLAlchemy's plain JSON type does not
        # track in-place dict mutation, so an edited-in-place payload would
        # silently never be written back.
        alert.payload = {**(alert.payload or {}), "resolution_reason": reason}

    def _set_clear_runs(self, alert: Alert, value: int) -> None:
        alert.payload = {**(alert.payload or {}), "consecutive_clear_runs": value}

    def _emit_all_clear(self, db: Session, resolved: Alert, now: datetime) -> Alert | None:
        """One ALL_CLEAR row per resolved alert. Level 1 (in-app only): an
        all-clear is good news and must never push a Telegram/email blast at
        the urgency of the warning it ends.

        An ALL_CLEAR is one of the two kinds of level-1 row the engine
        writes (IRRIGATION_DUE is the other). It is not a standing state —
        it announces a past event and is born resolved — so it never
        competes with the computed level-1 calm default."""
        subject = (resolved.payload or {}).get("subject")
        dedupe_key = dedupe_key_for(
            resolved.district_code, type_component(f"{TYPE_ALL_CLEAR}:{resolved.type}", subject), 1, now
        )
        if db.query(Alert).filter(Alert.dedupe_key == dedupe_key).first() is not None:
            return None

        context = {
            "district": resolved.district_code,
            "cleared_type": resolved.type,
            "clear_runs": self._clear_runs_to_resolve,
            "reason": f"The {resolved.type} alert for {resolved.district_code} has ended.",
        }
        message = render(TYPE_ALL_CLEAR, 1, context)
        all_clear = Alert(
            district_code=resolved.district_code,
            type=TYPE_ALL_CLEAR,
            level=1,
            title_en=message.title_en,
            title_ur=message.title_ur,
            body_en=message.body_en,
            body_ur=message.body_ur,
            payload={
                "cleared_alert_id": resolved.id,
                "cleared_type": resolved.type,
                "cleared_level": resolved.level,
                "subject": subject,
                "consecutive_clear_runs": self._clear_runs_to_resolve,
                "reason": context["reason"],
            },
            # An all-clear announces a past event; there is nothing left to
            # resolve later, so it is born resolved.
            status=STATUS_RESOLVED,
            dedupe_key=dedupe_key,
            created_at=now,
            resolved_at=now,
        )
        db.add(all_clear)
        return all_clear

    # --- the run -------------------------------------------------------

    def run(self, db: Session, trigger: str = TRIGGER_MANUAL, now: datetime | None = None) -> AlertRunResult:
        started_at = now or datetime.now(timezone.utc)
        start_perf = time.monotonic()

        run_row = AlertRun(started_at=started_at, trigger=trigger)
        db.add(run_row)
        db.flush()

        district_names = list(DISTRICTS)
        snapshots = self._fetch_all(district_names)
        districts_checked = sum(1 for snapshot in snapshots.values() if snapshot.ok)

        # (district_code, RuleOutcome) for everything that fired this run.
        outcomes: list[tuple[str, object]] = []
        for name in district_names:
            snapshot = snapshots.get(name)
            if snapshot is None:
                continue
            for outcome in self._evaluate_district(snapshot):
                outcomes.append((name, outcome))

        outcomes.extend(self._evaluate_irrigation(db, snapshots))

        ops_outcome, ops_had_events = self._evaluate_ops(db, started_at)
        if ops_outcome is not None:
            outcomes.append((SYSTEM_DISTRICT, ops_outcome))

        raised: list[Alert] = []
        suppressed: list[SuppressedOutcome] = []
        # Counts BOTH kinds of resolution: a condition that cleared, and an
        # alert superseded by an escalation/de-escalation in this same run.
        resolved_count = 0
        # Dedupe keys raised earlier in THIS run. The session is
        # autoflush=False (app/db.py), so a pending Alert is invisible to
        # the dedupe query below — two saved fields in the same district
        # firing IRRIGATION_DUE would otherwise both be added and violate
        # the UNIQUE constraint on commit.
        raised_keys: set[str] = set()
        # Every (district, type, subject) that produced an outcome — used
        # below to decide which open alerts had a CLEAR run. The subject
        # keeps one saved field's irrigation advisory from being counted as
        # "still firing" on behalf of another field in the same district.
        firing_keys: set[tuple[str, str, str | None]] = set()

        open_alerts, open_by_key = self._load_open_alerts(db)

        for district_code, outcome in outcomes:
            identity = (district_code, outcome.type, outcome.subject)
            firing_keys.add(identity)
            dedupe_key = dedupe_key_for(
                district_code, type_component(outcome.type, outcome.subject), outcome.level, started_at
            )

            if dedupe_key in raised_keys or db.query(Alert).filter(Alert.dedupe_key == dedupe_key).first() is not None:
                suppressed.append(SuppressedOutcome(district_code, outcome.type, outcome.level, SUPPRESS_DUPLICATE))
                continue

            prior = open_by_key.get(identity)
            if prior is not None:
                if outcome.level > prior.level:
                    # ESCALATION: always raises, cooldown or not. The lower
                    # alert is closed as superseded so a district never shows
                    # two open alerts for the same condition.
                    self._resolve(prior, started_at, RESOLUTION_SUPERSEDED)
                    open_by_key.pop(identity, None)
                    resolved_count += 1
                elif started_at - _as_utc(prior.created_at) < self._cooldown:
                    self._set_clear_runs(prior, 0)
                    suppressed.append(
                        SuppressedOutcome(district_code, outcome.type, outcome.level, SUPPRESS_COOLDOWN)
                    )
                    continue
                else:
                    # Same or lower level, cooldown elapsed: close the old
                    # alert and re-notify at the level that is true now.
                    self._resolve(prior, started_at, RESOLUTION_SUPERSEDED)
                    open_by_key.pop(identity, None)
                    resolved_count += 1

            alert = self._build_alert(district_code, outcome, started_at, dedupe_key)
            db.add(alert)
            raised.append(alert)
            raised_keys.add(dedupe_key)

        # --- resolution pass: conditions that have gone away ---
        # Walks the alerts loaded at the top of the run (in id order for a
        # stable ALL_CLEAR ordering); anything raised in THIS run is by
        # definition still firing, so it cannot be a clear-run candidate.
        all_clears: list[Alert] = []
        for alert in sorted(open_alerts, key=lambda a: a.id):
            if alert.status == STATUS_RESOLVED:
                continue  # already closed above as superseded
            identity = (alert.district_code, alert.type, (alert.payload or {}).get("subject"))
            if identity in firing_keys:
                self._set_clear_runs(alert, 0)
                continue
            clear_runs = int((alert.payload or {}).get("consecutive_clear_runs", 0)) + 1
            if clear_runs >= self._clear_runs_to_resolve:
                self._resolve(alert, started_at, RESOLUTION_CLEARED)
                resolved_count += 1
                all_clear = self._emit_all_clear(db, alert, started_at)
                if all_clear is not None:
                    all_clears.append(all_clear)
            else:
                self._set_clear_runs(alert, clear_runs)

        db.flush()

        # --- delivery ---
        # One call for the whole run, so the send budget is shared and spent
        # highest level first, and so level 4/5 re-sends and deferred retries
        # from earlier runs compete for it on the same terms (LEHAR Phase 3).
        subscriptions = db.query(AlertSubscription).order_by(AlertSubscription.id).all()
        self._dispatcher.dispatch_run(
            db,
            raised + all_clears,
            subscriptions,
            now=started_at,
            budget=SendBudget(self._max_sends_per_run),
            include_resends=True,
        )

        # With a pinned `now` (tests), finished_at is pinned too, so a run's
        # stored row is byte-identical across repeats.
        finished_at = datetime.now(timezone.utc) if now is None else started_at
        run_row.finished_at = finished_at
        run_row.districts_checked = districts_checked
        run_row.alerts_raised = len(raised)
        run_row.alerts_suppressed = len(suppressed)
        run_row.alerts_resolved = resolved_count
        db.commit()

        # OPS events are consumed, not re-read: a single rollback must raise
        # a single OPS alert, not one on every subsequent run for 24 h.
        if ops_outcome is not None and ops_had_events:
            ops_events.clear_ops_events()

        for alert in raised:
            alerts_raised_total.labels(type=alert.type, level=str(alert.level)).inc()
        for _ in suppressed:
            alerts_suppressed_total.inc()
        alert_run_duration_seconds.observe(time.monotonic() - start_perf)

        return AlertRunResult(
            run_id=run_row.id,
            started_at=started_at,
            finished_at=finished_at,
            trigger=trigger,
            districts_checked=districts_checked,
            alerts_raised=len(raised),
            alerts_suppressed=len(suppressed),
            alerts_resolved=resolved_count,
            raised_alert_ids=[alert.id for alert in raised],
            suppressed=suppressed,
            all_clear_alert_ids=[alert.id for alert in all_clears],
        )


def _as_utc(value: datetime) -> datetime:
    """SQLite gives naive datetimes back even from a DateTime(timezone=True)
    column, so a stored created_at has to be re-stamped as UTC before it can
    be compared with an aware `now`. Postgres returns an aware value and
    passes through unchanged."""
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def highest_active_by_district(db: Session) -> list[dict]:
    """EVERY district's current level — what GET /api/v1/alerts/active
    serves for the map choropleth and the banner.

    A district with an ACTIVE alert reports that alert's highest level,
    with source="alert". A district with none reports **level 1, computed,
    not stored** (source="default"): white is the calm baseline, the state
    almost every district is in almost every day. Storing a row per calm
    district per day would bury the alerts that matter under 107 daily
    "nothing is happening" records — so the calm state is derived here, and
    the FLOOD rule's LOW band writes nothing (see rules.py).

    Excluded from the alert side: acknowledged and resolved alerts (the
    farmer has seen it, or it is over), ALL_CLEAR rows (they announce a past
    event), and OPS notices — those are admin-only and must never colour a
    district on a farmer-facing map.
    """
    rows = (
        db.query(Alert)
        .filter(
            Alert.status == STATUS_ACTIVE,
            Alert.type != TYPE_ALL_CLEAR,
            Alert.type != TYPE_OPS,
            Alert.level > OPS_LEVEL,
        )
        .order_by(Alert.level.desc(), Alert.created_at.desc(), Alert.id.desc())
        .all()
    )
    highest: dict[str, Alert] = {}
    for alert in rows:
        # Rows arrive highest-level-first, so the first hit per district wins.
        highest.setdefault(alert.district_code, alert)

    # Every known district, plus any district_code that somehow has an alert
    # without being in the district list — reported rather than dropped.
    names = sorted(set(DISTRICTS) | set(highest))

    result: list[dict] = []
    for name in names:
        alert = highest.get(name)
        if alert is None:
            result.append(
                {
                    "district": name,
                    "level": CALM_LEVEL,
                    "source": SOURCE_DEFAULT,
                    "type": None,
                    "alert_id": None,
                    "title_en": CALM_TITLE_EN,
                    "title_ur": CALM_TITLE_UR,
                    "created_at": None,
                }
            )
            continue
        result.append(
            {
                "district": name,
                "level": alert.level,
                "source": SOURCE_ALERT,
                "type": alert.type,
                "alert_id": alert.id,
                "title_en": alert.title_en,
                "title_ur": alert.title_ur,
                "created_at": alert.created_at,
            }
        )
    return result
