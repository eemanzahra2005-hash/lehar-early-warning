"""The compact deployment model profile (LEHAR Phase 1).

`ml/pipeline.py --compact` trains the variant the 512MB-constrained
deployment serves. Two properties matter enough to pin down in tests:

  1. It must NOT move registry.json's "latest" pointer. Local dev keeps
     serving the full, more accurate model; the compact one is reached only
     by an explicit MODEL_VERSION (CLAUDE.md rule 1 — additive).
  2. Its tree count must stay within LOW_MEMORY_SHAP_MAX_ESTIMATORS, or the
     deployed host silently loses per-prediction explanations.

The deployment-wiring checks below read the committed registry.json and
render.yaml rather than re-training, so they stay fast and assert the thing
that actually ships.
"""

import json
from pathlib import Path

import yaml

from app.config import Settings
from ml.pipeline import (
    COMPACT_MAX_DEPTH,
    COMPACT_N_ESTIMATORS,
    DEFAULT_MAX_DEPTH,
    DEFAULT_N_ESTIMATORS,
    _apply_compact_profile,
    quality_gate,
)
from ml.registry import DEFAULT_MODEL_ROOT, read_registry

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class _Args:
    """Stand-in for argparse's Namespace — the profile resolver only reads
    and writes attributes, so this keeps the test free of argparse setup."""

    def __init__(self, **kwargs):
        defaults = {
            "compact": False,
            "n_estimators": None,
            "max_depth": None,
            "compare_to_production": None,
            "promote_on_pass": None,
        }
        self.__dict__.update({**defaults, **kwargs})


# --- The --compact profile ---------------------------------------------------


def test_compact_profile_sets_the_deployment_hyperparameters():
    args = _apply_compact_profile(_Args(compact=True))

    assert args.n_estimators == COMPACT_N_ESTIMATORS
    assert args.max_depth == COMPACT_MAX_DEPTH


def test_compact_profile_never_promotes_and_skips_the_production_comparison():
    """A deployment-profile candidate is not competing with the full local
    model on accuracy, and must not take over its production pointer."""
    args = _apply_compact_profile(_Args(compact=True))

    assert args.promote_on_pass is False
    assert args.compare_to_production is False


def test_compact_tree_count_stays_within_the_low_memory_shap_cap():
    """Above this cap, ExplainService skips building the TreeExplainer
    entirely under LOW_MEMORY_MODE and explanations become null — so the
    profile silently losing explainability would be a real regression."""
    assert COMPACT_N_ESTIMATORS <= Settings().low_memory_shap_max_estimators


def test_explicit_flags_win_over_the_compact_profile():
    """`--compact --n-estimators 40` must mean 40, not 60."""
    args = _apply_compact_profile(
        _Args(compact=True, n_estimators=40, max_depth=6, promote_on_pass=True, compare_to_production=True)
    )

    assert (args.n_estimators, args.max_depth) == (40, 6)
    assert args.promote_on_pass is True
    assert args.compare_to_production is True


def test_a_normal_run_is_unchanged_by_the_new_profile():
    """CLAUDE.md rule 1: without --compact, the pipeline still trains the
    full 120-tree model, gated against production and promoted on pass —
    exactly as every phase before this one."""
    args = _apply_compact_profile(_Args())

    assert (args.n_estimators, args.max_depth) == (DEFAULT_N_ESTIMATORS, DEFAULT_MAX_DEPTH)
    assert args.compare_to_production is True
    assert args.promote_on_pass is True


# --- What actually ships -----------------------------------------------------


def _render_api_env() -> dict:
    blueprint = yaml.safe_load((PROJECT_ROOT / "render.yaml").read_text(encoding="utf-8"))
    service = next(s for s in blueprint["services"] if s["name"] == "lehar-api")
    return {var["key"]: var.get("value") for var in service["envVars"]}


def test_render_pins_a_registered_compact_model_that_is_not_latest():
    """The deployed MODEL_VERSION must name a real registered version that
    is deliberately NOT the local production pointer — that separation is
    the whole point of the compact profile."""
    registry = read_registry(DEFAULT_MODEL_ROOT)
    pinned = _render_api_env()["MODEL_VERSION"]

    assert pinned in registry["versions"], f"render.yaml pins {pinned}, which is not in registry.json"
    assert pinned != registry["latest"], "the deployed model should not be local dev's 'latest' pointer"
    assert (DEFAULT_MODEL_ROOT / pinned / "model.joblib").exists()


def test_the_pinned_deployment_model_passes_the_real_quality_gate():
    """Re-runs ml/pipeline.py's own quality_gate() over the metrics recorded
    for the pinned version — real numbers from metrics.json, never asserted
    against hard-coded expectations (CLAUDE.md rule 4)."""
    settings = Settings()
    pinned = _render_api_env()["MODEL_VERSION"]
    metrics = read_registry(DEFAULT_MODEL_ROOT)["versions"][pinned]["metrics"]

    gate = quality_gate(metrics, None, settings, compare_to_production=False)

    assert gate.passed, gate.reasons
    assert metrics["mae"] <= settings.qg_max_mae
    assert metrics["r2"] >= settings.qg_min_r2


def test_the_pinned_deployment_model_keeps_shap_explanations_working():
    pinned = _render_api_env()["MODEL_VERSION"]
    metrics = read_registry(DEFAULT_MODEL_ROOT)["versions"][pinned]["metrics"]

    assert metrics["n_estimators"] <= Settings().low_memory_shap_max_estimators


def test_the_pinned_deployment_model_is_smaller_than_the_full_model():
    """The reason it exists. Compared against whatever 'latest' currently
    is, so this keeps meaning the right thing after a future retrain."""
    registry = read_registry(DEFAULT_MODEL_ROOT)
    pinned = _render_api_env()["MODEL_VERSION"]

    compact_size = (DEFAULT_MODEL_ROOT / pinned / "model.joblib").stat().st_size
    full_size = (DEFAULT_MODEL_ROOT / registry["latest"] / "model.joblib").stat().st_size

    assert compact_size < full_size


def test_the_pinned_deployment_models_metrics_json_matches_the_registry():
    """registry.json and the version folder's own metrics.json must agree —
    they are written by the same run, and a mismatch would mean one of them
    is reporting numbers the model never produced."""
    pinned = _render_api_env()["MODEL_VERSION"]
    registry_metrics = read_registry(DEFAULT_MODEL_ROOT)["versions"][pinned]["metrics"]
    on_disk = json.loads((DEFAULT_MODEL_ROOT / pinned / "metrics.json").read_text())

    for key in ("mae", "rmse", "r2", "n_estimators", "max_depth"):
        assert registry_metrics[key] == on_disk[key], key
