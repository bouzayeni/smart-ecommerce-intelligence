"""Run the data quality check catalog and write the Phase 2 quality report.

Outputs:
    data/processed/quality/dq_results.json   machine-readable results (git-ignored)
    docs/data_quality_report.md              generated report (only with --write-report)

Exit code 1 if any error-severity check fails.

Usage (from the repo root):
    uv run python -m data_engineering.scripts.assess_quality --write-report
    uv run python -m data_engineering.scripts.assess_quality --raw-dir data/sample
"""

import argparse
import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from data_engineering.business_rules import BusinessRules, get_rules
from data_engineering.config import PROJECT_ROOT, get_settings
from data_engineering.quality import analysis as a
from data_engineering.quality.checks import CheckResult, run_checks
from data_engineering.quality.loader import RawTables, load_raw

log = logging.getLogger("assess_quality")

REPORT_PATH = PROJECT_ROOT / "docs" / "data_quality_report.md"


def _md_table(df: pd.DataFrame) -> str:
    cols = [str(c) for c in df.columns]
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    lines += ["| " + " | ".join(str(v) for v in row) + " |" for row in df.itertuples(index=False)]
    return "\n".join(lines)


def build_summary(raw: RawTables, rules: BusinessRules) -> dict:
    start, end, end_source = a.resolve_window(raw, rules)
    td = rules.analysis_window.truncation_detection
    try:
        detected_end = str(
            a.detect_window_end(
                a.daily_orders(raw["orders"]), td.min_ratio, td.baseline_days,
                td.min_baseline_orders,
            )
        )  # fmt: skip
    except ValueError:
        detected_end = "not detectable (too few orders per day)"
    recon = a.payment_reconciliation(raw, rules.payments.reconciliation_tolerance_brl)
    status = a.status_summary(raw, rules)
    delivery = a.delivery_frame(raw, rules)
    opc = a.repeat_customer_summary(raw)
    reviews = raw["order_reviews"]
    daily = a.daily_orders(raw["orders"])
    in_window = daily[str(start) : str(end)]
    return {
        "window": {
            "start": str(start),
            "end": str(end),
            "end_source": end_source,
            "auto_detected_end": detected_end,
            "days": int(len(in_window)),
            "zero_order_days": int((in_window == 0).sum()),
            "orders_in_window": int(in_window.sum()),
            "orders_total": int(daily.sum()),
            "first_purchase": str(raw["orders"]["order_purchase_timestamp"].min()),
            "last_purchase": str(raw["orders"]["order_purchase_timestamp"].max()),
        },
        "reconciliation": recon,
        "status": status.reset_index().to_dict(orient="records"),
        "delivery": {
            "orders": int(len(delivery)),
            "late_rate": float(delivery["is_late"].mean()),
            "delivery_days_mean": float(delivery["delivery_days"].mean()),
            "delivery_days_median": float(delivery["delivery_days"].median()),
        },
        "customers": {
            "distinct": int(len(opc)),
            "repeat": int((opc >= 2).sum()),
            "repeat_rate": float((opc >= 2).mean()),
        },
        "reviews": {
            "orders_with_multiple_reviews": int((reviews.groupby("order_id").size() > 1).sum()),
        },
    }


def render_report(results: list[CheckResult], summary: dict, raw_dir: Path) -> str:
    w, rc, dv, cu = (
        summary["window"],
        summary["reconciliation"],
        summary["delivery"],
        summary["customers"],
    )
    checks = pd.DataFrame(
        [
            {
                "check": f"`{r.check_id}`",
                "severity": r.severity,
                "result": "pass" if r.passed else "FAIL" if r.severity == "error" else "flagged",
                "rows": f"{r.failed:,} / {r.total:,}",
                "rule": r.description,
            }
            for r in results
        ]
    )
    status = pd.DataFrame(summary["status"]).assign(
        orders=lambda d: d["orders"].map("{:,}".format),
        orders_with_items=lambda d: d["orders_with_items"].map("{:,}".format),
        gmv=lambda d: d["gmv"].map("{:,.2f}".format),
        gmv_share=lambda d: d["gmv_share"].map("{:.2%}".format),
    )
    errors = [r for r in results if r.severity == "error" and not r.passed]
    flagged = [r for r in results if r.severity != "error" and not r.passed]
    try:
        source = raw_dir.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        source = raw_dir.as_posix()

    recon_rows = [
        ("Σ item value (price + freight), all orders", rc["total_items_value"]),
        ("Payments on orders with no items", rc["payments_without_items_amount"]),
        ("Item value of orders with no payment (removed)", -rc["items_without_payments_amount"]),
        ("Overpayments beyond tolerance", rc["paid_more_amount"]),
        ("Underpayments beyond tolerance", rc["paid_less_amount"]),
        ("Differences within tolerance (rounding)", rc["matched_orders_diff_amount"]),
    ]
    explained = sum(v for _, v in recon_rows)
    recon_md = "\n".join(f"| {k} | {v:,.2f} |" for k, v in recon_rows)

    return f"""# Data quality report

> Generated by `data_engineering/scripts/assess_quality.py` on {datetime.now(UTC):%Y-%m-%d}
> from `{source}`. Do not edit by hand; re-run the script. Rules: `config/business_rules.yaml`;
> rationale: [business_rules.md](business_rules.md).

## Summary

- **{len(results)} checks**: {sum(r.severity == "error" for r in results)} error-level, all
  {"passed" if not errors else f"**{len(errors)} FAILED**"}; {len(flagged)} warn/info checks
  flagged rows, which are kept and flagged downstream.
- **Analysis window**: {w["start"]} → {w["end"]} ({w["end_source"]}; truncation
  auto-detection: {w["auto_detected_end"]}), {w["days"]} days,
  {w["orders_in_window"]:,} of {w["orders_total"]:,} orders. Raw purchases span
  {w["first_purchase"][:10]} → {w["last_purchase"][:10]}.
- **Customers**: {cu["distinct"]:,} distinct `customer_unique_id`, {cu["repeat"]:,}
  ({cu["repeat_rate"]:.2%}) with 2+ orders.
- **Delivery** (delivered orders with consistent timestamps, all dates): {dv["orders"]:,}
  orders, late rate {dv["late_rate"]:.2%}, mean {dv["delivery_days_mean"]:.2f} days,
  median {dv["delivery_days_median"]:.2f} days.

## Checks

{_md_table(checks)}

## Orders and item value by status

{_md_table(status)}

## Payment reconciliation (BRL)

| Component | Amount |
|---|---|
{recon_md}
| **= Σ payments (explained)** | **{explained:,.2f}** |
| Σ payments (actual) | {rc["total_payments"]:,.2f} |

{rc["orders_matching"]:,} of {rc["orders_with_both"]:,} orders with both items and payments match
within tolerance; {rc["orders_paid_more"]:,} paid more and {rc["orders_paid_less"]:,} paid less.
"""


def main(argv: list[str] | None = None) -> int:
    settings = get_settings()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--raw-dir", type=Path, default=settings.raw_dir)
    parser.add_argument("--out", type=Path, default=settings.data_dir / "processed" / "quality")
    parser.add_argument("--write-report", action="store_true", help=f"write {REPORT_PATH.name}")
    args = parser.parse_args(argv)

    rules = get_rules()
    raw = load_raw(args.raw_dir.resolve())
    results = run_checks(raw, rules)
    summary = build_summary(raw, rules)

    args.out.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "raw_dir": str(args.raw_dir),
        "checks": [r.to_dict() for r in results],
        "summary": summary,
    }
    (args.out / "dq_results.json").write_text(
        json.dumps(payload, indent=2, default=str), encoding="utf-8"
    )
    if args.write_report:
        REPORT_PATH.write_text(
            render_report(results, summary, args.raw_dir.resolve()), encoding="utf-8"
        )
        log.info("Wrote %s", REPORT_PATH.relative_to(PROJECT_ROOT))

    failed = [r for r in results if r.severity == "error" and not r.passed]
    for r in failed:
        log.error("FAIL %s: %d/%d rows (%s)", r.check_id, r.failed, r.total, r.description)
    log.info(
        "%d checks, %d error failures, %d flagged; window %s -> %s",
        len(results), len(failed), sum(not r.passed for r in results) - len(failed),
        summary["window"]["start"], summary["window"]["end"],
    )  # fmt: skip
    return 1 if failed else 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sys.exit(main())
