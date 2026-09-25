"""Build-time-only helper (Phase 13.1): keeps just the served model
version(s) inside a container image, deleting every other
backend/ml/model/<version>/ directory.

Invoked from backend/Dockerfile's RUN step ONLY when the PRUNE_MODEL_VERSIONS
build arg is "true" — Render's build sets this (see render.yaml; Render
auto-translates a Docker service's envVars into build ARGs of the same name,
see docs/DEPLOY_RENDER.md). Local `docker compose build`/`up` never sets that
build arg, so it's a no-op there and every version keeps shipping, exactly as
before this phase — CLAUDE.md rule 6 ("never overwrite a version directory")
is about the real, working registry; this script only ever runs against a
throwaway container filesystem during a build, never the real repo.

Keeps:
  - registry.json's "latest" pointer's version (the local production model —
    untouched by this phase)
  - the MODEL_VERSION build arg's value, if it's set to something other than
    "latest" (Render pins the compact deployment model this way)
registry.json itself is always kept — GET /api/v1/models reads it for every
version's metadata regardless of whether that version's artifact files are
still on disk (a pruned-away version's `model.joblib` simply won't exist,
which ml/registry.py's version_exists() already checks before any promote).
"""

import os
import shutil
import sys
from pathlib import Path

ML_DIR = Path(__file__).resolve().parent
BACKEND_DIR = ML_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from ml.registry import DEFAULT_MODEL_ROOT, read_registry  # noqa: E402


def main() -> None:
    model_root = DEFAULT_MODEL_ROOT
    registry = read_registry(model_root)

    keep = set()
    latest = registry.get("latest")
    if latest:
        keep.add(latest)

    pinned = os.environ.get("MODEL_VERSION", "latest")
    if pinned and pinned != "latest":
        keep.add(pinned)

    if not keep:
        print("prune_unused_versions: no version to keep (empty registry) — leaving backend/ml/model/ untouched.")
        return

    removed = []
    for entry in sorted(model_root.iterdir()):
        if entry.is_dir() and entry.name not in keep:
            shutil.rmtree(entry)
            removed.append(entry.name)

    print(f"prune_unused_versions: kept {sorted(keep)}; removed {len(removed)} version dir(s): {removed}")


if __name__ == "__main__":
    main()
