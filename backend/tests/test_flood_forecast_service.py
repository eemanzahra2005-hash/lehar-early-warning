"""LEHAR Phase 2.5: app/services/flood_forecast.py — the serving path of the
flood lead-time model.

Two kinds of test, deliberately separated:

**Plumbing**, against a tiny COMMITTED ONNX fixture
(backend/tests/fixtures/flood_dl/, three districts, randomly-initialised
weights — see scripts/make_flood_dl_test_fixture.py). The fixture's
predictions are meaningless numbers; what is being tested is that the
session loads, the input contract is honoured, normalisation and its inverse
are applied, the response is complete, and every failure mode degrades
honestly instead of inventing a forecast.

**Level mapping**, against the pure functions, where the inputs can be
chosen directly so an assertion about a band or a level means something.

No network (the discharge client and weather service are fakes) and NO
TORCH — the whole point of exporting to ONNX is that serving needs only
onnxruntime, and this file proves the suite runs without PyTorch installed.
"""

import json
import statistics
import sys
from pathlib import Path

import numpy as np
import pytest
from fastapi import HTTPException

from app.services.flood import DISCLAIMER, PAST_DAYS
from app.services.flood_forecast import (
    ATTRIBUTION,
    LEAD_TIME_HOURS,
    STATUS_DISABLED,
    STATUS_NO_MODEL,
    STATUS_OK,
    FloodForecastService,
    forecast_flood_index,
)
from ml.flood_dl import registry as flood_dl_registry
from ml.flood_dl.features import HORIZONS, WINDOW_DAYS

FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "flood_dl"
FIXTURE_VERSION = "vTEST0001"
FIXTURE_DISTRICT = "Lahore"
UNMODELLED_DISTRICT = "Multan"  # a real district the fixture was not built for

DEFAULT_WEIGHTS = {
    "discharge": 0.30,
    "rain_3day": 0.25,
    "rain_intensity": 0.15,
    "exposure": 0.20,
    "monsoon": 0.10,
}

# The 37-entry shape app/services/flood.py's client returns: 30 past days,
# today, then 6 forecast days.
SERIES_DATES = [f"2026-07-{day:02d}" for day in range(1, 32)] + [f"2026-08-{day:02d}" for day in range(1, 7)]


def discharge_series(values=None):
    values = values if values is not None else [5.0] * 37
    return {"dates": list(SERIES_DATES), "values": [float(v) for v in values]}


class FakeDischargeClient:
    def __init__(self, series=None):
        self._series = series if series is not None else discharge_series()
        self.calls = 0

    def fetch(self, lat, lon):
        self.calls += 1
        return {"dates": list(self._series["dates"]), "values": list(self._series["values"])}


class FakeWeatherService:
    """Returns a reading for every date in SERIES_DATES plus the three
    forecast days the horizons need."""

    def __init__(self, rainfall=2.0, tmax=33.0, missing_dates=(), forecast_rain=2.0):
        self.rainfall = rainfall
        self.tmax = tmax
        self.missing = set(missing_dates)
        self.forecast_rain = forecast_rain
        self.calls = 0

    def fetch_daily_history_and_outlook(self, district, past_days=14, forecast_days=4):
        self.calls += 1
        out = []
        for date in SERIES_DATES:
            if date in self.missing:
                out.append({"date": date, "temperature_max_c": None, "rainfall_mm": None})
                continue
            out.append({"date": date, "temperature_max_c": self.tmax, "rainfall_mm": self.rainfall})
        # The days being predicted into: 2026-08-01 is "today" (index 30), so
        # the horizons land on 08-02..08-04, which are already in SERIES_DATES.
        for day in range(7, 11):
            out.append(
                {"date": f"2026-08-{day:02d}", "temperature_max_c": self.tmax, "rainfall_mm": self.forecast_rain}
            )
        return out


def build_service(**kwargs):
    defaults = {
        "discharge_client": FakeDischargeClient(),
        "weather_service": FakeWeatherService(),
        "model_root": FIXTURE_ROOT,
        "version": "latest",
        "enabled": True,
        # Caching is exercised deliberately by its own tests below; every
        # other test wants a fresh computation, not a neighbour's leftovers.
        "ttl_seconds": 0,
    }
    defaults.update(kwargs)
    return FloodForecastService(**defaults)


# --- the fixture itself -----------------------------------------------------


def test_the_committed_fixture_is_a_complete_registered_version():
    assert flood_dl_registry.version_exists(FIXTURE_VERSION, FIXTURE_ROOT)
    assert flood_dl_registry.resolve_version("latest", FIXTURE_ROOT) == FIXTURE_VERSION

    norm = flood_dl_registry.read_norm(FIXTURE_VERSION, FIXTURE_ROOT)
    assert norm["window_days"] == WINDOW_DAYS
    assert tuple(norm["horizons"]) == HORIZONS
    assert FIXTURE_DISTRICT in norm["districts"]


def test_the_fixture_labels_itself_as_an_untrained_fixture():
    """It must be impossible to mistake this model's output for a result
    (CLAUDE.md rule 4)."""
    metrics = flood_dl_registry.read_metrics(FIXTURE_VERSION, FIXTURE_ROOT)
    assert metrics["fixture"] is True
    assert "never trained" in metrics["note"]


# --- availability and its reasons -------------------------------------------


def test_disabled_service_reports_why_and_never_loads_a_model():
    service = build_service(enabled=False)
    assert service.enabled is False
    assert service.is_available() is False
    assert service.status()["status"] == STATUS_DISABLED
    assert service.status()["model_version"] is None


def test_enabled_service_with_no_registered_model_reports_no_model(tmp_path):
    service = build_service(model_root=tmp_path)
    assert service.is_available() is False
    status = service.status()
    assert status["status"] == STATUS_NO_MODEL
    assert "backend/ml/flood_dl/model" in status["detail"]


def test_available_service_reports_the_resolved_version():
    service = build_service()
    assert service.is_available() is True
    assert service.status() == {"status": STATUS_OK, "detail": None, "model_version": FIXTURE_VERSION}


def test_a_disabled_service_refuses_to_forecast():
    service = build_service(enabled=False)
    with pytest.raises(HTTPException) as caught:
        service.forecast(FIXTURE_DISTRICT)
    assert caught.value.status_code == 503
    assert "FLOOD_DL_ENABLED" in caught.value.detail


def test_forecast_quietly_returns_none_instead_of_raising():
    """The alert engine calls this for all 107 districts — one district's
    failure must never fail the run for the other 106."""
    assert build_service(enabled=False).forecast_quietly(FIXTURE_DISTRICT) is None
    assert build_service().forecast_quietly(UNMODELLED_DISTRICT) is None


# --- a real forecast, through onnxruntime ------------------------------------


def test_forecast_returns_the_full_documented_payload():
    service = build_service()
    result = service.forecast(FIXTURE_DISTRICT)

    assert result["district"] == FIXTURE_DISTRICT
    assert result["status"] == STATUS_OK
    assert result["model_version"] == FIXTURE_VERSION
    assert result["lead_time_hours"] == LEAD_TIME_HOURS == 24
    assert result["horizons_days"] == list(HORIZONS)

    assert len(result["observed"]["values"]) == WINDOW_DAYS
    assert len(result["observed"]["dates"]) == WINDOW_DAYS
    assert len(result["predicted"]["values"]) == len(HORIZONS)
    assert len(result["predicted"]["dates"]) == len(HORIZONS)
    assert result["band"] in ("LOW", "WATCH", "HIGH")
    assert isinstance(result["score"], float)


def test_forecast_carries_the_disclaimer_attribution_and_training_provenance():
    """CLAUDE.md rules 12 and 13, plus both providers' attribution terms —
    all three travel on the response, not only in the docs."""
    result = build_service().forecast(FIXTURE_DISTRICT)
    assert result["disclaimer"] == DISCLAIMER
    assert result["attribution"] == ATTRIBUTION
    assert "Open-Meteo" in result["attribution"] and "GloFAS" in result["attribution"]
    assert "REAL data" in result["training_data"]
    assert "synthetic" in result["training_data"]


def test_the_observed_window_is_the_last_14_days_up_to_today():
    """The model must read OBSERVED days only — feeding it GloFAS's own
    forecast days would make its "prediction" partly a copy."""
    values = [float(i) for i in range(37)]
    service = build_service(discharge_client=FakeDischargeClient(discharge_series(values)))
    result = service.forecast(FIXTURE_DISTRICT)

    # Index 30 is today; the window is the 14 days ending there.
    assert result["observed"]["values"] == [float(v) for v in range(17, 31)]
    assert result["observed"]["dates"][-1] == SERIES_DATES[PAST_DAYS]


def test_the_baseline_median_matches_flood_watch_s_own_definition():
    """Flood Watch's baseline is the median of the 30 PAST days; the
    forecast must not quietly use a different one, or a predicted band and
    an observed band would stop being comparable."""
    values = [float(i) for i in range(37)]
    service = build_service(discharge_client=FakeDischargeClient(discharge_series(values)))
    result = service.forecast(FIXTURE_DISTRICT)
    assert result["observed"]["baseline_median"] == pytest.approx(statistics.median(values[:PAST_DAYS]))


def test_predictions_are_deterministic_for_the_same_input():
    """Same input, same output, every time — a forecast that wobbled between
    calls could not be audited (CLAUDE.md rule 10 applies to what feeds an
    alert as much as to the alert itself)."""
    first = build_service().forecast(FIXTURE_DISTRICT)
    second = build_service().forecast(FIXTURE_DISTRICT)
    assert first["predicted"]["values"] == second["predicted"]["values"]
    assert first["score"] == second["score"]


def test_predicted_discharge_is_never_negative():
    service = build_service(discharge_client=FakeDischargeClient(discharge_series([0.0] * 37)))
    result = service.forecast(FIXTURE_DISTRICT)
    assert all(value >= 0.0 for value in result["predicted"]["values"])


def test_different_districts_use_different_embeddings_and_normalisation():
    """If the district id or its normalisation were ignored, these would come
    out identical — which is exactly the bug a fixture with distinct
    per-district stats is there to catch."""
    service = build_service()
    lahore = service.forecast("Lahore")
    faisalabad = service.forecast("Faisalabad")
    assert lahore["predicted"]["values"] != faisalabad["predicted"]["values"]


def test_a_repeat_forecast_is_served_from_cache_without_re_calling_upstream():
    """An alert run sweeps all 107 districts. Without this cache every run
    would add 107 fresh GloFAS calls to a free API this project has already
    been rate-limited by (docs/FLOOD_DL.md)."""
    discharge, weather = FakeDischargeClient(), FakeWeatherService()
    service = build_service(discharge_client=discharge, weather_service=weather, ttl_seconds=3600)

    first = service.forecast(FIXTURE_DISTRICT)
    second = service.forecast(FIXTURE_DISTRICT)

    assert second is first
    assert discharge.calls == 1
    assert weather.calls == 1


def test_an_expired_cache_entry_is_recomputed():
    discharge = FakeDischargeClient()
    service = build_service(discharge_client=discharge, ttl_seconds=0)

    service.forecast(FIXTURE_DISTRICT)
    service.forecast(FIXTURE_DISTRICT)
    assert discharge.calls == 2


def test_each_district_is_cached_separately():
    discharge = FakeDischargeClient()
    service = build_service(discharge_client=discharge, ttl_seconds=3600)

    service.forecast("Lahore")
    service.forecast("Faisalabad")
    service.forecast("Lahore")
    assert discharge.calls == 2


def test_the_session_is_built_once_and_reused():
    service = build_service()
    service.forecast(FIXTURE_DISTRICT)
    session = service._session
    service.forecast("Faisalabad")
    assert service._session is session


def test_onnxruntime_is_not_imported_until_a_forecast_is_served():
    """CLAUDE.md rule 11: FLOOD_DL_ENABLED=false must cost a 512MB host
    nothing. Constructing the service, and asking it for its status, must
    not drag onnxruntime in."""
    for module in [name for name in sys.modules if name.startswith("onnxruntime")]:
        del sys.modules[module]

    service = build_service(enabled=False)
    service.status()
    service.is_available()
    assert not any(name.startswith("onnxruntime") for name in sys.modules)

    build_service().forecast(FIXTURE_DISTRICT)
    assert any(name.startswith("onnxruntime") for name in sys.modules)


def test_torch_is_never_imported_by_the_serving_path():
    """torch IS installed in the local venv (backend/requirements-ml.txt), so
    this is a real check rather than a vacuous one: nothing on the serving
    path may pull a ~200MB training dependency into a 512MB API process.
    test_no_heavy_imports.py makes the same guarantee for a booted app in a
    fresh subprocess, which is the order-independent version of this."""
    build_service().forecast(FIXTURE_DISTRICT)
    assert "torch" not in sys.modules, (
        "Serving a flood forecast imported torch. The API must load the exported ONNX graph with "
        "onnxruntime only — see app/services/flood_forecast.py."
    )


# --- honest failure ---------------------------------------------------------


def test_a_district_outside_the_training_set_is_refused_not_guessed():
    service = build_service()
    with pytest.raises(HTTPException) as caught:
        service.forecast(UNMODELLED_DISTRICT)
    assert caught.value.status_code == 503
    assert "not part of the training set" in caught.value.detail


def test_an_unknown_district_is_a_validation_error():
    with pytest.raises(HTTPException) as caught:
        build_service().forecast("Atlantis")
    assert caught.value.status_code in (400, 404)


def test_a_missing_weather_day_refuses_rather_than_filling_in_a_zero():
    """A fabricated 0 mm would be indistinguishable from a real dry day, and
    the forecast built on it indistinguishable from a real one — CLAUDE.md
    rule 4."""
    service = build_service(weather_service=FakeWeatherService(missing_dates=[SERIES_DATES[PAST_DAYS]]))
    with pytest.raises(HTTPException) as caught:
        service.forecast(FIXTURE_DISTRICT)
    assert caught.value.status_code == 503
    assert "No weather reading available" in caught.value.detail


def test_too_short_a_discharge_series_is_refused():
    short = {"dates": SERIES_DATES[:10], "values": [1.0] * 10}
    service = build_service(discharge_client=FakeDischargeClient(short))
    with pytest.raises(HTTPException) as caught:
        service.forecast(FIXTURE_DISTRICT)
    assert caught.value.status_code == 503
    assert "too short" in caught.value.detail


def test_a_model_built_against_a_different_feature_contract_is_refused(tmp_path):
    """A model exported with a different channel order would still RUN and
    still return floats — just meaningless ones. Refusing to serve beats
    serving nonsense."""
    version_dir = flood_dl_registry.version_dir(FIXTURE_VERSION, tmp_path)
    version_dir.mkdir(parents=True)
    source = flood_dl_registry.version_dir(FIXTURE_VERSION, FIXTURE_ROOT)
    (version_dir / "model.onnx").write_bytes((source / "model.onnx").read_bytes())
    (version_dir / "metrics.json").write_text("{}", encoding="utf-8")

    norm = json.loads((source / "norm.json").read_text(encoding="utf-8"))
    norm["window_days"] = WINDOW_DAYS + 1  # the contract no longer matches
    (version_dir / "norm.json").write_text(json.dumps(norm), encoding="utf-8")
    flood_dl_registry.register(FIXTURE_VERSION, {"fixture": True}, model_root=tmp_path)

    service = build_service(model_root=tmp_path)
    with pytest.raises(HTTPException) as caught:
        service.forecast(FIXTURE_DISTRICT)
    assert caught.value.status_code == 503
    assert "different feature contract" in caught.value.detail


def test_an_incomplete_version_directory_never_resolves(tmp_path):
    """Half an export — a model.onnx with no norm.json — must not look
    usable, or the API would serve numbers in the wrong units."""
    flood_dl_registry.version_dir("vBROKEN", tmp_path).mkdir(parents=True)
    (flood_dl_registry.version_dir("vBROKEN", tmp_path) / "model.onnx").write_bytes(b"not really a model")

    assert flood_dl_registry.version_exists("vBROKEN", tmp_path) is False
    assert flood_dl_registry.resolve_version("vBROKEN", tmp_path) is None
    with pytest.raises(FileNotFoundError):
        flood_dl_registry.register("vBROKEN", {}, model_root=tmp_path)


# --- the level mapping (pure) -----------------------------------------------


def test_forecast_index_is_low_when_the_prediction_matches_the_baseline():
    index = forecast_flood_index(
        baseline_median=10.0,
        forecast_discharge_m3s=[10.0, 10.0, 10.0],
        daily_rain_mm=[0.0, 0.0, 0.0],
        river_exposure=0.1,
        month=1,
        weights=DEFAULT_WEIGHTS,
    )
    assert index["anomaly_ratio"] == pytest.approx(1.0)
    assert index["band"] == "LOW"


def test_forecast_index_reaches_high_on_a_predicted_surge_in_monsoon():
    index = forecast_flood_index(
        baseline_median=10.0,
        forecast_discharge_m3s=[20.0, 40.0, 35.0],
        daily_rain_mm=[50.0, 60.0, 40.0],
        river_exposure=0.85,
        month=8,
        weights=DEFAULT_WEIGHTS,
    )
    assert index["forecast_peak_m3s"] == 40.0
    assert index["anomaly_ratio"] == pytest.approx(4.0)
    assert index["band"] == "HIGH"


def test_forecast_index_uses_the_predicted_peak_not_the_mean():
    """One dangerous day inside the horizon must not be averaged away."""
    spiky = forecast_flood_index(
        baseline_median=5.0,
        forecast_discharge_m3s=[5.0, 60.0, 5.0],
        daily_rain_mm=[0.0, 0.0, 0.0],
        river_exposure=0.5,
        month=8,
        weights=DEFAULT_WEIGHTS,
    )
    flat = forecast_flood_index(
        baseline_median=5.0,
        forecast_discharge_m3s=[23.3, 23.3, 23.3],
        daily_rain_mm=[0.0, 0.0, 0.0],
        river_exposure=0.5,
        month=8,
        weights=DEFAULT_WEIGHTS,
    )
    assert spiky["forecast_peak_m3s"] > flat["forecast_peak_m3s"]
    assert spiky["score"] >= flat["score"]


def test_forecast_index_survives_a_bone_dry_baseline():
    """A zero-discharge desert reach must not divide by zero — the same
    epsilon guard app/services/flood.py uses."""
    index = forecast_flood_index(
        baseline_median=0.0,
        forecast_discharge_m3s=[2.0, 3.0, 1.0],
        daily_rain_mm=[0.0, 0.0, 0.0],
        river_exposure=0.2,
        month=3,
        weights=DEFAULT_WEIGHTS,
    )
    assert np.isfinite(index["anomaly_ratio"])
    assert index["anomaly_ratio"] > 1.0
