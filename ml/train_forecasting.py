"""Sales forecasting: rolling-origin backtest, untouched test, 30/60/90-day forecast.
Tracks runs in MLflow, writes ml.* tables, regenerates the model card.
Anomaly detection is separate: ml/detect_anomalies.py.

Usage (from the repo root):
    uv run --group ml --group dl python -m ml.train_forecasting
    uv run --group ml --group dl python -m ml.train_forecasting --no-db-write
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
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import sqlalchemy as sa  # noqa: E402

from data_engineering.config import PROJECT_ROOT, get_settings  # noqa: E402
from ml import tracking  # noqa: E402
from ml.evaluation import ACCENT, ACCENT2, GRID, MUTED  # noqa: E402
from ml.forecasting.backtest import (  # noqa: E402
    add_conformal_interval,
    conformal_widths,
    evaluate,
    forecast_window,
    run_fold,
)
from ml.forecasting.config import get_forecast_config  # noqa: E402
from ml.forecasting.data import load_daily  # noqa: E402
from ml.forecasting.models import build_models  # noqa: E402

log = logging.getLogger("train_forecasting")
CARDS_DIR = PROJECT_ROOT / "docs" / "model_cards"


def _md(df: pd.DataFrame, floatfmt: str = "{:,.4f}") -> str:
    cols = list(df.columns)
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for row in df.itertuples(index=False):
        cells = ["" if (isinstance(v, float) and np.isnan(v)) else
                 floatfmt.format(v) if isinstance(v, float) else str(v) for v in row]  # fmt: skip
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def plot_forecasts(y: pd.Series, forecasts: dict[str, pd.DataFrame], selected: str,
                   path: Path, title: str, history_days: int = 120) -> Path:  # fmt: skip
    first = min(fc.index[0] for fc in forecasts.values())
    hist = y.loc[first - pd.Timedelta(days=history_days) :]
    fig, ax = plt.subplots(figsize=(13, 4.6), dpi=110)
    ax.plot(hist.index, hist.to_numpy(), color="#0b0b0b", lw=1.2, label="actual")
    sel = forecasts[selected]
    if {"lower", "upper"} <= set(sel.columns):
        ax.fill_between(sel.index, sel["lower"], sel["upper"], color=ACCENT, alpha=0.15, lw=0,
                        label=f"{selected} interval")  # fmt: skip
    palette = [ACCENT, ACCENT2, "#1baf7a", "#6250d6", MUTED]
    others = [selected] + [m for m in forecasts if m != selected]
    for name, color in zip(others, palette, strict=False):
        fc = forecasts[name]
        ax.plot(fc.index, fc["yhat"], color=color, lw=2 if name == selected else 1,
                alpha=1 if name == selected else 0.7, label=name)  # fmt: skip
    ax.set_title(title, loc="left", fontsize=11, fontweight="bold")
    ax.grid(color=GRID, lw=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v / 1e3:,.0f}k"))
    ax.set_ylabel("daily GMV (BRL)")
    ax.legend(frameon=False, fontsize=8, ncol=3)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--no-db-write", action="store_true")
    args = parser.parse_args(argv)

    cfg = get_forecast_config()
    daily, cal = load_daily()
    y = daily[cfg.target]
    end, h = y.index[-1], cfg.max_horizon
    test_origin = pd.Timestamp(cfg.test_origin)
    if test_origin + pd.Timedelta(days=h) > end:
        raise ValueError("Test window extends beyond the series")
    log.info("Series %s: %d days %s -> %s", cfg.target, len(y), y.index[0].date(), end.date())

    tracking.setup("sales-forecasting")
    generated_at = datetime.now(UTC)
    tmp = Path(tempfile.mkdtemp(prefix="forecast_artifacts_"))
    level = cfg.metrics.interval_level

    with mlflow.start_run(run_name=f"forecast-{generated_at:%Y%m%d-%H%M}") as parent:
        mlflow.log_params({
            "target": cfg.target, "max_horizon": h, "test_origin": str(cfg.test_origin),
            "backtest_origins": ",".join(map(str, cfg.backtest.origins)),
            "series_end": str(end.date()), "interval_level": level,
        })  # fmt: skip
        mlflow.log_dict(tracking.data_fingerprint(), "data_fingerprint.json")
        mlflow.log_dict(cfg.model_dump(mode="json"), "forecast_config.json")

        rows, test_fc, final_fc, widths_used, details = [], {}, {}, {}, {}
        for model in build_models(cfg, h):
            with mlflow.start_run(run_name=model.name, nested=True):
                backtests = [run_fold(model, y, cal, pd.Timestamp(o), h, "backtest")
                             for o in cfg.backtest.origins]  # fmt: skip
                test = run_fold(model, y, cal, test_origin, h, "test")
                widths = conformal_widths(backtests, y, level)
                if not model.native_intervals:
                    test.forecast = add_conformal_interval(test.forecast, widths)
                mape_min = cfg.metrics.mape_min_actual_brl
                model_rows = [r for f in [*backtests, test]
                              for r in evaluate(f, y, cfg.horizons, mape_min)]  # fmt: skip
                rows += model_rows
                test_fc[model.name] = test.forecast

                # Final forecast: refit on the full series; intervals from all folds.
                model.fit(y, cal)
                fc = model.predict(forecast_window(end, h))
                if not model.native_intervals:
                    widths_used[model.name] = conformal_widths([*backtests, test], y, level)
                    fc = add_conformal_interval(fc, widths_used[model.name])
                final_fc[model.name] = fc
                details[model.name] = getattr(model, "order", None)

                mdf = pd.DataFrame(model_rows)
                for (split, hz), g in mdf.groupby(["split", "horizon"]):
                    for metric in ("mae", "rmse", "wape", "mape", "interval_coverage"):
                        if metric in g and g[metric].notna().any():
                            mlflow.log_metric(f"{split}_{metric}_h{hz}", float(g[metric].mean()))
                mlflow.log_params({"interval_source": "native" if model.native_intervals
                                   else "conformal (backtest abs-error quantile)"})  # fmt: skip
                log.info("%-15s backtest WAPE@90=%.3f test WAPE@90=%.3f",
                         model.name, mdf.query("split=='backtest' and horizon==90")["wape"].mean(),
                         mdf.query("split=='test' and horizon==90")["wape"].iloc[0])  # fmt: skip

        metrics = pd.DataFrame(rows)
        summary = (metrics.groupby(["model", "split", "horizon"])
                   [["mae", "rmse", "wape", "mape", "interval_coverage", "interval_mean_width"]]
                   .mean().reset_index())  # fmt: skip
        selected = (summary.query("split == 'backtest' and horizon == @h")
                    .sort_values("wape").iloc[0]["model"])  # fmt: skip
        mlflow.log_param("selected_model", selected)
        sel_test = summary.query("model == @selected and split == 'test'")
        for r in sel_test.itertuples():
            mlflow.log_metric(f"selected_test_wape_h{r.horizon}", r.wape)

        metrics.to_csv(tmp / "forecast_fold_metrics.csv", index=False)
        summary.to_csv(tmp / "forecast_summary.csv", index=False)
        plot_forecasts(y, test_fc, selected, tmp / "forecast_test.png",
                       f"Test period: forecasts from origin {cfg.test_origin} vs actual "
                       f"(selected: {selected})")  # fmt: skip
        plot_forecasts(y, final_fc, selected, tmp / "forecast_future.png",
                       f"Forecast for the {h} days after {end.date()} (historical extract; "
                       f"no actuals exist)")  # fmt: skip

        for f in tmp.iterdir():
            mlflow.log_artifact(str(f))
        run_id = parent.info.run_id

    forecast_rows = []
    for name, fc in final_fc.items():
        forecast_rows.append(fc.assign(
            model=name, horizon_day=np.arange(1, len(fc) + 1), is_selected=name == selected,
            interval_level=level,
            interval_source="native" if name in ("sarima", "prophet") else "conformal",
        ))  # fmt: skip
    forecast_df = (pd.concat(forecast_rows).rename_axis("forecast_date").reset_index()
                   .assign(generated_at=generated_at, run_id=run_id,
                           series_end=end.date()))  # fmt: skip
    test_df = (pd.concat([fc.assign(model=n) for n, fc in test_fc.items()])
               .rename_axis("date").reset_index())  # fmt: skip
    test_df["actual"] = y.loc[test_df["date"]].to_numpy()

    if not args.no_db_write:
        engine = sa.create_engine(get_settings().database_url("etl"))
        tables = {
            "sales_forecast": forecast_df,
            "sales_forecast_test": test_df.assign(run_id=run_id),
            "forecast_metrics": metrics.assign(run_id=run_id, generated_at=generated_at),
        }
        with engine.begin() as conn:
            for name, df in tables.items():
                df.to_sql(name, conn, schema="ml", if_exists="replace", index=False,
                          method="multi", chunksize=2000)  # fmt: skip
                log.info("Wrote ml.%s (%d rows)", name, len(df))

    write_card(cfg, summary, selected, details, end, run_id, generated_at, y)
    log.info("Done. Selected %s; run %s", selected, run_id)
    return 0


def write_card(cfg, summary, selected, details, end, run_id, ts, y):
    CARDS_DIR.mkdir(parents=True, exist_ok=True)
    header = (f"> Generated by `ml/train_forecasting.py` on {ts:%Y-%m-%d} from MLflow run "
              f"`{run_id}`. Re-run to refresh.\n")  # fmt: skip
    cols = ["model", "horizon", "mae", "rmse", "wape", "mape", "interval_coverage",
            "interval_mean_width"]  # fmt: skip
    bt = summary.query("split == 'backtest'")[cols].sort_values(["horizon", "wape"])
    te = summary.query("split == 'test'")[cols].sort_values(["horizon", "wape"])
    naive90 = te.query("model == 'seasonal_naive' and horizon == 90")["wape"].iloc[0]
    sel90 = te.query("model == @selected and horizon == 90")
    best90 = te.query("horizon == 90").sort_values("wape").iloc[0]
    cov = sel90["interval_coverage"].iloc[0]
    verdict = (
        f"selected **{selected}** (lowest mean backtest WAPE at 90 days) has test WAPE "
        f"{sel90['wape'].iloc[0]:.1%} at 90 days vs {naive90:.1%} for the seasonal naive "
        f"baseline; the best model on test is **{best90['model']}** ({best90['wape']:.1%}). "
        f"The {cfg.metrics.interval_level:.0%} interval of the selected model covered "
        f"{cov:.0%} of test days."
    )
    if sel90["wape"].iloc[0] > naive90:
        verdict += (
            "\n\n**The selection did not generalise.** The backtest winner is worse than the "
            f"seasonal naive baseline on test. With only {len(cfg.backtest.origins)} backtest "
            f"origins the model ranking is unstable: the backtest and test rankings disagree. "
            f"The selection is kept as specified and not replaced by the test winner, because "
            f"choosing on the test set would make its error an in-sample number. All models' "
            f"forecasts are published (`ml.sales_forecast`, `is_selected` flag)."
        )
    (CARDS_DIR / "sales_forecasting.md").write_text(
        f"""# Model card — Daily GMV forecasting

{header}
## Task

- **Prediction:** daily GMV of revenue orders, 1–{cfg.max_horizon} days ahead. Evaluated over
  the first {", ".join(map(str, cfg.horizons))} days after the origin.
- **Series:** `marts.agg_daily_sales`, {y.index[0].date()} → {end.date()} ({len(y)} days).
- **Historical data.** The "future" forecast covers the {cfg.max_horizon} days after the extract
  ends, so no actual values exist for it.

## Evaluation design (no shuffling)

- **Rolling-origin backtest.** Origins {", ".join(map(str, cfg.backtest.origins))}. Each fold
  trains on all days up to and including the origin and forecasts the next
  {cfg.max_horizon} days. Model selection uses the mean backtest WAPE at {cfg.max_horizon} days.
- **Test.** Origin {cfg.test_origin}: the last {cfg.max_horizon} days of the window, used once.
- **Leakage controls.** Scalers (LSTM) and model orders (SARIMA, chosen by AIC) are fitted on
  training data only. XGBoost uses lags of 7 days or more and feeds back its own predictions.
  Calendar regressors (holidays, Black Friday) are known in advance.
- **Prediction intervals** at {cfg.metrics.interval_level:.0%}. SARIMA and Prophet use their
  native intervals. Seasonal naive, XGBoost and LSTM use conformal intervals: the
  {cfg.metrics.interval_level:.0%} quantile of absolute backtest errors per horizon bucket
  (1–30, 31–60, 61–90 days).
- **MAPE** is computed only on days with actual GMV ≥ R$ {cfg.metrics.mape_min_actual_brl:,.0f}.
  **WAPE** (Σ|error| ÷ Σ actual) is the headline metric.

## Backtest (mean over {len(cfg.backtest.origins)} origins)

{_md(bt)}

## Test (origin {cfg.test_origin})

{_md(te)}

**Verdict:** {verdict}

SARIMA order chosen on the final full-series fit: {details.get("sarima")}.

## Limitations

- **Short history.** About 20 months with a single Black Friday. Yearly seasonality is not
  modelled (Prophet `yearly_seasonality: false`). A Black Friday effect learned from one
  occurrence is uncertain.
- **Truncated extract.** The series ends 2018-08-21, before the extract's truncation
  (BR-02). Forecasts past that date cannot be checked.
- **Small LSTM training set.** Only a few hundred overlapping training windows exist, so it is
  included for comparison, not because deep learning suits a series this short.
""",
        encoding="utf-8",
    )

    log.info("Wrote sales forecasting model card")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    for noisy in ("mlflow", "cmdstanpy", "prophet", "tensorflow", "absl"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    sys.exit(main())
