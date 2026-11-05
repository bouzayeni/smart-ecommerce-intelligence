"""Rolling-origin backtesting, forecast metrics and conformal prediction intervals."""

import logging
import time
from dataclasses import dataclass

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

HORIZON_BUCKETS = [(1, 30), (31, 60), (61, 90)]


def forecast_window(origin: pd.Timestamp, horizon: int) -> pd.DatetimeIndex:
    """Days origin+1 .. origin+horizon (the origin day itself is the last training day)."""
    return pd.date_range(origin + pd.Timedelta(days=1), periods=horizon, freq="D")


def forecast_metrics(actual: np.ndarray, pred: np.ndarray, mape_min: float) -> dict[str, float]:
    err = pred - actual
    mask = actual >= mape_min
    return {
        "mae": float(np.mean(np.abs(err))),
        "rmse": float(np.sqrt(np.mean(err**2))),
        "wape": float(np.sum(np.abs(err)) / np.sum(np.abs(actual))) if actual.sum() else np.nan,
        "mape": float(np.mean(np.abs(err[mask]) / actual[mask])) if mask.any() else np.nan,
        "mape_days": int(mask.sum()),
        "bias": float(np.sum(err) / np.sum(actual)) if actual.sum() else np.nan,
    }


@dataclass
class FoldForecast:
    model: str
    origin: pd.Timestamp
    split: str  # backtest | test
    forecast: pd.DataFrame  # yhat (+ lower/upper), indexed by date
    fit_seconds: float


def run_fold(model, y: pd.Series, cal: pd.DataFrame, origin: pd.Timestamp, horizon: int,
             split: str) -> FoldForecast:  # fmt: skip
    train = y.loc[:origin]
    dates = forecast_window(origin, horizon)
    t0 = time.perf_counter()
    model.fit(train, cal)
    fc = model.predict(dates)
    return FoldForecast(model.name, origin, split, fc, time.perf_counter() - t0)


def conformal_widths(folds: list[FoldForecast], y: pd.Series, level: float) -> dict[int, float]:
    """Absolute-error quantile per horizon bucket, from backtest folds only (split conformal)."""
    errors: dict[int, list[float]] = {i: [] for i in range(len(HORIZON_BUCKETS))}
    for f in folds:
        steps = np.arange(1, len(f.forecast) + 1)
        abs_err = np.abs(f.forecast["yhat"].to_numpy() - y.loc[f.forecast.index].to_numpy())
        for i, (lo, hi) in enumerate(HORIZON_BUCKETS):
            errors[i].extend(abs_err[(steps >= lo) & (steps <= hi)])
    return {i: float(np.quantile(e, level)) for i, e in errors.items() if e}


def add_conformal_interval(fc: pd.DataFrame, widths: dict[int, float]) -> pd.DataFrame:
    """yhat ± bucket width. A bucket without backtest errors (folds shorter than the
    forecast) borrows the width of the furthest-ahead bucket that has them: errors grow with
    horizon, so this is the conservative choice."""
    if not widths:
        raise ValueError("No conformal widths: run backtest folds first")
    out = fc.copy()
    steps = np.arange(1, len(fc) + 1)
    w = np.zeros(len(fc))
    for i, (lo, hi) in enumerate(HORIZON_BUCKETS):
        w[(steps >= lo) & (steps <= hi)] = widths.get(i, widths[max(widths)])
    out["lower"] = (out["yhat"] - w).clip(lower=0)
    out["upper"] = out["yhat"] + w
    return out


def evaluate(fold: FoldForecast, y: pd.Series, horizons: list[int], mape_min: float) -> list:
    rows = []
    actual_all = y.loc[fold.forecast.index].to_numpy()
    for h in horizons:
        fc = fold.forecast.iloc[:h]
        actual = actual_all[:h]
        row = {"model": fold.model, "split": fold.split, "origin": fold.origin.date(),
               "horizon": h, **forecast_metrics(actual, fc["yhat"].to_numpy(), mape_min),
               "fit_seconds": fold.fit_seconds}  # fmt: skip
        if {"lower", "upper"} <= set(fc.columns):
            inside = (actual >= fc["lower"].to_numpy()) & (actual <= fc["upper"].to_numpy())
            row["interval_coverage"] = float(inside.mean())
            row["interval_mean_width"] = float((fc["upper"] - fc["lower"]).mean())
        rows.append(row)
    return rows
