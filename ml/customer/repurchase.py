"""Repurchase propensity: P(revenue order within the horizon); churn risk = 1 - P.

Flow (chronological, see config/ml.yaml):
  1. fit every candidate on the train snapshots (class weights computed from train only)
  2. select the best candidate per family and overall by validation PR-AUC
  3. calibrate the best model (Platt/sigmoid) and choose the F1 threshold on validation
  4. evaluate everything once on the untouched test snapshot (+ rule-based baselines)
"""

import json
from dataclasses import dataclass, field
from itertools import product

import numpy as np
import pandas as pd
import shap
from sklearn.calibration import CalibratedClassifierCV
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier
from sklearn.frozen import FrozenEstimator
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from xgboost import XGBClassifier

from ml.config import FeatureConfig, RepurchaseConfig
from ml.customer.features import NUMERIC_FEATURES, feature_matrix
from ml.evaluation import (
    best_f1_threshold,
    bootstrap_ci,
    classification_metrics,
    threshold_metrics,
)


def param_grid(spec: dict[str, list]) -> list[dict]:
    keys = list(spec)
    return [dict(zip(keys, values, strict=True)) for values in product(*spec.values())]


def make_preprocessor(features: FeatureConfig, scale: bool) -> ColumnTransformer:
    numeric = [("impute", SimpleImputer(strategy="median", add_indicator=True))]
    if scale:
        numeric.append(("scale", StandardScaler()))

    def onehot(max_categories: int) -> OneHotEncoder:
        return OneHotEncoder(
            handle_unknown="infrequent_if_exist", max_categories=max_categories,
            sparse_output=False,
        )  # fmt: skip

    return ColumnTransformer(
        [
            ("num", Pipeline(numeric), NUMERIC_FEATURES),
            ("state", onehot(features.top_states + 1), ["customer_state"]),
            ("category", onehot(features.top_categories + 1), ["last_order_category"]),
            ("payment", onehot(6), ["last_payment_type"]),
        ],
        verbose_feature_names_out=False,
    )


def make_classifier(
    family: str, params: dict, y_train: np.ndarray, features: FeatureConfig, seed: int
) -> Pipeline:
    if family == "logistic_regression":
        model = LogisticRegression(class_weight="balanced", max_iter=5000, **params)
    elif family == "random_forest":
        model = RandomForestClassifier(
            class_weight="balanced_subsample", n_jobs=-1, random_state=seed, **params
        )
    elif family == "xgboost":
        pos = int(y_train.sum())
        model = XGBClassifier(
            scale_pos_weight=(len(y_train) - pos) / max(pos, 1), subsample=0.8,
            colsample_bytree=0.8, eval_metric="aucpr", tree_method="hist", n_jobs=-1,
            random_state=seed, **params,
        )  # fmt: skip
    else:
        raise ValueError(f"Unknown model family {family!r}")
    return Pipeline([
        ("prep", make_preprocessor(features, scale=family == "logistic_regression")),
        ("model", model),
    ])  # fmt: skip


@dataclass
class RepurchaseResult:
    candidates: pd.DataFrame  # every config with validation metrics
    best_per_family: dict[str, Pipeline]
    best_family: str
    calibrated: CalibratedClassifierCV
    threshold: float
    test_metrics: pd.DataFrame  # one row per model/baseline
    test_scores: dict[str, np.ndarray]
    y_test: np.ndarray
    confusion: dict = field(default_factory=dict)


def train_repurchase(
    train: pd.DataFrame, val: pd.DataFrame, test: pd.DataFrame, cfg: RepurchaseConfig,
    features: FeatureConfig, seed: int, log_candidate=None,
) -> RepurchaseResult:  # fmt: skip
    x_tr, y_tr = feature_matrix(train), train["repurchase"].to_numpy()
    x_va, y_va = feature_matrix(val), val["repurchase"].to_numpy()
    x_te, y_te = feature_matrix(test), test["repurchase"].to_numpy()

    rows, fitted = [], {}
    for family, spec in cfg.models.items():
        for params in param_grid(spec):
            pipe = make_classifier(family, params, y_tr, features, seed).fit(x_tr, y_tr)
            metrics = classification_metrics(y_va, pipe.predict_proba(x_va)[:, 1])
            rows.append({"family": family, "params": params, **metrics})
            fitted[(family, repr(params))] = pipe
            if log_candidate:
                log_candidate(family, params, metrics)
    # Baselines are scored on validation too, so model selection is compared against them.
    baselines = baseline_scores(x_va)
    baseline_rows = [
        {"family": "baseline", "params": name, **classification_metrics(y_va, s)}
        for name, s in baselines.items()
    ]
    candidates = pd.DataFrame(rows + baseline_rows)
    models_only = candidates[candidates["family"] != "baseline"]
    best_rows = models_only.loc[models_only.groupby("family")["pr_auc"].idxmax()]
    best_per_family = {r.family: fitted[(r.family, repr(r.params))] for r in best_rows.itertuples()}
    best_family = best_rows.sort_values("pr_auc", ascending=False).iloc[0]["family"]

    calibrated = CalibratedClassifierCV(
        FrozenEstimator(best_per_family[best_family]), method="sigmoid"
    ).fit(x_va, y_va)
    threshold = best_f1_threshold(y_va, calibrated.predict_proba(x_va)[:, 1])

    scores = {f"{fam} (raw)": p.predict_proba(x_te)[:, 1] for fam, p in best_per_family.items()}
    scores[f"{best_family} (calibrated)"] = calibrated.predict_proba(x_te)[:, 1]
    scores.update(baseline_scores(x_te))
    test_rows = []
    for name, s in scores.items():
        pr_lo, pr_hi = bootstrap_ci(y_te, s, average_precision_score)
        roc_lo, roc_hi = bootstrap_ci(y_te, s, roc_auc_score)
        test_rows.append({
            "model": name, **classification_metrics(y_te, s),
            "pr_auc_ci_low": pr_lo, "pr_auc_ci_high": pr_hi,
            "roc_auc_ci_low": roc_lo, "roc_auc_ci_high": roc_hi,
        })  # fmt: skip
    confusion = threshold_metrics(y_te, scores[f"{best_family} (calibrated)"], threshold)
    return RepurchaseResult(
        candidates, best_per_family, best_family, calibrated, threshold,
        pd.DataFrame(test_rows), scores, y_te, confusion,
    )  # fmt: skip


def baseline_scores(x: pd.DataFrame) -> dict[str, np.ndarray]:
    """Rule-based rankings a business could use without a model."""
    recency, frequency = x["recency_days"].to_numpy(), x["frequency"].to_numpy()
    return {
        "baseline: recency rule": -recency,
        "baseline: frequency rule": frequency - 1e-6 * recency,
    }


def shap_values(pipe: Pipeline, x: pd.DataFrame, background: pd.DataFrame):
    """SHAP values (log-odds / margin space) of the uncalibrated pipeline, plus names."""
    prep, model = pipe.named_steps["prep"], pipe.named_steps["model"]
    names = list(prep.get_feature_names_out())
    xt = pd.DataFrame(prep.transform(x), columns=names)
    if isinstance(model, LogisticRegression):
        bg = pd.DataFrame(prep.transform(background), columns=names)
        values = shap.LinearExplainer(model, bg).shap_values(xt)
    else:
        values = shap.TreeExplainer(model).shap_values(xt)
        if isinstance(values, list):
            values = values[1]
        if values.ndim == 3:
            values = values[:, :, 1]
    return np.asarray(values), names, xt


def top_reasons(
    values: np.ndarray, names: list[str], xt: pd.DataFrame, raw: pd.DataFrame, k: int = 3
) -> list[str]:
    """Per row: JSON list of the k features moving repurchase propensity the most.

    Values are shown in original units (raw features), not scaled or one-hot space.
    """
    out = []
    order = np.argsort(-np.abs(values), axis=1)[:, :k]
    raw = raw.reset_index(drop=True)
    for i, idx in enumerate(order):

        def shown(j: int, i: int = i):
            name = names[j]
            if name in raw.columns:
                v = raw.at[i, name]
                if pd.isna(v):
                    return None
                return v if isinstance(v, str) else round(float(v), 2)
            return round(float(xt.iat[i, j]), 2)  # one-hot / missing indicator: 0 or 1

        out.append(json.dumps([
            {"feature": names[j], "value": shown(j),
             "effect": "raises repurchase propensity" if values[i, j] > 0
             else "lowers repurchase propensity",
             "shap": round(float(values[i, j]), 4)}
            for j in idx
        ]))  # fmt: skip
    return out


def score_customers(
    result: RepurchaseResult, scoring: pd.DataFrame, cfg: RepurchaseConfig
) -> pd.DataFrame:
    x = feature_matrix(scoring)
    proba = result.calibrated.predict_proba(x)[:, 1]
    ranks = pd.Series(proba).rank(method="first")
    decile = pd.qcut(ranks, 10, labels=list(range(1, 11))).astype(int).to_numpy()
    values, names, xt = shap_values(
        result.best_per_family[result.best_family], x, x.sample(min(1000, len(x)), random_state=0)
    )
    return pd.DataFrame({
        "customer_unique_id": scoring["customer_unique_id"].to_numpy(),
        "scored_at_cutoff": scoring["cutoff"].dt.date.to_numpy(),
        "repurchase_probability_90d": proba,
        "churn_risk_90d": 1 - proba,
        "propensity_decile": decile,
        "churn_risk_band": [cfg.risk_bands.band(int(d)) for d in decile],
        "top_reasons": top_reasons(values, names, xt, x),
    })  # fmt: skip


def global_importance(result: RepurchaseResult, x: pd.DataFrame) -> pd.DataFrame:
    sample = x.sample(min(5000, len(x)), random_state=0)
    values, names, _ = shap_values(result.best_per_family[result.best_family], sample, sample)
    imp = np.abs(values).mean(axis=0)
    return (
        pd.DataFrame({"feature": names, "mean_abs_shap": imp})
        .sort_values("mean_abs_shap", ascending=False)
        .reset_index(drop=True)
    )
