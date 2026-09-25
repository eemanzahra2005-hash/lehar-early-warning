"""
Helpers for reading/writing the model registry at backend/ml/model/registry.json.

The registry tracks every trained model version and a "latest" pointer, per
the versioning rule in CLAUDE.md: models are saved under
backend/ml/model/<version>/ and an existing version directory is never
overwritten.

Functions accept an explicit `model_root` so tests can point at a temporary
directory instead of the real backend/ml/model/ directory.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_MODEL_ROOT = Path(__file__).resolve().parent / "model"


def registry_path_for(model_root: Path) -> Path:
    return model_root / "registry.json"


def read_registry(model_root: Path = DEFAULT_MODEL_ROOT) -> dict:
    """Return the registry dict, or an empty-but-valid one if none exists yet."""
    path = registry_path_for(model_root)
    if not path.exists():
        return {"latest": None, "versions": {}}
    return json.loads(path.read_text())


def write_registry(registry: dict, model_root: Path = DEFAULT_MODEL_ROOT) -> None:
    model_root.mkdir(parents=True, exist_ok=True)
    registry_path_for(model_root).write_text(json.dumps(registry, indent=2))


def get_latest_version(model_root: Path = DEFAULT_MODEL_ROOT) -> str | None:
    """The "latest" model version string, or None if no model has been trained yet."""
    return read_registry(model_root).get("latest")


def register_version(
    version: str,
    metrics: dict,
    created_at: str,
    model_root: Path = DEFAULT_MODEL_ROOT,
    extra: dict | None = None,
    set_latest: bool = True,
) -> None:
    """Add/update one version's entry in the registry and (by default) bump
    "latest" to it.

    `extra` (Phase 7) merges additional fields into the version entry — e.g.
    {"source": "pipeline", "mlflow_run_id": ..., "gate": {...}} — so
    pipeline-trained versions carry MLOps metadata the legacy (pre-Phase-7)
    versions don't have. Versions saved without `extra` (or trained before
    Phase 7) are treated as `"source": "legacy"` by readers.

    `set_latest=False` (Phase 13.1): records the version normally — it's
    fully present in registry.json's "versions" dict, with real artifacts on
    disk — WITHOUT moving the "latest"/production pointer. Used for the
    memory-light deployment model variant (see ml/pipeline.py's
    `promote_on_pass`), which targets a RAM-constrained host rather than
    trying to beat the current production model on accuracy — it has no
    business becoming the local production pointer just by being trained.
    """
    registry = read_registry(model_root)
    entry = {"metrics": metrics, "created_at": created_at}
    if extra:
        entry.update(extra)
    registry["versions"][version] = entry
    if set_latest:
        registry["latest"] = version
    write_registry(registry, model_root)


# --- Promote / rollback (Phase 7) -------------------------------------------
#
# Pure registry.json mutations, deliberately kept free of FastAPI/auth/MLflow
# concerns (those live in app/routers/models.py + app/services/, which import
# these). This module has no opinion on quality-gate thresholds or whether a
# version's artifacts are actually valid — callers check that first.


def version_exists(version: str, model_root: Path = DEFAULT_MODEL_ROOT) -> bool:
    """True if this version has a loadable model.joblib on disk (not just a
    registry.json entry — the two could in theory drift apart)."""
    return (model_root / version / "model.joblib").exists()


def rollback_target(model_root: Path = DEFAULT_MODEL_ROOT) -> str | None:
    """The version rollback would promote — the most recently demoted
    production version — or None if "history" is empty (nothing to roll
    back to)."""
    history = read_registry(model_root).get("history", [])
    return history[0] if history else None


def promote_to(version: str, username: str, model_root: Path = DEFAULT_MODEL_ROOT, action: str = "promote") -> dict:
    """Sets registry.json's "latest" to `version`, pushes the outgoing
    production version onto the "history" stack (most-recently-demoted
    first, so rollback_target()/rollback = promote(history[0])), and appends
    an audit entry. Raises KeyError if `version` has no registry.json entry.

    Returns the updated registry dict.
    """
    registry = read_registry(model_root)
    if version not in registry.get("versions", {}):
        raise KeyError(f"Unknown model version: {version}")

    current_latest = registry.get("latest")
    history = registry.setdefault("history", [])
    if version in history:
        history.remove(version)
    if current_latest and current_latest != version:
        history.insert(0, current_latest)

    registry["latest"] = version
    registry.setdefault("audit", []).append(
        {
            "action": action,
            "version": version,
            "username": username,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    )
    write_registry(registry, model_root)
    return registry
