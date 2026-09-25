"""The deployed image's configuration (LEHAR Phase 1).

These assert on backend/Dockerfile, backend/docker-entrypoint.sh and
backend/requirements-deploy.txt as text, because the thing being protected
is what SHIPS, and nothing else in the suite would notice if a 512MB-safety
setting quietly disappeared from them. They intentionally do not build or
run the image (Docker is not a test dependency of this project) — see
docs/MEMORY.md for the measured runtime numbers.
"""

import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
BACKEND_DIR = PROJECT_ROOT / "backend"

DOCKERFILE = (BACKEND_DIR / "Dockerfile").read_text(encoding="utf-8")
ENTRYPOINT = (BACKEND_DIR / "docker-entrypoint.sh").read_text(encoding="utf-8")
DEPLOY_REQUIREMENTS = (BACKEND_DIR / "requirements-deploy.txt").read_text(encoding="utf-8")
RUNTIME_REQUIREMENTS = (BACKEND_DIR / "requirements.txt").read_text(encoding="utf-8")


def _without_comments(text: str) -> str:
    """Drops whole-line comments, so a "must NOT appear" assertion below is
    testing the actual instructions rather than prose that discusses them —
    these files document their own reasoning heavily, on purpose."""
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


DOCKERFILE_INSTRUCTIONS = _without_comments(DOCKERFILE)
ENTRYPOINT_COMMANDS = _without_comments(ENTRYPOINT)


def _pinned_packages(requirements: str) -> dict[str, str]:
    """{package_name: version} for every real (non-comment) pin, with any
    extras marker stripped: "psycopg[binary]==3.2.10" -> {"psycopg": "3.2.10"}."""
    pins = {}
    for line in requirements.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line or line.startswith("-r "):
            continue
        match = re.match(r"^([A-Za-z0-9._-]+)(?:\[[^\]]+\])?==(.+)$", line)
        assert match, f"not an exact pin (CLAUDE.md rule 8): {line!r}"
        pins[match.group(1).lower()] = match.group(2)
    return pins


# --- Production defaults baked into the image --------------------------------


def test_image_sets_the_512mb_production_defaults():
    for setting in ("WEB_CONCURRENCY=1", "LOW_MEMORY_MODE=true", "MALLOC_ARENA_MAX=2"):
        assert f"ENV {setting}" in DOCKERFILE, f"missing production default: {setting}"


def test_image_reports_production_environment():
    """GET /api/v1/health's `environment` should say "production" on a
    deployed host rather than the local-dev default."""
    assert "ENV ENVIRONMENT=production" in DOCKERFILE


def test_entrypoint_starts_exactly_one_worker_by_default():
    assert 'WEB_CONCURRENCY="${WEB_CONCURRENCY:-1}"' in ENTRYPOINT
    assert '--workers "${WEB_CONCURRENCY}"' in ENTRYPOINT
    # The reloader would fork a second watcher process this profile can't afford.
    assert "--reload" not in ENTRYPOINT_COMMANDS


def test_entrypoint_runs_migrations_when_run_migrations_is_true():
    """Render free has no shell, so this is the only path by which
    migrations get applied there."""
    assert 'RUN_MIGRATIONS="${RUN_MIGRATIONS:-true}"' in ENTRYPOINT
    assert 'if [ "$RUN_MIGRATIONS" = "true" ]; then' in ENTRYPOINT
    assert "alembic upgrade head" in ENTRYPOINT
    assert "ENV RUN_MIGRATIONS=true" in DOCKERFILE


def test_entrypoint_can_skip_migrations():
    """The gate has to have a real 'off' branch, for a deployment that
    applies migrations out-of-band."""
    assert "else" in ENTRYPOINT_COMMANDS
    assert "skipping" in ENTRYPOINT_COMMANDS


# --- What the image installs -------------------------------------------------


def test_image_installs_the_deployment_requirements_only():
    assert "requirements-deploy.txt" in DOCKERFILE
    assert "requirements-dev.txt" not in DOCKERFILE_INSTRUCTIONS
    # Guard against a plain `COPY backend/requirements.txt` creeping back in.
    assert not re.search(r"^COPY backend/requirements\.txt", DOCKERFILE_INSTRUCTIONS, flags=re.MULTILINE)


def test_deployment_requirements_exclude_the_training_only_dependencies():
    """mlflow is the single heaviest dependency here and is never used to
    serve a request; pandera validates training datasets only. Enforced at
    runtime too — see test_no_heavy_imports.py."""
    pins = _pinned_packages(DEPLOY_REQUIREMENTS)

    assert "mlflow" not in pins
    assert "pandera" not in pins
    assert "torch" not in pins
    # LEHAR Phase 2.5: torch trains the flood lead-time model; the API runs
    # the exported ONNX graph. `onnx` is the exporter's own dependency and is
    # equally training-only — only `onnxruntime` belongs in the image.
    assert "onnx" not in pins


def test_the_image_never_installs_the_training_only_requirements_file():
    """backend/requirements-ml.txt exists precisely so PyTorch has somewhere
    to live that is not the deployed image (CLAUDE.md rule 11)."""
    assert "requirements-ml.txt" not in DOCKERFILE_INSTRUCTIONS


def test_training_only_requirements_pin_torch_and_never_leak_into_the_runtime_set():
    ml_pins = _pinned_packages((BACKEND_DIR / "requirements-ml.txt").read_text(encoding="utf-8"))
    runtime_pins = _pinned_packages(RUNTIME_REQUIREMENTS)

    assert "torch" in ml_pins
    assert "onnx" in ml_pins
    # requirements.txt is the local/dev/CI source of truth and deliberately
    # does NOT pull torch in: the suite must stay runnable without it.
    assert "torch" not in runtime_pins
    assert "onnx" not in runtime_pins


def test_deployment_requirements_keep_every_real_serving_dependency():
    pins = _pinned_packages(DEPLOY_REQUIREMENTS)

    for package in (
        "fastapi",        # the API itself
        "uvicorn",
        "scikit-learn",   # loading/running the model
        "pandas",
        "numpy",
        "joblib",
        "shap",           # per-prediction explanations
        "reportlab",      # PDF reports
        "openpyxl",       # Excel reports
        "alembic",        # applied by the entrypoint on start
        "psycopg",        # the deployed database is Postgres
        "psutil",         # the RSS reporting this phase added
        "onnxruntime",    # the flood lead-time model's serving runtime (Phase 2.5)
    ):
        assert package in pins, f"serving dependency missing from requirements-deploy.txt: {package}"


def test_deployment_pins_match_requirements_txt_exactly():
    """The deployed image must run the versions the test suite actually ran
    against — a drifting pin here is a deploy-only bug by construction."""
    deploy_pins = _pinned_packages(DEPLOY_REQUIREMENTS)
    runtime_pins = _pinned_packages(RUNTIME_REQUIREMENTS)

    for package, version in deploy_pins.items():
        assert package in runtime_pins, f"{package} is deployed but not in requirements.txt"
        assert runtime_pins[package] == version, (
            f"{package} pinned at {version} for deployment but {runtime_pins[package]} in requirements.txt"
        )
