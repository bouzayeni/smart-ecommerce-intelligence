"""MLflow setup: local SQLite backend (runs, metrics, model registry) + file artifact store."""

import hashlib
import json
import os

import mlflow
from dotenv import load_dotenv

from data_engineering.config import PROJECT_ROOT

MLFLOW_DIR = PROJECT_ROOT / "mlflow"
DEFAULT_URI = f"sqlite:///{(MLFLOW_DIR / 'mlflow.db').as_posix()}"
ARTIFACT_ROOT = (MLFLOW_DIR / "artifacts").as_uri()


def tracking_uri() -> str:
    """MLFLOW_TRACKING_URI, or the project SQLite store (needed for the model registry)."""
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    uri = os.environ.get("MLFLOW_TRACKING_URI") or DEFAULT_URI
    return DEFAULT_URI if uri.startswith("file:") else uri  # .env.example's old default


def setup(experiment: str) -> str:
    """Point MLflow at the project store and return the experiment id."""
    MLFLOW_DIR.mkdir(exist_ok=True)
    mlflow.set_tracking_uri(tracking_uri())
    existing = mlflow.get_experiment_by_name(experiment)
    experiment_id = (
        existing.experiment_id
        if existing
        else mlflow.create_experiment(experiment, artifact_location=ARTIFACT_ROOT)
    )
    # Make it the active experiment: nested runs (start_run(nested=True)) use the active
    # experiment, not their parent's, and would otherwise land in "Default".
    mlflow.set_experiment(experiment_id=experiment_id)
    return experiment_id


def data_fingerprint() -> dict:
    """Identify the training data: bronze file hashes + dbt project vars."""
    manifest = json.loads((PROJECT_ROOT / "data" / "raw" / "_manifest.json").read_text())
    files = {k: v["sha256"] for k, v in sorted(manifest["files"].items())}
    digest = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
    return {"bronze_files_sha256": files, "bronze_fingerprint": digest[:16]}
