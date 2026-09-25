"""Phase 15.2 regression guard: "put the key in backend\\.env" must work in
Docker mode too.

docker-compose.yml's "api" service loads backend/.env via env_file. Compose
gives `environment:` precedence over `env_file`, so ANY LLM_* entry in that
service's environment block — even an empty ${LLM_CLOUD_API_KEY:-} — silently
shadows backend/.env again: the exact bug behind the 24 Aug support incident,
where a key in backend\\.env never reached the container. Static checks on
the committed files only — no Docker needed, so this also runs in CI.
"""

from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Container-specific values that deliberately override backend/.env inside
# the api container (documented next to that block in docker-compose.yml and
# at the top of backend/.env.example).
CONTAINER_OVERRIDES = {"DATABASE_URL", "JWT_SECRET", "OLLAMA_BASE_URL", "MLFLOW_TRACKING_URI", "PORT"}
ASSISTANT_KEYS = {"LLM_PROVIDER", "LLM_CLOUD_API_KEY"}


def _services() -> dict:
    return yaml.safe_load((PROJECT_ROOT / "docker-compose.yml").read_text(encoding="utf-8"))["services"]


def _assigned_keys(env_example: Path) -> set[str]:
    """Variable names actually assigned (not just mentioned in a comment)."""
    keys = set()
    for line in env_example.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            keys.add(stripped.split("=", 1)[0].strip())
    return keys


def test_api_service_loads_backend_env_file():
    entries = _services()["api"]["env_file"]
    paths = [entry["path"] if isinstance(entry, dict) else entry for entry in entries]
    assert "./backend/.env" in paths


def test_api_environment_never_shadows_backend_env_assistant_settings():
    environment = _services()["api"]["environment"]
    assert not [name for name in environment if name.startswith("LLM_")]
    # Only the documented container-specific overrides — anything else here
    # would silently beat the user's backend/.env value.
    assert set(environment) <= CONTAINER_OVERRIDES


def test_only_the_api_service_reads_backend_env():
    services = _services()
    assert [name for name, service in services.items() if "env_file" in service] == ["api"]


def test_assistant_settings_live_in_backend_env_example_not_root():
    assert ASSISTANT_KEYS <= _assigned_keys(PROJECT_ROOT / "backend" / ".env.example")
    assert not ASSISTANT_KEYS & _assigned_keys(PROJECT_ROOT / ".env.example")


def test_first_run_key_prompt_writes_backend_env_not_root_env():
    script = (PROJECT_ROOT / "scripts" / "ensure_env.ps1").read_text(encoding="utf-8")
    assert 'Set-EnvValue -Path $backendEnv -Key "LLM_CLOUD_API_KEY"' in script
    assert "Set-EnvValue -Path $rootEnv" not in script
