"""Daily business anomaly detection on seasonally adjusted metrics.

1. STL (robust, weekly period) splits each metric into trend + weekly seasonality + residual,
   so normal weekday patterns and the growth trend are not flagged.
2. Robust z-score of each residual (median / MAD): a transparent rule-based baseline.
3. Isolation Forest on the vector of residual z-scores: the primary detector.
4. Optional dense autoencoder on 7-day windows of residual z-scores: flags unusual
   multi-day patterns by reconstruction error.
Each flagged day gets its driver metric, direction, expected vs actual value, and any known
calendar event (holiday, Black Friday week), so events are told apart from unexplained ones.
"""

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from statsmodels.tsa.seasonal import STL

METRIC_LABELS = {
    "gmv": "GMV (BRL)",
    "revenue_orders": "orders",
    "freight_per_item": "freight per item (BRL)",
    "cancellation_rate": "cancellation rate",
}


def daily_metrics(daily: pd.DataFrame, min_orders_for_ratios: int = 1) -> pd.DataFrame:
    """Daily metrics. Ratios are undefined (NaN) on days with fewer than
    `min_orders_for_ratios` orders: one cancellation among 20 orders is noise, not a signal."""
    m = pd.DataFrame(index=daily.index)
    m["gmv"] = daily["gmv"]
    m["revenue_orders"] = daily["revenue_orders"]
    enough = daily["all_orders"] >= max(min_orders_for_ratios, 1)
    m["freight_per_item"] = (daily["freight"] / daily["items"].where(daily["items"] > 0)).where(
        enough
    )
    m["cancellation_rate"] = (daily["canceled_orders"] / daily["all_orders"]).where(enough)
    return m


def robust_z(x: pd.Series) -> pd.Series:
    mad = (x - x.median()).abs().median()
    return (x - x.median()) / (1.4826 * mad) if mad > 0 else x * 0.0


def decompose(metrics: pd.DataFrame, period: int, trend: int | None = None):
    """STL per metric -> {metric: frame(actual, expected, residual, z, imputed)}.

    `trend` is the STL trend window in days (odd). A window much longer than the period keeps
    multi-day level shifts in the residual instead of absorbing them into the trend.
    Undefined days are interpolated for the decomposition, flagged as imputed and given z = 0
    so they can never be the evidence for an anomaly."""
    out = {}
    for col in metrics:
        series = metrics[col]
        filled = series.interpolate(limit_direction="both")
        res = STL(filled, period=period, trend=trend, robust=True).fit()
        expected = (res.trend + res.seasonal).clip(lower=0)  # all metrics are non-negative
        z = robust_z(filled - expected).where(series.notna(), 0.0)
        out[col] = pd.DataFrame({
            "actual": series, "expected": expected, "residual": filled - expected,
            "z": z, "imputed": series.isna(),
        })  # fmt: skip
    return out


def autoencoder_scores(z: pd.DataFrame, window: int, encoding_dim: int, epochs: int,
                       seed: int) -> pd.Series:  # fmt: skip
    import tensorflow as tf

    tf.keras.utils.set_random_seed(seed)
    values = z.to_numpy()
    windows = np.stack([values[i - window + 1 : i + 1].ravel()
                        for i in range(window - 1, len(values))])  # fmt: skip
    mean, std = windows.mean(axis=0), windows.std(axis=0) + 1e-9
    x = (windows - mean) / std
    model = tf.keras.Sequential([
        tf.keras.layers.Input((x.shape[1],)),
        tf.keras.layers.Dense(16, activation="relu"),
        tf.keras.layers.Dense(encoding_dim, activation="relu"),
        tf.keras.layers.Dense(16, activation="relu"),
        tf.keras.layers.Dense(x.shape[1]),
    ])  # fmt: skip
    model.compile(optimizer=tf.keras.optimizers.Adam(1e-3), loss="mse")
    model.fit(x, x, epochs=epochs, batch_size=32, shuffle=False, verbose=0)
    err = np.mean((model.predict(x, verbose=0) - x) ** 2, axis=1)
    return pd.Series(err, index=z.index[window - 1 :])


def detect(daily: pd.DataFrame, cal: pd.DataFrame, cfg, seed: int,
           use_autoencoder: bool = True) -> pd.DataFrame:  # fmt: skip
    metrics = daily_metrics(daily, cfg.min_orders_for_ratios)[cfg.metrics]
    parts = decompose(metrics, cfg.stl_period, cfg.stl_trend_days)
    z = pd.DataFrame({m: parts[m]["z"] for m in cfg.metrics})

    iso = IsolationForest(random_state=seed, **cfg.isolation_forest).fit(z)
    out = pd.DataFrame(index=metrics.index)
    out["iforest_score"] = -iso.score_samples(z)  # higher = more anomalous
    out["is_anomaly_iforest"] = iso.predict(z) == -1
    out["is_anomaly_zrule"] = (z.abs() > cfg.robust_z_threshold).any(axis=1)
    if use_autoencoder:
        ae = cfg.autoencoder
        scores = autoencoder_scores(z, ae["window"], ae["encoding_dim"], ae["epochs"], seed)
        out["ae_reconstruction_error"] = scores
        out["is_anomaly_autoencoder"] = scores > scores.quantile(ae["quantile"])
        out["is_anomaly_autoencoder"] = out["is_anomaly_autoencoder"].fillna(False)

    for m in cfg.metrics:
        out[f"{m}_actual"] = parts[m]["actual"]
        out[f"{m}_expected"] = parts[m]["expected"]
        out[f"{m}_z"] = parts[m]["z"]
    driver = z.abs().idxmax(axis=1)
    out["driver_metric"] = driver
    out["driver_z"] = [z.at[d, m] for d, m in driver.items()]
    out["direction"] = np.where(out["driver_z"] > 0, "spike", "drop")

    c = cal.reindex(out.index)
    out["calendar_event"] = np.select(
        [c["is_black_friday"] == 1, c["bf_week"] == 1, c["is_holiday"] == 1],
        ["Black Friday", "Black Friday week", "holiday: " + c["holiday_name"].fillna("")],
        default="",
    )
    out = out.join(sustained_shifts(z, **cfg.sustained_shift))
    out["is_anomaly"] = out["is_anomaly_iforest"]
    out["is_explained_by_calendar"] = out["is_anomaly"] & (out["calendar_event"] != "")
    out["explanation"] = [
        _explain(row, parts) if row.is_anomaly else "" for row in out.itertuples()
    ]
    return out


def sustained_shifts(z: pd.DataFrame, metrics: list[str], window: int,
                     z_threshold: float) -> pd.DataFrame:  # fmt: skip
    """Days inside a `window`-day stretch whose mean residual z exceeds `z_threshold`.

    Returns is_sustained_shift, the rolling mean z (largest in magnitude across metrics) and
    the metric. Every day of a flagged window is marked, not only its last day."""
    threshold = z_threshold
    roll = z[metrics].rolling(window, min_periods=window).mean()
    defined = roll.notna().any(axis=1)  # the first window-1 days have no rolling mean
    strongest = roll.abs().fillna(-1.0).idxmax(axis=1).where(defined)
    rolling_z = pd.Series([roll.at[d, m] if isinstance(m, str) else np.nan
                           for d, m in strongest.items()], index=z.index)  # fmt: skip
    ends = rolling_z.abs() > threshold
    flagged = pd.Series(False, index=z.index)
    for end in z.index[ends]:
        flagged.loc[end - pd.Timedelta(days=window - 1) : end] = True
    return pd.DataFrame({
        "is_sustained_shift": flagged, "sustained_rolling_z": rolling_z,
        "sustained_metric": strongest.where(ends.reindex(z.index, fill_value=False)),
    })  # fmt: skip


def shift_episodes(det: pd.DataFrame) -> pd.DataFrame:
    """Collapse consecutive sustained-shift days into episodes."""
    flagged = det["is_sustained_shift"]
    if not flagged.any():
        return pd.DataFrame(
            columns=[
                "start",
                "end",
                "days",
                "metric",
                "peak_rolling_z",
                "direction",
                "calendar_events",
            ]  # fmt: skip
        )
    group = (flagged != flagged.shift()).cumsum()[flagged]
    rows = []
    for _, days in det[flagged].groupby(group):
        peak = days["sustained_rolling_z"].abs().idxmax()
        z = days.at[peak, "sustained_rolling_z"]
        rows.append({
            "start": days.index[0].date(), "end": days.index[-1].date(), "days": len(days),
            "metric": days["sustained_metric"].dropna().mode().iat[0]
            if days["sustained_metric"].notna().any() else "",
            "peak_rolling_z": float(z), "direction": "drop" if z < 0 else "rise",
            "calendar_events": ", ".join(sorted({e for e in days["calendar_event"] if e})),
        })  # fmt: skip
    return pd.DataFrame(rows)


def _explain(row, parts) -> str:
    m = row.driver_metric
    actual, expected = parts[m].at[row.Index, "actual"], parts[m].at[row.Index, "expected"]
    fmt = (
        "{:.1%}" if m == "cancellation_rate" else "{:,.0f}" if m != "freight_per_item" else "{:.2f}"
    )
    actual_s = "n/a (no orders)" if pd.isna(actual) else fmt.format(actual)
    text = (f"{METRIC_LABELS[m]} {row.direction}: {actual_s} vs expected {fmt.format(expected)} "
            f"after trend and weekday seasonality ({row.driver_z:+.1f} robust z)")  # fmt: skip
    if row.calendar_event:
        text += f"; coincides with {row.calendar_event}"
    return text
