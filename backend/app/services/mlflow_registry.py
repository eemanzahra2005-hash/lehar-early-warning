"""Best-effort MLflow Model Registry "champion" alias updates on promote/
rollback (Phase 7).

HARD RULE: this NEVER blocks or fails a promote/rollback API call. The local
backend/ml/model/registry.json dual-write (see ml/registry.py) is
authoritative for what ModelService actually serves — this service is
audit/UI-nicety on top of that, mirroring the "training must work fully
offline" contract from backend/ml/pipeline.py. Any failure (server down,
version has no MLflow registration, ...) is caught and logged, never raised.
"""

import logging

from app.config import get_settings

logger = logging.getLogger("app.mlflow_registry")

MLFLOW_REGISTERED_MODEL_NAME = "irrigation-rf"
HEALTH_TIMEOUT_SECONDS = 2.0


class MlflowRegistryService:
    def __init__(self, tracking_uri: str | None = None, health_timeout: float = HEALTH_TIMEOUT_SECONDS):
        settings = get_settings()
        self.tracking_uri = tracking_uri if tracking_uri is not None else settings.mlflow_tracking_uri
        self.health_timeout = health_timeout

    def is_reachable(self) -> bool:
        try:
            import requests

            response = requests.get(f"{self.tracking_uri.rstrip('/')}/health", timeout=self.health_timeout)
            return response.status_code == 200
        except Exception:
            return False

    def set_champion_alias(self, mlflow_model_version: str | None) -> bool:
        """Points the "champion" alias at this MLflow model version. Returns
        True if it actually updated the alias, False for any reason it
        didn't (no recorded version for this registry.json entry — e.g. a
        pre-Phase-7 "legacy" version — server unreachable, or any other
        failure). Never raises."""
        if not mlflow_model_version:
            logger.info("No recorded MLflow model version for this promotion — skipping 'champion' alias update.")
            return False
        if not self.is_reachable():
            logger.warning("MLflow server at %s is unreachable — skipping 'champion' alias update.", self.tracking_uri)
            return False
        try:
            import mlflow

            mlflow.set_tracking_uri(self.tracking_uri)
            mlflow.MlflowClient().set_registered_model_alias(
                MLFLOW_REGISTERED_MODEL_NAME, "champion", mlflow_model_version
            )
            logger.info("MLflow: alias 'champion' now points at version %s.", mlflow_model_version)
            return True
        except Exception:
            logger.warning("Failed to update the MLflow 'champion' alias — promotion still succeeded.", exc_info=True)
            return False
