"""Reusable analytical summaries behind the business rules (report + notebook)."""

from datetime import date

import pandas as pd

from data_engineering.business_rules import BusinessRules
from data_engineering.quality.loader import RawTables


def daily_orders(orders: pd.DataFrame) -> pd.Series:
    """Orders per purchase day (all statuses), including zero-order days."""
    return (
        orders.set_index("order_purchase_timestamp")
        .resample("D")["order_id"]
        .count()
        .rename("orders")
    )


def detect_window_end(
    daily: pd.Series, min_ratio: float, baseline_days: int, min_baseline_orders: int
) -> date:
    """Last complete day before an end-of-extract truncation.

    Scans backwards from the last day; a day is "complete" when its volume is at least
    `min_ratio` x the median of the preceding `baseline_days` days, and that baseline is
    itself at least `min_baseline_orders` (so a run of near-empty days is never "complete").
    """
    baseline = daily.shift(1).rolling(baseline_days, min_periods=baseline_days).median()
    complete = (baseline >= min_baseline_orders) & (daily >= min_ratio * baseline)
    if not complete.any():
        raise ValueError("No complete day found; check truncation_detection parameters")
    return complete[complete].index.max().date()


def resolve_window(raw: RawTables, rules: BusinessRules) -> tuple[date, date, str]:
    """Return (start, end, how the end was determined)."""
    window = rules.analysis_window
    if window.end_override is not None:
        return window.start, window.end_override, "override"
    td = window.truncation_detection
    daily = daily_orders(raw["orders"])
    try:
        end = detect_window_end(daily, td.min_ratio, td.baseline_days, td.min_baseline_orders)
    except ValueError:
        # Small fixtures have too few orders per day to detect truncation.
        return window.start, daily.index.max().date(), "fallback: last purchase day"
    return window.start, end, "auto-detected"


def item_totals(items: pd.DataFrame) -> pd.DataFrame:
    return (
        items.assign(gmv=items["price"] + items["freight_value"])
        .groupby("order_id")
        .agg(
            item_rows=("order_item_id", "size"),
            price=("price", "sum"),
            freight=("freight_value", "sum"),
            gmv=("gmv", "sum"),
        )
    )


def status_summary(raw: RawTables, rules: BusinessRules) -> pd.DataFrame:
    orders = raw["orders"].merge(
        item_totals(raw["order_items"]), left_on="order_id", right_index=True, how="left"
    )
    out = orders.groupby("order_status").agg(
        orders=("order_id", "size"),
        orders_with_items=("item_rows", "count"),
        gmv=("gmv", "sum"),
    )
    out["gmv_share"] = out["gmv"] / out["gmv"].sum()
    out["counts_as_revenue"] = out.index.isin(rules.revenue.include_statuses)
    return out.sort_values("orders", ascending=False)


def payment_reconciliation(raw: RawTables, tolerance: float) -> dict[str, float]:
    """Compare per-order item value (price + freight) with the sum of payments."""
    items = item_totals(raw["order_items"])["gmv"].rename("items")
    pays = raw["order_payments"].groupby("order_id")["payment_value"].sum().rename("payments")
    j = pd.concat([items, pays], axis=1)
    both = j.dropna()
    diff = both["payments"] - both["items"]
    return {
        "total_items_value": float(j["items"].sum()),
        "total_payments": float(j["payments"].sum()),
        "orders_with_both": int(len(both)),
        "orders_matching": int((diff.abs() <= tolerance).sum()),
        "orders_paid_more": int((diff > tolerance).sum()),
        "paid_more_amount": float(diff[diff > tolerance].sum()),
        "orders_paid_less": int((diff < -tolerance).sum()),
        "paid_less_amount": float(diff[diff < -tolerance].sum()),
        "orders_payments_without_items": int(j["items"].isna().sum()),
        "payments_without_items_amount": float(j.loc[j["items"].isna(), "payments"].sum()),
        "orders_items_without_payments": int(j["payments"].isna().sum()),
        "items_without_payments_amount": float(j.loc[j["payments"].isna(), "items"].sum()),
        "matched_orders_diff_amount": float(diff[diff.abs() <= tolerance].sum()),
    }


def per_order_review(reviews: pd.DataFrame, method: str) -> pd.DataFrame:
    """One review score per order according to the configured rule."""
    if method == "mean":
        return reviews.groupby("order_id", as_index=False)["review_score"].mean()
    latest = reviews.sort_values(["order_id", "review_answer_timestamp", "review_id"])
    return latest.drop_duplicates("order_id", keep="last")[["order_id", "review_score"]]


def delivery_frame(raw: RawTables, rules: BusinessRules) -> pd.DataFrame:
    """Delivered orders with valid timestamps, with lead time and lateness."""
    o = raw["orders"]
    valid = (
        (o["order_status"] == "delivered")
        & o["order_delivered_customer_date"].notna()
        & ~(o["order_delivered_carrier_date"] < o["order_purchase_timestamp"])
        & ~(o["order_delivered_customer_date"] < o["order_delivered_carrier_date"])
    )
    d = o[valid].copy()
    delivered = d["order_delivered_customer_date"]
    if rules.delivery.late_comparison == "calendar_date":
        delivered = delivered.dt.normalize()
    d["is_late"] = delivered > d["order_estimated_delivery_date"]
    d["delivery_days"] = (
        d["order_delivered_customer_date"] - d["order_purchase_timestamp"]
    ).dt.total_seconds() / 86400
    return d


def repeat_customer_summary(raw: RawTables) -> pd.Series:
    merged = raw["orders"].merge(
        raw["customers"][["customer_id", "customer_unique_id"]], on="customer_id"
    )
    return merged.groupby("customer_unique_id")["order_id"].nunique().rename("orders")
