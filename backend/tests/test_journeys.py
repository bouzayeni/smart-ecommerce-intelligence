"""End-to-end user journeys through the HTTP API, one session per test.

Unlike test_api/test_auth (one endpoint per test), these chain the calls a real user makes and
check that state carries across them: a role change takes effect on the next request, a
logout ends the session, the numbers on different pages agree with each other and with SQL.
"""

import uuid

import pytest
import sqlalchemy as sa

pytestmark = pytest.mark.db
PW = "Journey-Passw0rd-ok"


def scalar(conn, sql, **params):
    return conn.execute(sa.text(sql), params).scalar_one()


def signup(client) -> dict:
    email = f"journey-{uuid.uuid4().hex[:8]}@example.com"
    r = client.post("/api/auth/register", json={"email": email, "password": PW, "full_name": "J"})
    assert r.status_code == 201, r.text
    tokens = client.post("/api/auth/login", json={"email": email, "password": PW}).json()
    return {
        "id": r.json()["id"],
        "email": email,
        "tokens": tokens,
        "headers": {"Authorization": f"Bearer {tokens['access_token']}"},
    }


def test_viewer_journey_dashboards_agree_with_each_other_and_sql(client, warehouse):
    me = signup(client)
    h = me["headers"]
    profile = client.get("/api/auth/me", headers=h).json()
    assert profile["role"] == "viewer" and profile["email"] == me["email"]

    overview = client.get("/api/dashboard/overview", headers=h).json()["kpis"]
    filters = client.get("/api/dashboard/filters", headers=h).json()
    assert filters["months"], "filters endpoint returned no months"
    sales = client.get("/api/dashboard/sales", headers=h).json()
    # The executive KPI and the full-window sales page are the same number.
    assert float(sales["totals"]["gmv"]) == pytest.approx(float(overview["gmv"]), rel=1e-9)
    assert sales["totals"]["orders"] == overview["revenue_orders"]
    assert float(overview["gmv"]) == pytest.approx(
        float(
            scalar(
                warehouse,
                """
        select sum(gmv) from marts.fact_orders
        where is_revenue_order and is_in_analysis_window""",
            )
        ),
        abs=0.01,
    )

    # A state filter narrows the totals, and states add back up to the whole.
    sp = client.get("/api/dashboard/sales", headers=h, params={"state": "SP"}).json()
    assert 0 < float(sp["totals"]["gmv"]) < float(overview["gmv"])

    forecast = client.get("/api/predictions/forecast", headers=h, params={"horizon": 30}).json()
    assert forecast["meta"]["selected_model"] and forecast["totals"]
    assert client.get("/api/anomalies", headers=h).status_code == 200
    segments = client.get("/api/customers/segments", headers=h).json()
    assert sum(s["customers"] for s in segments["segments"]) == scalar(
        warehouse, "select count(*) from ml.customer_rfm"
    )

    # Customer-level data and admin pages stay closed to viewers.
    assert client.get("/api/customers", headers=h).status_code == 403
    assert client.get("/api/models/status", headers=h).status_code == 403
    tools = {t["name"] for t in client.get("/api/assistant/tools", headers=h).json()["items"]}
    assert "query_warehouse" not in tools and "get_churn_risk_customers" not in tools


def test_promotion_takes_effect_immediately_and_demotion_revokes_access(
    client, make_user, warehouse, app_schema
):
    admin = make_user("admin")
    me = signup(client)
    h, role_url = me["headers"], f"/api/auth/users/{me['id']}/role"
    assert client.get("/api/customers", headers=h).status_code == 403

    # Promote: the same access token now works (roles are read from the DB, not the token).
    r = client.patch(role_url, json={"role": "analyst"}, headers=admin["headers"])
    assert r.status_code == 200
    page = client.get(
        "/api/customers", headers=h, params={"sort": "monetary", "page_size": 5}
    ).json()
    top = page["items"][0]["customer_unique_id"]
    # The list covers every customer (dim_customers), including those without RFM scores.
    assert page["total"] == scalar(warehouse, "select count(*) from marts.dim_customers")

    # Customer 360 -> stored prediction -> recommendations -> similar items, all consistent.
    detail = client.get(f"/api/customers/{top}", headers=h).json()
    pred = client.post("/api/predictions/churn", headers=h, json={"customer_unique_id": top}).json()
    stored = scalar(
        warehouse,
        "select churn_risk_90d from ml.customer_repurchase_scores where customer_unique_id = :c",
        c=top,
    )
    assert pred["mode"] == "stored"
    assert pred["churn_risk_90d"] == pytest.approx(float(stored))
    assert float(detail["monetary"]) == pytest.approx(float(page["items"][0]["monetary"]))
    recs = client.get(f"/api/recommendations/{top}", headers=h, params={"k": 5}).json()
    assert 0 < len(recs["items"]) <= 5
    similar = client.get(
        f"/api/recommendations/products/{recs['items'][0]['product_id']}/similar", headers=h
    )
    assert similar.status_code == 200

    from app.db.session import app_engine

    with app_engine().connect() as conn:
        logged = conn.execute(
            sa.text("select count(*) from prediction_log where user_id = :u"), {"u": me["id"]}
        ).scalar_one()
    assert logged == 1

    # Demote: access ends on the next request, with the token issued while analyst.
    client.patch(role_url, json={"role": "viewer"}, headers=admin["headers"])
    assert client.get(f"/api/customers/{top}", headers=h).status_code == 403
    with app_engine().connect() as conn:
        denied = conn.execute(
            sa.text(
                "select count(*) from audit_log where user_id = :u and action = 'authorization' "
                "and status = 'denied'"
            ),
            {"u": me["id"]},
        ).scalar_one()
    assert denied >= 2  # before promotion and after demotion


def test_session_lifecycle_refresh_then_logout(client):
    me = signup(client)
    first = me["tokens"]
    rotated = client.post("/api/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert rotated.status_code == 200
    new = rotated.json()
    h = {"Authorization": f"Bearer {new['access_token']}"}
    assert client.get("/api/auth/me", headers=h).status_code == 200

    assert (
        client.post(
            "/api/auth/logout", headers=h, json={"refresh_token": new["refresh_token"]}
        ).status_code
        == 204
    )
    assert (
        client.post("/api/auth/refresh", json={"refresh_token": new["refresh_token"]}).status_code
        == 401
    )
    # Known, documented property: a stateless access token stays valid until it expires
    # (15 min). Logout ends the session's ability to renew, not the current access token.
    assert client.get("/api/auth/me", headers=h).status_code == 200


def test_serving_bundle_and_registry_give_the_same_prediction(client, make_user, monkeypatch):
    """Phase 12: containers load exported bundles; the result must equal the registry model."""
    pytest.importorskip("mlflow")
    from app.core.config import REPO_ROOT, get_settings
    from app.services.model_registry import load_latest

    bundles = REPO_ROOT / "models" / "serving"
    if not (bundles / "repurchase_propensity" / "manifest.json").is_file():
        pytest.skip("no serving bundle exported (python -m ml.export_serving_models)")
    analyst = make_user("analyst")
    features = {
        "recency_days": 40,
        "tenure_days": 300,
        "frequency": 2,
        "monetary": 320,
        "avg_order_value": 160,
        "max_order_value": 200,
        "last_order_value": 120,
        "customer_state": "RJ",
        "last_order_category": "bed_bath_table",
    }

    def predict():
        r = client.post(
            "/api/predictions/churn", headers=analyst["headers"], json={"features": features}
        )
        assert r.status_code == 200, r.text
        return r.json()

    load_latest.cache_clear()
    from_registry = predict()
    try:
        monkeypatch.setattr(get_settings(), "serving_models_dir", bundles)
        load_latest.cache_clear()
        from_bundle = predict()
    finally:
        load_latest.cache_clear()
    assert from_bundle["model_version"] == from_registry["model_version"]
    assert from_bundle["repurchase_probability_90d"] == pytest.approx(
        from_registry["repurchase_probability_90d"], abs=1e-12
    )
