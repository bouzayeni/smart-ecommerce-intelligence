"""Purchase interactions and product attributes from the marts (read-only analytics role)."""

from dataclasses import dataclass

import numpy as np
import pandas as pd
import sqlalchemy as sa

from data_engineering.config import get_settings

INTERACTIONS_SQL = """
select i.customer_unique_id as user_id, i.product_id as item_id, p.category_name,
       o.purchased_at, o.customer_state_at_order as state, i.price
from marts.fact_order_items i
join marts.fact_orders o using (order_id)
join marts.dim_products p using (product_id)
where i.is_revenue_order and i.is_in_analysis_window
"""
PRODUCTS_SQL = """
select product_id as item_id, category_name, product_weight_g, product_volume_cm3,
       product_photos_qty
from marts.dim_products
"""


@dataclass
class Interactions:
    """One row per unit purchased (user_id, item_id, purchased_at, category, state, price)."""

    events: pd.DataFrame
    products: pd.DataFrame  # static attributes, indexed by item_id

    def before(self, cutoff) -> "Interactions":
        return Interactions(
            self.events[self.events["purchased_at"] < pd.Timestamp(cutoff)], self.products
        )

    def between(self, start, end) -> pd.DataFrame:
        e = self.events
        return e[
            (e["purchased_at"] >= pd.Timestamp(start)) & (e["purchased_at"] < pd.Timestamp(end))
        ]


def load_interactions(engine: sa.Engine | None = None) -> Interactions:
    engine = engine or sa.create_engine(get_settings().database_url("analytics"))
    with engine.connect() as conn:
        events = pd.read_sql(INTERACTIONS_SQL, conn)
        products = pd.read_sql(PRODUCTS_SQL, conn).set_index("item_id")
    events["price"] = events["price"].astype(float)
    return Interactions(events, products)


def ground_truth(test_events: pd.DataFrame) -> dict[str, set[str]]:
    return test_events.groupby("user_id")["item_id"].agg(set).to_dict()


def user_states(events: pd.DataFrame) -> dict[str, str]:
    """Most recent state per user (location at their latest order)."""
    last = events.sort_values("purchased_at").groupby("user_id").tail(1)
    return dict(zip(last["user_id"], last["state"], strict=True))


def safe_log(x) -> np.ndarray:
    return np.log1p(np.nan_to_num(np.asarray(x, dtype=float), nan=0.0).clip(min=0))
