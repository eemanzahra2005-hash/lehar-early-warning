"""Checks on the REAL, committed flood lead-time model (LEHAR Phase 2.5).

Every other flood-forecast test runs against the untrained three-district
fixture in tests/fixtures/flood_dl/, which proves the code paths but says
nothing about the artifact that actually ships. These tests guard that
artifact: that it is complete, that it still matches this build's feature
contract, that it labels itself as REAL data (CLAUDE.md rule 13 cuts both
ways), and that the numbers docs/FLOOD_DL.md quotes are the ones in its
metrics.json rather than numbers typed by hand (rule 4).

No torch and no network: onnxruntime is a runtime dependency already.
"""

import numpy as np
import pytest

from ml.flood_dl import registry as flood_dl_registry
from ml.flood_dl.features import FEATURE_NAMES, HORIZONS, N_FEATURES, WINDOW_DAYS

VERSION = flood_dl_registry.resolve_version("latest")

pytestmark = pytest.mark.skipif(VERSION is None, reason="no flood lead-time model is registered")


def test_the_registered_version_matches_this_build_s_feature_contract():
    norm = flood_dl_registry.read_norm(VERSION)
    assert tuple(norm["feature_names"]) == FEATURE_NAMES
    assert norm["window_days"] == WINDOW_DAYS
    assert tuple(norm["horizons"]) == HORIZONS
    # Every district the model knows has its own training-only statistics.
    assert set(norm["districts"]) == set(norm["per_district"])


def test_the_model_card_says_real_data_not_synthetic():
    metrics = flood_dl_registry.read_metrics(VERSION)
    assert "fixture" not in metrics
    assert "REAL data" in metrics["data"]["source"]
    assert "Open-Meteo" in metrics["data"]["attribution"]
    entry = flood_dl_registry.list_versions()[VERSION]
    assert entry["training_data"].startswith("real")


def test_the_metrics_carry_a_persistence_baseline_and_an_explicit_verdict():
    metrics = flood_dl_registry.read_metrics(VERSION)
    for horizon in HORIZONS:
        key = f"D+{horizon}"
        assert key in metrics["evaluation"]["persistence"]
        verdict = metrics["verdict_vs_persistence"][key]
        # The boolean must agree with the two numbers it summarises.
        assert verdict["beats_persistence"] == (verdict["model_mae_log"] < verdict["persistence_mae_log"])
    hit = metrics["evaluation"]["level_hit_rate"]
    assert hit["persistence"]["event_days"] == hit["model"]["event_days"] > 0


def test_the_split_is_by_time():
    split = flood_dl_registry.read_metrics(VERSION)["split"]
    assert split["train"] == "issue day <= 2022-12-31"
    assert split["val"] == "issue day in 2023"
    assert split["test"] == "issue day >= 2024-01-01"


def test_the_documented_metrics_block_is_generated_from_this_version():
    """docs/FLOOD_DL.md must name the version that is actually `latest`, or
    the page is quoting a model that is no longer served."""
    from pathlib import Path

    doc = (Path(__file__).resolve().parents[2] / "docs" / "FLOOD_DL.md").read_text(encoding="utf-8")
    block = doc.split("<!-- METRICS:BEGIN -->", 1)[1].split("<!-- METRICS:END -->", 1)[0]
    assert f"`{VERSION}`" in block
    test_samples = flood_dl_registry.read_metrics(VERSION)["evaluation"]["test_samples"]
    assert f"{test_samples:,}" in block


def test_the_exported_graph_runs_under_onnxruntime():
    import onnxruntime

    path = flood_dl_registry.version_dir(VERSION) / "model.onnx"
    session = onnxruntime.InferenceSession(str(path), providers=["CPUExecutionProvider"])
    n_districts = len(flood_dl_registry.read_norm(VERSION)["districts"])
    window = np.zeros((4, WINDOW_DAYS, N_FEATURES), dtype=np.float32)
    district_ids = np.array([0, 1, n_districts - 2, n_districts - 1], dtype=np.int64)
    (prediction,) = session.run(None, {"window": window, "district_id": district_ids})
    assert prediction.shape == (4, len(HORIZONS))
    assert np.isfinite(prediction).all()
