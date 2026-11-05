"""Train the customer models (RFM, repurchase propensity, 90-day spend), track them in MLflow,
write scores to the `ml` schema and regenerate the model cards.

Usage (from the repo root):
    uv run --group ml python -m ml.train_customer_models
    uv run --group ml python -m ml.train_customer_models --no-db-write --no-register
"""

import argparse
import logging
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import mlflow
import pandas as pd
import sqlalchemy as sa

from data_engineering.config import PROJECT_ROOT, get_settings
from ml import tracking
from ml.config import get_ml_config
from ml.customer.clv import predict_spend, train_clv
from ml.customer.features import build_snapshot, build_snapshots, feature_matrix
from ml.customer.repurchase import global_importance, score_customers, train_repurchase
from ml.customer.rfm import compute_rfm
from ml.data import load_history
from ml.evaluation import plot_classification, plot_importance

log = logging.getLogger("train_customer_models")

EXPERIMENT = "customer-intelligence"
REPURCHASE_MODEL = "repurchase_propensity"
SPEND_MODEL = "customer_spend_90d"
CARDS_DIR = PROJECT_ROOT / "docs" / "model_cards"


def _md(df: pd.DataFrame, floatfmt: str = "{:.4f}") -> str:
    cols = list(df.columns)
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for row in df.itertuples(index=False):
        cells = [floatfmt.format(v) if isinstance(v, float) else str(v) for v in row]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def _skops_trusted_types(model) -> list[str]:
    """Types skops would refuse to load. They are trusted here because this process built the
    model itself; listing them explicitly keeps skops (not pickle) as the storage format."""
    import skops.io as sio

    return sio.get_untrusted_types(data=sio.dumps(model))


def _verdict(test_metrics: pd.DataFrame, selected: str) -> str:
    """Plain-language comparison of the selected model with the best rule-based baseline."""
    t = test_metrics.set_index("model")
    base = t[t.index.str.startswith("baseline")]["pr_auc"].idxmax()
    m, b = t.loc[selected], t.loc[base]
    if m["pr_auc_ci_low"] > b["pr_auc"]:
        outcome = "beats"
    elif b["pr_auc_ci_low"] > m["pr_auc"]:
        outcome = "is worse than"
    else:
        outcome = "is not distinguishable from"
    return (
        f"the selected model ({selected}, PR-AUC {m['pr_auc']:.4f}, 95% CI "
        f"{m['pr_auc_ci_low']:.4f}–{m['pr_auc_ci_high']:.4f}) **{outcome}** the best rule-based "
        f"baseline ({base}, PR-AUC {b['pr_auc']:.4f}, CI {b['pr_auc_ci_low']:.4f}–"
        f"{b['pr_auc_ci_high']:.4f}). Both are well above the base rate "
        f"{m['base_rate']:.4f}, so the ranking carries some signal, but it is weak."
    )


def _split_summary(name: str, df: pd.DataFrame) -> dict:
    return {
        "split": name,
        "cutoffs": ", ".join(sorted({str(c.date()) for c in df["cutoff"]})),
        "rows": len(df),
        "customers": df["customer_unique_id"].nunique(),
        "positives": int(df["repurchase"].sum()) if "repurchase" in df else None,
        "positive_rate": float(df["repurchase"].mean()) if "repurchase" in df else None,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--no-db-write", action="store_true", help="do not write ml.* tables")
    parser.add_argument("--no-register", action="store_true", help="skip the model registry")
    args = parser.parse_args(argv)

    cfg = get_ml_config()
    history = load_history()
    log.info("History: %d revenue orders up to %s", len(history.orders), history.window_end.date())

    rfm = compute_rfm(history, cfg.rfm)
    train = build_snapshots(history, cfg.snapshots.train, cfg.horizon)
    val = build_snapshot(history, cfg.snapshots.validation, cfg.horizon)
    test = build_snapshot(history, cfg.snapshots.test, cfg.horizon)
    scoring = build_snapshot(history, cfg.snapshots.scoring, None)
    named = [("train", train), ("validation", val), ("test", test), ("scoring", scoring)]
    splits = [_split_summary(n, d) for n, d in named]
    for s in splits:
        log.info("%-10s rows=%7d positives=%s cutoffs=%s", s["split"], s["rows"], s["positives"],
                 s["cutoffs"])  # fmt: skip

    experiment_id = tracking.setup(EXPERIMENT)
    trained_at = datetime.now(UTC)
    tmp = Path(tempfile.mkdtemp(prefix="ml_artifacts_"))

    run_name = f"customer-models-{trained_at:%Y%m%d-%H%M}"
    with mlflow.start_run(experiment_id=experiment_id, run_name=run_name) as parent:
        mlflow.log_params({
            "horizon_days": cfg.horizon_days, "train_cutoffs": len(cfg.snapshots.train),
            "validation_cutoff": str(cfg.snapshots.validation),
            "test_cutoff": str(cfg.snapshots.test), "scoring_cutoff": str(cfg.snapshots.scoring),
        })  # fmt: skip
        mlflow.log_dict(tracking.data_fingerprint(), "data_fingerprint.json")
        mlflow.log_dict(cfg.model_dump(mode="json"), "ml_config.json")
        mlflow.log_dict({"splits": splits}, "splits.json")
        mlflow.log_dict(rfm["segment"].value_counts().to_dict(), "rfm_segments.json")

        # ---------------------------------------------------------------- repurchase
        with mlflow.start_run(run_name=REPURCHASE_MODEL, nested=True) as rep_run:

            def log_rep(family, params, metrics):
                with mlflow.start_run(run_name=f"candidate {family}", nested=True):
                    mlflow.log_params({"family": family, **params})
                    mlflow.log_metrics({f"val_{k}": v for k, v in metrics.items()})

            rep = train_repurchase(train, val, test, cfg.repurchase, cfg.features,
                                   cfg.random_state, log_rep)  # fmt: skip
            calibrated_name = f"{rep.best_family} (calibrated)"
            best = rep.test_metrics.set_index("model").loc[calibrated_name]
            mlflow.log_params({"selected_family": rep.best_family, "calibration": "sigmoid",
                               "decision_threshold": rep.threshold})  # fmt: skip
            mlflow.log_metrics({f"test_{k}": float(v) for k, v in best.items()})
            mlflow.log_metrics({f"test_at_threshold_{k}": v for k, v in rep.confusion.items()})
            rep.candidates.to_csv(tmp / "repurchase_candidates.csv", index=False)
            rep.test_metrics.to_csv(tmp / "repurchase_test_metrics.csv", index=False)
            shown = {k: v for k, v in rep.test_scores.items()
                     if "baseline" not in k or "recency" in k}  # fmt: skip
            plot_classification(rep.y_test, shown, tmp / "repurchase_test_curves.png",
                                f"Repurchase within {cfg.horizon_days} days, test cutoff "
                                f"{cfg.snapshots.test}")  # fmt: skip
            importance = global_importance(rep, feature_matrix(test))
            importance.to_csv(tmp / "repurchase_shap_importance.csv", index=False)
            plot_importance(list(importance["feature"]), importance["mean_abs_shap"].to_numpy(),
                            tmp / "repurchase_shap_importance.png",
                            f"SHAP importance ({rep.best_family}, test snapshot)")  # fmt: skip
            for f in tmp.glob("repurchase_*"):
                mlflow.log_artifact(str(f))
            info = mlflow.sklearn.log_model(
                rep.calibrated, name="model", input_example=feature_matrix(test).head(3),
                skops_trusted_types=_skops_trusted_types(rep.calibrated),
                registered_model_name=None if args.no_register else REPURCHASE_MODEL,
            )  # fmt: skip
            rep_version = getattr(info, "registered_model_version", None)
            scores = score_customers(rep, scoring, cfg.repurchase)
            scores["model_name"], scores["model_version"] = REPURCHASE_MODEL, rep_version
            scores["run_id"] = rep_run.info.run_id

        # ---------------------------------------------------------------- spend (CLV)
        with mlflow.start_run(run_name=SPEND_MODEL, nested=True) as clv_run:

            def log_clv(family, params, metrics):
                with mlflow.start_run(run_name=f"candidate {family}", nested=True):
                    mlflow.log_params({"family": family, **params})
                    mlflow.log_metrics({f"val_{k}": v for k, v in metrics.items()})

            clv = train_clv(train, val, test, cfg.clv, cfg.features, cfg.random_state, log_clv)
            best_clv = clv.test_metrics.iloc[0]
            mlflow.log_params({"selected": clv.best_name, "selection_metric": "validation rmse"})
            mlflow.log_metrics({f"test_{k}": float(v) for k, v in best_clv.drop("model").items()})
            clv.candidates.to_csv(tmp / "clv_candidates.csv", index=False)
            clv.test_metrics.to_csv(tmp / "clv_test_metrics.csv", index=False)
            for f in tmp.glob("clv_*"):
                mlflow.log_artifact(str(f))
            info = mlflow.sklearn.log_model(
                clv.best_model, name="model", input_example=feature_matrix(test).head(3),
                skops_trusted_types=_skops_trusted_types(clv.best_model),
                registered_model_name=None if args.no_register else SPEND_MODEL,
            )  # fmt: skip
            clv_version = getattr(info, "registered_model_version", None)
            spend = predict_spend(clv, scoring, cfg.horizon_days)
            spend["model_name"], spend["model_version"] = SPEND_MODEL, clv_version
            spend["run_id"] = clv_run.info.run_id
        parent_id = parent.info.run_id

    metrics_rows = []
    for model_name, table, version, run_id in [
        (REPURCHASE_MODEL, rep.test_metrics, rep_version, rep_run.info.run_id),
        (SPEND_MODEL, clv.test_metrics, clv_version, clv_run.info.run_id),
    ]:
        for row in table.to_dict(orient="records"):
            candidate = row.pop("model")
            metrics_rows += [{
                "model_name": model_name, "model_version": version, "candidate": candidate,
                "split": "test", "metric": k, "value": float(v), "run_id": run_id,
                "trained_at": trained_at,
            } for k, v in row.items()]  # fmt: skip
    metrics_df = pd.DataFrame(metrics_rows)
    importance_df = importance.assign(
        model_name=REPURCHASE_MODEL, model_version=rep_version, rank=range(1, len(importance) + 1)
    )

    if not args.no_db_write:
        engine = sa.create_engine(get_settings().database_url("etl"))
        tables = {
            "customer_rfm": rfm.assign(trained_at=trained_at),
            "customer_repurchase_scores": scores.assign(trained_at=trained_at),
            "customer_spend_predictions": spend.assign(trained_at=trained_at),
            "model_metrics": metrics_df,
            "model_feature_importance": importance_df.assign(trained_at=trained_at),
        }
        with engine.begin() as conn:
            for name, df in tables.items():
                df.to_sql(name, conn, schema="ml", if_exists="replace", index=False,
                          method="multi", chunksize=5000)  # fmt: skip
                log.info("Wrote ml.%s (%d rows)", name, len(df))

    write_model_cards(cfg, splits, rfm, rep, clv, importance, rep_version, clv_version,
                      parent_id, trained_at)  # fmt: skip
    log.info("Done. MLflow parent run %s; %s v%s, %s v%s", parent_id, REPURCHASE_MODEL,
             rep_version, SPEND_MODEL, clv_version)  # fmt: skip
    return 0


def write_model_cards(cfg, splits, rfm, rep, clv, importance, rep_v, clv_v, run_id, trained_at):
    CARDS_DIR.mkdir(parents=True, exist_ok=True)
    split_df = pd.DataFrame(splits)
    # Only positive_rate is a ratio; the counts must not go through the percent format.
    split_df["positives"] = split_df["positives"].map(lambda v: "" if pd.isna(v) else int(v))
    split_md = _md(split_df.fillna(""), "{:.4%}")
    header = (f"> Generated by `ml/train_customer_models.py` on {trained_at:%Y-%m-%d} from MLflow "
              f"run `{run_id}`. Numbers are from that run; re-run to refresh.\n")  # fmt: skip

    rep_cols = ["model", "pr_auc", "pr_auc_ci_low", "pr_auc_ci_high", "roc_auc",
                "lift_top_decile", "recall_top_decile", "brier"]  # fmt: skip
    rep_table = rep.test_metrics.reindex(columns=rep_cols)
    cm = rep.confusion
    val_table = rep.candidates.assign(params=rep.candidates["params"].astype(str))[
        ["family", "params", "pr_auc", "roc_auc", "lift_top_decile"]
    ].sort_values("pr_auc", ascending=False)
    verdict = _verdict(rep.test_metrics, f"{rep.best_family} (calibrated)")
    (CARDS_DIR / "repurchase_propensity.md").write_text(
        f"""# Model card — Repurchase propensity (churn risk)

{header}
**Registered model:** `{REPURCHASE_MODEL}` version {rep_v} (MLflow registry). Selected family:
**{rep.best_family}**, sigmoid-calibrated on the validation snapshot.

## Task and definition

- **Prediction:** probability that a customer (`customer_unique_id`) places at least one
  revenue order in the **{cfg.horizon_days} days after the cutoff**.
- **Churn risk = 1 − P(repurchase).** Churn is an *operational definition* based on historical
  purchase behaviour (no repurchase within the horizon). It is not an observed event:
  Olist has no subscriptions or account closures.
- **Population at cutoff T:** customers with one or more revenue orders purchased before T,
  inside the analysis window.

## Data and leakage prevention

{split_md}

- **Point-in-time features:** orders purchased before T; deliveries completed before T;
  reviews *answered* before T.
- **Chronological splits.** Every training label window ends before the validation cutoff,
  and the validation window ends before the test cutoff (validated in `ml/config.py`). The
  test snapshot is used once, after selection.
- **Class imbalance** is handled inside each estimator from the training data only
  (`class_weight`, `scale_pos_weight`). No resampling.
- **Known look-ahead:** order status is the status at extract time, so orders purchased
  before T but cancelled later are already absent from the history.

## Model selection (validation cutoff {cfg.snapshots.validation})

{_md(val_table)}

## Test results (cutoff {cfg.snapshots.test}, untouched until final evaluation)

{_md(rep_table)}

95% CIs: percentile bootstrap over customers (500 resamples).

**Verdict:** {verdict}

Base rate on test: **{rep.test_metrics["base_rate"].iloc[0]:.3%}**, so a random model scores
PR-AUC ≈ base rate. "Raw" rows are uncalibrated candidates. Ranking metrics are unaffected by
calibration; Brier score measures the probabilities themselves.

**At the decision threshold** {cm["threshold"]:.4f} (maximises F1 on validation):
precision {cm["precision"]:.3f}, recall {cm["recall"]:.3f}, F1 {cm["f1"]:.3f}.
Confusion matrix: TP {cm["tp"]}, FP {cm["fp"]}, FN {cm["fn"]}, TN {cm["tn"]}.

## Explanations (SHAP, test snapshot)

Mean |SHAP| of the uncalibrated model (log-odds space); top 10:

{_md(importance.head(10))}

Per-customer top-3 drivers are stored in `ml.customer_repurchase_scores.top_reasons`.
Caveat: several features are near-duplicates for one-order customers (monetary, max and last
order value are equal), so a linear model can split their effect into offsetting signs
("max order value lowers" next to "monetary raises"). Read the drivers as a group, not one
by one.

## Intended use and limitations

- **Use:** rank customers for retention or win-back campaigns. The propensity decile (1 = least
  likely to return) is more meaningful than the absolute probability: with a base rate around
  0.6%, almost every customer's churn risk is above 99%.
- **Weak signal.** About 97% of customers have a single order, so there is little behavioural
  history. Compare against the recency baseline above before relying on the model.
- **Training period.** The model was trained on 2017 snapshots. Seasonality and growth in 2018
  may shift its calibration; re-check calibration on new data before use.
- **Historical data.** This is a 2016–2018 Brazilian marketplace extract, so the scores at
  cutoff {cfg.snapshots.scoring} describe the end of that period, not today.
""",
        encoding="utf-8",
    )

    clv_cols = ["model", "mae", "rmse", "rmse_ci_low", "rmse_ci_high",
                "top_decile_spend_capture", "capture_ci_low", "capture_ci_high", "spearman",
                "total_actual", "total_predicted"]  # fmt: skip
    ct = clv.test_metrics.set_index("model")
    best_row, mean_row = ct.iloc[0], ct.loc["baseline: training mean"]
    biz_row = ct.loc["baseline: business rule"]
    clv_verdict = (
        f"RMSE {best_row['rmse']:.2f} (CI {best_row['rmse_ci_low']:.2f}–"
        f"{best_row['rmse_ci_high']:.2f}) vs {mean_row['rmse']:.2f} for predicting the training "
        f"mean: **no meaningful improvement in squared error**, because a handful of large "
        f"future orders dominate it. Top-decile spend capture "
        f"{best_row['top_decile_spend_capture']:.1%} "
        f"(CI {best_row['capture_ci_low']:.1%}–{best_row['capture_ci_high']:.1%}) vs "
        f"{biz_row['top_decile_spend_capture']:.1%} for the business rule and 10% at random: "
        f"the model ranks future spenders about as well as the simple rule."
    )
    (CARDS_DIR / "customer_spend_90d.md").write_text(
        f"""# Model card — 90-day customer spend (short-horizon CLV)

{header}
**Registered model:** `{SPEND_MODEL}` version {clv_v}. Selected: **{clv.best_name}**
(lowest validation RMSE).

## Task

- **Prediction:** GMV (price + freight) of revenue orders a customer places in the
  **{cfg.horizon_days} days after the cutoff**.
- **This is spending, not profit.** There is no cost data (BR-03).
- **Same snapshots, population and leakage rules** as the repurchase model, so the target
  never enters the features.

## Test results (cutoff {cfg.snapshots.test})

{_md(clv.test_metrics.reindex(columns=clv_cols), "{:.4f}")}

95% CIs: percentile bootstrap over customers (500 resamples).

**Verdict:** {clv_verdict}

- **Business rule baseline:** expected orders by (frequency, recency) bucket, learned on the
  training snapshots, × the customer's average order value.
- **Mostly-zero target.** More than 99% of customers spend nothing in the horizon. Predicting
  zero minimises MAE, so MAE alone is misleading. Use RMSE, top-decile spend capture (share of
  actual future spend among the 10% highest predictions) and Spearman. MAPE is undefined
  with zero actuals.

## Intended use and limitations

- **Use:** budget and prioritisation at portfolio level, and ranking high-value prospects.
  Do not quote an individual customer's prediction as an expected value.
- **Short horizon.** {cfg.horizon_days} days only. Lifetime value over years cannot be
  estimated from about 20 months of history with about 3% repeat buyers.
""",
        encoding="utf-8",
    )

    seg = rfm.groupby("segment").agg(
        customers=("customer_unique_id", "size"), avg_recency_days=("recency_days", "mean"),
        avg_frequency=("frequency", "mean"), avg_monetary=("monetary", "mean"),
    ).reset_index().sort_values("customers", ascending=False)  # fmt: skip
    seg["share"] = seg["customers"] / seg["customers"].sum()
    rules = "\n".join(
        f"| {s.name} | {s.r_min}–{s.r_max} | {s.f_min}–{s.f_max} | {s.m_min}–{s.m_max} |"
        for s in cfg.rfm.segments
    )
    (CARDS_DIR / "rfm_segmentation.md").write_text(
        f"""# RFM segmentation

{header}
- **Reference date:** {cfg.rfm.reference_date}, the day after the analysis window. Revenue
  orders only.
- **Recency (R)** and **Monetary (M):** quintile scores 1–5 (5 = most recent / highest spend).
- **Frequency (F):** rule-based scores {cfg.rfm.frequency_scores} (orders → score). Quintiles
  are meaningless when about 97% of customers have exactly one order.

Rules are evaluated in order and the first match wins. They are configurable in
`config/ml.yaml`.

| Segment | R | F | M |
|---|---|---|---|
{rules}

## Result

{_md(seg, "{:.2f}")}

Because so few customers repeat, Champions, Loyal and At Risk are small groups of
repeat buyers. Most customers fall into the single-purchase segments, separated by recency
and spend.
""",
        encoding="utf-8",
    )
    log.info("Wrote model cards to %s", CARDS_DIR.relative_to(PROJECT_ROOT))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("mlflow").setLevel(logging.WARNING)
    sys.exit(main())
