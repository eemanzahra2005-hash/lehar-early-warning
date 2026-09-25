"""Regenerate the tiny ONNX fixture the flood-forecast tests run against.

    .venv\\Scripts\\python scripts\\make_flood_dl_test_fixture.py

** imports torch ** — which is exactly why it is a script and not a test.

The test suite must stay runnable with only backend/requirements.txt +
requirements-dev.txt installed: no torch, no network, no trained model. So
the flood-forecast tests load a COMMITTED three-district ONNX model from
backend/tests/fixtures/flood_dl/ with onnxruntime alone. This script is how
that fixture is made, so it is reproducible rather than a mystery binary.

The weights are random but SEEDED, so rerunning this produces a
byte-comparable model and the tests' determinism assertions keep meaning
something. The fixture's predictions are arbitrary numbers — it exists to
exercise the plumbing (session loading, the input contract, normalisation,
denormalisation, the response shape), not to be accurate. Anything that
depends on a specific level being reached is tested against the pure
functions in app/services/flood_forecast.py and
app/services/alerts/rules.py instead, where the inputs can be chosen
directly.
"""

import json
import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = PROJECT_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import torch  # noqa: E402

from ml.districts import DISTRICTS  # noqa: E402
from ml.flood_dl import registry as flood_dl_registry  # noqa: E402
from ml.flood_dl.export import export_onnx, verify_onnx  # noqa: E402
from ml.flood_dl.features import FEATURE_NAMES, HORIZONS, NORMALISED_CHANNELS, WINDOW_DAYS  # noqa: E402
from ml.flood_dl.model import FloodLeadTimeGRU  # noqa: E402

FIXTURE_ROOT = BACKEND_DIR / "tests" / "fixtures" / "flood_dl"
FIXTURE_VERSION = "vTEST0001"
SEED = 2025

# Three real district names, so validate_district() accepts them and the
# fixture exercises the same "is this district in the model?" path the real
# model does.
FIXTURE_DISTRICTS = list(DISTRICTS)[:3]

# Deliberately NOT mean 0 / std 1: a fixture that normalised to the identity
# would let a bug that skips normalisation entirely pass every test.
FIXTURE_NORM = {
    FIXTURE_DISTRICTS[0]: {"mean": [1.2, 2.0, 30.0], "std": [0.5, 4.0, 6.0]},
    FIXTURE_DISTRICTS[1]: {"mean": [0.4, 1.5, 32.0], "std": [0.3, 3.0, 5.0]},
    FIXTURE_DISTRICTS[2]: {"mean": [2.1, 3.0, 26.0], "std": [0.8, 5.0, 7.0]},
}


def main() -> int:
    torch.manual_seed(SEED)
    model = FloodLeadTimeGRU(n_districts=len(FIXTURE_DISTRICTS))
    model.eval()

    if FIXTURE_ROOT.exists():
        shutil.rmtree(FIXTURE_ROOT)
    directory = flood_dl_registry.version_dir(FIXTURE_VERSION, FIXTURE_ROOT)
    directory.mkdir(parents=True)

    onnx_path = export_onnx(model, directory / flood_dl_registry.MODEL_FILENAME)
    difference = verify_onnx(model, onnx_path, n_districts=len(FIXTURE_DISTRICTS))

    (directory / flood_dl_registry.NORM_FILENAME).write_text(
        json.dumps(
            {
                "window_days": WINDOW_DAYS,
                "horizons": list(HORIZONS),
                "feature_names": list(FEATURE_NAMES),
                "normalised_channels": NORMALISED_CHANNELS,
                "districts": FIXTURE_DISTRICTS,
                "per_district": FIXTURE_NORM,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (directory / flood_dl_registry.METRICS_FILENAME).write_text(
        json.dumps(
            {
                "fixture": True,
                "note": (
                    "TEST FIXTURE ONLY — randomly initialised weights, never trained. "
                    "Its predictions are meaningless numbers and must never be quoted as results. "
                    "Regenerate with scripts/make_flood_dl_test_fixture.py."
                ),
                "seed": SEED,
                "model": {"parameters": model.parameter_count(), "districts": len(FIXTURE_DISTRICTS)},
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    flood_dl_registry.register(
        version=FIXTURE_VERSION,
        metrics={"fixture": True},
        model_root=FIXTURE_ROOT,
        extra={"source": "scripts/make_flood_dl_test_fixture.py", "trained": False},
    )

    print(f"Wrote fixture {FIXTURE_VERSION} to {FIXTURE_ROOT}")
    print(f"  districts: {FIXTURE_DISTRICTS}")
    print(f"  parameters: {model.parameter_count()}")
    print(f"  onnx bytes: {onnx_path.stat().st_size}")
    print(f"  max |ONNX - PyTorch|: {difference:.3e}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
