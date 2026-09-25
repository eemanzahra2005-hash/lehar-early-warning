"""LEHAR Phase 2: the alert RULES and the bilingual message templates.

Everything here is pure arithmetic and string formatting — no database, no
network, no clock. Each rule is exercised at BOTH sides of every level
boundary (just below, exactly on, just above), because a threshold that is
off by one comparison operator is the most likely way this system could
mislead a farmer.
"""

import pytest

from app.services.alerts import rules as r
from app.services.alerts.levels import (
    DISCLAIMER_EN,
    DISCLAIMER_UR,
    FARMER_LEVELS,
    LEVELS,
    OPS_LEVEL,
    all_levels,
    channels_for,
)
from app.services.alerts.templates import render

T = r.AlertThresholds()  # the documented defaults


# --- levels.py: the scheme itself -----------------------------------------

def test_six_levels_exist_with_ops_outside_the_farmer_ladder():
    assert sorted(LEVELS) == [0, 1, 2, 3, 4, 5]
    assert OPS_LEVEL == 0
    assert LEVELS[OPS_LEVEL].audience == "admin"
    assert all(LEVELS[n].audience == "farmer" for n in FARMER_LEVELS)


def test_level_1_is_in_app_only_and_level_2_upward_adds_telegram_and_email():
    assert channels_for(1) == ("in_app",)
    for level in (2, 3, 4, 5):
        assert set(channels_for(level)) == {"in_app", "telegram", "email"}


def test_only_levels_4_and_5_take_over_the_screen():
    assert [n for n in sorted(LEVELS) if LEVELS[n].full_screen_takeover] == [4, 5]


def test_every_level_has_english_and_urdu_names_and_actions():
    for number, level in LEVELS.items():
        assert level.name_en and level.name_ur, number
        assert level.actions_en and level.actions_ur, number
        assert len(level.actions_en) == len(level.actions_ur), number


def test_all_levels_payload_carries_the_disclaimer_in_both_languages():
    for entry in all_levels():
        assert entry["disclaimer_en"] == DISCLAIMER_EN
        assert entry["disclaimer_ur"] == DISCLAIMER_UR


# --- FLOOD ----------------------------------------------------------------

def _flood(band, score=50.0, forecast=(10.0, 10.0, 10.0), ratio=1.0, **kwargs):
    return r.evaluate_flood(
        band=band,
        score=score,
        forecast_discharge=list(forecast),
        anomaly_ratio=ratio,
        thresholds=T,
        **kwargs,
    )


def test_flood_low_band_raises_nothing_at_all():
    """A calm river is the normal state of almost every district on almost
    every day. It is reported as the COMPUTED level-1 default by
    GET /api/v1/alerts/active, never stored as an alert row."""
    assert _flood("LOW", score=10.0) is None


def test_flood_low_is_a_declared_calm_band_not_an_unrecognised_one():
    """Distinguishes "we decided LOW is silent" from "LOW fell off the
    band map by accident"."""
    assert "LOW" in r.FLOOD_CALM_BANDS
    assert "LOW" not in r.FLOOD_BAND_LEVELS


def test_flood_watch_band_is_level_2():
    assert _flood("WATCH", score=50.0).level == 2


def test_flood_medium_is_accepted_as_a_synonym_for_watch():
    assert _flood("MEDIUM", score=50.0).level == 2


def test_flood_high_band_with_flat_discharge_is_level_3():
    assert _flood("HIGH", score=70.0, forecast=(10.0, 10.0, 10.0)).level == 3


def test_flood_high_band_with_rising_discharge_is_level_4():
    # +10% on day 2 — comfortably over the 5% rising threshold.
    assert _flood("HIGH", score=70.0, forecast=(10.0, 10.5, 11.0)).level == 4


def test_flood_rising_at_exactly_the_threshold_escalates_to_4():
    # Exactly +5%: the rule uses >=, so the boundary itself escalates.
    assert _flood("HIGH", score=70.0, forecast=(10.0, 10.0, 10.5)).level == 4


def test_flood_rising_just_below_the_threshold_stays_at_3():
    assert _flood("HIGH", score=70.0, forecast=(10.0, 10.0, 10.49)).level == 3


def test_flood_extreme_score_is_level_5_even_without_a_rise():
    assert _flood("HIGH", score=85.0, forecast=(10.0, 10.0, 10.0)).level == 5


def test_flood_just_below_the_extreme_score_is_not_level_5():
    assert _flood("HIGH", score=84.9, forecast=(10.0, 10.0, 10.0)).level == 3


def test_flood_anomaly_ratio_proxy_for_a_20_year_event_is_level_5():
    outcome = _flood("HIGH", score=70.0, ratio=3.0)
    assert outcome.level == 5
    # The payload must say this was a PROXY, never a computed return period.
    assert outcome.thresholds["return_period_is_proxy"] is True
    assert outcome.values["return_period_years"] is None


def test_flood_anomaly_ratio_just_below_the_proxy_is_not_level_5():
    assert _flood("HIGH", score=70.0, ratio=2.99).level == 3


def test_flood_real_return_period_of_20_years_is_level_5_and_not_flagged_a_proxy():
    outcome = _flood("HIGH", score=70.0, ratio=1.0, return_period_years=20)
    assert outcome.level == 5
    assert outcome.thresholds["return_period_is_proxy"] is False


def test_flood_real_return_period_below_20_years_does_not_reach_level_5():
    assert _flood("HIGH", score=70.0, ratio=5.0, return_period_years=19).level == 3


def test_flood_levels_4_and_5_are_unreachable_from_a_low_band():
    """A big discharge anomaly can still score LOW once rainfall and
    exposure are folded in — "evacuate now" must never fire from a calm
    band, and on LOW nothing fires at all."""
    assert _flood("LOW", score=20.0, ratio=9.0, forecast=(1.0, 5.0, 9.0)) is None


def test_flood_returns_nothing_for_an_unknown_or_missing_band():
    assert _flood(None) is None
    assert _flood("SOMETHING_ELSE") is None


def test_discharge_rising_needs_three_days_to_decide():
    assert r.discharge_rising_48h([10.0, 99.0], T.flood_rising_pct) is False


def test_discharge_rising_off_a_zero_baseline_uses_the_raw_value():
    assert r.discharge_rising_48h([0.0, 0.0, 0.1], T.flood_rising_pct) is True
    assert r.discharge_rising_48h([0.0, 0.0, 0.0], T.flood_rising_pct) is False


# --- HEAVY_RAIN -----------------------------------------------------------

def _rain(values):
    return r.evaluate_heavy_rain(daily_rain_mm=list(values), thresholds=T, dates=["d0", "d1", "d2"])


def test_heavy_rain_below_30mm_does_not_fire():
    assert _rain([29.9, 10.0, 5.0]) is None


def test_heavy_rain_at_exactly_30mm_is_level_2():
    assert _rain([30.0, 10.0, 5.0]).level == 2


def test_heavy_rain_just_below_80mm_is_still_level_2():
    assert _rain([79.9, 10.0, 5.0]).level == 2


def test_heavy_rain_at_exactly_80mm_is_level_3():
    assert _rain([80.0, 10.0, 5.0]).level == 3


def test_heavy_rain_uses_the_wettest_single_day_not_the_total():
    """3 x 29mm is 87mm in total but floods nothing — the rule must not
    fire on the sum."""
    assert _rain([29.0, 29.0, 29.0]) is None


def test_heavy_rain_reports_the_peak_day_and_its_date():
    outcome = _rain([5.0, 95.0, 5.0])
    assert outcome.values["peak_daily_rain_mm"] == 95.0
    assert outcome.values["peak_date"] == "d1"


def test_heavy_rain_with_no_forecast_does_not_fire():
    assert _rain([]) is None


# --- HEAT_STRESS ----------------------------------------------------------

def _heat(values):
    dates = [f"d{i}" for i in range(len(values))]
    return r.evaluate_heat_stress(daily_tmax_c=list(values), thresholds=T, dates=dates)


def test_heat_one_hot_day_alone_does_not_fire():
    assert _heat([41.0, 30.0, 30.0]) is None


def test_heat_two_consecutive_days_at_exactly_40c_is_level_2():
    assert _heat([40.0, 40.0, 30.0]).level == 2


def test_heat_two_hot_days_that_are_not_consecutive_do_not_fire():
    assert _heat([41.0, 30.0, 41.0]) is None


def test_heat_just_below_40c_on_both_days_does_not_fire():
    assert _heat([39.9, 39.9, 39.9]) is None


def test_heat_at_exactly_45c_is_level_3():
    assert _heat([45.0, 30.0, 30.0]).level == 3


def test_heat_just_below_45c_needs_the_consecutive_run_and_stays_level_2():
    assert _heat([44.9, 44.9, 30.0]).level == 2


def test_heat_a_single_45c_day_is_level_3_without_a_consecutive_run():
    """45 C damages a crop on its own, so level 3 deliberately has no
    consecutive-day requirement."""
    outcome = _heat([30.0, 45.5, 30.0])
    assert outcome.level == 3
    assert outcome.values["consecutive_days_at_or_above_l2"] == 1


def test_longest_run_counts_only_consecutive_entries():
    assert r.longest_run_at_or_above([41, 41, 30, 41], 40.0) == 2
    assert r.longest_run_at_or_above([30, 30], 40.0) == 0


# --- IRRIGATION_DUE -------------------------------------------------------

def _irrigation(predicted, rain, threshold=None):
    return r.evaluate_irrigation_due(
        predicted_mm=predicted,
        field_threshold_mm=threshold,
        daily_rain_mm=list(rain),
        thresholds=T,
        field_name="North Plot",
        crop_type="wheat",
        dates=["d0", "d1", "d2"],
    )


def test_irrigation_due_fires_at_exactly_the_default_threshold_when_dry():
    outcome = _irrigation(10.0, [0.0, 0.0, 0.0])
    assert outcome.level == 1
    assert outcome.thresholds["field_threshold_source"] == "default"


def test_irrigation_due_does_not_fire_just_below_the_threshold():
    assert _irrigation(9.9, [0.0, 0.0, 0.0]) is None


def test_irrigation_due_uses_the_fields_own_threshold_when_it_has_one():
    assert _irrigation(6.0, [0.0, 0.0, 0.0], threshold=5.0).thresholds["field_threshold_source"] == "field"
    assert _irrigation(6.0, [0.0, 0.0, 0.0], threshold=7.0) is None


def test_irrigation_due_does_not_fire_when_rain_is_expected():
    assert _irrigation(20.0, [0.0, 0.0, 1.0]) is None


def test_irrigation_due_at_exactly_the_dry_limit_counts_as_wet():
    """"No rain expected" is strictly BELOW ALERT_IRRIGATION_DRY_MM, so
    exactly 1.0 mm is rain and suppresses the advisory."""
    assert _irrigation(20.0, [0.5, 0.5, 0.0]) is None
    assert _irrigation(20.0, [0.5, 0.49, 0.0]).level == 1


def test_irrigation_due_only_looks_at_the_configured_dry_window():
    # Day 4 rain is outside the 3-day window and must not suppress today.
    assert _irrigation(20.0, [0.0, 0.0, 0.0, 50.0]).level == 1


def test_irrigation_due_never_fires_without_a_real_prediction():
    """No model number means no alert — never an invented one
    (CLAUDE.md rule 4)."""
    assert _irrigation(None, [0.0, 0.0, 0.0]) is None


# --- OPS ------------------------------------------------------------------

def _ops(max_psi=None, events=(), drift_status=None):
    return r.evaluate_ops(
        max_psi=max_psi,
        psi_feature="temperature_c" if max_psi is not None else None,
        drift_status=drift_status,
        ops_events=list(events),
        thresholds=T,
        model_version="v1",
    )


def test_ops_does_not_fire_when_everything_is_healthy():
    assert _ops(max_psi=0.24, drift_status="warning") is None


def test_ops_fires_at_exactly_the_psi_alert_threshold():
    outcome = _ops(max_psi=0.25, drift_status="significant_drift")
    assert outcome.level == OPS_LEVEL
    assert outcome.values["triggers"] == [r.OPS_TRIGGER_DRIFT]


def test_ops_treats_missing_psi_as_no_data_not_as_no_drift():
    assert _ops(max_psi=None, drift_status="insufficient_data") is None


def test_ops_fires_on_a_quality_gate_failure():
    outcome = _ops(events=[{"kind": "quality_gate_fail", "detail": "MAE too high", "recorded_at": "x"}])
    assert outcome.values["triggers"] == [r.OPS_TRIGGER_QUALITY_GATE]


def test_ops_fires_on_a_rollback():
    outcome = _ops(events=[{"kind": "rollback", "detail": "rolled back to v1", "recorded_at": "x"}])
    assert outcome.values["triggers"] == [r.OPS_TRIGGER_ROLLBACK]


def test_ops_ignores_event_kinds_it_does_not_know():
    assert _ops(events=[{"kind": "something_else", "detail": "", "recorded_at": "x"}]) is None


def test_ops_combines_every_trigger_that_is_active():
    outcome = _ops(
        max_psi=0.9,
        events=[
            {"kind": "rollback", "detail": "d", "recorded_at": "x"},
            {"kind": "quality_gate_fail", "detail": "d", "recorded_at": "x"},
        ],
    )
    assert set(outcome.values["triggers"]) == set(r.OPS_TRIGGERS)


# --- thresholds from settings --------------------------------------------

def test_thresholds_from_settings_match_the_documented_defaults():
    """The dataclass defaults and app/config.py's ALERT_* defaults are two
    copies of the same numbers — this asserts they agree."""
    from app.config import get_settings

    from_settings = r.AlertThresholds.from_settings(get_settings())
    assert from_settings == T


# --- templates ------------------------------------------------------------

def _all_rendered_messages():
    """One rendered message per (type, level) pair the templates declare."""
    contexts = {
        "district": "Multan",
        "reason": "test reason",
        "score": 70.0,
        "anomaly_ratio": 2.0,
        "peak_daily_rain_mm": 90.0,
        "peak_date": "2026-08-12",
        "total_rain_mm": 120.0,
        "peak_tmax_c": 46.0,
        "consecutive_days_at_or_above_l2": 2,
        "l2_c": 40.0,
        "predicted_mm": 12.0,
        "rain_next_days_mm": 0.0,
        "dry_days": 3,
        "field_name": "North Plot",
        "crop_type": "wheat",
        "cleared_type": "FLOOD",
        "clear_runs": 2,
    }
    from app.services.alerts.templates import TITLES

    for alert_type, by_level in TITLES.items():
        for level in by_level:
            yield alert_type, level, render(alert_type, level, contexts)


def test_every_message_ends_with_the_mandated_disclaimer_in_both_languages():
    """CLAUDE.md rule 12 — the exact sentence, on every message, in either
    language the farmer reads."""
    for alert_type, level, message in _all_rendered_messages():
        assert message.body_en.endswith(DISCLAIMER_EN), (alert_type, level)
        assert message.body_ur.endswith(DISCLAIMER_EN), (alert_type, level)
        assert DISCLAIMER_UR in message.body_ur, (alert_type, level)


def test_every_message_has_a_non_empty_title_and_body_in_both_languages():
    for alert_type, level, message in _all_rendered_messages():
        assert message.title_en.strip() and message.title_ur.strip(), (alert_type, level)
        assert message.body_en.strip() and message.body_ur.strip(), (alert_type, level)


def test_every_farmer_message_says_the_training_data_is_synthetic():
    """CLAUDE.md rule 13 — the synthetic label travels with the artifact,
    not only with the docs."""
    for alert_type, level, message in _all_rendered_messages():
        if alert_type == r.TYPE_OPS:
            continue
        assert "SYNTHETIC" in message.body_en, (alert_type, level)
        assert "synthetic" in message.body_ur, (alert_type, level)


def test_messages_carry_the_level_name_and_the_farmer_actions():
    message = render(r.TYPE_FLOOD, 4, {"district": "Sukkur", "score": 78.0, "anomaly_ratio": 2.1})
    assert "Urgent Warning" in message.body_en
    assert LEVELS[4].actions_en[0] in message.body_en
    assert LEVELS[4].actions_ur[0] in message.body_ur


def test_rendering_is_deterministic_for_identical_input():
    context = {"district": "Lahore", "score": 70.0, "anomaly_ratio": 2.0, "reason": "x"}
    first = render(r.TYPE_FLOOD, 3, context)
    second = render(r.TYPE_FLOOD, 3, dict(context))
    assert first.as_dict() == second.as_dict()


def test_a_missing_value_renders_as_na_instead_of_raising():
    """An alert must still reach the farmer when one optional number was
    unavailable."""
    message = render(r.TYPE_FLOOD, 3, {"district": "Multan"})
    assert "n/a" in message.body_en
    assert message.body_en.endswith(DISCLAIMER_EN)


def test_render_rejects_a_level_that_is_not_in_the_scheme():
    with pytest.raises(KeyError):
        render(r.TYPE_FLOOD, 9, {"district": "Multan"})
