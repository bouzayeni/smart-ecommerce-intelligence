"""Load the customer event history from the marts (read-only analytics role)."""

from dataclasses import dataclass

import pandas as pd
import sqlalchemy as sa

from data_engineering.config import get_settings


@dataclass
class CustomerHistory:
    """Revenue orders in the analysis window, plus per-order item categories and reviews.

    Only revenue orders are used (BR-03), so behaviour and labels share one definition.
    """

    orders: pd.DataFrame  # one row per revenue order
    order_categories: pd.DataFrame  # (order_id, category_name), one row per distinct pair
    reviews: pd.DataFrame  # selected review per order with its answer time (BR-06)
    window_end: pd.Timestamp


ORDERS_SQL = """
select order_id, customer_unique_id, purchased_at, gmv, price_total, freight_total,
       item_count, max_installments, primary_payment_type, customer_state_at_order,
       delivered_to_customer_at, is_late, delivery_days
from marts.fact_orders
where is_revenue_order and is_in_analysis_window
"""
CATEGORIES_SQL = """
select distinct i.order_id, p.category_name
from marts.fact_order_items i
join marts.dim_products p using (product_id)
where i.is_revenue_order and i.is_in_analysis_window
"""
REVIEWS_SQL = """
select order_id, review_score, review_answered_at
from marts.fact_reviews
where is_selected_for_order and is_in_analysis_window
"""


def load_history(engine: sa.Engine | None = None) -> CustomerHistory:
    engine = engine or sa.create_engine(get_settings().database_url("analytics"))
    with engine.connect() as conn:
        orders = pd.read_sql(ORDERS_SQL, conn)
        categories = pd.read_sql(CATEGORIES_SQL, conn)
        reviews = pd.read_sql(REVIEWS_SQL, conn)
        window_end = pd.Timestamp(
            conn.execute(sa.text("select window_end from marts.kpi_overview")).scalar_one()
        )
    for col in ("gmv", "price_total", "freight_total", "delivery_days"):
        orders[col] = orders[col].astype(float)
    return CustomerHistory(orders, categories, reviews, window_end)
