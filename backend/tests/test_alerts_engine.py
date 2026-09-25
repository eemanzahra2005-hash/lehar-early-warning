"""LEHAR Phase 2: the alert ENGINE — dedupe, cooldown, escalation,
resolution + ALL_CLEAR, delivery records and run bookkeeping.

Fully offline: the flood, weather, model and drift services are all
substituted with deterministic fakes, and DISTRICTS is narrowed to three
districts so each run is fast and its expected output can be reasoned about
by hand. `now` is pinned on every run so cooldown and escalation are driven
deliberately rather than by wall-clock luck.
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.db import Alert, AlertDelivery, AlertRun, AlertSubscription, User, get_session_factory
from app.db import Field as FieldModel
from app.services.alerts import engine as engine_module
from app.services.alerts import ops_events
from app.services.alerts.engine import SYSTEM_DISTRICT, AlertEngine, dedupe_key_for, highest_active_by_district
from app.services.alerts.rules import (
    TYPE_ALL_CLEAR,
    TYPE_FLOOD,
    TYPE_HEAT_STRESS,
    TYPE_HEAVY_RAIN,
    TYPE_IRRIGATION_DUE,
    TYPE_OPS,
)

# Three real districts, so ml/districts.py lookups (canal flow baseline,
# province) still resolve — just far fewer of them than the real 107.
TEST_DISTRICTS = {name: None for name in ("Multan", "Sukkur", "Lahore")}

T0 = datetime(2026, 8, 12, 6, 0, tzinfo=timezone.utc)

CALM_OUTLOOK = [
    {"date": "2026-08-12", "temperature_max_c": 32.0, "rainfall_mm": 0.5},
    {"date": "2026-08-13", "temperature_max_c": 33.0, "rainfall_mm": 0.0},
    {"date": "2026-08-14", "temperature_max_c": 33.0, "rainfall_mm": 0.0},
]


def flood_entry(band, score, forecast=(10.0, 10.0, 10.0), ratio=1.0):
    """A district entry shaped exactly like FloodService.get_district()'s —
    one combined 37-day series whose last 7 entries are the forecast."""
    values = [5.0] * 30 + list(forecast) + [10.0] * (7 - len(forecast))
    return {
        "district": "x",
        "province": "Punjab",
        "status": "ok",
        "score": score,
        "band": band,
        "components": {},
        "discharge": {
            "unit": "m3/s",
            "dates": [f"d{i}" for i in range(37)],
            "values": values,
            "baseline_median": 5.0,
            "forecast_max": max(values[-7:]),
            "anomaly_ratio": ratio,
        },
        "rain": {"dates": [], "values_mm": [], "cumulative_3day_mm": 0.0, "max_day_mm": 0.0},
    }


class FakeFloodService:
    """Serves a per-district entry. A district with nothing configured
    reports "unavailable" — the same shape FloodService returns when GloFAS
    has no usable data — so tests only get FLOOD outcomes for the districts
    they deliberately set up. (A LOW band is NOT silent: it raises a
    level-1 early advisory, which
    test_a_low_flood_band_raises_a_level_1_early_advisory covers.)"""

    def __init__(self, by_district=None, fail_for=()):
        self.by_district = by_district or {}
        self.fail_for = set(fail_for)

    def get_district(self, district):
        if district in self.fail_for:
            raise RuntimeError("flood provider down")
        return self.by_district.get(district, {"district": district, "province": "x", "status": "unavailable"})


class FakeWeatherService:
    def __init__(self, outlook_by_district=None, fail_for=()):
        self.outlook_by_district = outlook_by_district or {}
        self.fail_for = set(fail_for)

    def fetch_daily_outlook(self, district, days=3):
        if district in self.fail_for:
            raise RuntimeError("weather provider down")
        return self.outlook_by_district.get(district, CALM_OUTLOOK)

    def fetch(self, district):
        return {
            "temperature_c": 30.0,
            "humidity_pct": 45.0,
            "rainfall_mm": 0.0,
            "evapotranspiration_mm": 5.0,
        }


class FakeModelService:
    def __init__(self, recommendation_mm=12.0, fail=False):
        self.recommendation_mm = recommendation_mm
        self.fail = fail

    def predict(self, **kwargs):
        if self.fail:
            raise RuntimeError("model unavailable")
        return self.recommendation_mm


class FakeDriftService:
    """Mirrors DriftService.compute()'s DriftReport shape closely enough for
    the OPS rule (status + features with .psi/.name)."""

    def __init__(self, status="stable", features=(), model_version="v1"):
        self.status = status
        self.features = [SimpleNamespace(name=n, psi=p) for n, p in features]
        self.model_version = model_version

    def compute(self, db):
        return SimpleNamespace(
            status=self.status, features=self.features, reference_model_version=self.model_version
        )


@pytest.fixture(autouse=True)
def _small_district_set(monkeypatch):
    """Narrow the engine's district sweep to three districts. Patched on the
    engine module so both the district pass and the saved-field lookup see
    the same set."""
    from ml.districts import DISTRICTS as REAL_DISTRICTS

    subset = {name: REAL_DISTRICTS[name] for name in TEST_DISTRICTS}
    monkeypatch.setattr(engine_module, "DISTRICTS", subset)
    yield


@pytest.fixture(autouse=True)
def _isolated_ops_events(tmp_path, monkeypatch):
    """Point ALERT_OPS_EVENTS_PATH at a temp file so a developer's real
    backend/data/ops_events.jsonl can never leak an OPS alert into a test."""
    import app.config as config_module

    monkeypatch.setenv("ALERT_OPS_EVENTS_PATH", str(tmp_path / "ops_events.jsonl"))
    config_module.get_settings.cache_clear()
    yield
    config_module.get_settings.cache_clear()


@pytest.fixture
def db():
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


def build_engine(flood=None, weather=None, model=None, drift=None):
    return AlertEngine(
        flood_service=flood or FakeFloodService(),
        weather_service=weather or FakeWeatherService(),
        model_service=model,
        drift_service=drift,
    )


def alerts_in(db, **filters):
    query = db.query(Alert)
    for key, value in filters.items():
        query = query.filter(getattr(Alert, key) == value)
    return query.order_by(Alert.id).all()


# --- a plain run ----------------------------------------------------------

def test_a_calm_run_raises_nothing_but_still_records_the_run(db):
    """"The engine ran and found nothing" must be distinguishable from
    "the engine never ran"."""
    result = build_engine().run(db, trigger="cron", now=T0)

    assert result.alerts_raised == 0
    assert result.districts_checked == 3
    run_row = db.query(AlertRun).one()
    assert run_row.trigger == "cron"
    assert run_row.districts_checked == 3
    assert run_row.finished_at is not None


def test_a_low_flood_band_writes_no_alert_row_at_all(db):
    """A calm river is the normal state of almost every district on almost
    every day. Storing it would bury the alerts that matter — level 1 is
    the COMPUTED default instead (see the active-map tests below)."""
    flood = FakeFloodService({name: flood_entry("LOW", 12.0) for name in TEST_DISTRICTS})
    result = build_engine(flood=flood).run(db, now=T0)

    assert result.alerts_raised == 0
    assert alerts_in(db) == []
    # ...but the run still happened and still checked every district.
    assert result.districts_checked == 3


def test_a_calm_day_over_every_district_stores_nothing(db):
    """The whole point of the change: a quiet day leaves the alerts table
    empty rather than one row per district per rule."""
    flood = FakeFloodService({name: flood_entry("LOW", 8.0) for name in TEST_DISTRICTS})
    build_engine(flood=flood).run(db, now=T0)
    build_engine(flood=flood).run(db, now=T0 + timedelta(hours=13))

    assert db.query(Alert).count() == 0
    assert db.query(AlertRun).count() == 2  # both runs still recorded


def test_a_flood_band_raises_one_alert_per_district_with_a_full_payload(db):
    flood = FakeFloodService({"Multan": flood_entry("HIGH", 70.0)})
    result = build_engine(flood=flood).run(db, now=T0)

    assert result.alerts_raised == 1
    alert = alerts_in(db, type=TYPE_FLOOD)[0]
    assert alert.district_code == "Multan"
    assert alert.level == 3
    assert alert.status == "active"
    assert alert.payload["values"]["band"] == "HIGH"
    assert alert.payload["thresholds"]["extreme_score"] == 85.0
    assert alert.payload["reason"]


def test_every_rule_family_can_fire_in_one_run(db):
    flood = FakeFloodService({"Multan": flood_entry("WATCH", 50.0)})
    weather = FakeWeatherService(
        {
            "Sukkur": [
                {"date": "2026-08-12", "temperature_max_c": 33.0, "rainfall_mm": 95.0},
                {"date": "2026-08-13", "temperature_max_c": 33.0, "rainfall_mm": 0.0},
                {"date": "2026-08-14", "temperature_max_c": 33.0, "rainfall_mm": 0.0},
            ],
            "Lahore": [
                {"date": "2026-08-12", "temperature_max_c": 41.0, "rainfall_mm": 0.0},
                {"date": "2026-08-13", "temperature_max_c": 41.0, "rainfall_mm": 0.0},
                {"date": "2026-08-14", "temperature_max_c": 33.0, "rainfall_mm": 0.0},
            ],
        }
    )
    build_engine(flood=flood, weather=weather).run(db, now=T0)

    by_type = {a.type: a for a in alerts_in(db)}
    assert by_type[TYPE_FLOOD].level == 2
    assert by_type[TYPE_HEAVY_RAIN].level == 3
    assert by_type[TYPE_HEAT_STRESS].level == 2


def test_a_broken_upstream_district_never_fails_the_run(db):
    """One district's flood/weather failure degrades that district only —
    the same per-section tolerance FloodService and MapOverviewService have."""
    flood = FakeFloodService({"Sukkur": flood_entry("HIGH", 70.0)}, fail_for=["Multan"])
    weather = FakeWeatherService(fail_for=["Multan"])
    result = build_engine(flood=flood, weather=weather).run(db, now=T0)

    assert result.districts_checked == 2  # Multan had neither half
    assert result.alerts_raised == 1
    assert alerts_in(db)[0].district_code == "Sukkur"


# --- dedupe + cooldown ----------------------------------------------------

def test_an_unchanged_condition_does_not_re_fire_on_the_next_run(db):
    flood = FakeFloodService({"Multan": flood_entry("HIGH", 70.0)})
    engine = build_engine(flood=flood)

    engine.run(db, now=T0)
    result = engine.run(db, now=T0 + timedelta(hours=1))

    assert result.alerts_raised == 0
    assert result.alerts_suppressed == 1
    assert result.suppressed[0].reason == "duplicate"
    assert len(alerts_in(db, type=TYPE_FLOOD)) == 1


def test_cooldown_blocks_a_re_fire_on_the_next_day_within_12_hours(db):
    """A new UTC day gives a fresh dedupe key, so the COOLDOWN is what has
    to stop the re-notification — 11 h after the first alert."""
    flood = FakeFloodService({"Multan": flood_entry("HIGH", 70.0)})
    engine = build_engine(flood=flood)

    engine.run(db, now=datetime(2026, 8, 12, 20, 0, tzinfo=timezone.utc))
    result = engine.run(db, now=datetime(2026, 8, 13, 7, 0, tzinfo=timezone.utc))

    assert result.alerts_raised == 0
    assert result.suppressed[0].reason == "cooldown"


def test_the_same_condition_re_notifies_once_the_cooldown_has_elapsed(db):
    flood = FakeFloodService({"Multan": flood_entry("HIGH", 70.0)})
    engine = build_engine(flood=flood)

    engine.run(db, now=datetime(2026, 8, 12, 6, 0, tzinfo=timezone.utc))
    result = engine.run(db, now=datetime(2026, 8, 13, 6, 0, tzinfo=timezone.utc))

    assert result.alerts_raised == 1
    flood_alerts = alerts_in(db, type=TYPE_FLOOD)
    assert len(flood_alerts) == 2
    # The superseded alert is closed, so a district never shows two open
    # alerts of the same type.
    assert [a.status for a in flood_alerts] == ["resolved", "active"]
    assert flood_alerts[0].payload["resolution_reason"] == "superseded"


def test_the_dedupe_key_is_district_type_level_and_day(db):
    assert dedupe_key_for("Multan", TYPE_FLOOD, 3, T0) == "Multan|FLOOD|3|2026-08-12"


def _save_fields(db, username, *specs):
    """specs are (name, district) pairs; returns the created field ids."""
    user = User(username=username, password_hash="x", password_salt="y")
    db.add(user)
    db.flush()
    fields = [
        FieldModel(user_id=user.id, name=name, district=district, crop_type="wheat")
        for name, district in specs
    ]
    db.add_all(fields)
    db.commit()
    return [f.id for f in fields]


def test_two_fields_in_one_district_each_get_their_own_irrigation_alert(db):
    """IRRIGATION_DUE is about a FIELD, not a district — two fields on the
    same farm are two separate decisions, so each gets its own alert."""
    field_ids = _save_fields(db, "farmer", ("North", "Multan"), ("South", "Multan"))

    result = build_engine(model=FakeModelService(12.0)).run(db, now=T0)

    assert result.alerts_raised == 2
    assert result.alerts_suppressed == 0
    alerts = alerts_in(db, type=TYPE_IRRIGATION_DUE)
    assert [a.payload["values"]["field_id"] for a in alerts] == field_ids
    assert [a.payload["subject"] for a in alerts] == [f"field:{i}" for i in field_ids]
    # Distinct dedupe keys, both scoped to the same district and day.
    assert len({a.dedupe_key for a in alerts}) == 2
    assert all(a.dedupe_key.startswith("Multan|IRRIGATION_DUE:field:") for a in alerts)


def test_one_field_produces_one_irrigation_alert_per_day(db):
    """Deduped per field per day: a second run the same day adds nothing."""
    _save_fields(db, "farmer_dedupe", ("North", "Multan"))
    engine = build_engine(model=FakeModelService(12.0))

    engine.run(db, now=T0)
    result = engine.run(db, now=T0 + timedelta(hours=2))

    assert result.alerts_raised == 0
    assert result.suppressed[0].reason == "duplicate"
    assert len(alerts_in(db, type=TYPE_IRRIGATION_DUE)) == 1


def test_one_fields_irrigation_alert_resolving_does_not_touch_the_other(db):
    """Per-field scoping has to hold through the whole life cycle, not just
    at creation — one field going quiet must not resolve the other's alert,
    which is exactly what a district-wide identity would have done."""
    field_ids = _save_fields(db, "farmer_split", ("North", "Multan"), ("South", "Multan"))
    engine = build_engine(model=FakeModelService(12.0))
    engine.run(db, now=T0)

    # The second field stops producing an outcome; the first keeps firing.
    db.query(FieldModel).filter(FieldModel.id == field_ids[1]).delete()
    db.commit()

    engine.run(db, now=T0 + timedelta(hours=13))
    engine.run(db, now=T0 + timedelta(hours=26))

    by_subject = {}
    for alert in alerts_in(db, type=TYPE_IRRIGATION_DUE):
        by_subject.setdefault(alert.payload["subject"], []).append(alert)

    # The removed field's alert cleared for two runs and resolved.
    assert by_subject[f"field:{field_ids[1]}"][-1].status == "resolved"
    # The surviving field is still open, and got an ALL_CLEAR only for the
    # field that actually went quiet.
    assert by_subject[f"field:{field_ids[0]}"][-1].status == "active"
    all_clears = alerts_in(db, type=TYPE_ALL_CLEAR)
    assert [a.payload["subject"] for a in all_clears] == [f"field:{field_ids[1]}"]


def test_irrigation_due_is_skipped_entirely_without_a_model(db):
    user = User(username="farmer2", password_hash="x", password_salt="y")
    db.add(user)
    db.flush()
    db.add(FieldModel(user_id=user.id, name="North", district="Multan", crop_type="wheat"))
    db.commit()

    build_engine(model=None).run(db, now=T0)
    assert alerts_in(db, type=TYPE_IRRIGATION_DUE) == []


def test_irrigation_due_is_skipped_when_the_model_cannot_predict(db):
    """No number means no alert — never an invented one (CLAUDE.md rule 4)."""
    user = User(username="farmer3", password_hash="x", password_salt="y")
    db.add(user)
    db.flush()
    db.add(FieldModel(user_id=user.id, name="North", district="Multan", crop_type="wheat"))
    db.commit()

    build_engine(model=FakeModelService(fail=True)).run(db, now=T0)
    assert alerts_in(db, type=TYPE_IRRIGATION_DUE) == []


# --- escalation -----------------------------------------------------------

def test_escalation_creates_a_new_alert_and_closes_the_lower_one(db):
    flood = FakeFloodService({"Multan": flood_entry("WATCH", 50.0)})
    engine = build_engine(flood=flood)
    engine.run(db, now=T0)

    flood.by_district["Multan"] = flood_entry("HIGH", 70.0)
    result = engine.run(db, now=T0 + timedelta(hours=1))

    assert result.alerts_raised == 1
    alerts = alerts_in(db, type=TYPE_FLOOD)
    assert [(a.level, a.status) for a in alerts] == [(2, "resolved"), (3, "active")]
    assert alerts[0].payload["resolution_reason"] == "superseded"


def test_escalation_ignores_the_cooldown(db):
    """A farmer must never wait out a 12 h cooldown to be told it got worse."""
    flood = FakeFloodService({"Multan": flood_entry("HIGH", 70.0)})
    engine = build_engine(flood=flood)
    engine.run(db, now=T0)

    flood.by_district["Multan"] = flood_entry("HIGH", 90.0)  # extreme -> level 5
    result = engine.run(db, now=T0 + timedelta(minutes=30))

    assert result.alerts_raised == 1
    assert alerts_in(db, type=TYPE_FLOOD)[-1].level == 5


def test_escalation_through_every_flood_level_leaves_exactly_one_active_alert(db):
    """2 -> 3 -> 4 -> 5. The ladder starts at WATCH because LOW writes
    nothing at all."""
    flood = FakeFloodService({"Multan": flood_entry("WATCH", 50.0)})
    engine = build_engine(flood=flood)
    engine.run(db, now=T0)

    for offset, entry in enumerate(
        [
            flood_entry("HIGH", 70.0),
            flood_entry("HIGH", 70.0, forecast=(10.0, 12.0, 14.0)),
            flood_entry("HIGH", 90.0),
        ],
        start=1,
    ):
        flood.by_district["Multan"] = entry
        engine.run(db, now=T0 + timedelta(minutes=offset))

    alerts = alerts_in(db, type=TYPE_FLOOD)
    assert [a.level for a in alerts] == [2, 3, 4, 5]
    assert [a.status for a in alerts].count("active") == 1
    assert alerts[-1].level == 5


# --- resolve + all clear --------------------------------------------------

def test_one_clear_run_is_not_enough_to_resolve(db):
    """A single failed upstream fetch must never declare a flood over."""
    flood = FakeFloodService({"Multan": flood_entry("HIGH", 70.0)})
    engine = build_engine(flood=flood)
    engine.run(db, now=T0)

    flood.by_district.pop("Multan")
    result = engine.run(db, now=T0 + timedelta(hours=13))

    assert result.alerts_resolved == 0
    alert = alerts_in(db, type=TYPE_FLOOD)[0]
    assert alert.status == "active"
    assert alert.payload["consecutive_clear_runs"] == 1


def test_two_consecutive_clear_runs_resolve_the_alert_and_emit_an_all_clear(db):
    flood = FakeFloodService({"Multan": flood_entry("HIGH", 70.0)})
    engine = build_engine(flood=flood)
    engine.run(db, now=T0)

    flood.by_district.pop("Multan")
    engine.run(db, now=T0 + timedelta(hours=13))
    result = engine.run(db, now=T0 + timedelta(hours=26))

    assert result.alerts_resolved == 1
    alert = alerts_in(db, type=TYPE_FLOOD)[0]
    assert alert.status == "resolved"
    assert alert.resolved_at is not None
    assert alert.payload["resolution_reason"] == "cleared"

    all_clear = alerts_in(db, type=TYPE_ALL_CLEAR)[0]
    assert all_clear.district_code == "Multan"
    assert all_clear.level == 1  # good news never blasts at warning urgency
    assert all_clear.status == "resolved"
    assert all_clear.payload["cleared_type"] == TYPE_FLOOD
    assert all_clear.payload["cleared_alert_id"] == alert.id
    assert result.all_clear_alert_ids == [all_clear.id]


def test_a_returning_condition_resets_the_clear_counter(db):
    flood = FakeFloodService({"Multan": flood_entry("HIGH", 70.0)})
    engine = build_engine(flood=flood)
    engine.run(db, now=T0)

    flood.by_district.pop("Multan")
    engine.run(db, now=T0 + timedelta(hours=1))  # one clear run
    flood.by_district["Multan"] = flood_entry("HIGH", 70.0)
    engine.run(db, now=T0 + timedelta(hours=2))  # condition is back

    alert = alerts_in(db, type=TYPE_FLOOD)[0]
    assert alert.status == "active"
    assert alert.payload["consecutive_clear_runs"] == 0


def test_an_acknowledged_alert_still_resolves_when_the_condition_clears(db):
    flood = FakeFloodService({"Multan": flood_entry("HIGH", 70.0)})
    engine = build_engine(flood=flood)
    engine.run(db, now=T0)

    alert = alerts_in(db, type=TYPE_FLOOD)[0]
    alert.status = "acknowledged"
    db.commit()

    flood.by_district.pop("Multan")
    engine.run(db, now=T0 + timedelta(hours=13))
    engine.run(db, now=T0 + timedelta(hours=26))

    db.refresh(alert)
    assert alert.status == "resolved"


def test_all_clear_rows_never_themselves_need_resolving(db):
    """An ALL_CLEAR is born resolved, so a later run must not treat it as an
    open alert that has gone quiet."""
    flood = FakeFloodService({"Multan": flood_entry("HIGH", 70.0)})
    engine = build_engine(flood=flood)
    engine.run(db, now=T0)
    flood.by_district.pop("Multan")
    engine.run(db, now=T0 + timedelta(hours=13))
    engine.run(db, now=T0 + timedelta(hours=26))

    result = engine.run(db, now=T0 + timedelta(hours=39))
    assert result.alerts_resolved == 0
    assert len(alerts_in(db, type=TYPE_ALL_CLEAR)) == 1


# --- OPS ------------------------------------------------------------------

def test_ops_alert_fires_on_significant_drift_and_is_filed_under_system(db):
    drift = FakeDriftService(status="significant_drift", features=[("temperature_c", 0.4)])
    build_engine(drift=drift).run(db, now=T0)

    ops_alert = alerts_in(db, type=TYPE_OPS)[0]
    assert ops_alert.district_code == SYSTEM_DISTRICT
    assert ops_alert.level == 0
    assert ops_alert.payload["values"]["max_psi"] == 0.4
    assert ops_alert.payload["values"]["triggers"] == ["drift_psi_alert"]


def test_ops_alert_fires_on_a_recorded_rollback_and_consumes_the_event(db):
    ops_events.record_ops_event("rollback", "rolled back to v1", now=T0)
    engine = build_engine()

    engine.run(db, now=T0)
    assert len(alerts_in(db, type=TYPE_OPS)) == 1

    # The event is consumed, so the next run does not re-raise it.
    engine.run(db, now=T0 + timedelta(hours=13))
    assert len(alerts_in(db, type=TYPE_OPS)) == 1
    assert ops_events.read_recent_events(now=T0 + timedelta(hours=13)) == []


def test_ops_events_older_than_the_max_age_are_ignored(db):
    ops_events.record_ops_event("rollback", "old rollback", now=T0 - timedelta(days=3))
    build_engine().run(db, now=T0)
    assert alerts_in(db, type=TYPE_OPS) == []


def test_insufficient_drift_data_never_raises_an_ops_alert(db):
    build_engine(drift=FakeDriftService(status="insufficient_data", features=[])).run(db, now=T0)
    assert alerts_in(db, type=TYPE_OPS) == []


def test_ops_alerts_are_excluded_from_the_farmer_facing_active_map(db):
    """An OPS notice is filed under SYSTEM and must never appear as a
    district — not even as a calm one."""
    drift = FakeDriftService(status="significant_drift", features=[("temperature_c", 0.4)])
    flood = FakeFloodService({"Multan": flood_entry("HIGH", 70.0)})
    build_engine(flood=flood, drift=drift).run(db, now=T0)

    active = highest_active_by_district(db)
    assert SYSTEM_DISTRICT not in {row["district"] for row in active}
    assert {row["district"] for row in active} == set(TEST_DISTRICTS)


# --- highest active by district -------------------------------------------

def test_active_map_reports_each_districts_highest_level(db):
    flood = FakeFloodService({"Multan": flood_entry("WATCH", 50.0)})
    weather = FakeWeatherService(
        {
            "Multan": [
                {"date": "2026-08-12", "temperature_max_c": 33.0, "rainfall_mm": 95.0},
                {"date": "2026-08-13", "temperature_max_c": 33.0, "rainfall_mm": 0.0},
                {"date": "2026-08-14", "temperature_max_c": 33.0, "rainfall_mm": 0.0},
            ]
        }
    )
    build_engine(flood=flood, weather=weather).run(db, now=T0)

    active = {row["district"]: row for row in highest_active_by_district(db)}
    assert len(active) == 3  # every district, not just the alerting ones
    assert active["Multan"]["level"] == 3  # heavy rain level 3 beats flood level 2
    assert active["Multan"]["type"] == TYPE_HEAVY_RAIN
    assert active["Multan"]["source"] == "alert"


def test_resolved_and_acknowledged_alerts_fall_back_to_the_calm_default(db):
    flood = FakeFloodService({"Multan": flood_entry("HIGH", 70.0)})
    build_engine(flood=flood).run(db, now=T0)

    alert = alerts_in(db, type=TYPE_FLOOD)[0]
    alert.status = "acknowledged"
    db.commit()

    multan = {row["district"]: row for row in highest_active_by_district(db)}["Multan"]
    assert multan["level"] == 1
    assert multan["source"] == "default"
    assert multan["alert_id"] is None


# --- the computed level-1 calm default ------------------------------------

def test_every_district_is_level_1_by_default_with_nothing_stored(db):
    """Level 1 is COMPUTED, not stored: an empty alerts table still yields a
    complete, white map."""
    rows = highest_active_by_district(db)

    assert {row["district"] for row in rows} == set(TEST_DISTRICTS)
    assert all(row["level"] == 1 for row in rows)
    assert all(row["source"] == "default" for row in rows)
    assert all(row["type"] is None and row["alert_id"] is None for row in rows)
    assert all(row["title_en"] and row["title_ur"] for row in rows)
    assert db.query(Alert).count() == 0


def test_an_alerting_district_sits_alongside_calm_ones_on_the_same_map(db):
    flood = FakeFloodService({"Multan": flood_entry("HIGH", 70.0)})
    build_engine(flood=flood).run(db, now=T0)

    rows = {row["district"]: row for row in highest_active_by_district(db)}
    assert rows["Multan"]["level"] == 3 and rows["Multan"]["source"] == "alert"
    assert rows["Sukkur"]["level"] == 1 and rows["Sukkur"]["source"] == "default"
    assert rows["Lahore"]["level"] == 1 and rows["Lahore"]["source"] == "default"


def test_a_real_level_1_irrigation_alert_is_distinguishable_from_the_default(db):
    """Both read "level 1" — `source` is what tells a console that one of
    them has something to say."""
    _save_fields(db, "farmer_default", ("North", "Multan"))
    build_engine(model=FakeModelService(12.0)).run(db, now=T0)

    rows = {row["district"]: row for row in highest_active_by_district(db)}
    assert rows["Multan"]["level"] == 1
    assert rows["Multan"]["source"] == "alert"
    assert rows["Multan"]["type"] == TYPE_IRRIGATION_DUE
    assert rows["Sukkur"]["level"] == 1
    assert rows["Sukkur"]["source"] == "default"


# --- delivery -------------------------------------------------------------

def test_every_raised_alert_gets_an_in_app_delivery_row(db):
    flood = FakeFloodService({"Multan": flood_entry("HIGH", 70.0)})
    build_engine(flood=flood).run(db, now=T0)

    delivery = db.query(AlertDelivery).one()
    assert delivery.channel == "in_app"
    assert delivery.status == "sent"
    assert delivery.subscription_id is None
    assert delivery.sent_at is not None


def test_a_matching_verified_subscription_records_an_honest_skipped_delivery(db):
    """Telegram/email transports arrive in Phase 3 — until then the
    delivery row says "skipped", never a fabricated "sent"."""
    db.add(
        AlertSubscription(
            channel="telegram", target="12345", districts=["Multan"], min_level=2, language="en", verified=True
        )
    )
    db.commit()

    flood = FakeFloodService({"Multan": flood_entry("HIGH", 70.0)})
    build_engine(flood=flood).run(db, now=T0)

    telegram = db.query(AlertDelivery).filter(AlertDelivery.channel == "telegram").one()
    assert telegram.status == "skipped"
    assert "Phase 3" in telegram.error


def test_a_subscription_for_another_district_gets_no_delivery(db):
    db.add(
        AlertSubscription(
            channel="email", target="a@b.c", districts=["Sukkur"], min_level=2, language="en", verified=True
        )
    )
    db.commit()

    flood = FakeFloodService({"Multan": flood_entry("HIGH", 70.0)})
    build_engine(flood=flood).run(db, now=T0)

    assert db.query(AlertDelivery).filter(AlertDelivery.channel == "email").count() == 0


def test_a_subscription_below_its_min_level_gets_no_delivery(db):
    db.add(
        AlertSubscription(
            channel="email", target="a@b.c", districts=[], min_level=4, language="en", verified=True
        )
    )
    db.commit()

    flood = FakeFloodService({"Multan": flood_entry("HIGH", 70.0)})  # level 3
    build_engine(flood=flood).run(db, now=T0)

    assert db.query(AlertDelivery).filter(AlertDelivery.channel == "email").count() == 0


def test_an_unverified_subscription_is_never_messaged(db):
    db.add(
        AlertSubscription(
            channel="email", target="a@b.c", districts=[], min_level=1, language="en", verified=False
        )
    )
    db.commit()

    flood = FakeFloodService({"Multan": flood_entry("HIGH", 70.0)})
    build_engine(flood=flood).run(db, now=T0)

    email = db.query(AlertDelivery).filter(AlertDelivery.channel == "email").one()
    assert email.status == "skipped"
    assert "not verified" in email.error


def test_a_level_1_alert_never_reaches_telegram_or_email(db):
    """Level 1 is in-app only — an irrigation advisory must not push a
    message, even to a subscriber who asked for min_level=1."""
    _save_fields(db, "farmer_l1", ("North", "Multan"))
    db.add(
        AlertSubscription(
            channel="telegram", target="1", districts=[], min_level=1, language="en", verified=True
        )
    )
    db.commit()

    build_engine(model=FakeModelService(12.0)).run(db, now=T0)

    assert len(alerts_in(db, type=TYPE_IRRIGATION_DUE)) == 1
    channels = {d.channel for d in db.query(AlertDelivery).all()}
    assert channels == {"in_app"}


# --- determinism ----------------------------------------------------------

def test_identical_inputs_produce_identical_alert_text(db):
    """CLAUDE.md rule 10: same inputs, same alert, every time."""
    flood = FakeFloodService({"Multan": flood_entry("HIGH", 70.0)})
    build_engine(flood=flood).run(db, now=T0)
    first = alerts_in(db, type=TYPE_FLOOD)[0]
    snapshot = (first.title_en, first.title_ur, first.body_en, first.body_ur, first.dedupe_key)

    db.query(AlertDelivery).delete()
    db.query(Alert).delete()
    db.commit()

    build_engine(flood=flood).run(db, now=T0)
    second = alerts_in(db, type=TYPE_FLOOD)[0]
    assert (second.title_en, second.title_ur, second.body_en, second.body_ur, second.dedupe_key) == snapshot
