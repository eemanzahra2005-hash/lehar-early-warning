"""Farm Risk Score (Phase 6): a transparent, documented IRRIGATION-STRESS
(dryness) risk score — distinct from the Flood Risk Index in
app/services/flood.py, which measures the opposite extreme (too much
water). Every component is a simple, clamped [0, 1] linear formula computed
directly from inputs already shown to the user (soil moisture, ET0,
temperature, canal flow, rainfall) — never a black-box model output, and
never fabricated. See docs/RISK_SCORE.md for the full methodology and every
default.

This is a decision-support heuristic, NOT a validated agronomic index — see
the disclaimer in docs/RISK_SCORE.md, repeated on every UI surface that
shows this score.
"""

from app.config import get_settings

LOW_BAND_MAX = 34.0  # score < this -> LOW
HIGH_BAND_MIN = 66.0  # score > this -> HIGH; in between (inclusive) -> MODERATE

DISCLAIMER = (
    "Transparent decision-support heuristic, NOT a validated agronomic index — "
    "see docs/RISK_SCORE.md."
)


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def band_for_score(score: float) -> str:
    if score < LOW_BAND_MAX:
        return "LOW"
    if score > HIGH_BAND_MIN:
        return "HIGH"
    return "MODERATE"


def compute_components(
    *,
    soil_moisture_pct: float,
    evapotranspiration_mm: float,
    temperature_c: float,
    canal_flow_cusecs: float,
    rainfall_mm: float,
) -> dict:
    """The 5 Farm Risk Score components, each clamped to [0, 1]. See
    docs/RISK_SCORE.md for the justification of every divisor."""
    return {
        "moisture_deficit": clamp01((35.0 - soil_moisture_pct) / 25.0),
        "et0_demand": clamp01((evapotranspiration_mm - 5.0) / 5.0),
        "heat_stress": clamp01((temperature_c - 35.0) / 10.0),
        "water_scarcity": clamp01((300.0 - canal_flow_cusecs) / 300.0),
        "rain_relief": clamp01(rainfall_mm / 20.0),
    }


def compute_score(components: dict, weights: dict) -> float:
    """rain_relief is SUBTRACTED — recent rain lowers irrigation stress."""
    raw = (
        weights["moisture_deficit"] * components["moisture_deficit"]
        + weights["et0_demand"] * components["et0_demand"]
        + weights["heat_stress"] * components["heat_stress"]
        + weights["water_scarcity"] * components["water_scarcity"]
        - weights["rain_relief"] * components["rain_relief"]
    )
    return 100.0 * clamp01(raw)


class RiskService:
    """Stateless wrapper around compute_components/compute_score that reads
    weights from Settings once (env-configurable, RISK_W_*), so callers
    don't each have to know the env-var names."""

    def __init__(self, weights: dict | None = None):
        settings = get_settings()
        self._weights = weights or {
            "moisture_deficit": settings.risk_w_moisture_deficit,
            "et0_demand": settings.risk_w_et0_demand,
            "heat_stress": settings.risk_w_heat_stress,
            "water_scarcity": settings.risk_w_water_scarcity,
            "rain_relief": settings.risk_w_rain_relief,
        }

    def compute(
        self,
        *,
        soil_moisture_pct: float,
        evapotranspiration_mm: float,
        temperature_c: float,
        canal_flow_cusecs: float,
        rainfall_mm: float,
    ) -> dict:
        components = compute_components(
            soil_moisture_pct=soil_moisture_pct,
            evapotranspiration_mm=evapotranspiration_mm,
            temperature_c=temperature_c,
            canal_flow_cusecs=canal_flow_cusecs,
            rainfall_mm=rainfall_mm,
        )
        score = compute_score(components, self._weights)
        return {
            "score": round(score, 1),
            "band": band_for_score(score),
            "components": {k: round(v, 3) for k, v in components.items()},
        }
