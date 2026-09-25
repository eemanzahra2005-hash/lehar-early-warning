"""Deterministic, auditable alert rules (CLAUDE.md rule 10).

Every function here is PURE: plain numbers in, a RuleOutcome (or None) out.
No I/O, no clock, no database, no model, no LLM — engine.py does all the
fetching and hands the values over. That is what makes an alert auditable:
a reader can trace input -> threshold -> level without leaving this file,
and the same inputs always produce the same level.

Each outcome carries the VALUES it fired on, the THRESHOLDS it compared
them against and the SOURCE TIMESTAMPS behind them, so the stored alert
explains itself years later even if the thresholds have since changed.

Five rule families (see docs/ALERT_LEVELS.md for the farmer-facing view):

  FLOOD          app/services/flood.py's Flood Risk Index band
  HEAVY_RAIN     Open-Meteo daily precipitation_sum
  HEAT_STRESS    Open-Meteo daily temperature_2m_max
  IRRIGATION_DUE the model's predicted mm vs. a saved field's threshold
  OPS            platform health (drift PSI / quality gate / rollback)

Every threshold below is env-configurable (ALERT_* in app/config.py) —
AlertThresholds.from_settings() is the one place env values enter, and the
dataclass defaults ARE the documented defaults.
"""

from dataclasses import dataclass, field

from app.services.alerts.levels import OPS_LEVEL

TYPE_FLOOD = "FLOOD"
# LEHAR Phase 2.5: the same flood conditions, but PREDICTED 1-3 days ahead by
# the lead-time model (ml/flood_dl/) rather than read off today's GloFAS
# forecast. Deliberately its OWN type rather than a flag on FLOOD: the two
# have different evidence behind them and different lifetimes, a farmer must
# be able to tell "the river is high" from "the river is expected to rise",
# and keeping them separate means a forecast alert can never dedupe against,
# supersede or resolve an observed one.
TYPE_FLOOD_FORECAST = "FLOOD_FORECAST"
TYPE_HEAVY_RAIN = "HEAVY_RAIN"
TYPE_HEAT_STRESS = "HEAT_STRESS"
TYPE_IRRIGATION_DUE = "IRRIGATION_DUE"
TYPE_OPS = "OPS"
# Emitted by engine.py when a condition clears, never by a rule below.
TYPE_ALL_CLEAR = "ALL_CLEAR"

ALERT_TYPES = (
    TYPE_FLOOD,
    TYPE_FLOOD_FORECAST,
    TYPE_HEAVY_RAIN,
    TYPE_HEAT_STRESS,
    TYPE_IRRIGATION_DUE,
    TYPE_OPS,
    TYPE_ALL_CLEAR,
)

# The rule families the engine evaluates per district, in evaluation order.
DISTRICT_RULE_TYPES = (TYPE_FLOOD, TYPE_FLOOD_FORECAST, TYPE_HEAVY_RAIN, TYPE_HEAT_STRESS)

# app/services/flood.py bands -> base alert level. That module's middle band
# is spelled "WATCH"; "MEDIUM" is accepted as its synonym so a future
# renaming there can't silently stop producing level-2 flood alerts.
#
# LOW is deliberately ABSENT: a calm river is the normal state of almost
# every district on almost every day, and storing 107 "nothing is happening"
# rows daily would bury the alerts that matter, in the database and on the
# farmer's screen alike. Level 1 (white) is instead the COMPUTED DEFAULT
# that GET /api/v1/alerts/active reports for any district with no active
# alert — see engine.py's highest_active_by_district. The only rule that
# writes level-1 rows is IRRIGATION_DUE, which is about one specific saved
# field rather than a district-wide state.
FLOOD_BAND_LEVELS = {"WATCH": 2, "MEDIUM": 2, "HIGH": 3}

# Bands that mean "nothing to raise" rather than "unknown band". Listed
# explicitly so a LOW band is visibly a decision, not an oversight.
FLOOD_CALM_BANDS = ("LOW",)

# OPS trigger identifiers, recorded in the alert payload.
OPS_TRIGGER_DRIFT = "drift_psi_alert"
OPS_TRIGGER_QUALITY_GATE = "quality_gate_fail"
OPS_TRIGGER_ROLLBACK = "rollback"
OPS_TRIGGERS = (OPS_TRIGGER_DRIFT, OPS_TRIGGER_QUALITY_GATE, OPS_TRIGGER_ROLLBACK)


@dataclass(frozen=True)
class RuleOutcome:
    """One rule firing. `level` is an alerts/levels.py level number."""

    type: str
    level: int
    # What the rule actually saw (real measured/computed numbers only).
    values: dict
    # What it compared them against, as configured at evaluation time.
    thresholds: dict
    # Where the values came from and when, e.g. {"forecast_dates": [...]}.
    source_timestamps: dict = field(default_factory=dict)
    # One short human-readable line tracing input -> level. Shown in the
    # console's "why did this fire?" panel and stored in the payload.
    reason: str = ""
    # What this outcome is ABOUT within its district, when the district
    # alone is not specific enough. None for the district-wide rules
    # (FLOOD, HEAVY_RAIN, HEAT_STRESS, OPS); "field:<id>" for
    # IRRIGATION_DUE, which is about one saved field. The engine folds this
    # into the dedupe key and the open-alert lookup, so two fields in the
    # same district each get their own alert and their own life cycle
    # instead of colliding on one row.
    subject: str | None = None


@dataclass(frozen=True)
class AlertThresholds:
    """Every configurable number the rules below use, in one immutable
    bundle. The defaults here are the documented defaults — .env.example
    and docs/ALERT_LEVELS.md quote these exact values."""

    # --- FLOOD ---
    # Within the HIGH band: minimum relative rise in forecast river
    # discharge over the next 48 h for level 4 ("HIGH and still rising").
    flood_rising_pct: float = 0.05
    # Within the HIGH band: the "extreme" sub-band — Flood Risk Index score
    # at or above this is level 5 on its own.
    flood_extreme_score: float = 85.0
    # Level-5 discharge proxy. GloFAS via Open-Meteo publishes no return
    # period, so a >= 20-year event is APPROXIMATED by the forecast peak
    # being at least this multiple of the 30-day baseline median. This is a
    # documented proxy, never presented as a computed return period
    # (CLAUDE.md rule 4) — see docs/ALERT_LEVELS.md.
    flood_return_period_ratio: float = 3.0
    # The return period that proxy stands in for, and the value used
    # directly if a real return period is ever available.
    flood_return_period_years: int = 20

    # --- FLOOD_FORECAST (LEHAR Phase 2.5) ---
    # Lowest PREDICTED level that raises a forecast alert at all. 2, so a
    # predicted WATCH band is the quietest thing that can fire — a lead-time
    # alert exists to be acted on, and level 1 is the calm default that is
    # never stored (see engine.py).
    flood_forecast_min_level: int = 2
    # Highest level a PREDICTED flood may ever reach. 3 by default, which
    # deliberately stops one rung below the observation-driven FLOOD rule's
    # ceiling of 5. Levels 4 and 5 take over the whole screen and tell a
    # farmer to evacuate; a ~44k-parameter research model forecasting three
    # days ahead is not evidence enough to say that on its own, and the
    # observed FLOOD rule is still there to say it the moment the water
    # actually arrives. Raise it only with evidence from docs/FLOOD_DL.md's
    # measured hit rate and false-alarm rate.
    flood_forecast_max_level: int = 3

    # --- HEAVY_RAIN --- (Open-Meteo daily precipitation_sum, mm)
    heavy_rain_l2_mm: float = 30.0
    heavy_rain_l3_mm: float = 80.0

    # --- HEAT_STRESS --- (Open-Meteo daily temperature_2m_max, C)
    heat_l2_c: float = 40.0
    heat_l3_c: float = 45.0
    heat_consecutive_days: int = 2

    # --- IRRIGATION_DUE ---
    # Fallback threshold for a saved field that has no irrigation_threshold_mm
    # of its own (app/db.py's Field).
    irrigation_threshold_mm: float = 10.0
    # "No rain expected" means less than this much total rain over the next
    # irrigation_dry_days days.
    irrigation_dry_mm: float = 1.0
    irrigation_dry_days: int = 3

    # --- OPS ---
    # Mirrors DRIFT_PSI_ALERT (app/config.py) so the OPS rule and
    # GET /api/v1/monitoring/drift can never disagree about what "alert"
    # means; from_settings() copies the live value.
    drift_psi_alert: float = 0.25

    @classmethod
    def from_settings(cls, settings) -> "AlertThresholds":
        """Build from a Settings instance — the single place env values
        enter the rules. Keeping this off the module level means tests can
        construct thresholds directly without touching the environment."""
        return cls(
            flood_rising_pct=settings.alert_flood_rising_pct,
            flood_extreme_score=settings.alert_flood_extreme_score,
            flood_return_period_ratio=settings.alert_flood_return_period_ratio,
            flood_return_period_years=settings.alert_flood_return_period_years,
            flood_forecast_min_level=settings.alert_flood_forecast_min_level,
            flood_forecast_max_level=settings.alert_flood_forecast_max_level,
            heavy_rain_l2_mm=settings.alert_heavy_rain_l2_mm,
            heavy_rain_l3_mm=settings.alert_heavy_rain_l3_mm,
            heat_l2_c=settings.alert_heat_l2_c,
            heat_l3_c=settings.alert_heat_l3_c,
            heat_consecutive_days=settings.alert_heat_consecutive_days,
            irrigation_threshold_mm=settings.alert_irrigation_threshold_mm,
            irrigation_dry_mm=settings.alert_irrigation_dry_mm,
            irrigation_dry_days=settings.alert_irrigation_dry_days,
            drift_psi_alert=settings.drift_psi_alert,
        )


# --- FLOOD -------------------------------------------------------------


def discharge_rising_48h(forecast_values: list[float], rising_pct: float) -> bool:
    """True when river discharge is forecast to RISE over the next 48 hours.

    `forecast_values` is app/services/flood.py's forecast slice: index 0 is
    today, 1 is tomorrow, 2 is the day after — so indices 1 and 2 are the
    next 48 hours. Rising means the higher of those two is at least
    `rising_pct` above today's value. A series with fewer than 3 days can't
    answer the question, so it answers False rather than guessing."""
    if len(forecast_values) < 3:
        return False
    start = float(forecast_values[0])
    peak_48h = max(float(v) for v in forecast_values[1:3])
    if start <= 0.0:
        # A dry-to-wet transition off a zero baseline is a rise by any
        # reading, but a percentage of zero is undefined — decide it on the
        # raw value instead of dividing.
        return peak_48h > 0.0
    return (peak_48h - start) / start >= rising_pct


def evaluate_flood(
    *,
    band: str | None,
    score: float | None,
    forecast_discharge: list[float],
    anomaly_ratio: float | None,
    thresholds: AlertThresholds,
    return_period_years: float | None = None,
    forecast_dates: list[str] | None = None,
) -> RuleOutcome | None:
    """FLOOD levels, mapped from the existing Flood Risk Index band
    (app/services/flood.py) so the alert engine and Flood Watch can never
    disagree about a district:

        LOW                                      -> nothing (the calm default)
        WATCH (a.k.a. MEDIUM)                    -> 2
        HIGH                                     -> 3
        HIGH + discharge rising over next 48 h   -> 4
        HIGH + extreme sub-band, or >= 20-yr     -> 5
              return period (or its ratio proxy)

    A LOW band raises NOTHING. "The river is normal" is the state of almost
    every district on almost every day; it is reported as the computed
    level-1 default by GET /api/v1/alerts/active, not stored as an alert.

    Levels 4 and 5 are deliberately reachable only from within HIGH: the
    Flood Risk Index blends rainfall and exposure into its score, so a large
    discharge anomaly alone can still land in LOW, and "evacuate now" must
    never fire off a calm band."""
    if band is None:
        return None
    if band.upper() in FLOOD_CALM_BANDS:
        return None
    base = FLOOD_BAND_LEVELS.get(band.upper())
    if base is None:
        return None

    score_value = float(score) if score is not None else None
    ratio = float(anomaly_ratio) if anomaly_ratio is not None else None

    extreme_score = score_value is not None and score_value >= thresholds.flood_extreme_score
    # A real return period wins whenever one is available; the ratio proxy
    # is only consulted when it is not (documented in docs/ALERT_LEVELS.md).
    if return_period_years is not None:
        rare_event = float(return_period_years) >= thresholds.flood_return_period_years
        rarity_basis = f"return period {float(return_period_years):.0f} yr"
    else:
        rare_event = ratio is not None and ratio >= thresholds.flood_return_period_ratio
        rarity_basis = (
            f"discharge anomaly ratio {ratio:.2f}x the 30-day baseline median "
            f"(proxy for a >= {thresholds.flood_return_period_years}-year return period)"
            if ratio is not None
            else "no discharge anomaly available"
        )

    rising = discharge_rising_48h(forecast_discharge, thresholds.flood_rising_pct)

    score_suffix = f" (score {score_value:.1f})" if score_value is not None else ""

    if base < 3:
        level = base
        reason = f"Flood Risk Index band {band.upper()}{score_suffix}"
    elif extreme_score or rare_event:
        level = 5
        trigger = (
            f"extreme sub-band{score_suffix}, at or above {thresholds.flood_extreme_score:.0f}"
            if extreme_score
            else rarity_basis
        )
        reason = f"Flood Risk Index band HIGH with {trigger}"
    elif rising:
        level = 4
        reason = f"Flood Risk Index band HIGH{score_suffix} and river discharge rising over the next 48 h"
    else:
        level = 3
        reason = f"Flood Risk Index band HIGH{score_suffix}"

    return RuleOutcome(
        type=TYPE_FLOOD,
        level=level,
        values={
            "band": band.upper(),
            "score": score_value,
            "anomaly_ratio": ratio,
            "return_period_years": return_period_years,
            "discharge_rising_48h": rising,
            "forecast_discharge_m3s": [round(float(v), 2) for v in forecast_discharge[:3]],
        },
        thresholds={
            "band_levels": dict(FLOOD_BAND_LEVELS),
            "rising_pct": thresholds.flood_rising_pct,
            "extreme_score": thresholds.flood_extreme_score,
            "return_period_ratio": thresholds.flood_return_period_ratio,
            "return_period_years": thresholds.flood_return_period_years,
            "return_period_is_proxy": return_period_years is None,
        },
        source_timestamps={"forecast_dates": list(forecast_dates or [])[:3]},
        reason=reason,
    )


# --- FLOOD_FORECAST (LEHAR Phase 2.5) -----------------------------------


def evaluate_flood_forecast(
    *,
    band: str | None,
    score: float | None,
    predicted_discharge: list[float],
    anomaly_ratio: float | None,
    thresholds: AlertThresholds,
    current_discharge: float | None = None,
    model_version: str | None = None,
    lead_time_hours: int = 24,
    forecast_dates: list[str] | None = None,
    return_period_years: float | None = None,
) -> RuleOutcome | None:
    """FLOOD_FORECAST: the flood level the lead-time model says this district
    will be at 1-3 days from now.

    The level is computed by delegating to evaluate_flood() above with the
    PREDICTED discharge in place of the observed forecast slice — the same
    band table, the same rising-48 h test, the same extreme/rarity triggers,
    the same thresholds. That delegation is the point: a predicted level 3
    has to mean exactly what an observed level 3 means, only a day earlier,
    and two parallel implementations of "what level is this" would drift
    apart the first time a threshold moved.

    Two things then differ from the observed rule:

    **A ceiling.** The result is clamped to `flood_forecast_max_level` (3 by
    default). Levels 4 and 5 take over the farmer's whole screen and say
    "evacuate now"; a ~44k-parameter research model forecasting three days
    out is not, on its own, evidence enough to say that. The observed FLOOD
    rule still escalates to 4 and 5 the moment real discharge justifies it.
    When the clamp bites, the outcome records both the raw level and the
    fact that it was clamped, so the record shows what the mapping actually
    said.

    **A floor.** Anything below `flood_forecast_min_level` (2) raises
    nothing, for the same reason a LOW observed band does: level 1 is the
    calm default, computed rather than stored (see engine.py).

    `current_discharge` is today's OBSERVED value. It is prepended to the
    predicted series so the inherited rising-48 h test compares the next two
    predicted days against today, exactly as the observed rule compares the
    next two forecast days against today. Without it the rising test has too
    short a series and answers "not rising" rather than guessing.

    Pure, like every rule here: engine.py runs the model and hands the
    already-computed band, score and predicted discharge over."""
    values = [float(v) for v in predicted_discharge]
    series = ([float(current_discharge)] + values) if current_discharge is not None else values

    base = evaluate_flood(
        band=band,
        score=score,
        forecast_discharge=series,
        anomaly_ratio=anomaly_ratio,
        thresholds=thresholds,
        return_period_years=return_period_years,
        forecast_dates=forecast_dates,
    )
    if base is None:
        return None

    level = min(base.level, thresholds.flood_forecast_max_level)
    if level < thresholds.flood_forecast_min_level:
        return None

    rounded = [round(value, 3) for value in values]
    peak = max(rounded) if rounded else None
    ratio = float(anomaly_ratio) if anomaly_ratio is not None else None
    score_value = float(score) if score is not None else None
    score_suffix = f" (predicted score {score_value:.1f})" if score_value is not None else ""

    return RuleOutcome(
        type=TYPE_FLOOD_FORECAST,
        level=level,
        values={
            **base.values,
            "predicted_discharge_m3s": rounded,
            "predicted_peak_m3s": peak,
            "current_discharge_m3s": round(float(current_discharge), 3) if current_discharge is not None else None,
            "lead_time_hours": lead_time_hours,
            "horizon_days": list(range(1, len(rounded) + 1)),
            "model_version": model_version,
            "mapped_level_before_clamp": base.level,
            "clamped": base.level > level,
        },
        thresholds={
            **base.thresholds,
            "min_level": thresholds.flood_forecast_min_level,
            "max_level": thresholds.flood_forecast_max_level,
        },
        source_timestamps={"forecast_dates": list(forecast_dates or [])},
        reason=(
            f"Flood lead-time model {model_version or 'unversioned'} predicts band "
            f"{(band or '?').upper()}{score_suffix} over the next "
            f"{lead_time_hours * max(len(rounded), 1)} h"
            + (f", peaking at {peak:.2f} m3/s" if peak is not None else "")
            + (f" ({ratio:.2f}x the 30-day baseline median)" if ratio is not None else "")
            + f", issued {lead_time_hours} h ahead"
            + (
                f". Raw mapping was level {base.level}, clamped to {level} because a forecast never "
                f"raises above level {thresholds.flood_forecast_max_level}."
                if base.level > level
                else "."
            )
        ),
    )


# --- HEAVY_RAIN ---------------------------------------------------------


def evaluate_heavy_rain(
    *,
    daily_rain_mm: list[float],
    thresholds: AlertThresholds,
    dates: list[str] | None = None,
) -> RuleOutcome | None:
    """HEAVY_RAIN from Open-Meteo's daily precipitation_sum over the
    forecast window: the WETTEST single day decides the level.

        peak daily precipitation_sum >= 30 mm -> 2
        peak daily precipitation_sum >= 80 mm -> 3

    A single day is the right unit here: 80 mm spread over three days is a
    good soaking, 80 mm in one day floods a field."""
    if not daily_rain_mm:
        return None
    values = [float(v) for v in daily_rain_mm]
    peak = max(values)
    peak_index = values.index(peak)

    if peak >= thresholds.heavy_rain_l3_mm:
        level = 3
    elif peak >= thresholds.heavy_rain_l2_mm:
        level = 2
    else:
        return None

    peak_date = (dates or [])[peak_index] if dates and peak_index < len(dates) else None
    return RuleOutcome(
        type=TYPE_HEAVY_RAIN,
        level=level,
        values={
            "peak_daily_rain_mm": round(peak, 1),
            "peak_date": peak_date,
            "daily_rain_mm": [round(v, 1) for v in values],
            "total_rain_mm": round(sum(values), 1),
        },
        thresholds={"l2_mm": thresholds.heavy_rain_l2_mm, "l3_mm": thresholds.heavy_rain_l3_mm},
        source_timestamps={"forecast_dates": list(dates or [])},
        reason=f"Forecast peak daily rainfall {peak:.1f} mm"
        + (f" on {peak_date}" if peak_date else "")
        + f" (level-{level} threshold "
        + f"{thresholds.heavy_rain_l3_mm if level == 3 else thresholds.heavy_rain_l2_mm:.0f} mm)",
    )


# --- HEAT_STRESS --------------------------------------------------------


def longest_run_at_or_above(values: list[float], threshold: float) -> int:
    """Length of the longest run of CONSECUTIVE entries >= threshold."""
    longest = 0
    current = 0
    for value in values:
        if float(value) >= threshold:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def evaluate_heat_stress(
    *,
    daily_tmax_c: list[float],
    thresholds: AlertThresholds,
    dates: list[str] | None = None,
) -> RuleOutcome | None:
    """HEAT_STRESS from Open-Meteo's daily temperature_2m_max:

        >= 40 C on 2+ CONSECUTIVE days -> 2
        >= 45 C on any day             -> 3

    The consecutive-day requirement at level 2 exists because a single hot
    day is normal in a Pakistani summer — sustained heat is what damages a
    crop. Level 3 has no such requirement: 45 C is damaging on its own, and
    any 45 C day is by definition also a 40 C day."""
    if not daily_tmax_c:
        return None
    values = [float(v) for v in daily_tmax_c]
    peak = max(values)
    peak_index = values.index(peak)
    hot_run = longest_run_at_or_above(values, thresholds.heat_l2_c)

    if peak >= thresholds.heat_l3_c:
        level = 3
    elif hot_run >= thresholds.heat_consecutive_days:
        level = 2
    else:
        return None

    peak_date = (dates or [])[peak_index] if dates and peak_index < len(dates) else None
    if level == 3:
        reason = f"Forecast maximum temperature {peak:.1f} C" + (f" on {peak_date}" if peak_date else "")
        reason += f" at or above the {thresholds.heat_l3_c:.0f} C level-3 threshold"
    else:
        reason = (
            f"Forecast maximum temperature at or above {thresholds.heat_l2_c:.0f} C "
            f"on {hot_run} consecutive days (peak {peak:.1f} C)"
        )

    return RuleOutcome(
        type=TYPE_HEAT_STRESS,
        level=level,
        values={
            "peak_tmax_c": round(peak, 1),
            "peak_date": peak_date,
            "consecutive_days_at_or_above_l2": hot_run,
            "daily_tmax_c": [round(v, 1) for v in values],
        },
        thresholds={
            "l2_c": thresholds.heat_l2_c,
            "l3_c": thresholds.heat_l3_c,
            "consecutive_days": thresholds.heat_consecutive_days,
        },
        source_timestamps={"forecast_dates": list(dates or [])},
        reason=reason,
    )


# --- IRRIGATION_DUE -----------------------------------------------------


def evaluate_irrigation_due(
    *,
    predicted_mm: float | None,
    field_threshold_mm: float | None,
    daily_rain_mm: list[float],
    thresholds: AlertThresholds,
    field_id: int | None = None,
    field_name: str | None = None,
    crop_type: str | None = None,
    dates: list[str] | None = None,
) -> RuleOutcome | None:
    """IRRIGATION_DUE (level 1 only — this is decision support, not danger):

        predicted irrigation >= the field's threshold
        AND no rain expected for the next 3 days      -> 1

    "No rain expected" means the next `irrigation_dry_days` days add up to
    LESS than `irrigation_dry_mm` in total. A field with no threshold of its
    own falls back to ALERT_IRRIGATION_THRESHOLD_MM.

    This is the ONLY rule that writes level-1 alert rows, and the only one
    scoped to a single saved field rather than a whole district — hence the
    "field:<id>" subject, which gives each field its own alert, its own
    dedupe key and its own life cycle. (Every other level-1 state is the
    computed calm default; see engine.py's highest_active_by_district.)

    `predicted_mm` is None whenever the model could not produce a number —
    the rule then declines to fire rather than inventing one (CLAUDE.md
    rule 4)."""
    if predicted_mm is None:
        return None
    threshold = float(field_threshold_mm) if field_threshold_mm is not None else thresholds.irrigation_threshold_mm
    window = [float(v) for v in daily_rain_mm[: thresholds.irrigation_dry_days]]
    rain_total = sum(window)

    if float(predicted_mm) < threshold:
        return None
    if rain_total >= thresholds.irrigation_dry_mm:
        return None

    return RuleOutcome(
        type=TYPE_IRRIGATION_DUE,
        level=1,
        subject=f"field:{field_id}" if field_id is not None else None,
        values={
            "predicted_mm": round(float(predicted_mm), 2),
            "field_id": field_id,
            "field_name": field_name,
            "crop_type": crop_type,
            "rain_next_days_mm": round(rain_total, 1),
            "daily_rain_mm": [round(v, 1) for v in window],
        },
        thresholds={
            "field_threshold_mm": threshold,
            "field_threshold_source": "field" if field_threshold_mm is not None else "default",
            "dry_mm": thresholds.irrigation_dry_mm,
            "dry_days": thresholds.irrigation_dry_days,
        },
        source_timestamps={"forecast_dates": list(dates or [])[: thresholds.irrigation_dry_days]},
        reason=(
            f"Model recommends {float(predicted_mm):.1f} mm (threshold {threshold:.1f} mm) and only "
            f"{rain_total:.1f} mm of rain is forecast over the next {thresholds.irrigation_dry_days} days "
            f"(dry below {thresholds.irrigation_dry_mm:.1f} mm)"
        ),
    )


# --- OPS ----------------------------------------------------------------


def evaluate_ops(
    *,
    max_psi: float | None,
    psi_feature: str | None,
    drift_status: str | None,
    ops_events: list[dict],
    thresholds: AlertThresholds,
    model_version: str | None = None,
) -> RuleOutcome | None:
    """OPS (grey, admin-only, level 0) — platform health, never a weather
    condition and never shown to a farmer. Fires on any of:

        worst feature PSI >= DRIFT_PSI_ALERT   (app/services/drift.py)
        a quality-gate FAIL                    (ml/pipeline.py)
        a model rollback                       (POST /api/v1/models/rollback)

    `ops_events` are the recent recorded events from ops_events.py; PSI is
    computed live by the engine from DriftService. When drift reports
    "insufficient_data", `max_psi` is None and the drift trigger stays
    silent rather than treating "no data" as "no drift"."""
    triggers: list[str] = []
    if max_psi is not None and float(max_psi) >= thresholds.drift_psi_alert:
        triggers.append(OPS_TRIGGER_DRIFT)
    for event in ops_events:
        kind = event.get("kind")
        if kind in (OPS_TRIGGER_QUALITY_GATE, OPS_TRIGGER_ROLLBACK) and kind not in triggers:
            triggers.append(kind)

    if not triggers:
        return None

    parts: list[str] = []
    if OPS_TRIGGER_DRIFT in triggers:
        parts.append(
            f"PSI {float(max_psi):.4f}"
            + (f" on '{psi_feature}'" if psi_feature else "")
            + f" at or above DRIFT_PSI_ALERT={thresholds.drift_psi_alert}"
        )
    if OPS_TRIGGER_QUALITY_GATE in triggers:
        parts.append("a training run failed the quality gate")
    if OPS_TRIGGER_ROLLBACK in triggers:
        parts.append("the served model was rolled back")

    return RuleOutcome(
        type=TYPE_OPS,
        level=OPS_LEVEL,
        values={
            "triggers": triggers,
            "max_psi": round(float(max_psi), 4) if max_psi is not None else None,
            "psi_feature": psi_feature,
            "drift_status": drift_status,
            "model_version": model_version,
            "events": [
                {"kind": e.get("kind"), "detail": e.get("detail"), "recorded_at": e.get("recorded_at")}
                for e in ops_events
                if e.get("kind") in triggers
            ],
        },
        thresholds={"drift_psi_alert": thresholds.drift_psi_alert},
        source_timestamps={},
        reason="Operations: " + "; ".join(parts) + ".",
    )
