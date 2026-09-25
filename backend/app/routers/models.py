"""Model introspection endpoints (feature importance, model card, ...) and
the Phase 7 MLOps registry: list versions, promote, rollback."""

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth import get_current_user
from app.config import get_settings
from app.db import User
from app.dependencies import get_mlflow_registry_service, get_model_service, reload_model_service
from app.schemas import (
    FeatureImportanceResponse,
    ModelInfoResponse,
    ModelListResponse,
    ModelVersionSummary,
    PromoteResponse,
)
from app.services.alerts.ops_events import record_ops_event
from app.services.ml_model import ModelService
from ml.explain_utils import AGGREGATED_FEATURE_ORDER
from ml.registry import promote_to, read_registry, rollback_target, version_exists

if TYPE_CHECKING:  # pragma: no cover - typing only
    # LEHAR Phase 1: type-only, so importing this router (which app/main.py
    # does at startup) never pulls the MLflow-facing service in. The real
    # instance arrives via Depends(get_mlflow_registry_service), which
    # imports it lazily — see app/dependencies.py. Every registry read on
    # this router goes through ml/registry.py (plain registry.json), never
    # through MLflow.
    from app.services.mlflow_registry import MlflowRegistryService

router = APIRouter(prefix="/models", tags=["models"])


@router.get("/feature-importance", response_model=FeatureImportanceResponse)
def get_feature_importance(model_service: ModelService = Depends(get_model_service)) -> FeatureImportanceResponse:
    return FeatureImportanceResponse(
        model_version=model_service.version,
        feature_importance=model_service.feature_importance(),
    )


@router.get("/info", response_model=ModelInfoResponse)
def get_model_info(model_service: ModelService = Depends(get_model_service)) -> ModelInfoResponse:
    """Model card data for the Explainability page (#/explainability):
    version + created_at from registry.json, real metrics from
    metrics.json (via ModelService.metrics), dataset_rows derived from the
    real train/test split sizes recorded at training time, and the fixed
    11-feature list (ml/explain_utils.py) the model was trained on."""
    registry = read_registry(model_service.model_root)
    entry = registry.get("versions", {}).get(model_service.version, {})
    metrics = model_service.metrics
    return ModelInfoResponse(
        version=model_service.version,
        created_at=entry.get("created_at"),
        metrics=metrics,
        feature_list=AGGREGATED_FEATURE_ORDER,
        dataset_rows=int(metrics.get("n_train", 0)) + int(metrics.get("n_test", 0)),
    )


@router.get("", response_model=ModelListResponse)
def list_models(model_service: ModelService = Depends(get_model_service)) -> ModelListResponse:
    """All trained model versions (public — same visibility as the other
    /models endpoints): metrics, which one is PRODUCTION, and — for
    pipeline-trained versions — the quality-gate decision that got them
    there. Powers the Models page (#/models)."""
    registry = read_registry(model_service.model_root)
    latest = registry.get("latest")

    versions = [
        ModelVersionSummary(
            version=version,
            created_at=entry.get("created_at"),
            metrics=entry.get("metrics", {}),
            source=entry.get("source", "legacy"),
            is_production=(version == latest),
            gate=entry.get("gate"),
            mlflow_run_id=entry.get("mlflow_run_id"),
            mlflow_model_version=entry.get("mlflow_model_version"),
        )
        for version, entry in registry.get("versions", {}).items()
    ]
    versions.sort(key=lambda v: v.created_at or "", reverse=True)

    return ModelListResponse(
        latest=latest,
        versions=versions,
        history=registry.get("history", []),
        mlflow_url=get_settings().mlflow_tracking_uri,
    )


def _promote_or_raise(
    version: str,
    action: str,
    username: str,
    model_service: ModelService,
    mlflow_registry: "MlflowRegistryService",
) -> PromoteResponse:
    model_root = model_service.model_root
    if not version_exists(version, model_root):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Model version '{version}' not found.")

    registry = read_registry(model_root)
    entry = registry.get("versions", {}).get(version)
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Model version '{version}' has no registry.json entry."
        )

    # Promote/rollback validates against the ABSOLUTE ceilings only (not the
    # tolerance-vs-production comparison — that's the training-time gate's
    # job; this is an explicit human decision on an already-registered
    # model). See docs/MLOPS.md.
    settings = get_settings()
    metrics = entry.get("metrics", {})
    if metrics.get("mae") is not None and metrics["mae"] > settings.qg_max_mae:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Version '{version}' MAE {metrics['mae']:.4f} exceeds QG_MAX_MAE={settings.qg_max_mae}.",
        )
    if metrics.get("r2") is not None and metrics["r2"] < settings.qg_min_r2:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Version '{version}' R2 {metrics['r2']:.4f} is below QG_MIN_R2={settings.qg_min_r2}.",
        )

    updated_registry = promote_to(version, username, model_root=model_root, action=action)
    reload_model_service(model_root)
    mlflow_registry.set_champion_alias(entry.get("mlflow_model_version"))

    if action == "rollback":
        # LEHAR Phase 2: a rollback is one of the three OPS triggers (see
        # app/services/alerts/rules.py's evaluate_ops). record_ops_event is
        # best-effort and never raises, so this can't turn a successful
        # rollback into a failed request.
        record_ops_event("rollback", f"Rolled back to model version {version} (by {username}).")

    return PromoteResponse(
        version=version,
        latest=updated_registry["latest"],
        history=updated_registry.get("history", []),
        message=f"{'Promoted' if action == 'promote' else 'Rolled back'} to version {version}.",
    )


@router.post("/{version}/promote", response_model=PromoteResponse)
def promote_model(
    version: str,
    current_user: User = Depends(get_current_user),
    model_service: ModelService = Depends(get_model_service),
    # Deliberately un-annotated: FastAPI resolves path-operation parameter
    # annotations at import time, which would defeat the lazy import above.
    mlflow_registry=Depends(get_mlflow_registry_service),
) -> PromoteResponse:
    """Promotes `version` to production: registry.json's "latest" ->
    version, the outgoing production version is pushed onto "history" (so
    rollback can undo this), an audit entry is appended, and every service
    built on ModelService (including the SHAP explainer) hot-reloads
    in-process. Auth required. See docs/MLOPS.md."""
    return _promote_or_raise(version, "promote", current_user.username, model_service, mlflow_registry)


@router.post("/rollback", response_model=PromoteResponse)
def rollback_model(
    current_user: User = Depends(get_current_user),
    model_service: ModelService = Depends(get_model_service),
    mlflow_registry=Depends(get_mlflow_registry_service),  # un-annotated: see promote_model above
) -> PromoteResponse:
    """Promotes whatever is at the top of registry.json's "history" stack —
    i.e. the previous production version — through the exact same path as
    promote_model. 400 if there's nothing to roll back to. Auth required."""
    model_root = model_service.model_root
    target = rollback_target(model_root)
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="No previous production version to roll back to."
        )
    return _promote_or_raise(target, "rollback", current_user.username, model_service, mlflow_registry)
