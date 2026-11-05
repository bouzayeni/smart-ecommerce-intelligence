"""Forecasting and anomaly tests on synthetic series (no database)."""

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from ml.forecasting.backtest import (
    add_conformal_interval,
    conformal_widths,
    forecast_metrics,
    forecast_window,
    run_fold,
)
from ml.forecasting.config import FORECAST_CONFIG_PATH, get_forecast_config, load_forecast_config
from ml.forecasting.models import SeasonalNaive, XGBoostRecursive


def _calendar(index: pd.DatetimeIndex) -> pd.DataFrame:
    cal = pd.DataFrame(index=index)
    cal["dow"] = index.dayofweek + 1
    cal["month"] = index.month
    cal["day_of_month"] = index.day
    cal["is_weekend"] = (index.dayofweek >= 5).astype(int)
    cal["is_holiday"] = 0
    cal["is_black_friday"] = 0
    cal["bf_week"] = 0
    cal["holiday_name"] = None
    return cal


@pytest.fixture
def weekly_series() -> pd.Series:
    idx = pd.date_range("2017-01-01", periods=200, freq="D")
    pattern = np.array([100, 120, 130, 125, 110, 80, 70], dtype=float)
    return pd.Series(pattern[np.arange(200) % 7] + np.arange(200) * 0.5, index=idx)


def test_project_config_is_chronological():
    cfg = get_forecast_config()
    last = pd.Timestamp(cfg.backtest.origins[-1]) + pd.Timedelta(days=cfg.max_horizon)
    assert last <= pd.Timestamp(cfg.test_origin)


def test_overlapping_backtest_window_is_rejected(tmp_path):
    bad = tmp_path / "f.yaml"
    bad.write_text(FORECAST_CONFIG_PATH.read_text(encoding="utf-8").replace(
        "origins: [2017-10-01, 2017-12-01, 2018-02-01]",
        "origins: [2017-10-01, 2017-12-01, 2018-04-01]"), encoding="utf-8")  # fmt: skip
    with pytest.raises(ValidationError, match="before the test origin"):
        load_forecast_config(bad)


def test_forecast_window_starts_after_origin():
    w = forecast_window(pd.Timestamp("2018-05-23"), 90)
    assert w[0] == pd.Timestamp("2018-05-24") and w[-1] == pd.Timestamp("2018-08-21")


def test_seasonal_naive_repeats_last_week(weekly_series):
    m = SeasonalNaive(season=7).fit(weekly_series, None)
    fc = m.predict(forecast_window(weekly_series.index[-1], 14))
    np.testing.assert_array_equal(fc["yhat"].to_numpy()[:7], weekly_series.iloc[-7:].to_numpy())
    np.testing.assert_array_equal(fc["yhat"].to_numpy()[7:], weekly_series.iloc[-7:].to_numpy())


def test_metrics_wape_and_mape_threshold():
    actual = np.array([100.0, 200.0, 0.5])
    pred = np.array([110.0, 180.0, 5.0])
    m = forecast_metrics(actual, pred, mape_min=10)
    assert m["wape"] == pytest.approx((10 + 20 + 4.5) / 300.5)
    assert m["mape"] == pytest.approx((0.1 + 0.1) / 2)  # tiny day excluded
    assert m["mape_days"] == 2


def test_run_fold_trains_only_on_data_up_to_origin(weekly_series):
    class Spy(SeasonalNaive):
        def fit(self, y, cal):
            self.seen_last = y.index[-1]
            return super().fit(y, cal)

    origin = weekly_series.index[100]
    spy = Spy()
    run_fold(spy, weekly_series, None, origin, 30, "backtest")
    assert spy.seen_last == origin


def test_xgboost_recursive_forecast_ignores_future_actuals(weekly_series):
    cal = _calendar(pd.date_range("2017-01-01", periods=260, freq="D"))
    origin = weekly_series.index[150]
    params = {"lags": [7, 14], "rolling_windows": [7], "n_estimators": 50, "max_depth": 3}
    a = XGBoostRecursive(**params).fit(weekly_series.loc[:origin], cal)
    corrupted = weekly_series.copy()
    corrupted.loc[origin + pd.Timedelta(days=1) :] = 1e9  # future actuals must be unused
    b = XGBoostRecursive(**params).fit(corrupted.loc[:origin], cal)
    dates = forecast_window(origin, 30)
    pd.testing.assert_frame_equal(a.predict(dates), b.predict(dates))


def test_conformal_interval_uses_bucket_quantiles(weekly_series):
    origin = weekly_series.index[120]
    fold = run_fold(SeasonalNaive(), weekly_series, None, origin, 60, "backtest")
    widths = conformal_widths([fold], weekly_series, 0.8)
    assert set(widths) == {0, 1}  # 60-day fold fills buckets 1-30 and 31-60 only
    longer = (
        SeasonalNaive().fit(weekly_series.loc[:origin], None).predict(forecast_window(origin, 90))
    )
    out = add_conformal_interval(longer, widths)  # bucket 61-90 borrows bucket 31-60
    assert (out["upper"] >= out["yhat"]).all() and (out["lower"] <= out["yhat"]).all()
    width = (out["upper"] - out["yhat"]).to_numpy()
    assert width[75] == pytest.approx(widths[1])


def test_anomaly_detection_finds_injected_drop_and_labels_calendar_events():
    pytest.importorskip("statsmodels")
    from ml.forecasting import anomalies

    idx = pd.date_range("2017-01-01", periods=300, freq="D")
    rng = np.random.default_rng(0)
    weekly = np.array([1.0, 1.1, 1.15, 1.1, 1.0, 0.8, 0.7])[np.arange(300) % 7]
    orders = 200 * weekly + rng.normal(0, 5, 300)
    orders[150] = 40  # injected collapse
    orders[200] = 900  # a spike on a known event
    daily = pd.DataFrame({
        # Cancellations proportional to orders: the only injected anomaly is the volume.
        "gmv": orders * 150, "revenue_orders": orders, "all_orders": orders * 1.01,
        "canceled_orders": orders * 0.01, "freight": orders * 20, "items": orders * 1.1,
    }, index=idx)  # fmt: skip
    cal = _calendar(idx)
    cal.loc[idx[200], "is_black_friday"] = 1
    cfg = get_forecast_config().anomalies.model_copy(
        update={"isolation_forest": {"n_estimators": 100, "contamination": 0.02}}
    )
    det = anomalies.detect(daily, cal, cfg, seed=0, use_autoencoder=False)
    assert det.loc[idx[150], "is_anomaly"] and det.loc[idx[150], "direction"] == "drop"
    assert det.loc[idx[200], "is_explained_by_calendar"]
    assert det.loc[idx[200], "calendar_event"] == "Black Friday"
    assert det["is_anomaly"].sum() <= 0.05 * len(det)  # weekly pattern itself is not flagged


def test_sustained_drop_is_an_episode_even_when_no_single_day_is_extreme():
    pytest.importorskip("statsmodels")
    from ml.forecasting import anomalies

    idx = pd.date_range("2017-01-01", periods=300, freq="D")
    rng = np.random.default_rng(1)
    weekly = np.array([1.0, 1.1, 1.15, 1.1, 1.0, 0.8, 0.7])[np.arange(300) % 7]
    orders = 200 * weekly + rng.normal(0, 8, 300)
    orders[180:188] *= 0.65  # a week at -35%: moderate per day, persistent
    daily = pd.DataFrame({
        "gmv": orders * 150, "revenue_orders": orders, "all_orders": orders * 1.01,
        "canceled_orders": orders * 0.01, "freight": orders * 20, "items": orders * 1.1,
    }, index=idx)  # fmt: skip
    det = anomalies.detect(daily, _calendar(idx), get_forecast_config().anomalies, seed=0,
                           use_autoencoder=False)  # fmt: skip
    episodes = anomalies.shift_episodes(det)
    hit = episodes[(pd.to_datetime(episodes["start"]) <= idx[187])
                   & (pd.to_datetime(episodes["end"]) >= idx[180])]  # fmt: skip
    assert len(hit) == 1 and hit["direction"].iat[0] == "drop"
    assert det["is_sustained_shift"].mean() < 0.1  # stable stretches are not flagged
