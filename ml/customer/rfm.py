"""RFM scoring and rule-based segmentation (thresholds in config/ml.yaml)."""

from datetime import date

import pandas as pd

from ml.config import RfmConfig
from ml.data import CustomerHistory


def frequency_score(orders: int, scores: dict[int, int]) -> int:
    """Score of the largest threshold <= orders (e.g. {1: 1, 2: 3, 3: 5})."""
    eligible = [k for k in scores if k <= orders]
    if not eligible:
        raise ValueError(f"No frequency score for {orders} orders")
    return scores[max(eligible)]


def quintile_score(values: pd.Series, ascending: bool) -> pd.Series:
    """1..5 by quintile of rank (ties broken by position, which is sorted by customer id)."""
    ranks = values.rank(method="first", ascending=ascending)
    return pd.qcut(ranks, 5, labels=[1, 2, 3, 4, 5]).astype(int)


def compute_rfm(history: CustomerHistory, cfg: RfmConfig, reference: date | None = None):
    ref = pd.Timestamp(reference or cfg.reference_date)
    past = history.orders[history.orders["purchased_at"] < ref]
    rfm = (
        past.groupby("customer_unique_id")
        .agg(
            last_purchase=("purchased_at", "max"),
            frequency=("order_id", "size"),
            monetary=("gmv", "sum"),
        )  # fmt: skip
        .sort_index()
    )
    rfm["recency_days"] = (ref - rfm["last_purchase"]).dt.days
    # Most recent -> 5: rank descending on recency_days so the smallest gets the top quintile.
    rfm["r_score"] = quintile_score(rfm["recency_days"], ascending=False)
    rfm["f_score"] = rfm["frequency"].map(lambda n: frequency_score(n, cfg.frequency_scores))
    rfm["m_score"] = quintile_score(rfm["monetary"], ascending=True)

    def segment(row) -> str:
        for s in cfg.segments:
            if s.matches(row.r_score, row.f_score, row.m_score):
                return s.name
        return "Other"

    rfm["segment"] = [segment(r) for r in rfm.itertuples()]
    rfm["rfm_code"] = (
        rfm["r_score"].astype(str) + rfm["f_score"].astype(str) + rfm["m_score"].astype(str)
    )
    rfm.insert(0, "reference_date", ref.date())
    return rfm.drop(columns="last_purchase").reset_index()
