"""Versioned registry for the flood lead-time model (LEHAR Phase 2.5).

Same pattern as the irrigation model's registry (CLAUDE.md rule 6): a model
lives in its own timestamped version directory, an existing version
directory is NEVER overwritten, and a registry.json tracks a "latest"
pointer. The read/write/register primitives are reused verbatim from
ml/registry.py rather than reimplemented — only the ROOT and the "what
counts as a complete version on disk" check differ.

Why a separate root (backend/ml/flood_dl/model/) rather than another
subdirectory of backend/ml/model/: ml/prune_unused_versions.py walks
backend/ml/model/ and treats every directory in it as a RandomForest
version. Dropping a differently-shaped model family in there would have that
script offer to delete it. Two model families, two roots, one pattern.

Each version directory holds exactly three files:

    model.onnx     the exported graph (no PyTorch needed to run it)
    norm.json      per-district normalisation + the feature contract
    metrics.json   the REAL measured evaluation, including the persistence
                   baseline it is compared against (CLAUDE.md rule 4)

No torch, no onnxruntime — this module is plain JSON and pathlib, so the API
can resolve a version without loading anything heavy.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from ml.registry import read_registry, register_version

FLOOD_DL_MODEL_ROOT = Path(__file__).resolve().parent / "model"

MODEL_FILENAME = "model.onnx"
NORM_FILENAME = "norm.json"
METRICS_FILENAME = "metrics.json"
REQUIRED_FILES = (MODEL_FILENAME, NORM_FILENAME, METRICS_FILENAME)

LATEST = "latest"


def new_version_id(now: datetime | None = None) -> str:
    """A sortable UTC version id, in the same shape the irrigation registry
    uses (v20260923T212705208535Z) so both registries read alike."""
    moment = now or datetime.now(timezone.utc)
    return "v" + moment.strftime("%Y%m%dT%H%M%S%f") + "Z"


def version_dir(version: str, model_root: Path = FLOOD_DL_MODEL_ROOT) -> Path:
    return Path(model_root) / version


def version_exists(version: str, model_root: Path = FLOOD_DL_MODEL_ROOT) -> bool:
    """True only when ALL THREE artifacts are on disk. A half-written version
    (say, an export that died after model.onnx) must not resolve as usable —
    the API would then load a graph it has no normalisation for, and quietly
    serve numbers in the wrong units."""
    directory = version_dir(version, model_root)
    return all((directory / name).exists() for name in REQUIRED_FILES)


def resolve_version(version: str = LATEST, model_root: Path = FLOOD_DL_MODEL_ROOT) -> str | None:
    """The concrete version string to load, or None when there is nothing
    usable to load. Returning None rather than raising is deliberate: "no
    flood lead-time model is registered yet" is the NORMAL state of a fresh
    checkout, and it must degrade to the feature being off, never to a
    500."""
    if version and version != LATEST:
        return version if version_exists(version, model_root) else None
    latest = read_registry(Path(model_root)).get(LATEST)
    if latest and version_exists(latest, model_root):
        return latest
    return None


def read_metrics(version: str, model_root: Path = FLOOD_DL_MODEL_ROOT) -> dict:
    path = version_dir(version, model_root) / METRICS_FILENAME
    return json.loads(path.read_text(encoding="utf-8"))


def read_norm(version: str, model_root: Path = FLOOD_DL_MODEL_ROOT) -> dict:
    path = version_dir(version, model_root) / NORM_FILENAME
    return json.loads(path.read_text(encoding="utf-8"))


def register(
    version: str,
    metrics: dict,
    model_root: Path = FLOOD_DL_MODEL_ROOT,
    extra: dict | None = None,
    set_latest: bool = True,
) -> None:
    """Record a fully-written version and (by default) make it "latest".

    Refuses a version whose artifacts are not all present, so registry.json
    can never point at something the API cannot actually load."""
    model_root = Path(model_root)
    if not version_exists(version, model_root):
        missing = [name for name in REQUIRED_FILES if not (version_dir(version, model_root) / name).exists()]
        raise FileNotFoundError(f"{version} is incomplete, missing: {missing}")
    register_version(
        version=version,
        metrics=metrics,
        created_at=datetime.now(timezone.utc).isoformat(),
        model_root=model_root,
        extra={"family": "flood_dl", **(extra or {})},
        set_latest=set_latest,
    )


def list_versions(model_root: Path = FLOOD_DL_MODEL_ROOT) -> dict:
    """Every registered version's entry, for `--help`-style introspection and
    for a future console view. read_registry() returns an empty-but-valid
    registry when no file exists yet, so a fresh checkout answers {} rather
    than raising."""
    return read_registry(Path(model_root)).get("versions", {})
