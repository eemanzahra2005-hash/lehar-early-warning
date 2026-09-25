"""LEHAR Phase 1: the served API process must never import MLflow.

*LEHAR Phase 2.5 extends the same guarantee to `torch` and `onnxruntime`.*
PyTorch trains the flood lead-time model and is installed in the local venv
(backend/requirements-ml.txt) but never in the image — so the `torch`
assertions below are real checks, not vacuous ones. `onnxruntime` IS a
runtime dependency, but it is imported lazily inside the first forecast
served, and FLOOD_DL_ENABLED defaults to false; a deployment that never
turns the feature on must never pay for it. See docs/FLOOD_DL.md.

Why this test exists: the deployed backend runs inside Render's free-tier
512MB ceiling (CLAUDE.md rule 11) and was previously OOM-killed on
`/api/v1/meta` and `/api/v1/predict`. `mlflow` is by far the heaviest
dependency in this project, and it is needed only by the TRAINING pipeline
(backend/ml/pipeline.py) and the promote/rollback alias update
(app/services/mlflow_registry.py) — never to serve a request. Model-registry
reads on the serving path go through backend/ml/registry.py, which is plain
registry.json parsing with no MLflow involvement at all.

`shap` gets a narrower guarantee, because the two deployment profiles want
different things and Phase 13's local behaviour must not regress
(CLAUDE.md rule 1):

  - LOW_MEMORY_MODE=true (the Render profile): `shap` must stay lazily
    imported inside ExplainService, so `/health` and `/meta` — which never
    explain anything — never pay for the shap/numba/llvmlite stack.
  - LOW_MEMORY_MODE unset (local dev): the explainer is deliberately warmed
    up eagerly at startup so a user's first `/predict` isn't slowed by the
    one-time numba JIT (see app/main.py's lifespan). `shap` being resident
    there is correct, so only the `mlflow` guarantee is asserted.

Each check runs in a FRESH SUBPROCESS on purpose. Within one pytest
process, backend/tests/test_pipeline.py legitimately imports mlflow, which
would leave it in sys.modules and make an in-process assertion meaningless
(and order-dependent).
"""

import json
import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent

# Runs inside the subprocess: boot the real app, drive real requests through
# it with the same offline fakes conftest.py uses, then report which heavy
# modules ended up in sys.modules. Printed as one JSON line so the parent
# test can assert on it with a real error message.
_PROBE = r'''
import json, os, sys, tempfile
from pathlib import Path

BACKEND_DIR, STAGE, LOW_MEMORY = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
sys.path.insert(0, str(BACKEND_DIR))

os.environ["DB_PATH"] = str(Path(tempfile.mkdtemp(prefix="lehar_import_probe_")) / "probe.db")
os.environ["JWT_SECRET"] = "probe-secret-not-for-production-use"
os.environ["LLM_CLOUD_API_KEY"] = ""
os.environ["LOW_MEMORY_MODE"] = LOW_MEMORY

HEAVY = ("mlflow", "shap", "torch", "onnxruntime")


def loaded():
    return sorted(name for name in HEAVY if name in sys.modules)


from fastapi.testclient import TestClient  # noqa: E402

from app.dependencies import get_flood_service, get_weather_service  # noqa: E402
from app.main import app  # noqa: E402

result = {"after_import": loaded()}


class FakeWeatherService:
    def fetch(self, district):
        return {
            "temperature_c": 30.0,
            "humidity_pct": 45.0,
            "rainfall_mm": 2.0,
            "evapotranspiration_mm": 5.0,
        }


class FakeFloodService:
    """Stands in for the real flood lookup so the probe stays offline; the
    real one would try to reach Open-Meteo for all 107 districts."""

    def get_band_for(self, district):
        return None


app.dependency_overrides[get_weather_service] = lambda: FakeWeatherService()
app.dependency_overrides[get_flood_service] = lambda: FakeFloodService()

with TestClient(app) as client:
    result["health_status"] = client.get("/api/v1/health").status_code
    result["deep_status"] = client.get("/api/v1/health/deep").status_code
    result["meta_status"] = client.get("/api/v1/meta").status_code
    result["after_meta"] = loaded()

    if STAGE == "predict":
        response = client.post(
            "/api/v1/predict",
            json={
                "district": "Lahore",
                "crop_type": "wheat",
                "soil_moisture_pct": 25.0,
                "canal_flow_cusecs": 300.0,
                "use_live_weather": False,
                "manual_temperature_c": 30.0,
                "manual_humidity_pct": 45.0,
                "manual_rainfall_mm": 2.0,
                "manual_evapotranspiration_mm": 5.0,
            },
        )
        result["predict_status"] = response.status_code
        result["predict_body"] = response.text[:400]
        result["after_predict"] = loaded()

print("PROBE_JSON:" + json.dumps(result))
'''


def _run_probe(stage: str, low_memory: bool) -> dict:
    """Boot the app in a clean interpreter and return the probe's report."""
    completed = subprocess.run(
        [sys.executable, "-c", _PROBE, str(BACKEND_DIR), stage, "true" if low_memory else "false"],
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert completed.returncode == 0, f"probe subprocess failed:\n{completed.stdout}\n{completed.stderr}"
    for line in completed.stdout.splitlines():
        if line.startswith("PROBE_JSON:"):
            return json.loads(line[len("PROBE_JSON:"):])
    raise AssertionError(f"probe produced no result line:\n{completed.stdout}\n{completed.stderr}")


def test_importing_the_app_imports_neither_mlflow_nor_shap():
    """Boot cost only — this is measured BEFORE the lifespan runs, so even
    in the local profile (where the lifespan then warms SHAP up on purpose)
    neither stack should be resident from imports alone."""
    report = _run_probe("meta", low_memory=False)
    assert report["after_import"] == [], (
        f"Heavy modules imported just by importing app.main: {report['after_import']}. "
        "Move the import inside the function that needs it (see app/dependencies.py's "
        "get_mlflow_registry_service for the pattern)."
    )


def test_health_and_meta_import_nothing_heavy_under_low_memory_mode():
    """The deployment profile, and the two endpoints an uptime pinger and
    the console's bootstrap call most often. `/meta` in particular was part
    of the OOM that motivated LEHAR Phase 1."""
    report = _run_probe("meta", low_memory=True)
    assert report["health_status"] == 200
    assert report["deep_status"] == 200
    assert report["meta_status"] == 200
    assert report["after_meta"] == [], (
        f"Serving /health, /health/deep and /meta pulled in heavy modules: {report['after_meta']}."
    )


def test_predict_never_imports_mlflow():
    """A real prediction may legitimately import shap (that is what builds
    the explanation), but must never import mlflow: model loading resolves
    the version through registry.json, not through the MLflow registry.
    Asserted in BOTH profiles, since the local one is where a stray
    module-level `import mlflow` would most easily slip in unnoticed."""
    for low_memory in (False, True):
        report = _run_probe("predict", low_memory=low_memory)
        assert report["predict_status"] == 200, report["predict_body"]
        assert "mlflow" not in report["after_predict"], (
            f"POST /predict imported mlflow (LOW_MEMORY_MODE={low_memory}). Registry reads on the "
            "serving path must go through ml/registry.py (registry.json) only — see "
            "app/services/ml_model.py."
        )
        assert "torch" not in report["after_predict"]
        # LEHAR Phase 2.5: the flood lead-time model's runtime is imported
        # lazily, inside the first forecast actually served — and
        # FLOOD_DL_ENABLED defaults to false, so a deployment that does not
        # use the feature must never pay its ~20MB (docs/FLOOD_DL.md).
        assert "onnxruntime" not in report["after_predict"]
