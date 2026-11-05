"""Forecasters with a common interface: fit(y, calendar) -> self; predict(dates) -> DataFrame.

predict returns columns yhat and, for models with native intervals, lower/upper at the
configured level. Models only ever see the training series passed to fit (everything up to
the origin); calendar regressors are known in advance, so future calendar rows are allowed.
"""

import logging
import warnings

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

EXOG = ["is_holiday", "is_black_friday", "bf_week"]
XGB_CALENDAR = ["dow", "month", "day_of_month", "is_weekend", *EXOG]


class SeasonalNaive:
    name = "seasonal_naive"
    native_intervals = False

    def __init__(self, season: int = 7, **_):
        self.season = season

    def fit(self, y: pd.Series, cal: pd.DataFrame):
        self.last = y.iloc[-self.season :]
        self.end = y.index[-1]
        return self

    def predict(self, dates: pd.DatetimeIndex) -> pd.DataFrame:
        steps = (dates - self.end).days - 1
        values = self.last.to_numpy()[steps % self.season]
        return pd.DataFrame({"yhat": values}, index=dates)


class Sarima:
    """SARIMAX on log1p(GMV) with weekly seasonality and holiday/Black Friday regressors.
    The order is chosen by AIC on the training data only."""

    name = "sarima"
    native_intervals = True

    def __init__(self, order_grid, seasonal_order, level: float = 0.8, **_):
        self.order_grid = [tuple(o) for o in order_grid]
        self.seasonal_order = tuple(seasonal_order)
        self.level = level

    def fit(self, y: pd.Series, cal: pd.DataFrame):
        from statsmodels.tsa.statespace.sarimax import SARIMAX

        self.cal = cal
        endog = np.log1p(y)
        exog = cal.loc[y.index, EXOG].astype(float)
        best = None
        for order in self.order_grid:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                res = SARIMAX(endog, exog=exog, order=order, seasonal_order=self.seasonal_order,
                              enforce_stationarity=False, enforce_invertibility=False
                              ).fit(disp=False, maxiter=200)  # fmt: skip
            if best is None or res.aic < best.aic:
                best, self.order = res, order
        self.result = best
        return self

    def predict(self, dates: pd.DatetimeIndex) -> pd.DataFrame:
        fc = self.result.get_forecast(len(dates), exog=self.cal.loc[dates, EXOG].astype(float))
        ci = fc.conf_int(alpha=1 - self.level)
        return pd.DataFrame({
            "yhat": np.expm1(fc.predicted_mean.to_numpy()),
            "lower": np.expm1(ci.iloc[:, 0].to_numpy()).clip(min=0),
            "upper": np.expm1(ci.iloc[:, 1].to_numpy()),
        }, index=dates)  # fmt: skip


class ProphetModel:
    name = "prophet"
    native_intervals = True

    def __init__(self, level: float = 0.8, seed: int = 0, **params):
        self.level, self.seed, self.params = level, seed, params

    def fit(self, y: pd.Series, cal: pd.DataFrame):
        from prophet import Prophet

        logging.getLogger("cmdstanpy").setLevel(logging.WARNING)
        hol = cal[cal["is_holiday"] == 1].reset_index()
        holidays = pd.concat([
            pd.DataFrame({"holiday": "br_holiday", "ds": hol["date_day"],
                          "lower_window": 0, "upper_window": 0}),
            pd.DataFrame({"holiday": "black_friday",
                          "ds": cal.index[cal["is_black_friday"] == 1],
                          "lower_window": 0, "upper_window": 7}),
        ])  # fmt: skip
        self.model = Prophet(holidays=holidays, interval_width=self.level, **self.params)
        df = pd.DataFrame({"ds": y.index, "y": y.to_numpy()})
        np.random.seed(self.seed)
        self.model.fit(df)
        return self

    def predict(self, dates: pd.DatetimeIndex) -> pd.DataFrame:
        fc = self.model.predict(pd.DataFrame({"ds": dates}))
        return pd.DataFrame({
            "yhat": fc["yhat"].clip(lower=0).to_numpy(),
            "lower": fc["yhat_lower"].clip(lower=0).to_numpy(),
            "upper": fc["yhat_upper"].to_numpy(),
        }, index=dates)  # fmt: skip


class XGBoostRecursive:
    """Gradient boosting on lag/rolling/calendar features, forecasting one day at a time and
    feeding its own predictions back as lags. All lags are >= 7 days."""

    name = "xgboost"
    native_intervals = False

    def __init__(self, lags, rolling_windows, seed: int = 0, **params):
        self.lags, self.windows, self.seed, self.params = lags, rolling_windows, seed, params

    def _features(self, history: pd.Series, day: pd.Timestamp) -> dict:
        row = {f"lag_{lag}": history.get(day - pd.Timedelta(days=lag), np.nan)
               for lag in self.lags}  # fmt: skip
        base = day - pd.Timedelta(days=7)  # rolling stats end 7 days back (no short lags)
        for w in self.windows:
            window = history.loc[base - pd.Timedelta(days=w - 1) : base]
            row[f"roll_mean_{w}"] = window.mean() if len(window) else np.nan
            row[f"roll_std_{w}"] = window.std() if len(window) > 1 else np.nan
        row.update(self.cal.loc[day, XGB_CALENDAR].astype(float).to_dict())
        return row

    def fit(self, y: pd.Series, cal: pd.DataFrame):
        from xgboost import XGBRegressor

        self.cal, self.history = cal, y.copy()
        start = y.index[0] + pd.Timedelta(days=max(self.lags))
        days = y.index[y.index >= start]
        x = pd.DataFrame([self._features(y, d) for d in days], index=days)
        self.columns = list(x.columns)
        self.model = XGBRegressor(random_state=self.seed, n_jobs=-1, tree_method="hist",
                                  **self.params).fit(x, y.loc[days])  # fmt: skip
        return self

    def predict(self, dates: pd.DatetimeIndex) -> pd.DataFrame:
        history = self.history.copy()
        preds = []
        for day in dates:
            x = pd.DataFrame([self._features(history, day)])[self.columns]
            value = max(float(self.model.predict(x)[0]), 0.0)
            history.loc[day] = value
            preds.append(value)
        return pd.DataFrame({"yhat": preds}, index=dates)


class LSTMForecaster:
    """Keras LSTM mapping the last `lookback` days to the next `horizon` days directly.

    Inputs: standardised log1p(GMV) plus day-of-week sin/cos. The scaler is fitted on the
    training series only; the early-stopping split is the chronologically last part of the
    training windows."""

    name = "lstm"
    native_intervals = False

    def __init__(self, lookback, units, epochs, batch_size, patience, validation_fraction,
                 horizon: int = 90, seed: int = 0, **_):  # fmt: skip
        self.lookback, self.units, self.epochs = lookback, units, epochs
        self.batch_size, self.patience, self.val_frac = batch_size, patience, validation_fraction
        self.horizon, self.seed = horizon, seed

    def _inputs(self, logy: np.ndarray, dates: pd.DatetimeIndex) -> np.ndarray:
        dow = dates.dayofweek.to_numpy()
        return np.stack([(logy - self.mean) / self.std, np.sin(2 * np.pi * dow / 7),
                         np.cos(2 * np.pi * dow / 7)], axis=-1)  # fmt: skip

    def fit(self, y: pd.Series, cal: pd.DataFrame):
        import tensorflow as tf

        tf.keras.utils.set_random_seed(self.seed)
        logy = np.log1p(y.to_numpy())
        self.mean, self.std = logy.mean(), logy.std()  # training data only
        feats = self._inputs(logy, y.index)
        target = (logy - self.mean) / self.std
        n = len(y) - self.lookback - self.horizon + 1
        if n < 10:
            raise ValueError(f"Too little history for LSTM windows ({n})")
        x = np.stack([feats[i : i + self.lookback] for i in range(n)])
        t = np.stack([target[i + self.lookback : i + self.lookback + self.horizon]
                      for i in range(n)])  # fmt: skip
        split = int(n * (1 - self.val_frac))
        self.model = tf.keras.Sequential([
            tf.keras.layers.Input((self.lookback, x.shape[-1])),
            tf.keras.layers.LSTM(self.units),
            tf.keras.layers.Dense(self.horizon),
        ])  # fmt: skip
        self.model.compile(optimizer=tf.keras.optimizers.Adam(1e-3), loss="mse")
        self.model.fit(
            x[:split], t[:split], validation_data=(x[split:], t[split:]), epochs=self.epochs,
            batch_size=self.batch_size, shuffle=False, verbose=0,
            callbacks=[tf.keras.callbacks.EarlyStopping(patience=self.patience,
                                                        restore_best_weights=True)],
        )  # fmt: skip
        self.last_x = feats[-self.lookback :][None]
        self.end = y.index[-1]
        return self

    def predict(self, dates: pd.DatetimeIndex) -> pd.DataFrame:
        steps = (dates - self.end).days - 1
        if steps.max() >= self.horizon:
            raise ValueError("LSTM forecasts at most `horizon` days ahead")
        out = self.model.predict(self.last_x, verbose=0)[0] * self.std + self.mean
        return pd.DataFrame({"yhat": np.expm1(out[steps]).clip(min=0)}, index=dates)


def build_models(cfg, horizon: int) -> list:
    m, level, seed = cfg.models, cfg.metrics.interval_level, cfg.random_state
    return [
        SeasonalNaive(**m["seasonal_naive"]),
        Sarima(level=level, **m["sarima"]),
        ProphetModel(level=level, seed=seed, **m["prophet"]),
        XGBoostRecursive(seed=seed, **m["xgboost"]),
        LSTMForecaster(horizon=horizon, seed=seed, **m["lstm"]),
    ]
