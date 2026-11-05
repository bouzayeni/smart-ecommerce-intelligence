"""Forecasts, anomalies, recommendations and model metadata from the ml schema."""

import sqlalchemy as sa

from app.repositories.base import one, rows


def forecast(conn: sa.Connection, horizon: int, model: str | None) -> dict:
    meta = one(
        conn,
        """select model as selected_model, series_end, interval_level, generated_at
                        from ml.sales_forecast where is_selected limit 1""",
    )
    if meta is None:
        return {"meta": None, "points": [], "totals": []}
    points = rows(
        conn,
        """
        select model, forecast_date, horizon_day, yhat, lower, upper, interval_source, is_selected
        from ml.sales_forecast
        where horizon_day <= :h and (cast(:model as text) is null or model = :model)
        order by model, forecast_date""",
        h=horizon,
        model=model,
    )
    totals = rows(
        conn,
        """
        select model, sum(yhat) as gmv_forecast, bool_or(is_selected) as is_selected
        from ml.sales_forecast
        where horizon_day <= :h and (cast(:model as text) is null or model = :model)
        group by model order by model""",
        h=horizon,
        model=model,
    )
    history = rows(
        conn,
        """
        select date_day, gmv from marts.agg_daily_sales
        where date_day > (select max(date_day) from marts.agg_daily_sales) - 120
        order by date_day""",
    )
    return {"meta": meta, "points": points, "totals": totals, "history": history}


def forecast_metrics(conn: sa.Connection) -> list[dict]:
    return rows(
        conn,
        """
        select model, split, horizon, avg(mae) as mae, avg(rmse) as rmse, avg(wape) as wape,
               avg(mape) as mape, avg(interval_coverage) as interval_coverage
        from ml.forecast_metrics group by 1, 2, 3 order by split, horizon, wape""",
    )


def anomalies(conn: sa.Connection, start, end, only_flagged: bool) -> dict:
    days = rows(
        conn,
        """
        select date, gmv_actual, gmv_expected, revenue_orders_actual, revenue_orders_expected,
               freight_per_item_actual, cancellation_rate_actual, iforest_score, is_anomaly,
               is_anomaly_zrule, is_sustained_shift, driver_metric, driver_z, direction,
               calendar_event, is_explained_by_calendar, explanation
        from ml.daily_anomalies
        where (cast(:start as date) is null or date >= :start)
          and (cast(:end as date) is null or date <= :end)
          and (not :only or is_anomaly)
        order by date""",
        start=start,
        end=end,
        only=only_flagged,
    )
    episodes = rows(
        conn,
        """select start, "end", days, metric, peak_rolling_z, direction,
                                    calendar_events from ml.anomaly_shift_episodes
                             order by start""",
    )
    return {"days": days, "episodes": episodes}


def recommendations(conn: sa.Connection, customer_id: str, k: int) -> list[dict]:
    return rows(
        conn,
        """
        select r.rank, r.product_id, r.category_name, r.score, r.strategy
        from ml.product_recommendations r
        where r.customer_unique_id = :cid order by r.rank limit :k""",
        cid=customer_id,
        k=k,
    )


def popular(conn: sa.Connection, state: str | None, k: int) -> list[dict]:
    found = rows(
        conn,
        """select rank, product_id, category_name, score, state
                          from ml.popular_products where state = :s order by rank limit :k""",
        s=state or "ALL",
        k=k,
    )
    if not found and state:
        return popular(conn, None, k)
    return found


def similar_products(conn: sa.Connection, product_id: str, k: int) -> list[dict]:
    return rows(
        conn,
        """
        select n.rank, n.neighbour_product_id as product_id, p.category_name, n.similarity
        from ml.item_neighbours n
        join marts.dim_products p on p.product_id = n.neighbour_product_id
        where n.product_id = :pid order by n.rank limit :k""",
        pid=product_id,
        k=k,
    )


def product_exists(conn: sa.Connection, product_id: str) -> bool:
    return (
        one(conn, "select 1 as x from marts.dim_products where product_id = :p", p=product_id)
        is not None
    )


def customer_state(conn: sa.Connection, customer_id: str) -> str | None:
    found = one(
        conn,
        "select customer_state from marts.dim_customers where customer_unique_id = :c",
        c=customer_id,
    )
    return found["customer_state"] if found else None


def model_metrics(conn: sa.Connection) -> dict:
    return {
        "customer_models": rows(
            conn,
            """select model_name, model_version, candidate, metric, value,
                                                trained_at from ml.model_metrics
                                         order by model_name, candidate, metric""",
        ),
        "forecasting": forecast_metrics(conn),
        "recommendations": rows(
            conn,
            """select split, segment, family, params,
                                                "hit_rate@10", "ndcg@10", "category_hit_rate@10",
                                                users from ml.recommendation_metrics
                                         order by split, segment, "ndcg@10" desc""",
        ),
    }


def table_freshness(conn: sa.Connection) -> list[dict]:
    out = []
    checks = {
        "customer_repurchase_scores": "trained_at",
        "customer_spend_predictions": "trained_at",
        "sales_forecast": "generated_at",
        "daily_anomalies": "detected_at",
        "product_recommendations": "generated_at",
    }
    for table, column in checks.items():
        r = one(conn, f'select count(*) as rows, max("{column}") as updated_at from ml.{table}')
        out.append({"table": f"ml.{table}", **r})
    return out
