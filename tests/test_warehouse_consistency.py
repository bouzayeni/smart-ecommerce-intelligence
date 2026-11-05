"""Integration: the loaded warehouse is consistent across layers (raw -> marts -> ml -> serving).

These run against the real, fully built warehouse (not the sample fixture) and catch a layer
that was rebuilt without the others, e.g. dbt re-run on new raw data but ML not re-scored, or
a model promoted without re-scoring the batch tables.

Run with: uv run --all-groups pytest -m db tests/test_warehouse_consistency.py
"""

import contextlib
import json

import psycopg
import pytest

from data_engineering.config import PROJECT_ROOT, get_settings

pytestmark = pytest.mark.db
ANALYSIS_END = "2018-08-21"


@pytest.fixture(scope="module")
def db():
    try:
        conn = psycopg.connect(**get_settings().psycopg_kwargs("etl"))
    except psycopg.OperationalError as exc:
        pytest.skip(f"database not reachable: {exc}")
    if not conn.execute("select to_regclass('ml.customer_rfm')").fetchone()[0]:
        pytest.skip("warehouse not built (run ETL, dbt and the ML scripts first)")
    yield conn
    conn.close()


def one(conn, sql: str):
    return conn.execute(sql).fetchone()


# ------------------------------------------------------------------ raw -> marts
def test_every_raw_order_is_in_fact_orders_once(db):
    raw, fact, distinct = one(
        db,
        """
        select (select count(*) from raw.orders), (select count(*) from marts.fact_orders),
               (select count(distinct order_id) from marts.fact_orders)""",
    )
    assert raw == fact == distinct


def test_item_rows_and_order_totals_reconcile_with_raw(db):
    assert one(
        db,
        "select (select count(*) from raw.order_items) = "
        "(select count(*) from marts.fact_order_items)",
    )[0]
    mismatched = one(
        db,
        """
        with r as (
            select order_id, sum(price::numeric) price, sum(freight_value::numeric) freight
            from raw.order_items group by 1)
        select count(*) from marts.fact_orders f join r using (order_id)
        where abs(f.price_total - r.price) > 0.005 or abs(f.freight_total - r.freight) > 0.005
        """,
    )[0]
    assert mismatched == 0


def test_kpi_overview_equals_fact_orders(db):
    kpi_gmv, kpi_orders, fact_gmv, fact_orders = one(
        db,
        """
        select k.gmv, k.revenue_orders, f.gmv, f.n from marts.kpi_overview k,
          (select sum(gmv) gmv, count(*) n from marts.fact_orders
           where is_revenue_order and is_in_analysis_window) f""",
    )
    assert kpi_orders == fact_orders
    assert float(kpi_gmv) == pytest.approx(float(fact_gmv), abs=0.01)


def test_daily_aggregate_sums_to_fact_orders(db):
    agg, fact = one(
        db,
        """
        select (select sum(gmv) from marts.agg_daily_sales),
               (select sum(gmv) from marts.fact_orders where is_revenue_order)""",
    )
    # agg_daily_sales may cover all dates or only the window; it must equal one of the two.
    window = one(
        db,
        "select sum(gmv) from marts.fact_orders where is_revenue_order and is_in_analysis_window",
    )[0]
    assert float(agg) in (
        pytest.approx(float(fact), abs=0.05),
        pytest.approx(float(window), abs=0.05),
    )


# ------------------------------------------------------------------ marts -> ml
def test_rfm_covers_exactly_the_revenue_customers_of_the_window(db):
    missing, extra = one(
        db,
        """
        with c as (select distinct customer_unique_id from marts.fact_orders
                   where is_revenue_order and is_in_analysis_window)
        select (select count(*) from c left join ml.customer_rfm r using (customer_unique_id)
                where r.customer_unique_id is null),
               (select count(*) from ml.customer_rfm r left join c using (customer_unique_id)
                where c.customer_unique_id is null)""",
    )
    assert (missing, extra) == (0, 0)


def test_rfm_frequency_and_monetary_match_fact_orders(db):
    bad = one(
        db,
        """
        with f as (select customer_unique_id, count(*) n, sum(gmv) gmv from marts.fact_orders
                   where is_revenue_order and is_in_analysis_window group by 1)
        select count(*) from ml.customer_rfm r join f using (customer_unique_id)
        where r.frequency <> f.n or abs(r.monetary - f.gmv) > 0.01""",
    )[0]
    assert bad == 0


def test_scores_cover_every_rfm_customer(db):
    rfm, rep, spend = one(
        db,
        """
        select (select count(*) from ml.customer_rfm),
               (select count(*) from ml.customer_repurchase_scores s join ml.customer_rfm
                using (customer_unique_id)),
               (select count(*) from ml.customer_spend_predictions s join ml.customer_rfm
                using (customer_unique_id))""",
    )
    assert rfm == rep == spend


def test_scores_are_probabilities_and_bands_follow_deciles(db):
    bad_prob, bad_band = one(
        db,
        """
        select count(*) filter (where repurchase_probability_90d not between 0 and 1
                                or abs(churn_risk_90d - (1 - repurchase_probability_90d)) > 1e-9),
               count(*) filter (where (propensity_decile <= 5) <> (churn_risk_band = 'high'))
        from ml.customer_repurchase_scores""",
    )
    assert bad_prob == 0
    # Bands: high = deciles 1-5 (lowest propensity) per the model card.
    assert bad_band == 0


def test_forecast_starts_after_data_and_has_one_selected_model(db):
    rows = db.execute("""
        select model, count(*), min(horizon_day), max(horizon_day),
               min(forecast_date)::date - max(series_end), bool_or(is_selected)
        from ml.sales_forecast group by 1""").fetchall()
    assert rows and sum(r[5] for r in rows) == 1
    for model, n, lo, hi, gap, _ in rows:
        assert (lo, hi, n) == (1, 90, 90), model
        assert gap == 1, f"{model} forecast does not start the day after the series ends"


def test_recommendations_reference_known_products(db):
    orphans = one(
        db,
        """
        select count(*) from ml.product_recommendations r
        left join marts.dim_products p using (product_id) where p.product_id is null""",
    )[0]
    assert orphans == 0


# ------------------------------------------------------------------ ml -> serving
def _registry_champions() -> dict[str, str]:
    pytest.importorskip("mlflow")
    from mlflow.exceptions import MlflowException
    from mlflow.tracking import MlflowClient

    from ml.promote_model import ALIAS, GATES
    from ml.tracking import tracking_uri

    client = MlflowClient(tracking_uri=tracking_uri())
    out = {}
    for name in GATES:
        with contextlib.suppress(MlflowException):
            out[name] = str(client.get_model_version_by_alias(name, ALIAS).version)
    return out


def test_batch_scores_come_from_the_champion_model(db):
    champions = _registry_champions()
    if not champions:
        pytest.skip("no champion aliases in the registry")
    for name, table in [
        ("repurchase_propensity", "ml.customer_repurchase_scores"),
        ("customer_spend_90d", "ml.customer_spend_predictions"),
    ]:
        versions = {
            str(v)
            for (v,) in db.execute(
                f"select distinct model_version from {table} where model_name = %s", (name,)
            )
        }
        assert versions == {champions[name]}, (
            f"{table} was scored by v{versions} but the champion is v{champions[name]}: "
            "re-score after promoting (docs/deployment.md)"
        )


def test_serving_bundles_match_the_champion():
    bundles = PROJECT_ROOT / "models" / "serving"
    if not bundles.is_dir():
        pytest.skip("no serving bundles exported")
    champions = _registry_champions()
    for name, version in champions.items():
        manifest = bundles / name / "manifest.json"
        assert manifest.is_file(), f"missing bundle for {name}: run ml.export_serving_models"
        assert json.loads(manifest.read_text(encoding="utf-8"))["version"] == version
