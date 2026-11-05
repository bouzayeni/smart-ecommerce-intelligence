"""Load registered models from the MLflow registry, cached per process.

The API serves the version behind the `champion` alias (set by `python -m ml.promote_model`
after its quality gate). If a model has no champion yet it falls back to the latest version
and says so in the logs and in /api/models/status."""

import json
import logging
import threading
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.core.config import REPO_ROOT, get_settings

log = logging.getLogger("app.models")
_lock = threading.Lock()


CHAMPION = "champion"


@dataclass
class LoadedModel:
    name: str
    version: int
    model: object
    source: str = CHAMPION  # "champion" or "latest (no champion alias)"


def _serving_version(client, name: str):
    """(version, source): the champion alias, else the highest version number."""
    from mlflow.exceptions import MlflowException

    try:
        return client.get_model_version_by_alias(name, CHAMPION), CHAMPION
    except MlflowException:
        versions = client.search_model_versions(f"name = '{name}'")
        if not versions:
            raise LookupError(f"No registered versions for model {name!r}") from None
        return max(versions, key=lambda v: int(v.version)), "latest (no champion alias)"


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
            serving, source = _serving_version(client, rm.name)
            out.append(
                {
                    "name": rm.name,
                    "latest_version": latest.version,
                    "serving_version": serving.version,
                    "serving_source": source,
                    "created_at": latest.creation_timestamp,
                    "run_id": serving.run_id,
                    "status": latest.status,
                }
            )
        return out
    except Exception as exc:  # registry is optional for read-only endpoints
        log.warning("MLflow registry unavailable: %s", exc)
        return []


@lru_cache(maxsize=4)
def load_latest(name: str) -> LoadedModel:
    """The serving version (champion, else latest). Cached: restart the API after promoting.

    With SERVING_MODELS_DIR set (containers), loads the bundle written by
    `python -m ml.export_serving_models` instead of resolving registry artifact paths."""
    bundle_dir = get_settings().serving_models_dir
    if bundle_dir is not None:
        return _load_bundle(name, bundle_dir)
    with _lock:
        import mlflow
        from mlflow.tracking import MlflowClient

        mlflow.set_tracking_uri(tracking_uri())
        version, source = _serving_version(MlflowClient(), name)
        model = mlflow.sklearn.load_model(f"models:/{name}/{version.version}")
        if source != CHAMPION:
            log.warning(
                "Model %s has no %s alias; serving latest v%s", name, CHAMPION, version.version
            )
        log.info("Loaded model %s v%s (%s)", name, version.version, source)
        return LoadedModel(name, int(version.version), model, source)


def _load_bundle(name: str, bundle_dir: Path) -> LoadedModel:
    import mlflow

    manifest_path = bundle_dir / name / "manifest.json"
    if not manifest_path.is_file():
        raise LookupError(f"No serving bundle for model {name!r} in {bundle_dir}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    with _lock:
        model = mlflow.sklearn.load_model(str(bundle_dir / name / "model"))
    log.info("Loaded model %s v%s from serving bundle", name, manifest["version"])
    # Same type as the registry path (and ml.* model_version bigint columns).
    return LoadedModel(name, int(manifest["version"]), model, f"bundle ({manifest['alias']})")
