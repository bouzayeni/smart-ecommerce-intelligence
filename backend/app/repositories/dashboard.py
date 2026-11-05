"""Dashboard KPIs. Unfiltered requests use the dbt KPI views; filtered ones aggregate the
facts with the same definitions (docs/kpi_dictionary.md)."""

import sqlalchemy as sa

from app.repositories.base import month_bounds, one, rows

ORDER_FILTER = """
  o.is_revenue_order and o.is_in_analysis_window
  and (cast(:start as date) is null or o.purchased_at >= :start)
  and (cast(:end as date) is null or o.purchased_at < :end)
  and (cast(:state as text) is null or o.customer_state_at_order = :state)
"""


def overview(conn: sa.Connection) -> dict:
    return one(conn, "select * from marts.kpi_overview")


def sales(conn: sa.Connection, date_from=None, date_to=None, state=None, category=None) -> dict:
    start, end = month_bounds(date_from, date_to)
    p = {"start": start, "end": end, "state": state, "category": category}
    item_join = (
        """
      from marts.fact_order_items i
      join marts.fact_orders o using (order_id)
      join marts.dim_products p using (product_id)
      where """
        + ORDER_FILTER
        + " and (cast(:category as text) is null or p.category_name = :category)"
    )
    if category:
        # Category filter: item-level GMV (an order can mix categories).
        monthly = rows(
            conn,
            f"""
            select to_char(o.purchased_at, 'YYYY-MM') as year_month, sum(i.gmv) as gmv,
                   count(distinct o.order_id) as orders,
                   count(distinct o.customer_unique_id) as customers
            {item_join} group by 1 order by 1""",
            **p,
        )
    else:
        monthly = rows(
            conn,
            f"""
            select to_char(o.purchased_at, 'YYYY-MM') as year_month, sum(o.gmv) as gmv,
                   count(*) as orders, count(distinct o.customer_unique_id) as customers
            from marts.fact_orders o where {ORDER_FILTER} group by 1 order by 1""",
            **p,
        )
    complete = {
        r["year_month"]: r["is_complete_month"]
        for r in rows(conn, "select year_month, is_complete_month from marts.kpi_monthly_sales")
    }
    previous = None
    for r in monthly:
        r["avg_order_value"] = r["gmv"] / r["orders"] if r["orders"] else None
        r["is_complete_month"] = complete.get(r["year_month"], False)
        ok = previous and previous["is_complete_month"] and r["is_complete_month"]
        r["gmv_mom_growth"] = (r["gmv"] - previous["gmv"]) / previous["gmv"] if ok else None
        previous = r
    by_category = rows(
        conn,
        f"""
        select p.category_name, sum(i.gmv) as gmv, count(*) as units
        {item_join} group by 1 order by gmv desc limit 15""",
        **p,
    )
    by_state = rows(
        conn,
        f"""
        select o.customer_state_at_order as state, sum(i.gmv) as gmv,
               count(distinct o.order_id) as orders
        {item_join} group by 1 order by gmv desc""",
        **p,
    )
    totals = {
        "gmv": sum(r["gmv"] for r in monthly),
        "orders": sum(r["orders"] for r in monthly),
    }
    totals["avg_order_value"] = totals["gmv"] / totals["orders"] if totals["orders"] else None
    return {"totals": totals, "monthly": monthly, "by_category": by_category, "by_state": by_state}


def operations(conn: sa.Connection, date_from=None, date_to=None, state=None) -> dict:
    start, end = month_bounds(date_from, date_to)
    p = {"start": start, "end": end, "state": state}
    window = """
      o.is_in_analysis_window
      and (cast(:start as date) is null or o.purchased_at >= :start)
      and (cast(:end as date) is null or o.purchased_at < :end)
      and (cast(:state as text) is null or o.customer_state_at_order = :state)"""
    monthly = rows(
        conn,
        f"""
        select to_char(o.purchased_at, 'YYYY-MM') as year_month,
               count(*) as all_orders,
               avg((o.order_status in ('canceled', 'unavailable'))::int) as cancellation_rate,
               count(*) filter (where o.is_delivery_kpi_eligible) as delivery_eligible_orders,
               avg(o.delivery_days) filter (where o.is_delivery_kpi_eligible) as avg_delivery_days,
               avg(o.is_late::int) filter (where o.is_delivery_kpi_eligible) as late_delivery_rate,
               sum(o.freight_total) filter (where o.is_revenue_order)
                 / nullif(count(*) filter (where o.is_revenue_order), 0) as avg_freight_per_order
        from marts.fact_orders o where {window} group by 1 order by 1""",
        **p,
    )
    reviews = rows(
        conn,
        f"""
        select o.review_score, count(*) as orders,
               count(*) filter (where o.is_delivery_kpi_eligible and o.is_late) as late_orders
        from marts.fact_orders o where {window} and o.review_score is not null
        group by 1 order by 1""",
        **p,
    )
    by_state = rows(
        conn,
        f"""
        select o.customer_state_at_order as state,
               count(*) filter (where o.is_delivery_kpi_eligible) as delivery_eligible_orders,
               avg(o.delivery_days) filter (where o.is_delivery_kpi_eligible) as avg_delivery_days,
               avg(o.is_late::int) filter (where o.is_delivery_kpi_eligible) as late_delivery_rate
        from marts.fact_orders o where {window} group by 1
        having count(*) filter (where o.is_delivery_kpi_eligible) > 0
        order by late_delivery_rate desc""",
        **p,
    )
    return {"monthly": monthly, "review_distribution": reviews, "delivery_by_state": by_state}


def filter_options(conn: sa.Connection) -> dict:
    return {
        "months": [
            r["year_month"]
            for r in rows(conn, "select year_month from marts.kpi_monthly_sales order by 1")
        ],
        "states": [
            r["state"] for r in rows(conn, "select state from marts.kpi_sales_by_state order by 1")
        ],
        "categories": [
            r["category_name"]
            for r in rows(conn, "select category_name from marts.kpi_sales_by_category order by 1")
        ],
    }
