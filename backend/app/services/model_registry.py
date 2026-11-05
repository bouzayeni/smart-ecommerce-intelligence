"""Load registered models from the MLflow registry (latest version), cached per process."""

import logging
import threading
from dataclasses import dataclass
from functools import lru_cache

from app.core.config import REPO_ROOT, get_settings

log = logging.getLogger("app.models")
_lock = threading.Lock()


@dataclass
class LoadedModel:
    name: str
    version: str
    model: object


def tracking_uri() -> str:
    uri = get_settings().mlflow_tracking_uri
    if not uri or uri.startswith("file:"):
        uri = f"sqlite:///{(REPO_ROOT / 'mlflow' / 'mlflow.db').as_posix()}"
    return uri


def registry_versions() -> list[dict]:
    """Every registered model's latest version, or [] when MLflow is unavailable."""
    try:
        from mlflow.tracking import MlflowClient

        client = MlflowClient(tracking_uri=tracking_uri())
        out = []
        for rm in client.search_registered_models():
            versions = client.search_model_versions(f"name = '{rm.name}'")
            latest = max(versions, key=lambda v: int(v.version))
            out.append(
                {
                    "name": rm.name,
                    "latest_version": latest.version,
                    "created_at": latest.creation_timestamp,
                    "run_id": latest.run_id,
                    "status": latest.status,
                }
            )
        return out
    except Exception as exc:  # registry is optional for read-only endpoints
        log.warning("MLflow registry unavailable: %s", exc)
        return []


@lru_cache(maxsize=4)
def load_latest(name: str) -> LoadedModel:
    with _lock:
        import mlflow
        from mlflow.tracking import MlflowClient

        mlflow.set_tracking_uri(tracking_uri())
        versions = MlflowClient().search_model_versions(f"name = '{name}'")
        if not versions:
            raise LookupError(f"No registered versions for model {name!r}")
        latest = max(versions, key=lambda v: int(v.version))
        model = mlflow.sklearn.load_model(f"models:/{name}/{latest.version}")
        log.info("Loaded model %s v%s", name, latest.version)
        return LoadedModel(name, latest.version, model)
