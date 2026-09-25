"""Tests for GET /api/v1/models/feature-importance, /api/v1/models/info, and
the Phase 7 MLOps registry: GET /api/v1/models (list), POST
/api/v1/models/{version}/promote, POST /api/v1/models/rollback.
"""

import json
from types import SimpleNamespace

import pytest

from app import dependencies
from app.dependencies import get_mlflow_registry_service
from app.main import app
from app.services.ml_model import ModelService
from ml.explain_utils import AGGREGATED_FEATURE_ORDER
from ml.generate_data import generate_dataset
from ml.registry import read_registry
from ml.train_model import run_training


def test_feature_importance_returns_real_model_data(client):
    response = client.get("/api/v1/models/feature-importance")

    assert response.status_code == 200
    body = response.json()
    assert body["model_version"]
    assert body["feature_importance"]
    assert set(body["feature_importance"].keys()) == set(AGGREGATED_FEATURE_ORDER)


def test_model_info_returns_registry_and_metrics_data(client):
    response = client.get("/api/v1/models/info")

    assert response.status_code == 200
    body = response.json()
    assert body["version"]
    assert body["created_at"]
    assert body["metrics"]["mae"] >= 0
    assert body["metrics"]["r2"] <= 1.0
    assert set(body["feature_list"]) == set(AGGREGATED_FEATURE_ORDER)
    assert body["dataset_rows"] == body["metrics"]["n_train"] + body["metrics"]["n_test"]


# --- Phase 7: registry list + promote/rollback --------------------------------

class FakeMlflowRegistryService:
    """No-op stand-in for MlflowRegistryService — keeps promote/rollback
    tests fully offline regardless of whether a real
    `docker compose up -d mlflow` happens to be running locally, and records
    calls so tests can assert the router actually invoked it."""

    def __init__(self):
        self.calls: list[str | None] = []

    def set_champion_alias(self, mlflow_model_version):
        self.calls.append(mlflow_model_version)
        return False


@pytest.fixture
def promotable_registry(tmp_path):
    """Seeds the ModelService singleton with two REAL, tiny trained versions
    in a tmp registry (via the existing, already-tested run_training()), so
    promote/rollback's hot-reload — including rebuilding the SHAP explainer
    against a genuinely different loadable model — is exercised end to end.
    version_b (trained second) starts as production; version_a is the
    promote/rollback target. Restores the original production ModelService
    singleton afterward so later tests are unaffected."""
    original_model_service = dependencies.get_model_service()

    df = generate_dataset(rows_per_district=15)
    model_root = tmp_path / "model"
    metrics_a = run_training(df=df, model_root=model_root, n_estimators=5, max_depth=5)
    metrics_b = run_training(df=df, model_root=model_root, n_estimators=5, max_depth=5)

    fake_mlflow = FakeMlflowRegistryService()
    app.dependency_overrides[get_mlflow_registry_service] = lambda: fake_mlflow
    dependencies.set_model_service(ModelService(model_root=model_root, version="latest"))

    yield SimpleNamespace(
        model_root=model_root, version_a=metrics_a["version"], version_b=metrics_b["version"], fake_mlflow=fake_mlflow
    )

    dependencies.set_model_service(original_model_service)
    app.dependency_overrides.pop(get_mlflow_registry_service, None)


def test_list_models_shows_both_versions_with_production_flag(client, promotable_registry):
    response = client.get("/api/v1/models")

    assert response.status_code == 200
    body = response.json()
    assert body["latest"] == promotable_registry.version_b
    versions_by_id = {v["version"]: v for v in body["versions"]}
    assert set(versions_by_id) == {promotable_registry.version_a, promotable_registry.version_b}
    assert versions_by_id[promotable_registry.version_b]["is_production"] is True
    assert versions_by_id[promotable_registry.version_a]["is_production"] is False
    # run_training() (unlike ml/pipeline.py) never sets extra_registry_fields
    # — both versions here should read back as "legacy".
    assert versions_by_id[promotable_registry.version_a]["source"] == "legacy"


def test_promote_requires_auth(client, promotable_registry):
    response = client.post(f"/api/v1/models/{promotable_registry.version_a}/promote")
    assert response.status_code == 401


def test_rollback_requires_auth(client, promotable_registry):
    response = client.post("/api/v1/models/rollback")
    assert response.status_code == 401


def test_promote_nonexistent_version_returns_404(client, register_user, promotable_registry):
    token = register_user()
    response = client.post(
        "/api/v1/models/v-does-not-exist/promote", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 404


def test_rollback_with_no_history_returns_400(client, register_user, promotable_registry):
    token = register_user()
    response = client.post("/api/v1/models/rollback", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 400


def test_promote_rejects_version_exceeding_absolute_ceiling(client, register_user, promotable_registry):
    registry_path = promotable_registry.model_root / "registry.json"
    registry = read_registry(promotable_registry.model_root)
    registry["versions"][promotable_registry.version_a]["metrics"]["mae"] = 999.0
    registry_path.write_text(json.dumps(registry))

    token = register_user()
    response = client.post(
        f"/api/v1/models/{promotable_registry.version_a}/promote", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 422


def test_promote_and_rollback_roundtrip(client, register_user, promotable_registry):
    token = register_user(username="mlops_admin")
    headers = {"Authorization": f"Bearer {token}"}
    version_a, version_b = promotable_registry.version_a, promotable_registry.version_b

    # --- Promote version_a (currently production is version_b) ---
    promote_response = client.post(f"/api/v1/models/{version_a}/promote", headers=headers)
    assert promote_response.status_code == 200
    body = promote_response.json()
    assert body["version"] == version_a
    assert body["latest"] == version_a
    assert body["history"] == [version_b]

    # Hot reload actually took effect app-wide (not just in the response body).
    info_response = client.get("/api/v1/models/info")
    assert info_response.json()["version"] == version_a

    registry = read_registry(promotable_registry.model_root)
    assert registry["latest"] == version_a
    assert registry["history"] == [version_b]
    assert len(registry["audit"]) == 1
    assert registry["audit"][0] == {
        "action": "promote",
        "version": version_a,
        "username": "mlops_admin",
        "timestamp": registry["audit"][0]["timestamp"],
    }
    assert promotable_registry.fake_mlflow.calls == [None]  # "legacy" versions have no mlflow_model_version

    # --- Roll back: should promote version_b again ---
    rollback_response = client.post("/api/v1/models/rollback", headers=headers)
    assert rollback_response.status_code == 200
    rollback_body = rollback_response.json()
    assert rollback_body["version"] == version_b
    assert rollback_body["latest"] == version_b
    assert rollback_body["history"] == [version_a]

    info_response_2 = client.get("/api/v1/models/info")
    assert info_response_2.json()["version"] == version_b

    registry_after_rollback = read_registry(promotable_registry.model_root)
    assert registry_after_rollback["latest"] == version_b
    assert registry_after_rollback["history"] == [version_a]
    assert len(registry_after_rollback["audit"]) == 2
    assert registry_after_rollback["audit"][1]["action"] == "rollback"
    assert registry_after_rollback["audit"][1]["version"] == version_b
