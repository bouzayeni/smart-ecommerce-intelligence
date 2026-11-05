"""Point-in-time customer features and labels for a snapshot cutoff T.

Leakage rules (tested in tests/test_ml_features.py):
  - orders: purchased strictly before T
  - deliveries: only if delivered to the customer before T (otherwise "pending")
  - reviews: only if answered before T (review_answered_at, BR-06)
  - labels: revenue orders purchased in [T, T + horizon), for customers already active before T
Order status is the status at extract time, so an order purchased before T and cancelled
later is already excluded from the history. This small look-ahead is documented in the
model card.
"""

from datetime import date, timedelta

import numpy as np
import pandas as pd

from ml.data import CustomerHistory

NUMERIC_FEATURES = [
    "recency_days", "tenure_days", "frequency", "monetary", "avg_order_value",
    "max_order_value", "last_order_value", "avg_items_per_order", "freight_share",
    "mean_installments", "mean_days_between_orders", "orders_last_90d", "orders_last_180d",
    "n_delivered", "avg_delivery_days", "late_share", "last_order_delivered",
    "n_reviews", "mean_review_score", "min_review_score", "last_review_score",
    "n_categories",
]  # fmt: skip
CATEGORICAL_FEATURES = ["last_payment_type", "customer_state", "last_order_category"]
LABELS = ["repurchase", "future_orders", "future_gmv"]


def build_snapshot(
    history: CustomerHistory, cutoff: date, horizon: timedelta | None
) -> pd.DataFrame:
    """One row per customer with >= 1 revenue order before `cutoff`.

    With a horizon, label columns are added; the label window must end within the data.
    """
    t = pd.Timestamp(cutoff)
    orders = history.orders
    past = orders[orders["purchased_at"] < t].sort_values(["purchased_at", "order_id"])
    if past.empty:
        raise ValueError(f"No orders before cutoff {cutoff}")
    days = lambda delta: delta.dt.total_seconds() / 86400  # noqa: E731

    g = past.groupby("customer_unique_id")
    f = g.agg(
        first_purchase=("purchased_at", "min"),
        last_purchase=("purchased_at", "max"),
        frequency=("order_id", "size"),
        monetary=("gmv", "sum"),
        max_order_value=("gmv", "max"),
        freight=("freight_total", "sum"),
        items=("item_count", "sum"),
        mean_installments=("max_installments", "mean"),
    )
    last = g.tail(1).set_index("customer_unique_id")
    f["recency_days"] = days(t - f["last_purchase"])
    f["tenure_days"] = days(t - f["first_purchase"])
    f["avg_order_value"] = f["monetary"] / f["frequency"]
    f["avg_items_per_order"] = f["items"] / f["frequency"]
    f["freight_share"] = f["freight"] / f["monetary"].where(f["monetary"] > 0)
    f["mean_days_between_orders"] = (
        days(f["last_purchase"] - f["first_purchase"]) / (f["frequency"] - 1)
    ).where(f["frequency"] > 1)
    for window in (90, 180):
        recent = past[past["purchased_at"] >= t - pd.Timedelta(days=window)]
        f[f"orders_last_{window}d"] = recent.groupby("customer_unique_id").size()
        f[f"orders_last_{window}d"] = f[f"orders_last_{window}d"].fillna(0)
    f["last_order_value"] = last["gmv"]
    f["last_payment_type"] = last["primary_payment_type"]
    f["customer_state"] = last["customer_state_at_order"]

    # Deliveries known at T
    delivered = past[past["delivered_to_customer_at"] < t]
    d = delivered.groupby("customer_unique_id").agg(
        n_delivered=("order_id", "size"),
        avg_delivery_days=("delivery_days", "mean"),
        n_late=("is_late", "sum"),
    )
    f = f.join(d)
    f["n_delivered"] = f["n_delivered"].fillna(0)
    f["late_share"] = f["n_late"] / f["n_delivered"].where(f["n_delivered"] > 0)
    f["last_order_delivered"] = (last["delivered_to_customer_at"] < t).astype(float)

    # Reviews known at T (answered before the cutoff)
    rv = history.reviews.merge(past[["order_id", "customer_unique_id"]], on="order_id")
    rv = rv[rv["review_answered_at"] < t].sort_values(["review_answered_at", "order_id"])
    r = rv.groupby("customer_unique_id").agg(
        n_reviews=("review_score", "size"),
        mean_review_score=("review_score", "mean"),
        min_review_score=("review_score", "min"),
        last_review_score=("review_score", "last"),
    )
    f = f.join(r)
    f["n_reviews"] = f["n_reviews"].fillna(0)

    # Categories of past orders
    cats = history.order_categories.merge(past[["order_id", "customer_unique_id"]], on="order_id")
    f["n_categories"] = cats.groupby("customer_unique_id")["category_name"].nunique()
    last_cat = (
        cats[cats["order_id"].isin(last["order_id"])]
        .sort_values(["customer_unique_id", "category_name"])
        .drop_duplicates("customer_unique_id")
        .set_index("customer_unique_id")["category_name"]
    )
    f["last_order_category"] = last_cat
    for col in CATEGORICAL_FEATURES:
        f[col] = f[col].fillna("unknown").astype(str)

    out = f[NUMERIC_FEATURES + CATEGORICAL_FEATURES].astype({c: float for c in NUMERIC_FEATURES})
    out.insert(0, "cutoff", t)

    if horizon is not None:
        end = t + pd.Timedelta(horizon)
        if end > history.window_end + pd.Timedelta(days=1):
            raise ValueError(f"Label window {t.date()}..{end.date()} ends after the data")
        future = orders[(orders["purchased_at"] >= t) & (orders["purchased_at"] < end)]
        fut = future.groupby("customer_unique_id").agg(
            future_orders=("order_id", "size"), future_gmv=("gmv", "sum")
        )
        out = out.join(fut)
        out["future_orders"] = out["future_orders"].fillna(0).astype(int)
        out["future_gmv"] = out["future_gmv"].fillna(0.0)
        out["repurchase"] = (out["future_orders"] > 0).astype(int)
    return out.reset_index().rename(columns={"index": "customer_unique_id"})


def build_snapshots(
    history: CustomerHistory, cutoffs: list[date], horizon: timedelta | None
) -> pd.DataFrame:
    return pd.concat([build_snapshot(history, c, horizon) for c in cutoffs], ignore_index=True)


def feature_matrix(df: pd.DataFrame) -> pd.DataFrame:
    return df[NUMERIC_FEATURES + CATEGORICAL_FEATURES]


def replace_inf(df: pd.DataFrame) -> pd.DataFrame:
    return df.replace([np.inf, -np.inf], np.nan)
