"""
Phase 8: Population Stability Index (PSI) data-drift monitoring.

Compares the CURRENT production model's training-time reference
distribution (reference_distribution.json, written into the model's
version folder by ml/pipeline.py's compute_reference_distribution() — see
ml/train_model.py's save_versioned_model()) against the last
DRIFT_WINDOW real prediction inputs logged to prediction_logs
(app/db.py's PredictionLog — weather + soil + canal values are already
recorded on every /predict call).

PSI is a simple, widely-used drift heuristic — NOT a rigorous statistical
test. DRIFT_PSI_WARN=0.1 / DRIFT_PSI_ALERT=0.25 (app/config.py) are common
industry rules of thumb (credit-risk-scoring literature), not
scientifically validated for irrigation/weather data specifically — see
docs/DRIFT.md.

Honesty rule (CLAUDE.md rule 4): with fewer than DRIFT_MIN_SAMPLES real
predictions logged, or no reference_distribution.json for the active model
version, this reports status="insufficient_data" with the REAL sample
count — never a fabricated PSI computed on too little (or no) baseline
data to mean anything.
"""

import json
import logging
import math
from dataclasses import dataclass, field

# numpy is imported lazily inside the functions that need it, not here —
# this module is imported unconditionally by app/dependencies.py, and a
# top-level `import numpy` would force it into every worker process
# regardless of whether /api/v1/monitoring/drift is ever hit
# (LOW_MEMORY_MODE, Phase 13.1 — see docs/DEPLOY_RENDER.md).
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import PredictionLog
from app.services.ml_model import ModelService

logger = logging.getLogger("app.drift")

# Laplace ("add-one") smoothing constant added to every bin's raw count
# before normalizing to a proportion — see _psi_from_counts()'s docstring
# for why this matters more than a fixed-epsilon floor at this app's
# realistic window sizes (DRIFT_WINDOW/DRIFT_MIN_SAMPLES default 200/50).
LAPLACE_ALPHA = 1.0

STABLE = "stable"
WARNING = "warning"
SIGNIFICANT_DRIFT = "significant_drift"
INSUFFICIENT_DATA = "insufficient_data"
_BAND_RANK = {STABLE: 0, WARNING: 1, SIGNIFICANT_DRIFT: 2}

# Same 6 numeric + 2 categorical features ml/pipeline.py's
# compute_reference_distribution() computes the baseline for — exactly the
# columns PredictionLog logs per prediction (app/db.py).
DRIFT_NUMERIC_FEATURES = [
    "temperature_c",
    "humidity_pct",
    "rainfall_mm",
    "evapotranspiration_mm",
    "canal_flow_cusecs",
    "soil_moisture_pct",
]
DRIFT_CATEGORICAL_FEATURES = ["district", "crop_type"]


def band_for_psi(psi: float, warn: float, alert: float) -> str:
    if psi >= alert:
        return SIGNIFICANT_DRIFT
    if psi >= warn:
        return WARNING
    return STABLE


def _psi_from_counts(reference_counts, current_counts, alpha: float = LAPLACE_ALPHA) -> float:
    """Standard PSI: sum((current - reference) * ln(current / reference))
    over aligned bins, computed from RAW COUNTS with Laplace ("add-one")
    smoothing rather than flooring proportions at a fixed epsilon.

    Why: DRIFT_WINDOW/DRIFT_MIN_SAMPLES (app/config.py) default to 200/50 —
    a live "current" window this small, split across the reference's 20
    fixed bins, will often land ZERO samples in a tail bin purely by
    chance even with no real drift at all (average ~2.5-10 samples/bin).
    Flooring such a bin's proportion at a tiny constant epsilon makes it
    look dramatically different from a reference bin that has a real, if
    small, share — inflating PSI on pure sampling noise, not drift. Adding
    `alpha` to every bin's raw COUNT before normalizing (both windows,
    symmetrically) is the standard fix: it scales the smoothing to the
    actual sample size instead of an arbitrary fixed proportion, so a
    same-population resample stays close to 0 while a real, large shift in
    mass still dominates and produces a large PSI (verified empirically —
    see backend/tests/test_drift.py)."""
    import numpy as np

    reference_counts = np.asarray(reference_counts, dtype=float)
    current_counts = np.asarray(current_counts, dtype=float)
    reference_total = reference_counts.sum() + alpha * len(reference_counts)
    current_total = current_counts.sum() + alpha * len(current_counts)
    reference_props = (reference_counts + alpha) / reference_total
    current_props = (current_counts + alpha) / current_total

    total = 0.0
    for ref_p, cur_p in zip(reference_props, current_props):
        total += (cur_p - ref_p) * math.log(cur_p / ref_p)
    return float(total)


def _numeric_drift(reference: dict, values: list[float]) -> dict:
    """Bins the CURRENT window into the reference's exact histogram edges
    (never recomputed — a fresh binning would make two histograms
    incomparable) and computes PSI. Current values outside the reference's
    min/max are clipped into the outermost bin rather than dropped, so a
    real shift outside the historical range still shows up as drift
    instead of being silently discarded."""
    import numpy as np

    edges = np.asarray(reference["hist_edges"], dtype=float)
    reference_counts = np.asarray(reference["hist_counts"], dtype=float)

    clipped = np.clip(np.asarray(values, dtype=float), edges[0], edges[-1])
    current_counts, _ = np.histogram(clipped, bins=edges)

    psi = _psi_from_counts(reference_counts, current_counts)
    return {
        "psi": round(psi, 4),
        "reference_hist": {"edges": edges.tolist(), "counts": reference_counts.astype(int).tolist()},
        "current_hist": {"edges": edges.tolist(), "counts": current_counts.astype(int).tolist()},
    }


def _categorical_drift(reference_counts: dict, values: list[str]) -> dict:
    """Aligns reference + current value counts onto the union of categories
    seen in either window (a brand-new crop/district value in current
    traffic that never appeared in training is real drift, not an error)."""
    current_counts: dict[str, int] = {}
    for value in values:
        current_counts[value] = current_counts.get(value, 0) + 1

    categories = sorted(set(reference_counts) | set(current_counts))
    reference_counts_arr = [reference_counts.get(c, 0) for c in categories]
    current_counts_arr = [current_counts.get(c, 0) for c in categories]

    psi = _psi_from_counts(reference_counts_arr, current_counts_arr)
    return {
        "psi": round(psi, 4),
        "reference_hist": {"edges": categories, "counts": [int(reference_counts.get(c, 0)) for c in categories]},
        "current_hist": {"edges": categories, "counts": [int(current_counts.get(c, 0)) for c in categories]},
    }


@dataclass
class DriftFeatureResult:
    name: str
    psi: float
    band: str  # "stable" | "warning" | "significant_drift"
    reference_hist: dict
    current_hist: dict


@dataclass
class DriftReport:
    status: str  # "stable" | "warning" | "significant_drift" | "insufficient_data"
    window_used: int
    samples_available: int
    reference_model_version: str | None
    # Real, currently-configured DRIFT_PSI_WARN/DRIFT_PSI_ALERT (app/config.py)
    # — surfaced so the UI can draw its threshold lines from the actual
    # config rather than a hardcoded guess that could go stale.
    psi_warn: float
    psi_alert: float
    features: list[DriftFeatureResult] = field(default_factory=list)


class DriftService:
    """Reads the CURRENT production model's reference_distribution.json —
    re-resolved from model_service.version on every call, never cached
    across a promote/rollback (see app/dependencies.py's
    _drift_service_for, keyed by ModelService identity so a hot-reloaded
    model naturally invalidates the cache) — and the last DRIFT_WINDOW rows
    of prediction_logs to compute per-feature PSI."""

    def __init__(self, model_service: ModelService):
        self._model_service = model_service

    def _load_reference_distribution(self) -> dict | None:
        path = self._model_service.model_root / self._model_service.version / "reference_distribution.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text())
        except Exception:
            logger.warning(
                "Failed to parse reference_distribution.json for model version %s",
                self._model_service.version,
                exc_info=True,
            )
            return None

    def compute(self, db: Session) -> DriftReport:
        settings = get_settings()
        window = settings.drift_window
        min_samples = settings.drift_min_samples

        rows = (
            db.query(PredictionLog)
            .order_by(PredictionLog.created_at.desc())
            .limit(window)
            .all()
        )
        samples_available = len(rows)
        reference = self._load_reference_distribution()

        if samples_available < min_samples or reference is None:
            return DriftReport(
                status=INSUFFICIENT_DATA,
                window_used=window,
                samples_available=samples_available,
                reference_model_version=self._model_service.version,
                psi_warn=settings.drift_psi_warn,
                psi_alert=settings.drift_psi_alert,
                features=[],
            )

        results: list[DriftFeatureResult] = []
        for feature in DRIFT_NUMERIC_FEATURES:
            values = [getattr(row, feature) for row in rows]
            computed = _numeric_drift(reference["numeric"][feature], values)
            band = band_for_psi(computed["psi"], settings.drift_psi_warn, settings.drift_psi_alert)
            results.append(DriftFeatureResult(name=feature, band=band, **computed))

        for feature in DRIFT_CATEGORICAL_FEATURES:
            values = [getattr(row, feature) for row in rows]
            computed = _categorical_drift(reference["categorical"][feature], values)
            band = band_for_psi(computed["psi"], settings.drift_psi_warn, settings.drift_psi_alert)
            results.append(DriftFeatureResult(name=feature, band=band, **computed))

        worst_band = STABLE
        for result in results:
            if _BAND_RANK[result.band] > _BAND_RANK[worst_band]:
                worst_band = result.band

        return DriftReport(
            status=worst_band,
            window_used=window,
            samples_available=samples_available,
            reference_model_version=self._model_service.version,
            psi_warn=settings.drift_psi_warn,
            psi_alert=settings.drift_psi_alert,
            features=results,
        )
