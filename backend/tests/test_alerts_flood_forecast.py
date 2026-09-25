"""LEHAR Phase 2.5: the FLOOD_FORECAST alert type.

Three layers, all offline and none of them touching torch or a trained model:

  the rule      app/services/alerts/rules.py's evaluate_flood_forecast —
                pure numbers in, level out
  the messages  app/services/alerts/templates.py — bilingual, deterministic,
                and unmistakably about a FORECAST
  the engine    a full run with a fake flood-forecast service injected,
                proving a predicted flood raises its own alert without
                disturbing the observed FLOOD alert beside it
"""

from datetime import datetime, timezone

import pytest

from app.db import Alert, get_session_factory
from app.services.alerts import engine as engine_module
from app.services.alerts.engine import AlertEngine, dedupe_key_for, highest_active_by_district, type_component
from app.services.alerts.levels import DISCLAIMER_EN, DISCLAIMER_UR
from app.services.alerts.rules import (
    ALERT_TYPES,
    DISTRICT_RULE_TYPES,
    TYPE_FLOOD,
    TYPE_FLOOD_FORECAST,
    AlertThresholds,
    evaluate_flood,
    evaluate_flood_forecast,
)
from app.services.alerts.templates import render

T0 = datetime(2026, 8, 12, 6, 0, tzinfo=timezone.utc)
TEST_DISTRICTS = ("Multan", "Sukkur", "Lahore")

CALM_OUTLOOK = [
    {"date": "2026-08-12", "temperature_max_c": 32.0, "rainfall_mm": 0.5},
    {"date": "2026-08-13", "temperature_max_c": 33.0, "rainfall_mm": 0.0},
    {"date": "2026-08-14", "temperature_max_c": 33.0, "rainfall_mm": 0.0},
]

THRESHOLDS = AlertThresholds()


# --- the rule ---------------------------------------------------------------


def test_flood_forecast_is_a_registered_alert_type_and_a_district_rule():
    assert TYPE_FLOOD_FORECAST in ALERT_TYPES
    assert TYPE_FLOOD_FORECAST in DISTRICT_RULE_TYPES
    # Its own type, never a variant of FLOOD — the two must dedupe, escalate
    # and resolve independently.
    assert TYPE_FLOOD_FORECAST != TYPE_FLOOD


def test_a_predicted_low_band_raises_nothing():
    """The calm default is computed, not stored — a forecast of "the river
    will be fine" is not news."""
    assert (
        evaluate_flood_forecast(
            band="LOW",
            score=12.0,
            predicted_discharge=[4.0, 4.1, 4.0],
            anomaly_ratio=1.0,
            thresholds=THRESHOLDS,
            current_discharge=4.0,
        )
        is None
    )


def test_a_predicted_watch_band_raises_level_2():
    outcome = evaluate_flood_forecast(
        band="WATCH",
        score=48.0,
        predicted_discharge=[9.0, 12.0, 11.0],
        anomaly_ratio=2.0,
        thresholds=THRESHOLDS,
        current_discharge=6.0,
        model_version="vTEST",
    )
    assert outcome is not None
    assert outcome.type == TYPE_FLOOD_FORECAST
    assert outcome.level == 2
    assert outcome.values["predicted_peak_m3s"] == 12.0
    assert outcome.values["model_version"] == "vTEST"
    assert outcome.values["lead_time_hours"] == 24
    assert outcome.values["horizon_days"] == [1, 2, 3]


def test_a_predicted_high_band_raises_level_3():
    outcome = evaluate_flood_forecast(
        band="HIGH",
        score=70.0,
        predicted_discharge=[40.0, 39.0, 38.0],  # not rising
        anomaly_ratio=2.0,
        thresholds=THRESHOLDS,
        current_discharge=41.0,
    )
    assert outcome.level == 3
    assert outcome.values["clamped"] is False


def test_the_forecast_level_is_clamped_below_the_evacuate_levels():
    """A predicted HIGH-and-rising maps to level 4 under the shared FLOOD
    mapping. Level 4 takes over the farmer's whole screen and says
    "evacuate" — a three-day-ahead prediction from a small research model
    must not be what does that, so it is clamped to 3 and says so."""
    raw = evaluate_flood(
        band="HIGH",
        score=70.0,
        forecast_discharge=[10.0, 20.0, 30.0],
        anomaly_ratio=2.0,
        thresholds=THRESHOLDS,
    )
    assert raw.level == 4  # what the observed rule would say

    outcome = evaluate_flood_forecast(
        band="HIGH",
        score=70.0,
        predicted_discharge=[20.0, 30.0, 35.0],
        anomaly_ratio=2.0,
        thresholds=THRESHOLDS,
        current_discharge=10.0,
    )
    assert outcome.level == 3
    assert outcome.values["mapped_level_before_clamp"] == 4
    assert outcome.values["clamped"] is True
    assert "clamped to 3" in outcome.reason


def test_an_extreme_predicted_score_is_also_clamped():
    outcome = evaluate_flood_forecast(
        band="HIGH",
        score=92.0,  # the extreme sub-band: level 5 under the observed rule
        predicted_discharge=[80.0, 90.0, 85.0],
        anomaly_ratio=4.0,
        thresholds=THRESHOLDS,
        current_discharge=20.0,
    )
    assert outcome.values["mapped_level_before_clamp"] == 5
    assert outcome.level == 3


def test_raising_the_ceiling_lets_the_shared_mapping_through():
    """The clamp is configuration, not a hard-coded truncation — so the
    ceiling can be raised later on the evidence in docs/FLOOD_DL.md."""
    permissive = AlertThresholds(flood_forecast_max_level=5)
    outcome = evaluate_flood_forecast(
        band="HIGH",
        score=92.0,
        predicted_discharge=[80.0, 90.0, 85.0],
        anomaly_ratio=4.0,
        thresholds=permissive,
        current_discharge=20.0,
    )
    assert outcome.level == 5
    assert outcome.values["clamped"] is False


def test_the_minimum_level_suppresses_anything_quieter_than_an_advisory():
    strict = AlertThresholds(flood_forecast_min_level=3)
    assert (
        evaluate_flood_forecast(
            band="WATCH",
            score=48.0,
            predicted_discharge=[9.0, 12.0, 11.0],
            anomaly_ratio=2.0,
            thresholds=strict,
            current_discharge=6.0,
        )
        is None
    )


def test_the_forecast_rule_uses_the_same_band_table_as_the_observed_rule():
    """A predicted level and an observed level must mean the same thing."""
    for band, expected in (("WATCH", 2), ("MEDIUM", 2), ("HIGH", 3)):
        observed = evaluate_flood(
            band=band, score=50.0, forecast_discharge=[10.0, 10.0, 10.0], anomaly_ratio=1.5, thresholds=THRESHOLDS
        )
        predicted = evaluate_flood_forecast(
            band=band,
            score=50.0,
            predicted_discharge=[10.0, 10.0],
            anomaly_ratio=1.5,
            thresholds=THRESHOLDS,
            current_discharge=10.0,
        )
        assert observed.level == predicted.level == expected


def test_an_unknown_or_missing_band_raises_nothing():
    for band in (None, "SOMETHING_ELSE"):
        assert (
            evaluate_flood_forecast(
                band=band,
                score=50.0,
                predicted_discharge=[10.0],
                anomaly_ratio=1.0,
                thresholds=THRESHOLDS,
                current_discharge=10.0,
            )
            is None
        )


def test_the_outcome_records_the_evidence_it_fired_on():
    """An alert has to explain itself years later, even if the thresholds
    have moved since."""
    outcome = evaluate_flood_forecast(
        band="HIGH",
        score=71.5,
        predicted_discharge=[30.0, 44.0, 41.0],
        anomaly_ratio=3.2,
        thresholds=THRESHOLDS,
        current_discharge=14.0,
        model_version="v20260924T000000000000Z",
        forecast_dates=["2026-08-13", "2026-08-14", "2026-08-15"],
    )
    assert outcome.values["predicted_discharge_m3s"] == [30.0, 44.0, 41.0]
    assert outcome.values["current_discharge_m3s"] == 14.0
    assert outcome.source_timestamps["forecast_dates"] == ["2026-08-13", "2026-08-14", "2026-08-15"]
    assert outcome.thresholds["max_level"] == 3
    assert "v20260924T000000000000Z" in outcome.reason
    assert "24 h ahead" in outcome.reason


# --- the messages -----------------------------------------------------------


FORECAST_CONTEXT = {
    "district": "Multan",
    "reason": "forecast reason",
    "band": "HIGH",
    "score": 71.5,
    "anomaly_ratio": 3.2,
    "predicted_peak_m3s": 44.0,
    "lead_time_hours": 24,
    "model_version": "v20260924T000000000000Z",
}


@pytest.mark.parametrize("level", [2, 3, 4, 5])
def test_forecast_messages_say_forecast_in_both_languages(level):
    """The one thing a farmer must never do is read a prediction as a
    measurement."""
    message = render(TYPE_FLOOD_FORECAST, level, FORECAST_CONTEXT)
    assert "forecast" in message.title_en.lower()
    assert "FORECAST, not a measurement" in message.body_en
    assert "پیش گوئی" in message.title_ur
    assert "یہ پیش گوئی ہے، پیمائش نہیں" in message.body_ur


@pytest.mark.parametrize("level", [2, 3, 4, 5])
def test_forecast_messages_carry_the_mandated_disclaimer(level):
    """CLAUDE.md rule 12."""
    message = render(TYPE_FLOOD_FORECAST, level, FORECAST_CONTEXT)
    assert message.body_en.endswith(DISCLAIMER_EN)
    assert message.body_ur.endswith(DISCLAIMER_EN)
    assert DISCLAIMER_UR in message.body_ur


@pytest.mark.parametrize("level", [2, 3, 4, 5])
def test_forecast_messages_state_that_the_model_was_trained_on_real_data(level):
    """CLAUDE.md rule 13 in the other direction: this is the one model here
    trained on real measurements, and the message says so rather than
    letting the reader assume it shares the irrigation model's synthetic
    provenance."""
    message = render(TYPE_FLOOD_FORECAST, level, FORECAST_CONTEXT)
    assert "REAL data" in message.body_en
    assert "GloFAS" in message.body_en
    assert "may be wrong in either direction" in message.body_en
    assert "اصل (real) ڈیٹا" in message.body_ur


def test_forecast_messages_name_the_model_version():
    message = render(TYPE_FLOOD_FORECAST, 3, FORECAST_CONTEXT)
    assert "v20260924T000000000000Z" in message.body_en
    assert "v20260924T000000000000Z" in message.body_ur


def test_other_alert_types_messages_are_unchanged_by_this_phase():
    """CLAUDE.md rule 1 — the extra data note is added for FLOOD_FORECAST
    only; a FLOOD message must be byte-for-byte what it was."""
    message = render(TYPE_FLOOD, 3, {"district": "Multan", "reason": "r", "score": 70.0, "anomaly_ratio": 2.0})
    assert "may be wrong in either direction" not in message.body_en
    assert message.body_en.endswith(DISCLAIMER_EN)


# --- the engine -------------------------------------------------------------


class FakeFloodService:
    def __init__(self, by_district=None):
        self.by_district = by_district or {}

    def get_district(self, district):
        return self.by_district.get(district, {"district": district, "province": "x", "status": "unavailable"})


class FakeWeatherService:
    def fetch_daily_outlook(self, district, days=3):
        return CALM_OUTLOOK

    def fetch(self, district):
        return {"temperature_c": 30.0, "humidity_pct": 45.0, "rainfall_mm": 0.0, "evapotranspiration_mm": 5.0}


class FakeFloodForecastService:
    """Stands in for app/services/flood_forecast.py, in the shape the engine
    reads: the dict FloodForecastService.forecast() returns."""

    def __init__(self, by_district=None, available=True):
        self.by_district = by_district or {}
        self.available = available
        self.asked = []

    def is_available(self):
        return self.available

    def forecast_quietly(self, district):
        self.asked.append(district)
        if not self.available:
            return None
        return self.by_district.get(district)


def forecast_entry(band, score, predicted=(20.0, 30.0, 28.0), observed_last=10.0, ratio=2.5, version="vTEST0001"):
    return {
        "district": "x",
        "status": "ok",
        "model_version": version,
        "lead_time_hours": 24,
        "band": band,
        "score": score,
        "observed": {"unit": "m3/s", "dates": [], "values": [observed_last], "baseline_median": 8.0},
        "predicted": {
            "unit": "m3/s",
            "dates": ["2026-08-13", "2026-08-14", "2026-08-15"],
            "values": list(predicted),
            "peak": max(predicted),
            "anomaly_ratio": ratio,
        },
    }


def flood_entry(band, score, forecast=(10.0, 10.0, 10.0), ratio=1.0):
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


@pytest.fixture(autouse=True)
def _small_district_set(monkeypatch):
    from ml.districts import DISTRICTS as REAL_DISTRICTS

    monkeypatch.setattr(engine_module, "DISTRICTS", {name: REAL_DISTRICTS[name] for name in TEST_DISTRICTS})
    yield


@pytest.fixture(autouse=True)
def _isolated_ops_events(tmp_path, monkeypatch):
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


def build_engine(flood=None, forecast=None):
    return AlertEngine(
        flood_service=flood or FakeFloodService(),
        weather_service=FakeWeatherService(),
        flood_forecast_service=forecast,
    )


def test_a_run_without_a_forecast_service_behaves_exactly_as_before(db):
    """CLAUDE.md rule 1: a checkout with no flood lead-time model runs the
    Phase 2 engine unchanged."""
    engine = build_engine(flood=FakeFloodService({"Multan": flood_entry("HIGH", 70.0)}))
    result = engine.run(db, now=T0)

    types = {alert.type for alert in db.query(Alert).all()}
    assert types == {TYPE_FLOOD}
    assert result.alerts_raised == 1


def test_a_predicted_flood_raises_a_flood_forecast_alert(db):
    forecast = FakeFloodForecastService({"Multan": forecast_entry("HIGH", 68.0)})
    engine = build_engine(forecast=forecast)
    engine.run(db, now=T0)

    alerts = db.query(Alert).filter(Alert.type == TYPE_FLOOD_FORECAST).all()
    assert len(alerts) == 1
    alert = alerts[0]
    assert alert.district_code == "Multan"
    assert alert.level == 3
    assert alert.payload["values"]["model_version"] == "vTEST0001"
    assert alert.payload["values"]["lead_time_hours"] == 24
    assert alert.payload["values"]["horizon_days"] == [1, 2, 3]
    assert "forecast" in alert.title_en.lower()


def test_a_predicted_low_band_raises_nothing_in_a_real_run(db):
    forecast = FakeFloodForecastService({"Multan": forecast_entry("LOW", 15.0, predicted=(4.0, 4.0, 4.0))})
    engine = build_engine(forecast=forecast)
    result = engine.run(db, now=T0)

    assert db.query(Alert).count() == 0
    assert result.alerts_raised == 0
    # The run still happened and still checked the district.
    assert forecast.asked.count("Multan") == 1


def test_observed_and_predicted_flood_alerts_coexist_without_colliding(db):
    """They are different claims about different moments, so they get
    different alerts, different dedupe keys and independent life cycles."""
    engine = build_engine(
        flood=FakeFloodService({"Multan": flood_entry("WATCH", 45.0)}),
        forecast=FakeFloodForecastService({"Multan": forecast_entry("HIGH", 68.0)}),
    )
    engine.run(db, now=T0)

    by_type = {alert.type: alert for alert in db.query(Alert).all()}
    assert set(by_type) == {TYPE_FLOOD, TYPE_FLOOD_FORECAST}
    assert by_type[TYPE_FLOOD].level == 2
    assert by_type[TYPE_FLOOD_FORECAST].level == 3
    assert by_type[TYPE_FLOOD].dedupe_key != by_type[TYPE_FLOOD_FORECAST].dedupe_key
    assert by_type[TYPE_FLOOD_FORECAST].dedupe_key == dedupe_key_for(
        "Multan", type_component(TYPE_FLOOD_FORECAST), 3, T0
    )


def test_an_unchanged_forecast_is_deduped_on_a_second_run(db):
    forecast = FakeFloodForecastService({"Multan": forecast_entry("HIGH", 68.0)})
    engine = build_engine(forecast=forecast)
    engine.run(db, now=T0)
    second = engine.run(db, now=T0)

    assert db.query(Alert).filter(Alert.type == TYPE_FLOOD_FORECAST).count() == 1
    assert second.alerts_raised == 0
    assert second.alerts_suppressed == 1


def test_a_forecast_alert_colours_the_district_on_the_active_map(db):
    engine = build_engine(forecast=FakeFloodForecastService({"Sukkur": forecast_entry("HIGH", 68.0)}))
    engine.run(db, now=T0)

    rows = {row["district"]: row for row in highest_active_by_district(db)}
    assert rows["Sukkur"]["level"] == 3
    assert rows["Sukkur"]["source"] == "alert"
    assert rows["Sukkur"]["type"] == TYPE_FLOOD_FORECAST
    # Every other district stays on the computed calm default.
    assert rows["Lahore"]["level"] == 1 and rows["Lahore"]["source"] == "default"


def test_an_unavailable_forecast_service_never_fails_the_run(db):
    forecast = FakeFloodForecastService({"Multan": forecast_entry("HIGH", 68.0)}, available=False)
    engine = build_engine(
        flood=FakeFloodService({"Multan": flood_entry("HIGH", 70.0)}),
        forecast=forecast,
    )
    result = engine.run(db, now=T0)

    # The observed FLOOD alert still fired; only FLOOD_FORECAST is missing.
    assert {alert.type for alert in db.query(Alert).all()} == {TYPE_FLOOD}
    assert result.alerts_raised == 1


def test_a_forecast_alert_resolves_and_all_clears_when_the_prediction_calms(db):
    forecast = FakeFloodForecastService({"Multan": forecast_entry("HIGH", 68.0)})
    engine = build_engine(forecast=forecast)
    engine.run(db, now=T0)

    forecast.by_district = {}  # the model no longer predicts anything notable
    engine.run(db, now=T0)
    engine.run(db, now=T0)  # two clear runs, not one

    raised = db.query(Alert).filter(Alert.type == TYPE_FLOOD_FORECAST).one()
    assert raised.status == "resolved"
    assert raised.payload["resolution_reason"] == "cleared"
    all_clears = db.query(Alert).filter(Alert.type == "ALL_CLEAR").all()
    assert len(all_clears) == 1
    assert all_clears[0].payload["cleared_type"] == TYPE_FLOOD_FORECAST
    assert all_clears[0].level == 1
