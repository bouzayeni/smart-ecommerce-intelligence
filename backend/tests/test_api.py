"""Analytics endpoints: authorization matrix, values vs independent SQL, validation."""

import pytest
import sqlalchemy as sa


def scalar(conn: sa.Connection, sql: str, **params):
    return conn.execute(sa.text(sql), params).scalar_one()


pytestmark = pytest.mark.db


@pytest.fixture(scope="module")
def users(make_user):
    return {role: make_user(role) for role in ("viewer", "analyst", "admin")}


@pytest.fixture(scope="module")
def known_customer(warehouse):
    return scalar(
        warehouse,
        """select customer_unique_id from ml.customer_rfm
                                where frequency >= 2 order by monetary desc limit 1""",
    )


@pytest.mark.parametrize(
    ("path", "minimum"),
    [
        ("/api/dashboard/overview", "viewer"),
        ("/api/dashboard/sales", "viewer"),
        ("/api/dashboard/operations", "viewer"),
        ("/api/customers/segments", "viewer"),
        ("/api/predictions/forecast", "viewer"),
        ("/api/anomalies", "viewer"),
        ("/api/models/metrics", "viewer"),
        ("/api/customers", "analyst"),
        ("/api/customers/churn-risk", "analyst"),
        ("/api/models/status", "admin"),
        ("/api/data-quality", "admin"),
    ],
)
def test_authorization_matrix(client, users, path, minimum):
    order = ["viewer", "analyst", "admin"]
    assert client.get(path).status_code == 401
    for role in order:
        r = client.get(path, headers=users[role]["headers"])
        expected = 200 if order.index(role) >= order.index(minimum) else 403
        assert r.status_code == expected, (path, role, r.text[:200])


def test_overview_matches_kpi_view(client, users, warehouse):
    kpis = client.get("/api/dashboard/overview", headers=users["viewer"]["headers"]).json()["kpis"]
    assert kpis["gmv"] == pytest.approx(
        float(scalar(warehouse, "select gmv from marts.kpi_overview"))
    )
    assert kpis["revenue_orders"] == scalar(
        warehouse, "select revenue_orders from marts.kpi_overview"
    )


def test_filtered_sales_match_independent_sql(client, users, warehouse):
    r = client.get(
        "/api/dashboard/sales",
        headers=users["viewer"]["headers"],
        params={"state": "SP", "date_from": "2018-01", "date_to": "2018-03"},
    )
    body = r.json()
    expected = scalar(
        warehouse,
        """select sum(gmv) from marts.fact_orders
        where is_revenue_order and is_in_analysis_window and customer_state_at_order = 'SP'
          and purchased_at >= '2018-01-01' and purchased_at < '2018-04-01'""",
    )
    assert body["totals"]["gmv"] == pytest.approx(float(expected))
    assert [m["year_month"] for m in body["monthly"]] == ["2018-01", "2018-02", "2018-03"]
    assert body["meta"]["filters"] == {"date_from": "2018-01", "date_to": "2018-03", "state": "SP"}


def test_category_filter_uses_item_level_gmv(client, users, warehouse):
    r = client.get(
        "/api/dashboard/sales",
        headers=users["viewer"]["headers"],
        params={"category": "health_beauty"},
    ).json()
    expected = scalar(
        warehouse,
        "select gmv from marts.kpi_sales_by_category where category_name = 'health_beauty'",
    )
    assert r["totals"]["gmv"] == pytest.approx(float(expected))


@pytest.mark.parametrize(
    "params",
    [
        {"date_from": "2018-13"},
        {"state": "sp"},
        {"state": "S;"},
        {"category": "x' or '1'='1"},
        {"date_from": "2018-05", "date_to": "2018-01"},
    ],
)
def test_sales_rejects_invalid_filters(client, users, params):
    r = client.get("/api/dashboard/sales", headers=users["viewer"]["headers"], params=params)
    assert r.status_code == 422


def test_customer_list_paginates_and_sorts(client, users, warehouse):
    h = users["analyst"]["headers"]
    page1 = client.get(
        "/api/customers", headers=h, params={"page_size": 5, "sort": "monetary"}
    ).json()
    page2 = client.get(
        "/api/customers", headers=h, params={"page_size": 5, "page": 2, "sort": "monetary"}
    ).json()
    assert page1["total"] == scalar(warehouse, "select count(*) from marts.dim_customers")
    values = [c["monetary"] for c in page1["items"] + page2["items"]]
    assert values == sorted(values, reverse=True)
    assert {c["customer_unique_id"] for c in page1["items"]}.isdisjoint(
        {c["customer_unique_id"] for c in page2["items"]}
    )


@pytest.mark.parametrize(
    "params",
    [
        {"sort": "monetary; drop table x"},
        {"page_size": 1000},
        {"page": 0},
        {"search": "abc' or 1=1"},
        {"risk_band": "extreme"},
    ],
)
def test_customer_list_rejects_invalid_parameters(client, users, params):
    assert (
        client.get("/api/customers", headers=users["analyst"]["headers"], params=params).status_code
        == 422
    )


def test_customer_detail_and_not_found(client, users, known_customer):
    h = users["analyst"]["headers"]
    body = client.get(f"/api/customers/{known_customer}", headers=h).json()
    assert body["customer_unique_id"] == known_customer
    assert body["orders"] and body["segment"] and len(body["recommendations"]) == 10
    assert isinstance(body["top_reasons"], list)
    assert client.get(f"/api/customers/{'0' * 32}", headers=h).status_code == 404
    assert client.get("/api/customers/not-a-valid-id", headers=h).status_code == 422


def test_stored_churn_prediction_is_logged(client, users, known_customer, warehouse, app_schema):
    r = client.post(
        "/api/predictions/churn",
        headers=users["analyst"]["headers"],
        json={"customer_unique_id": known_customer},
    )
    body = r.json()
    expected = scalar(
        warehouse,
        "select churn_risk_90d from ml.customer_repurchase_scores where customer_unique_id = :c",
        c=known_customer,
    )
    assert body["mode"] == "stored" and body["churn_risk_90d"] == pytest.approx(float(expected))
    from app.db.session import app_engine

    with app_engine().connect() as conn:
        n = conn.execute(
            sa.text("select count(*) from prediction_log where customer_unique_id = :c"),
            {"c": known_customer},
        ).scalar_one()
    assert n >= 1


def test_on_demand_churn_prediction_uses_registered_model(client, users):
    pytest.importorskip("mlflow")
    features = {
        "recency_days": 30,
        "tenure_days": 200,
        "frequency": 3,
        "monetary": 450,
        "avg_order_value": 150,
        "max_order_value": 200,
        "last_order_value": 120,
        "customer_state": "SP",
        "last_order_category": "health_beauty",
    }
    r = client.post(
        "/api/predictions/churn", headers=users["analyst"]["headers"], json={"features": features}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["mode"] == "on_demand" and 0 <= body["repurchase_probability_90d"] <= 1
    assert body["churn_risk_90d"] == pytest.approx(1 - body["repurchase_probability_90d"])


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"customer_unique_id": "0" * 32, "features": {"recency_days": 1}},
        {"features": {"recency_days": -5}},
        {"customer_unique_id": "short"},
        {"features": {"unexpected": 1}},
    ],
)
def test_prediction_payload_validation(client, users, payload):
    r = client.post("/api/predictions/churn", headers=users["analyst"]["headers"], json=payload)
    assert r.status_code == 422


def test_forecast_horizon(client, users, warehouse):
    h = users["viewer"]["headers"]
    body = client.get("/api/predictions/forecast", headers=h, params={"horizon": 30}).json()
    models = scalar(warehouse, "select count(distinct model) from ml.sales_forecast")
    assert len(body["points"]) == 30 * models
    assert body["meta"]["selected_model"] in {p["model"] for p in body["points"]}
    assert (
        client.get("/api/predictions/forecast", headers=h, params={"horizon": 91}).status_code
        == 422
    )


def test_recommendations_personalised_and_cold_start(client, users, known_customer):
    h = users["analyst"]["headers"]
    warm = client.get(f"/api/recommendations/{known_customer}", headers=h).json()
    assert warm["strategy"] == "personalised" and len(warm["items"]) == 10
    cold = client.get(f"/api/recommendations/{'f' * 32}", headers=h, params={"state": "RJ"}).json()
    assert cold["strategy"].startswith("popular") and len(cold["items"]) == 10


def test_similar_products(client, users, warehouse):
    pid = scalar(warehouse, "select product_id from ml.item_neighbours where rank = 1 limit 1")
    r = client.get(
        f"/api/recommendations/products/{pid}/similar", headers=users["viewer"]["headers"]
    ).json()
    assert r["items"] and r["items"][0]["product_id"] != pid
    assert (
        client.get(
            f"/api/recommendations/products/{'0' * 32}/similar", headers=users["viewer"]["headers"]
        ).status_code
        == 404
    )


def test_anomalies_match_table(client, users, warehouse):
    body = client.get("/api/anomalies", headers=users["viewer"]["headers"]).json()
    assert len(body["days"]) == scalar(
        warehouse, "select count(*) from ml.daily_anomalies where is_anomaly"
    )
    assert body["episodes"]


def test_error_format_and_security_headers(client):
    r = client.get("/api/dashboard/overview", headers={"X-Request-ID": "trace-123"})
    assert r.status_code == 401
    assert r.json()["error"]["request_id"] == "trace-123"
    assert r.headers["X-Request-ID"] == "trace-123"
    for header in ("X-Content-Type-Options", "X-Frame-Options", "Content-Security-Policy"):
        assert header in r.headers


def test_openapi_docs_available(client):
    spec = client.get("/openapi.json").json()
    assert "/api/auth/login" in spec["paths"] and "/api/dashboard/overview" in spec["paths"]
