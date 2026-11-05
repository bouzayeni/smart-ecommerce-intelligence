"""Dashboard, customers, predictions, recommendations, anomalies, models, data quality."""

import datetime as dt
import json
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Path, Query, Request

from app.api.deps import Admin, Analyst, AppSession, ReadConn, Viewer
from app.core.config import get_settings
from app.core.errors import ApiError, not_found
from app.repositories import customers as customers_repo
from app.repositories import dashboard as dashboard_repo
from app.repositories import insights
from app.schemas.common import DataNote, Page, PageParams
from app.schemas.predictions import PredictionRequest
from app.services import prediction_service
from app.services.model_registry import registry_versions

router = APIRouter()

Month = Annotated[str | None, Query(pattern=r"^\d{4}-(0[1-9]|1[0-2])$", description="YYYY-MM")]
State = Annotated[str | None, Query(pattern=r"^[A-Z]{2}$")]
Category = Annotated[str | None, Query(max_length=80, pattern=r"^[a-z0-9_]+$")]
HEX32 = r"^[0-9a-f]{32}$"
CustomerId = Annotated[str, Path(pattern=HEX32, description="customer_unique_id")]
ProductId = Annotated[str, Path(pattern=HEX32)]


ANALYSIS_WINDOW = "2017-01-01 to 2018-08-21"


def _note(source: str, **filters) -> dict:
    return DataNote(
        source=source,
        window=ANALYSIS_WINDOW,
        filters={k: v for k, v in filters.items() if v is not None},
        note="Historical Olist data; analysis window 2017-01-01 to 2018-08-21. "
        "GMV is gross merchandise value, not profit.",
    ).model_dump()


# ------------------------------------------------------------------ dashboard
@router.get("/dashboard/overview", tags=["dashboard"])
def overview(_: Viewer, conn: ReadConn):
    return {"kpis": dashboard_repo.overview(conn), "meta": _note("marts.kpi_overview")}


@router.get("/dashboard/sales", tags=["dashboard"])
def sales(
    _: Viewer,
    conn: ReadConn,
    date_from: Month = None,
    date_to: Month = None,
    state: State = None,
    category: Category = None,
):
    if date_from and date_to and date_from > date_to:
        raise ApiError(422, "validation_error", "date_from must not be after date_to")
    data = dashboard_repo.sales(conn, date_from, date_to, state, category)
    return {
        **data,
        "meta": _note(
            "marts.fact_orders / fact_order_items",
            date_from=date_from,
            date_to=date_to,
            state=state,
            category=category,
        ),
    }


@router.get("/dashboard/operations", tags=["dashboard"])
def operations(
    _: Viewer, conn: ReadConn, date_from: Month = None, date_to: Month = None, state: State = None
):
    data = dashboard_repo.operations(conn, date_from, date_to, state)
    return {
        **data,
        "meta": _note(
            "marts.fact_orders (delivery KPIs: eligible orders, BR-07)",
            date_from=date_from,
            date_to=date_to,
            state=state,
        ),
    }


@router.get("/dashboard/filters", tags=["dashboard"])
def filters(_: Viewer, conn: ReadConn):
    return dashboard_repo.filter_options(conn)


# ------------------------------------------------------------------ customers
SortKey = Literal[tuple(customers_repo.SORTS)]  # type: ignore[valid-type]
Segment = Annotated[str | None, Query(max_length=40, pattern=r"^[A-Za-z ]+$")]


@router.get("/customers", response_model=Page[dict], tags=["customers"])
def list_customers(
    _: Analyst,
    conn: ReadConn,
    paging: Annotated[PageParams, Depends()],
    segment: Segment = None,
    state: State = None,
    risk_band: Literal["high", "medium", "low"] | None = None,
    search: Annotated[str | None, Query(pattern=r"^[0-9a-f]{1,32}$")] = None,
    sort: SortKey = "monetary",
    order: Literal["asc", "desc"] = "desc",
):
    items, total = customers_repo.list_customers(
        conn,
        paging.offset,
        paging.page_size,
        sort,
        order == "desc",
        segment,
        state,
        risk_band,
        search,
    )
    return Page(items=items, total=total, page=paging.page, page_size=paging.page_size)


@router.get("/customers/segments", tags=["customers"])
def segments(_: Viewer, conn: ReadConn):
    return {
        "segments": customers_repo.segments(conn),
        "meta": _note("ml.customer_rfm (reference date 2018-08-22)"),
    }


@router.get("/customers/churn-risk", response_model=Page[dict], tags=["customers"])
def churn_risk(
    _: Analyst,
    conn: ReadConn,
    paging: Annotated[PageParams, Depends()],
    band: Literal["high", "medium", "low"] = "high",
    segment: Segment = None,
    sort: Literal["monetary", "churn_risk", "predicted_spend"] = "monetary",
):
    """Customers in a churn-risk band, highest historical value first by default: the list a
    retention team would work from. Bands are propensity deciles (see model card)."""
    items, total = customers_repo.list_customers(
        conn,
        paging.offset,
        paging.page_size,
        sort,
        True,
        segment,
        None,
        band,
        None,
    )
    return Page(items=items, total=total, page=paging.page, page_size=paging.page_size)


@router.get("/customers/{customer_id}", tags=["customers"])
def customer_detail(_: Analyst, conn: ReadConn, customer_id: CustomerId):
    found = customers_repo.get_customer(conn, customer_id)
    if found is None:
        raise not_found("Customer")
    found["recommendations"] = insights.recommendations(conn, customer_id, 10)
    return found


# ------------------------------------------------------------------ predictions
@router.post("/predictions/churn", tags=["predictions"])
def predict_churn(
    request: Request, body: PredictionRequest, user: Analyst, conn: ReadConn, session: AppSession
):
    return prediction_service.churn(conn, session, request, user, body)


@router.post("/predictions/clv", tags=["predictions"])
def predict_clv(
    request: Request, body: PredictionRequest, user: Analyst, conn: ReadConn, session: AppSession
):
    return prediction_service.spend(conn, session, request, user, body)


@router.get("/predictions/forecast", tags=["predictions"])
def forecast(
    _: Viewer,
    conn: ReadConn,
    # Days ahead (the UI offers 30/60/90). Literal[30, 60, 90] would reject the query-string
    # value "30": pydantic matches literals strictly.
    horizon: Annotated[int, Query(ge=1, le=90)] = 30,
    model: Literal["seasonal_naive", "sarima", "prophet", "xgboost", "lstm"] | None = None,
):
    data = insights.forecast(conn, horizon, model)
    return {
        **data,
        # Keep the forecast's own metadata (selected model, series end) and add the data note.
        "meta": (data["meta"] or {})
        | _note("ml.sales_forecast", horizon=horizon, model=model)
        | {
            "note": "Forecast of the days after the historical extract (no actuals exist). "
            "See docs/model_cards/sales_forecasting.md: the selected model did not beat "
            "the naive baseline on the test period."
        },
    }


# ------------------------------------------------------------------ recommendations
@router.get("/recommendations/{customer_id}", tags=["recommendations"])
def recommend(
    _: Analyst,
    conn: ReadConn,
    customer_id: CustomerId,
    k: Annotated[int, Query(ge=1, le=10)] = 10,
    state: State = None,
):
    recs = insights.recommendations(conn, customer_id, k)
    if recs:
        return {"customer_unique_id": customer_id, "strategy": "personalised", "items": recs}
    # Cold start: unknown customer -> popular products in their (or the given) state.
    st = state or insights.customer_state(conn, customer_id)
    return {
        "customer_unique_id": customer_id,
        "strategy": f"popular ({st or 'all states'})",
        "items": insights.popular(conn, st, k),
    }


@router.get("/recommendations/products/{product_id}/similar", tags=["recommendations"])
def similar(
    _: Viewer, conn: ReadConn, product_id: ProductId, k: Annotated[int, Query(ge=1, le=20)] = 10
):
    if not insights.product_exists(conn, product_id):
        raise not_found("Product")
    return {"product_id": product_id, "items": insights.similar_products(conn, product_id, k)}


# ------------------------------------------------------------------ anomalies
@router.get("/anomalies", tags=["anomalies"])
def anomalies(
    _: Viewer,
    conn: ReadConn,
    date_from: dt.date | None = None,
    date_to: dt.date | None = None,
    only_flagged: bool = True,
):
    data = insights.anomalies(conn, date_from, date_to, only_flagged)
    return {
        **data,
        "meta": _note(
            "ml.daily_anomalies, ml.anomaly_shift_episodes",
            date_from=str(date_from) if date_from else None,
            date_to=str(date_to) if date_to else None,
        ),
    }


# ------------------------------------------------------------------ models & data quality
@router.get("/models/status", tags=["models"])
def model_status(_: Admin, conn: ReadConn):
    return {"registry": registry_versions(), "tables": insights.table_freshness(conn)}


@router.get("/models/metrics", tags=["models"])
def model_metrics(_: Viewer, conn: ReadConn):
    return insights.model_metrics(conn)


@router.get("/data-quality", tags=["data quality"])
def data_quality(_: Admin):
    path = get_settings().data_quality_results_path
    if not path.is_file():
        raise ApiError(404, "not_found", "No quality results; run assess_quality.py")
    payload = json.loads(path.read_text(encoding="utf-8"))
    checks = payload["checks"]
    return {
        "generated_at": payload["generated_at"],
        "summary": {
            "checks": len(checks),
            "error_failures": sum(c["severity"] == "error" and not c["passed"] for c in checks),
            "flagged": sum(c["severity"] != "error" and not c["passed"] for c in checks),
        },
        "checks": checks,
        "window": payload["summary"]["window"],
    }
