"""Customer 360, segments and churn-risk lists (dim_customers + ml.* batch scores)."""

import json

import sqlalchemy as sa

from app.repositories.base import one, rows

# Allowlisted sort keys -> SQL expressions (never interpolate request strings directly).
SORTS = {
    "monetary": "r.monetary",
    "recency": "r.recency_days",
    "frequency": "r.frequency",
    "churn_risk": "s.churn_risk_90d",
    "repurchase_probability": "s.repurchase_probability_90d",
    "predicted_spend": "p.predicted_spend_brl",
    "last_order": "c.last_order_at",
}

FROM = """
from marts.dim_customers c
left join ml.customer_rfm r using (customer_unique_id)
left join ml.customer_repurchase_scores s using (customer_unique_id)
left join ml.customer_spend_predictions p using (customer_unique_id)
"""
BASE = (
    FROM
    + """
where (cast(:segment as text) is null or r.segment = :segment)
  and (cast(:state as text) is null or c.customer_state = :state)
  and (cast(:band as text) is null or s.churn_risk_band = :band)
  and (cast(:search as text) is null or c.customer_unique_id like :search || '%')
"""
)
COLUMNS = """
c.customer_unique_id, c.customer_state, c.customer_city, c.first_order_at, c.last_order_at,
c.order_count, r.recency_days, r.frequency, r.monetary, r.r_score, r.f_score, r.m_score,
r.segment, s.repurchase_probability_90d, s.churn_risk_90d, s.propensity_decile,
s.churn_risk_band, p.predicted_spend_brl
"""


def list_customers(
    conn: sa.Connection,
    offset: int,
    limit: int,
    sort: str,
    descending: bool,
    segment=None,
    state=None,
    band=None,
    search=None,
) -> tuple[list, int]:
    p = {"segment": segment, "state": state, "band": band, "search": search}
    order = f"{SORTS[sort]} {'desc' if descending else 'asc'} nulls last, c.customer_unique_id"
    items = rows(
        conn,
        f"select {COLUMNS} {BASE} order by {order} limit :limit offset :offset",
        limit=limit,
        offset=offset,
        **p,
    )
    total = one(conn, f"select count(*) as n {BASE}", **p)["n"]
    return items, total


def get_customer(conn: sa.Connection, customer_id: str) -> dict | None:
    profile = one(
        conn,
        f"""select {COLUMNS}, c.customer_zip_code_prefix, c.latitude, c.longitude,
                                   c.revenue_order_count, s.top_reasons, s.scored_at_cutoff,
                                   s.model_version as churn_model_version,
                                   p.baseline_spend_brl, p.model_version as spend_model_version
                            {FROM} where c.customer_unique_id = :cid""",
        cid=customer_id,
    )
    if profile is None:
        return None
    if profile.get("top_reasons"):
        profile["top_reasons"] = json.loads(profile["top_reasons"])
    profile["orders"] = rows(
        conn,
        """
        select order_id, purchased_at, order_status, gmv, item_count, review_score, is_late,
               delivery_days, customer_state_at_order
        from marts.fact_orders where customer_unique_id = :cid
        order by purchased_at desc limit 50""",
        cid=customer_id,
    )
    return profile


def segments(conn: sa.Connection) -> list[dict]:
    return rows(
        conn,
        """
        select r.segment, count(*) as customers, avg(r.recency_days) as avg_recency_days,
               avg(r.frequency) as avg_frequency, avg(r.monetary) as avg_monetary,
               sum(r.monetary) as total_monetary,
               avg(s.repurchase_probability_90d) as avg_repurchase_probability_90d,
               sum(p.predicted_spend_brl) as predicted_spend_90d_brl
        from ml.customer_rfm r
        left join ml.customer_repurchase_scores s using (customer_unique_id)
        left join ml.customer_spend_predictions p using (customer_unique_id)
        group by r.segment order by customers desc""",
    )
