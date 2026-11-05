"""Read-only analytics tools the assistant may call.

Every tool:
- has a strict JSON schema (additionalProperties: false) so arguments are validated by the API
  and again here (pydantic) before any query runs;
- declares the minimum role; tools above the user's role are never offered to the model and
  are refused if called anyway;
- returns {"data": ..., "meta": {"metric", "window", "filters", "source", "rows"}} so the model
  can state what each number is, and the UI can show the evidence.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict, Field

from app.assistant.sql_guard import MAX_ROWS, check_query
from app.repositories import customers as customers_repo
from app.repositories import dashboard as dashboard_repo
from app.repositories import insights
from app.repositories.base import rows

WINDOW = "2017-01-01 to 2018-08-21 (analysis window; historical Olist data)"
Month = Field(None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$", description="YYYY-MM")
State = Field(None, pattern=r"^[A-Z]{2}$", description="Brazilian state code, e.g. SP")


class Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NoArgs(Args):
    pass


class SalesArgs(Args):
    date_from: str | None = Month
    date_to: str | None = Month
    state: str | None = State
    category: str | None = Field(
        None, pattern=r"^[a-z0-9_]+$", description="English category, snake_case"
    )


class DeliveryArgs(Args):
    date_from: str | None = Month
    date_to: str | None = Month


class ChurnArgs(Args):
    band: Literal["high", "medium", "low"] = "high"
    sort: Literal["monetary", "churn_risk", "predicted_spend"] = "monetary"
    limit: int = Field(10, ge=1, le=50)


class ForecastArgs(Args):
    horizon: int = Field(30, ge=1, le=90, description="days ahead")
    model: Literal["seasonal_naive", "sarima", "prophet", "xgboost", "lstm"] | None = None


class AnomalyArgs(Args):
    date_from: str | None = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    date_to: str | None = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$")


class SqlArgs(Args):
    sql: str = Field(min_length=1, max_length=5000)


@dataclass
class Tool:
    name: str
    description: str
    args_model: type[Args]
    min_role: Literal["viewer", "analyst", "admin"]
    handler: Callable[[sa.Connection, Args], dict]
    examples: list[str] = field(default_factory=list)

    def schema(self) -> dict:
        """JSON schema for the Messages API.

        Strict tools need additionalProperties: false and every property in `required`
        (optional values are nullable via anyOf). Strict mode does not support numeric or
        string constraints (minimum/maximum, minLength/maxLength) and `pattern` is not in its
        supported list, so those are removed here; the pydantic model still enforces them on
        every call before a tool runs."""
        raw = self.args_model.model_json_schema()
        props = {name: _strip(prop) for name, prop in raw.get("properties", {}).items()}
        return {
            "type": "object",
            "properties": props,
            "required": list(props),
            "additionalProperties": False,
        }

    def api_definition(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.schema(),
            "strict": True,
        }


UNSUPPORTED_IN_STRICT = {
    "title",
    "default",
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "multipleOf",
    "minLength",
    "maxLength",
    "pattern",
}


def _strip(node):
    if isinstance(node, dict):
        return {k: _strip(v) for k, v in node.items() if k not in UNSUPPORTED_IN_STRICT}
    if isinstance(node, list):
        return [_strip(v) for v in node]
    return node


def _meta(metric: str, source: str, filters: dict, n: int, window: str = WINDOW) -> dict:
    return {
        "metric": metric,
        "window": window,
        "source": source,
        "filters": {k: v for k, v in filters.items() if v is not None},
        "rows": n,
    }


def _kpi_overview(conn, _: NoArgs) -> dict:
    k = dashboard_repo.overview(conn)
    return {
        "data": k,
        "meta": _meta(
            "Headline KPIs: GMV (price + freight of revenue orders, not profit), orders, AOV, "
            "customers, repeat rate, delivery and cancellation rates, review score",
            "marts.kpi_overview",
            {},
            1,
        ),
    }


def _sales(conn, a: SalesArgs) -> dict:
    s = dashboard_repo.sales(conn, a.date_from, a.date_to, a.state, a.category)
    data = {
        "totals": s["totals"],
        "monthly": s["monthly"],
        "top_categories": s["by_category"][:10],
        "top_states": s["by_state"][:10],
    }
    metric = "Monthly GMV (item-level, category filter)" if a.category else "Monthly GMV"
    return {
        "data": data,
        "meta": _meta(
            metric
            + ", orders, customers, AOV, MoM growth (complete months only; Aug 2018 partial)",
            "marts.fact_orders / fact_order_items",
            a.model_dump(),
            len(s["monthly"]),
        ),
    }


def _delivery(conn, a: DeliveryArgs) -> dict:
    o = dashboard_repo.operations(conn, a.date_from, a.date_to, None)
    return {
        "data": {"by_state": o["delivery_by_state"], "monthly": o["monthly"]},
        "meta": _meta(
            "Delivery KPIs on eligible delivered orders (avg days, late rate = delivered after the "
            "estimated date) and cancellation rate",
            "marts.fact_orders",
            a.model_dump(),
            len(o["delivery_by_state"]),
        ),
    }


def _segments(conn, _: NoArgs) -> dict:
    seg = customers_repo.segments(conn)
    return {
        "data": seg,
        "meta": _meta("RFM segments (reference date 2018-08-22)", "ml.customer_rfm", {}, len(seg)),
    }


def _churn(conn, a: ChurnArgs) -> dict:
    items, total = customers_repo.list_customers(
        conn, 0, a.limit, a.sort, True, None, None, a.band, None
    )
    return {
        "data": {"customers": items, "customers_in_band": total},
        "meta": _meta(
            "Churn risk = 1 - P(repurchase within 90 days), scored at 2018-08-22; bands are "
            "propensity deciles (high = 1-5). The model is weak: it does not beat a simple "
            "frequency rule beyond noise (see model card)",
            "ml.customer_repurchase_scores",
            a.model_dump(),
            len(items),
        ),
    }


def _forecast(conn, a: ForecastArgs) -> dict:
    f = insights.forecast(conn, a.horizon, a.model)
    return {
        "data": {"selected_model": (f["meta"] or {}).get("selected_model"), "totals": f["totals"]},
        "meta": _meta(
            f"Forecast daily GMV summed over the next {a.horizon} days after the extract ends "
            "(2018-08-21); no actuals exist. The selected model (prophet) lost to the seasonal "
            "naive baseline on the test period - report all models",
            "ml.sales_forecast",
            a.model_dump(),
            len(f["totals"]),
            window=f"2018-08-22 + {a.horizon} days (forecast)",
        ),
    }


def _anomalies(conn, a: AnomalyArgs) -> dict:
    d = insights.anomalies(conn, a.date_from, a.date_to, True)
    days = [
        {
            k: r[k]
            for k in (
                "date",
                "driver_metric",
                "direction",
                "driver_z",
                "calendar_event",
                "explanation",
            )
        }
        for r in d["days"]
    ]
    return {
        "data": {"anomaly_days": days, "sustained_shifts": d["episodes"]},
        "meta": _meta(
            "Days and multi-day stretches deviating from trend + weekday seasonality "
            "(unsupervised; leads to investigate, not confirmed incidents)",
            "ml.daily_anomalies, ml.anomaly_shift_episodes",
            a.model_dump(),
            len(days),
        ),
    }


def _model_quality(conn, _: NoArgs) -> dict:
    m = insights.model_metrics(conn)
    summary = [
        r
        for r in m["customer_models"]
        if r["metric"] in ("pr_auc", "roc_auc", "rmse", "top_decile_spend_capture")
    ]
    fc = [r for r in m["forecasting"] if r["horizon"] == 90]
    return {
        "data": {"customer_models": summary, "forecasting_90d": fc},
        "meta": _meta(
            "Held-out test metrics recorded at training time",
            "ml.model_metrics, ml.forecast_metrics",
            {},
            len(summary) + len(fc),
        ),
    }


def _sql(conn, a: SqlArgs) -> dict:
    checked = check_query(a.sql)
    started = time.perf_counter()
    with conn.begin_nested() if conn.in_transaction() else conn.begin():
        conn.execute(sa.text("set local statement_timeout = '5s'"))
        result = rows(conn, checked.sql)
    return {
        "data": result,
        "meta": _meta(
            f"Result of a validated read-only SELECT (at most {MAX_ROWS} rows; "
            f"{(time.perf_counter() - started) * 1000:.0f} ms)",
            ", ".join(checked.tables) or "none",
            {"sql": a.sql},
            len(result),
        ),
    }


TOOLS: list[Tool] = [
    Tool(
        "get_kpi_overview",
        "Headline KPIs for the whole analysis window: GMV, orders, AOV, "
        "customers, repeat purchase rate, on-time/late delivery rates, cancellation rate, "
        "average review score.",
        NoArgs,
        "viewer",
        _kpi_overview,
    ),
    Tool(
        "get_sales",
        "Monthly GMV, orders, customers, AOV and month-over-month growth, plus top "
        "categories and states, with optional month range (YYYY-MM), customer state and "
        "category filters. Use for revenue trends, top categories and regional revenue.",
        SalesArgs,
        "viewer",
        _sales,
    ),
    Tool(
        "get_delivery_performance",
        "Delivery KPIs by customer state (average delivery days, late "
        "delivery rate) and by month (also cancellation rate). Use for delivery delays by "
        "region.",
        DeliveryArgs,
        "viewer",
        _delivery,
    ),
    Tool(
        "get_customer_segments",
        "RFM segments with customer counts, average recency, frequency, "
        "spend, repurchase probability and predicted 90-day spend.",
        NoArgs,
        "viewer",
        _segments,
    ),
    Tool(
        "get_sales_forecast",
        "Forecast GMV totals per model for the next N days (1-90) after the "
        "data ends, and which model is selected.",
        ForecastArgs,
        "viewer",
        _forecast,
    ),
    Tool(
        "get_anomalies",
        "Flagged anomaly days (with driver metric, direction, calendar event and "
        "explanation) and sustained level-shift episodes, optional ISO date range.",
        AnomalyArgs,
        "viewer",
        _anomalies,
    ),
    Tool(
        "get_model_quality",
        "Held-out test metrics of the churn, CLV and forecasting models, "
        "including simple baselines. Use before stating how reliable a prediction is.",
        NoArgs,
        "viewer",
        _model_quality,
    ),
    Tool(
        "get_churn_risk_customers",
        "Customers in a churn-risk band (propensity deciles), with "
        "RFM, churn risk and predicted spend, sorted by value or risk. Customer-level data.",
        ChurnArgs,
        "analyst",
        _churn,
    ),
    Tool(
        "query_warehouse",
        "Run ONE read-only SQL SELECT (PostgreSQL) on schema-qualified tables "
        "in marts.* or ml.* when no other tool answers the question. At most 200 rows, 5 s. "
        "Key tables: marts.fact_orders (order grain: gmv, order_status, purchased_at, "
        "customer_state_at_order, is_revenue_order, is_in_analysis_window, delivery_days, "
        "is_late), marts.fact_order_items (item grain), marts.dim_products (category_name), "
        "marts.dim_customers, marts.kpi_* views, ml.customer_rfm. Always filter "
        "is_revenue_order and is_in_analysis_window for revenue.",
        SqlArgs,
        "analyst",
        _sql,
    ),
]
TOOLS_BY_NAME = {t.name: t for t in TOOLS}
