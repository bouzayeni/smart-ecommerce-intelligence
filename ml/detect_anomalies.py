"""Daily business anomaly detection: track in MLflow, write ml.daily_anomalies, regenerate the
model card. Method: ml/forecasting/anomalies.py.

Usage (from the repo root):
    uv run --all-groups python -m ml.detect_anomalies
    uv run --all-groups python -m ml.detect_anomalies --no-autoencoder --no-db-write
"""

import argparse
import logging
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import mlflow  # noqa: E402
import pandas as pd  # noqa: E402
import sqlalchemy as sa  # noqa: E402

from data_engineering.config import PROJECT_ROOT, get_settings  # noqa: E402
from ml import tracking  # noqa: E402
from ml.evaluation import ACCENT, ACCENT2, GRID  # noqa: E402
from ml.forecasting import anomalies  # noqa: E402
from ml.forecasting.config import get_forecast_config  # noqa: E402
from ml.forecasting.data import load_daily  # noqa: E402
from ml.train_forecasting import _md  # noqa: E402

log = logging.getLogger("detect_anomalies")
CARD = PROJECT_ROOT / "docs" / "model_cards" / "anomaly_detection.md"


def plot_anomalies(det: pd.DataFrame, path: Path) -> Path:
    fig, axes = plt.subplots(4, 1, figsize=(13, 9), dpi=110, sharex=True)
    for ax, m in zip(axes, anomalies.METRIC_LABELS, strict=True):
        if m in ("gmv", "revenue_orders"):
            shift = det["is_sustained_shift"].astype(bool)
            ax.fill_between(det.index, 0, 1, where=shift.to_numpy(), color="#eda100", alpha=0.18,
                            lw=0, transform=ax.get_xaxis_transform(),
                            label="sustained shift")  # fmt: skip
        ax.plot(det.index, det[f"{m}_actual"], color="#0b0b0b", lw=0.9, label="actual")
        ax.plot(det.index, det[f"{m}_expected"], color=ACCENT, lw=1.2, label="expected (STL)")
        flagged = det[det["is_anomaly"] & (det["driver_metric"] == m)]
        explained = flagged["is_explained_by_calendar"]
        ax.scatter(flagged.index[~explained], flagged.loc[~explained, f"{m}_actual"], s=28,
                   color="#e34948", zorder=3, label="anomaly")  # fmt: skip
        ax.scatter(flagged.index[explained], flagged.loc[explained, f"{m}_actual"], s=28,
                   facecolors="none", edgecolors=ACCENT2, zorder=3,
                   label="calendar event")  # fmt: skip
        ax.set_title(anomalies.METRIC_LABELS[m], loc="left", fontsize=10, fontweight="bold")
        ax.grid(color=GRID, lw=0.8)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
    axes[0].legend(frameon=False, fontsize=8, ncol=4)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--no-db-write", action="store_true")
    parser.add_argument("--no-autoencoder", action="store_true")
    args = parser.parse_args(argv)

    cfg = get_forecast_config()
    daily, cal = load_daily()
    tracking.setup("anomaly-detection")
    ts = datetime.now(UTC)
    tmp = Path(tempfile.mkdtemp(prefix="anomaly_artifacts_"))

    with mlflow.start_run(run_name=f"anomalies-{ts:%Y%m%d-%H%M}") as run:
        mlflow.log_params({k: str(v) for k, v in cfg.anomalies.model_dump().items()})
        mlflow.log_dict(tracking.data_fingerprint(), "data_fingerprint.json")
        det = anomalies.detect(daily, cal, cfg.anomalies, cfg.random_state,
                               use_autoencoder=not args.no_autoencoder)  # fmt: skip
        episodes = anomalies.shift_episodes(det)
        plot_anomalies(det, tmp / "anomalies.png")
        episodes.to_csv(tmp / "shift_episodes.csv", index=False)
        det.reset_index().to_csv(tmp / "daily_anomalies.csv", index=False)
        mlflow.log_metrics({
            "anomaly_days": int(det["is_anomaly"].sum()),
            "anomaly_days_explained_by_calendar": int(det["is_explained_by_calendar"].sum()),
            "zrule_days": int(det["is_anomaly_zrule"].sum()),
            "sustained_shift_episodes": len(episodes),
        })  # fmt: skip
        for f in tmp.iterdir():
            mlflow.log_artifact(str(f))
        run_id = run.info.run_id

    if not args.no_db_write:
        engine = sa.create_engine(get_settings().database_url("etl"))
        with engine.begin() as conn:
            det.rename_axis("date").reset_index().assign(run_id=run_id, detected_at=ts).to_sql(
                "daily_anomalies", conn, schema="ml", if_exists="replace", index=False,
                method="multi", chunksize=2000,
            )  # fmt: skip
            episodes.assign(run_id=run_id, detected_at=ts).to_sql(
                "anomaly_shift_episodes",
                conn,
                schema="ml",
                if_exists="replace",
                index=False,
            )
        log.info("Wrote ml.daily_anomalies (%d rows), ml.anomaly_shift_episodes (%d)", len(det),
                 len(episodes))  # fmt: skip

    write_card(cfg.anomalies, det, episodes, run_id, ts)
    flagged = det[det["is_anomaly"]]
    log.info("Done. %d anomaly days (%d with a calendar event); z-rule %d days; run %s",
             len(flagged), int(flagged["is_explained_by_calendar"].sum()),
             int(det["is_anomaly_zrule"].sum()), run_id)  # fmt: skip
    return 0


def write_card(cfg, det: pd.DataFrame, episodes: pd.DataFrame, run_id: str, ts) -> None:
    flagged = det[det["is_anomaly"]]
    counts = flagged["driver_metric"].value_counts().to_dict()
    table = flagged.assign(date=flagged.index.date)[
        ["date", "driver_metric", "direction", "driver_z", "iforest_score", "is_anomaly_zrule",
         "calendar_event", "explanation"]
    ].sort_values("iforest_score", ascending=False)  # fmt: skip
    ae = ""
    if "is_anomaly_autoencoder" in det:
        both = int((det["is_anomaly"] & det["is_anomaly_autoencoder"]).sum())
        ae = (f"- The autoencoder (7-day windows) flags {int(det['is_anomaly_autoencoder'].sum())} "
              f"days; {both} overlap with Isolation Forest.\n")  # fmt: skip
    CARD.write_text(
        f"""# Model card — Daily business anomaly detection

> Generated by `ml/detect_anomalies.py` on {ts:%Y-%m-%d} from MLflow run `{run_id}`.
> Re-run to refresh.

## Method

1. **Seasonal adjustment.** Robust STL on each metric ({", ".join(cfg.metrics)}), with weekly
   period {cfg.stl_period} and a **{cfg.stl_trend_days}-day trend window**. Expected value =
   trend + weekday seasonality, so weekday patterns and gradual growth are not anomalies. The
   long trend window keeps multi-day level shifts in the residual.
2. **Ratio metrics need volume.** Cancellation rate and freight per item are undefined on days
   with fewer than {cfg.min_orders_for_ratios} orders. Such days get z = 0 and are never the
   evidence for a flag.
3. **Baseline rule.** Robust z-score (median and MAD) of each residual; flagged if any
   |z| > {cfg.robust_z_threshold}.
4. **Isolation Forest** on the vector of residual z-scores (contamination
   {cfg.isolation_forest["contamination"]}). This is the **primary flag** (`is_anomaly`).
5. **Sustained level shifts.** Isolation Forest scores days independently, so it misses
   moderate but persistent deviations. A **{cfg.sustained_shift["window"]}-day rolling mean** of
   residual z for {", ".join(cfg.sustained_shift["metrics"])} beyond
   ±{cfg.sustained_shift["z_threshold"]} marks an episode (`is_sustained_shift`,
   `ml.anomaly_shift_episodes`).
6. **Autoencoder** (optional, Keras): a dense autoencoder on 7-day windows of z-scores; a window
   is unusual when its reconstruction error is above the {cfg.autoencoder["quantile"]:.0%}
   quantile.

Each flag reports the driver metric (largest |z|), the direction, actual vs expected, and any
**calendar event** (holiday, Black Friday, the week after Black Friday). This separates known
events from unexplained anomalies.

### Design iteration (first run of this pipeline)

The first version used STL's default trend window (~11 days) and computed ratios at any
volume. It missed the ~10-day GMV drop of late May 2018: the trend absorbed it, giving GMV
z ≈ −1.5. Its two strongest "anomalies" were cancellation-rate spikes in January 2017, at about
25 orders a day. The z-rule baseline flagged 196 of 598 days. The two settings above fix these
visible failures. With no labelled incidents there is no test set, so this was not tuned
against one.

## Result ({det.index[0].date()} → {det.index[-1].date()}, {len(det)} days)

- **{len(flagged)} anomaly days** (Isolation Forest).
  {int(flagged["is_explained_by_calendar"].sum())} coincide with a calendar event.
  By driver metric: {counts}.
- The z-rule flags {int(det["is_anomaly_zrule"].sum())} days;
  {int((det["is_anomaly"] & det["is_anomaly_zrule"]).sum())} overlap with Isolation Forest.
{ae}
### Point anomalies (Isolation Forest)

{_md(table, "{:.2f}")}

### Sustained shift episodes ({len(episodes)})

{_md(episodes, "{:.2f}") if len(episodes) else "None."}

## Limitations

- **Unsupervised.** There are no labelled incidents, so precision and recall cannot be
  measured. Flags are leads to investigate, not confirmed incidents. External causes (strikes,
  outages, campaigns) are not in the data and are not asserted.
- **Early 2017** is the marketplace's ramp-up, with low volume. Volume metrics there are still
  noisy.
- **Cancellation rate** uses the status at extract time; cancellations after the extract are
  not visible.
""",
        encoding="utf-8",
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    for noisy in ("mlflow", "tensorflow", "absl"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    sys.exit(main())
