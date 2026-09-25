"""Flood LEAD-TIME forecasting on the serving path (LEHAR Phase 2.5).

What this adds to Flood Watch: `app/services/flood.py` answers "how bad does
the river look right now, given GloFAS's own forecast". This module answers
"where will the river BE in 1, 2 and 3 days", from a small GRU trained on
years of real GloFAS discharge and ERA5 weather history (see
docs/FLOOD_DL.md for the exact window, the measured skill and the
limitations), so an alert can fire roughly a day before the water arrives
instead of alongside it.

** onnxruntime only — this module must never import torch. **

PyTorch is a ~200 MB dependency that exists in this project purely to TRAIN
the model (backend/requirements-ml.txt, never backend/requirements.txt or
requirements-deploy.txt). The API loads the exported ONNX graph with
onnxruntime, and even that import is deferred until the first forecast is
actually served, so a deployment with FLOOD_DL_ENABLED=false — the default —
pays nothing at all for this feature on its 512 MB host (CLAUDE.md rule 11).
`backend/tests/test_no_heavy_imports.py` enforces the torch half.

The mapped level comes from the SAME thresholds Flood Watch already uses
(flood.py's components, weights and bands), with the model's predicted
discharge substituted for the observed forecast peak — so a predicted
level 3 means exactly what an observed level 3 means, one day earlier.

This is a research indicator, not an official forecast. GloFAS and NDMA/PMD/
PDMA remain authoritative, and every response here says so.
"""

import logging
import statistics
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
from fastapi import HTTPException, status

from app.config import get_settings
from app.services.flood import (
    DISCLAIMER,
    PAST_DAYS,
    band_for_score,
    compute_anomaly_ratio,
    compute_components,
    compute_score,
)
from app.validators import validate_district
from ml.districts import DISTRICTS
from ml.flood_dl import registry as flood_dl_registry
from ml.flood_dl.features import (
    FEATURE_NAMES,
    HORIZONS,
    WINDOW_DAYS,
    apply_normalisation,
    build_raw_features,
    predictions_to_m3s,
)

logger = logging.getLogger("app.flood_forecast")

# How far ahead the forecast is issued. The model's shortest horizon is D+1,
# i.e. the alert is raised at least 24 h before the day it is about — which
# is the whole point of this phase.
LEAD_TIME_HOURS = 24

# Attribution required by both upstream data providers, carried on every
# response (see scripts/data/fetch_flood_history.py's module docstring).
ATTRIBUTION = (
    "Weather data by Open-Meteo.com (CC BY 4.0). River discharge from GloFAS / "
    "Copernicus Emergency Management Service, served via Open-Meteo."
)

# Unlike the irrigation model, this one is trained on REAL measurements. Said
# explicitly on every response so the distinction travels with the data
# (CLAUDE.md rule 13) rather than being something a reader has to infer.
TRAINING_DATA_NOTE = (
    "Trained on REAL data: GloFAS river discharge and ERA5 weather reanalysis via Open-Meteo. "
    "LEHAR's irrigation model is separate and remains trained on synthetic research data."
)

STATUS_OK = "ok"
STATUS_DISABLED = "disabled"
STATUS_NO_MODEL = "no_model"


def forecast_flood_index(
    *,
    baseline_median: float,
    forecast_discharge_m3s: list[float],
    daily_rain_mm: list[float],
    river_exposure: float,
    month: int,
    weights: dict,
) -> dict:
    """The Flood Risk Index for a PREDICTED discharge series.

    Deliberately a thin composition of app/services/flood.py's own pure
    functions rather than a parallel implementation: the index, its weights
    and its band boundaries stay defined in exactly one place, so a predicted
    band and an observed band can never come to mean different things
    (docs/FLOOD_RISK.md). The only substitution is the discharge component's
    forecast peak — observed there, model-predicted here.
    """
    peak = max(forecast_discharge_m3s) if forecast_discharge_m3s else 0.0
    anomaly_ratio = compute_anomaly_ratio(baseline_median, peak)
    rain_values = [float(v) for v in daily_rain_mm]
    components = compute_components(
        anomaly_ratio=anomaly_ratio,
        rain_3day_mm=sum(rain_values),
        rain_intensity_mm=max(rain_values) if rain_values else 0.0,
        river_exposure=river_exposure,
        month=month,
    )
    score = compute_score(components, weights)
    return {
        "anomaly_ratio": anomaly_ratio,
        "forecast_peak_m3s": peak,
        "components": components,
        "score": score,
        "band": band_for_score(score),
    }


class FloodForecastService:
    """Lazy, small, and off by default.

    Nothing is loaded until the first forecast is served: no onnxruntime
    import, no session, no normalisation table. A process that never serves
    one — which is every process until FLOOD_DL_ENABLED is turned on and a
    model is registered — carries no cost for this at all.
    """

    def __init__(
        self,
        discharge_client,
        weather_service,
        model_root: Path | None = None,
        version: str | None = None,
        enabled: bool | None = None,
        weights: dict | None = None,
        ttl_seconds: int | None = None,
    ):
        settings = get_settings()
        self._discharge_client = discharge_client
        self._weather_service = weather_service
        # Per-district TTL cache over the whole computed forecast, at the
        # same 1-hour default as Flood Watch's own cache. This is not a
        # micro-optimisation: an alert run sweeps all 107 districts, and
        # without it every run would add 107 fresh GloFAS calls on top of the
        # ones Flood Watch already makes — against a free tier whose fair-use
        # budget this project has already been rate-limited by (see
        # docs/FLOOD_DL.md). Being a courteous caller of a free API is a
        # requirement here, not a nicety.
        self._ttl_seconds = ttl_seconds if ttl_seconds is not None else settings.flood_cache_ttl_seconds
        self._cache: dict[str, tuple[float, dict]] = {}
        self._model_root = Path(model_root) if model_root else flood_dl_registry.FLOOD_DL_MODEL_ROOT
        self._version_setting = version if version is not None else settings.flood_dl_model_version
        self._enabled = settings.flood_dl_enabled if enabled is None else enabled
        self._weights = weights or {
            "discharge": settings.flood_w_discharge,
            "rain_3day": settings.flood_w_rain_3day,
            "rain_intensity": settings.flood_w_rain_intensity,
            "exposure": settings.flood_w_exposure,
            "monsoon": settings.flood_w_monsoon,
        }
        self._session = None
        self._norm: dict | None = None
        self._resolved_version: str | None = None

    # --- model loading -------------------------------------------------

    @property
    def enabled(self) -> bool:
        return bool(self._enabled)

    def resolved_version(self) -> str | None:
        """The concrete registered version this service would serve, or None
        when nothing usable is registered. Cheap: registry.json only."""
        if self._resolved_version is None:
            self._resolved_version = flood_dl_registry.resolve_version(self._version_setting, self._model_root)
        return self._resolved_version

    def is_available(self) -> bool:
        return self.enabled and self.resolved_version() is not None

    def status(self) -> dict:
        """Why the feature is or is not serving — reported by GET /meta and
        by the endpoint's 503, so "nothing happened" always has a reason."""
        if not self.enabled:
            return {"status": STATUS_DISABLED, "detail": "FLOOD_DL_ENABLED is false.", "model_version": None}
        version = self.resolved_version()
        if version is None:
            return {
                "status": STATUS_NO_MODEL,
                "detail": "No flood lead-time model is registered in backend/ml/flood_dl/model/.",
                "model_version": None,
            }
        return {"status": STATUS_OK, "detail": None, "model_version": version}

    def _load(self) -> tuple[object, dict, str]:
        """Build the onnxruntime session once, and validate that the model's
        norm.json agrees with this build's feature contract.

        The check matters: a model exported against a different channel order
        or window length would still RUN — onnxruntime only sees float
        tensors of the right shape — and would silently return numbers in the
        wrong units. Better to refuse to serve than to serve nonsense."""
        version = self.resolved_version()
        if version is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="No flood lead-time model is registered.",
            )
        if self._session is not None and self._norm is not None:
            return self._session, self._norm, version

        norm = flood_dl_registry.read_norm(version, self._model_root)
        if (
            tuple(norm.get("feature_names", ())) != FEATURE_NAMES
            or int(norm.get("window_days", -1)) != WINDOW_DAYS
            or tuple(norm.get("horizons", ())) != HORIZONS
        ):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=(
                    f"Registered flood lead-time model {version} was built against a different feature "
                    "contract than this build of ml/flood_dl/features.py. Re-export it."
                ),
            )

        # Imported HERE, not at module scope: see this module's docstring.
        import onnxruntime  # noqa: PLC0415

        options = onnxruntime.SessionOptions()
        # One thread each way. The model is ~44k parameters over a 14-step
        # sequence — a single forecast is sub-millisecond work, and a thread
        # pool would cost more RAM than the inference saves (CLAUDE.md
        # rule 11).
        options.intra_op_num_threads = 1
        options.inter_op_num_threads = 1
        model_path = flood_dl_registry.version_dir(version, self._model_root) / flood_dl_registry.MODEL_FILENAME
        session = onnxruntime.InferenceSession(
            str(model_path), sess_options=options, providers=["CPUExecutionProvider"]
        )

        self._session, self._norm = session, norm
        logger.info("Loaded flood lead-time model %s (%s districts)", version, len(norm.get("districts", [])))
        return session, norm, version

    # --- inference -----------------------------------------------------

    def _predict_discharge(self, window: np.ndarray, district_index: int, stats: dict) -> list[float]:
        """One district, one window -> predicted discharge in m3/s at D+1..D+3."""
        session, _, _ = self._load()
        normalised = apply_normalisation(window, stats).astype(np.float32)[None, :, :]
        outputs = session.run(
            None,
            {
                "window": normalised,
                "district_id": np.array([district_index], dtype=np.int64),
            },
        )
        predicted = predictions_to_m3s(np.asarray(outputs[0])[0], stats)
        return [float(v) for v in predicted]

    def _weather_by_date(self, district: str) -> dict[str, dict]:
        """Recent + forecast daily rain/tmax, keyed by ISO date."""
        series = self._weather_service.fetch_daily_history_and_outlook(
            district, past_days=WINDOW_DAYS, forecast_days=max(HORIZONS) + 1
        )
        return {str(day["date"]): day for day in series}

    def forecast(self, district: str) -> dict:
        """The full lead-time forecast for one district.

        Raises a clean 503 rather than guessing whenever an input is missing:
        a forecast built on a fabricated zero for a day Open-Meteo had no
        reading for would be indistinguishable from a real one (CLAUDE.md
        rule 4).
        """
        validate_district(district)
        if not self.enabled:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Flood lead-time forecasting is disabled. Set FLOOD_DL_ENABLED=true to enable it.",
            )

        cached = self._cache.get(district)
        if cached is not None and (time.monotonic() - cached[0]) < self._ttl_seconds:
            return cached[1]

        session, norm, version = self._load()

        districts = list(norm.get("districts", []))
        if district not in districts:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"{district} was not part of the training set for model {version}.",
            )
        district_index = districts.index(district)
        stats = norm["per_district"][district]

        params = DISTRICTS[district]
        series = self._discharge_client.fetch(params["lat"], params["lon"])
        dates, values = list(series["dates"]), [float(v) for v in series["values"]]
        if len(values) < PAST_DAYS + 1 or len(dates) != len(values):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="The flood provider returned too short a discharge series to forecast from.",
            )

        # flood.py's series is 30 past days + today + 6 forecast days. The
        # model reads OBSERVED days only, so the window ends at today
        # (index PAST_DAYS) and reaches WINDOW_DAYS back from there.
        today_index = PAST_DAYS
        window_slice = slice(today_index + 1 - WINDOW_DAYS, today_index + 1)
        window_dates = dates[window_slice]
        window_discharge = values[window_slice]
        if len(window_discharge) != WINDOW_DAYS:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Not enough observed river-discharge history to build a forecast window.",
            )

        weather = self._weather_by_date(district)
        rain, tmax, day_of_year = [], [], []
        for iso_date in window_dates:
            day = weather.get(str(iso_date))
            if day is None or day.get("rainfall_mm") is None or day.get("temperature_max_c") is None:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail=f"No weather reading available for {iso_date}, so no forecast can be made.",
                )
            rain.append(float(day["rainfall_mm"]))
            tmax.append(float(day["temperature_max_c"]))
            day_of_year.append(_day_of_year(str(iso_date)))

        window = build_raw_features(window_discharge, rain, tmax, day_of_year)
        predicted = self._predict_discharge(window, district_index, stats)

        # Rain over the days being predicted into, from the same Open-Meteo
        # outlook — the operational rain input Flood Watch already uses.
        issue_date = _parse_date(str(window_dates[-1]))
        horizon_dates = [(issue_date + timedelta(days=h)).date().isoformat() for h in HORIZONS]
        horizon_rain = [
            float(weather[d]["rainfall_mm"])
            for d in horizon_dates
            if d in weather and weather[d].get("rainfall_mm") is not None
        ]

        baseline_median = statistics.median(values[:PAST_DAYS])
        index = forecast_flood_index(
            baseline_median=baseline_median,
            forecast_discharge_m3s=predicted,
            daily_rain_mm=horizon_rain,
            river_exposure=params["river_exposure"],
            month=(issue_date + timedelta(days=1)).month,
            weights=self._weights,
        )

        from app.services.alerts.rules import AlertThresholds, evaluate_flood_forecast  # noqa: PLC0415

        outcome = evaluate_flood_forecast(
            band=index["band"],
            score=index["score"],
            predicted_discharge=predicted,
            anomaly_ratio=index["anomaly_ratio"],
            thresholds=AlertThresholds.from_settings(get_settings()),
            # Today's observed value, so the inherited rising-48 h test has
            # something to measure the predicted days against.
            current_discharge=float(window_discharge[-1]),
            model_version=version,
            lead_time_hours=LEAD_TIME_HOURS,
            forecast_dates=horizon_dates,
        )

        result = {
            "district": district,
            "province": params["province"],
            "status": STATUS_OK,
            "model_version": version,
            "issued_for_date": issue_date.date().isoformat(),
            "lead_time_hours": LEAD_TIME_HOURS,
            "horizons_days": list(HORIZONS),
            "observed": {
                "unit": "m3/s",
                "dates": [str(d) for d in window_dates],
                "values": [round(v, 3) for v in window_discharge],
                "baseline_median": round(baseline_median, 3),
            },
            "predicted": {
                "unit": "m3/s",
                "dates": horizon_dates,
                "values": [round(v, 3) for v in predicted],
                "peak": round(index["forecast_peak_m3s"], 3),
                "anomaly_ratio": round(index["anomaly_ratio"], 2),
            },
            "rain_forecast_mm": [round(v, 1) for v in horizon_rain],
            "score": round(index["score"], 1),
            "band": index["band"],
            "components": {key: round(value, 3) for key, value in index["components"].items()},
            "level": outcome.level if outcome is not None else None,
            "alert_type": outcome.type if outcome is not None else None,
            "reason": outcome.reason if outcome is not None else "Predicted flood band is LOW — nothing raised.",
            "generated_at": datetime.now(timezone.utc),
            "training_data": TRAINING_DATA_NOTE,
            "attribution": ATTRIBUTION,
            "disclaimer": DISCLAIMER,
        }
        # `generated_at` is cached along with the rest, which is correct: it
        # records when this forecast was actually computed, not when it was
        # last handed out.
        self._cache[district] = (time.monotonic(), result)
        return result

    def forecast_quietly(self, district: str) -> dict | None:
        """Best-effort variant for the alert engine: returns None instead of
        raising, exactly like FloodService.get_band_for. A flood lead-time
        model that cannot answer must never be able to fail an alert run for
        the other 106 districts."""
        if not self.is_available():
            return None
        try:
            return self.forecast(district)
        except Exception:
            logger.warning("Flood lead-time forecast unavailable for %s", district)
            return None


def _parse_date(value: str) -> datetime:
    return datetime.fromisoformat(value[:10])


def _day_of_year(value: str) -> int:
    return _parse_date(value).timetuple().tm_yday
