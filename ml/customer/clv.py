"""Customer spend over the next horizon (a short-horizon CLV): GMV of revenue orders in
[T, T + horizon). Predicted spend is GMV, not profit (no cost data, BR-03).

The target is ~99% zeros, so models are selected on validation RMSE (MAE rewards predicting
zero for everyone) and reported with MAE, RMSE, normalised errors, top-decile spend capture
and Spearman rank correlation. MAPE is undefined with zero actuals and is not used.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.pipeline import Pipeline
from xgboost import XGBRegressor

from ml.config import ClvConfig, FeatureConfig
from ml.customer.features import feature_matrix
from ml.customer.repurchase import make_preprocessor, param_grid
from ml.evaluation import bootstrap_ci, regression_metrics, rmse, top_decile_capture


def _bucket(df: pd.DataFrame) -> pd.Series:
    freq = np.where(df["frequency"] >= 3, "3+", df["frequency"].astype(int).astype(str))
    rec = pd.cut(df["recency_days"], [-1, 90, 180, np.inf], labels=["<=90d", "91-180d", ">180d"])
    return pd.Series(freq, index=df.index) + "|" + rec.astype(str)


class BusinessBaseline:
    """Expected future orders by (frequency, recency) bucket from training snapshots,
    times the customer's own average order value."""

    def fit(self, train: pd.DataFrame) -> "BusinessBaseline":
        self.rates = train.groupby(_bucket(train))["future_orders"].mean()
        self.default = float(train["future_orders"].mean())
        return self

    def predict(self, df: pd.DataFrame) -> np.ndarray:
        rate = _bucket(df).map(self.rates).fillna(self.default).to_numpy()
        return rate * df["avg_order_value"].to_numpy()


def make_regressor(family: str, params: dict, features: FeatureConfig, seed: int) -> Pipeline:
    if family == "random_forest":
        model = RandomForestRegressor(n_jobs=-1, random_state=seed, **params)
    elif family == "xgboost":
        model = XGBRegressor(subsample=0.8, colsample_bytree=0.8, tree_method="hist",
                             n_jobs=-1, random_state=seed, **params)  # fmt: skip
    else:
        raise ValueError(f"Unknown model family {family!r}")
    return Pipeline([("prep", make_preprocessor(features, scale=False)), ("model", model)])


@dataclass
class ClvResult:
    candidates: pd.DataFrame
    best_name: str
    best_model: Pipeline
    baseline: BusinessBaseline
    test_metrics: pd.DataFrame


def train_clv(
    train: pd.DataFrame, val: pd.DataFrame, test: pd.DataFrame, cfg: ClvConfig,
    features: FeatureConfig, seed: int, log_candidate=None,
) -> ClvResult:  # fmt: skip
    x_tr, y_tr = feature_matrix(train), train["future_gmv"].to_numpy()
    x_va, y_va = feature_matrix(val), val["future_gmv"].to_numpy()
    x_te, y_te = feature_matrix(test), test["future_gmv"].to_numpy()

    rows, fitted = [], {}
    for family, spec in cfg.models.items():
        for params in param_grid(spec):
            pipe = make_regressor(family, params, features, seed).fit(x_tr, y_tr)
            metrics = regression_metrics(y_va, np.clip(pipe.predict(x_va), 0, None))
            name = f"{family} {params}"
            rows.append({"family": family, "params": params, "name": name, **metrics})
            fitted[name] = pipe
            if log_candidate:
                log_candidate(family, params, metrics)
    candidates = pd.DataFrame(rows)
    best_name = candidates.sort_values("rmse").iloc[0]["name"]
    best = fitted[best_name]
    baseline = BusinessBaseline().fit(train)

    preds = {
        f"best: {best_name}": np.clip(best.predict(x_te), 0, None),
        "baseline: business rule": baseline.predict(test),
        "baseline: training mean": np.full(len(y_te), y_tr.mean()),
        "baseline: zero": np.zeros(len(y_te)),
    }
    for family in cfg.models:
        fam_rows = candidates[candidates["family"] == family].sort_values("rmse")
        name = fam_rows.iloc[0]["name"]
        if name != best_name:
            preds[f"{family} (best config)"] = np.clip(fitted[name].predict(x_te), 0, None)
    test_rows = []
    for k, v in preds.items():
        rmse_lo, rmse_hi = bootstrap_ci(y_te, v, rmse)
        cap_lo, cap_hi = bootstrap_ci(y_te, v, top_decile_capture)
        test_rows.append({
            "model": k, **regression_metrics(y_te, v),
            "rmse_ci_low": rmse_lo, "rmse_ci_high": rmse_hi,
            "capture_ci_low": cap_lo, "capture_ci_high": cap_hi,
        })  # fmt: skip
    return ClvResult(candidates, best_name, best, baseline, pd.DataFrame(test_rows))


def predict_spend(result: ClvResult, scoring: pd.DataFrame, horizon_days: int) -> pd.DataFrame:
    pred = np.clip(result.best_model.predict(feature_matrix(scoring)), 0, None)
    return pd.DataFrame({
        "customer_unique_id": scoring["customer_unique_id"].to_numpy(),
        "scored_at_cutoff": scoring["cutoff"].dt.date.to_numpy(),
        "horizon_days": horizon_days,
        "predicted_spend_brl": np.round(pred, 2),
        "baseline_spend_brl": np.round(result.baseline.predict(scoring), 2),
        "historical_spend_brl": scoring["monetary"].round(2).to_numpy(),
    })  # fmt: skip
