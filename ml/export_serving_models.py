"""Export the champion version of each registered model to a portable serving bundle.

The local registry stores absolute artifact paths of the machine that trained the models, so
a container cannot resolve them. This copies each champion model to
`models/serving/<name>/model/` with a `manifest.json` (name, version, run id, metrics); the
API loads from there when SERVING_MODELS_DIR is set (docker-compose mounts it read-only).

    python -m ml.export_serving_models              # all models with a champion alias
    python -m ml.export_serving_models --out other/dir
"""

import argparse
import json
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

import mlflow
from mlflow.exceptions import MlflowException
from mlflow.tracking import MlflowClient

from data_engineering.config import PROJECT_ROOT
from ml.promote_model import ALIAS, GATES
from ml.tracking import tracking_uri


def export(client: MlflowClient, name: str, out: Path) -> dict:
    version = client.get_model_version_by_alias(name, ALIAS)
    target = out / name
    staging = out / f".{name}.tmp"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    mlflow.artifacts.download_artifacts(f"models:/{name}@{ALIAS}", dst_path=str(staging / "model"))
    metrics = client.get_run(version.run_id).data.metrics if version.run_id else {}
    manifest = {
        "name": name,
        "version": str(version.version),
        "alias": ALIAS,
        "run_id": version.run_id,
        "test_metrics": {k: v for k, v in sorted(metrics.items()) if k.startswith("test_")},
        "exported_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    (staging / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    # Copy rather than rename: on Windows a just-written directory can stay locked briefly.
    shutil.rmtree(target, ignore_errors=True)
    shutil.copytree(staging, target)
    shutil.rmtree(staging, ignore_errors=True)
    return manifest


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--out", type=Path, default=PROJECT_ROOT / "models" / "serving")
    args = p.parse_args(argv)
    mlflow.set_tracking_uri(tracking_uri())
    client = MlflowClient()
    failed = False
    for name in sorted(GATES):
        try:
            m = export(client, name, args.out)
            print(f"exported {name} v{m['version']} -> {args.out / name}")
        except MlflowException as exc:
            failed = True
            print(f"skipped {name}: {exc.message}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
