"""Promote a registered model version to the `champion` alias, behind a quality gate.

Training registers a new version on every run but does not change what the API serves: the
API loads `models:/<name>@champion`. Promotion compares the candidate's held-out test metric
(logged on its run at training time) with the current champion's and moves the alias only if
the candidate is not worse than the tolerance allows.

    python -m ml.promote_model repurchase_propensity            # latest version vs champion
    python -m ml.promote_model customer_spend_90d --version 3
    python -m ml.promote_model repurchase_propensity --dry-run
    python -m ml.promote_model repurchase_propensity --force    # skip the gate (audited tag)

Exit code 0 = promoted (or already champion), 1 = gate failed, 2 = usage/registry error.
"""

import argparse
import getpass
import sys
from dataclasses import dataclass
from datetime import UTC, datetime

from mlflow.exceptions import MlflowException
from mlflow.tracking import MlflowClient

from ml.tracking import tracking_uri

ALIAS = "champion"


@dataclass(frozen=True)
class Gate:
    metric: str  # run metric logged at training time
    higher_is_better: bool
    tolerance: float  # allowed regression, in metric units


GATES = {
    "repurchase_propensity": Gate("test_pr_auc", True, 0.005),
    "customer_spend_90d": Gate("test_rmse", False, 0.5),
}


@dataclass
class Decision:
    promote: bool
    reason: str
    candidate_value: float | None
    champion_value: float | None


def decide(gate: Gate, candidate: float | None, champion: float | None) -> Decision:
    if candidate is None:
        return Decision(False, f"candidate has no {gate.metric} metric", None, champion)
    if champion is None:
        return Decision(True, "no current champion", candidate, None)
    delta = candidate - champion if gate.higher_is_better else champion - candidate
    if delta >= -gate.tolerance:
        return Decision(
            True, f"{gate.metric} change within gate ({delta:+.4f} better)", candidate, champion
        )
    return Decision(
        False,
        f"{gate.metric} regressed by {-delta:.4f} > tolerance {gate.tolerance}",
        candidate,
        champion,
    )


def run_metric(client: MlflowClient, run_id: str | None, metric: str) -> float | None:
    if not run_id:
        return None
    return client.get_run(run_id).data.metrics.get(metric)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("model", choices=sorted(GATES))
    p.add_argument("--version", help="registered version to promote (default: latest)")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--force", action="store_true", help="promote even if the gate fails")
    args = p.parse_args(argv)

    client = MlflowClient(tracking_uri=tracking_uri())
    gate = GATES[args.model]
    try:
        versions = client.search_model_versions(f"name = '{args.model}'")
        if not versions:
            print(f"No registered versions of {args.model}", file=sys.stderr)
            return 2
        by_number = {v.version: v for v in versions}
        version = args.version or max(by_number, key=int)
        if version not in by_number:
            print(f"{args.model} has no version {version}", file=sys.stderr)
            return 2
        candidate = by_number[version]
        try:
            champion = client.get_model_version_by_alias(args.model, ALIAS)
        except MlflowException:
            champion = None
    except MlflowException as exc:
        print(f"Registry error: {exc}", file=sys.stderr)
        return 2

    if champion is not None and champion.version == version:
        print(f"{args.model} v{version} is already {ALIAS}")
        return 0
    decision = decide(
        gate,
        run_metric(client, candidate.run_id, gate.metric),
        run_metric(client, champion.run_id, gate.metric) if champion else None,
    )
    label = f"v{champion.version}" if champion else "none"
    print(
        f"{args.model}: candidate v{version} {gate.metric}={decision.candidate_value} | "
        f"champion {label} {gate.metric}={decision.champion_value}"
    )
    print(f"gate: {'PASS' if decision.promote else 'FAIL'} - {decision.reason}")
    if not decision.promote and not args.force:
        return 1
    if args.dry_run:
        print("dry run: alias not changed")
        return 0
    client.set_registered_model_alias(args.model, ALIAS, version)
    stamp = datetime.now(UTC).isoformat(timespec="seconds")
    tags = {
        "promoted_at": stamp,
        "promoted_by": getpass.getuser(),
        "promotion_gate": "forced" if not decision.promote else "passed",
        "promotion_reason": decision.reason,
    }
    for k, v in tags.items():
        client.set_model_version_tag(args.model, version, k, v)
    print(f"{args.model} v{version} is now {ALIAS}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
