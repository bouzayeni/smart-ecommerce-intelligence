"""End-to-end: bronze-load the sample fixture, run `dbt build` on it in isolated schemas, and
check the marts against the independent Python implementation from Phase 2.

Run with: uv run --group dbt pytest -m db tests/test_dbt_build.py
"""

import uuid

import psycopg
import pytest

from data_engineering.business_rules import get_rules
from data_engineering.config import PROJECT_ROOT, get_settings
from data_engineering.etl.bronze import run_bronze
from data_engineering.quality import analysis as a
from data_engineering.quality.loader import load_raw

pytestmark = pytest.mark.db
pytest.importorskip("dbt.cli.main", reason="dbt dependency group not installed")

from data_engineering.scripts import run_dbt  # noqa: E402

SAMPLE_DIR = PROJECT_ROOT / "data" / "sample"


@pytest.fixture(scope="module")
def warehouse():
    """Yield (connection, schema prefix) for a sample warehouse built by dbt."""
    settings = get_settings()
    try:
        conn = psycopg.connect(**settings.psycopg_kwargs("etl"), autocommit=True)
    except psycopg.OperationalError as exc:
        pytest.skip(f"database not reachable: {exc}")
    prefix = f"test_{uuid.uuid4().hex[:8]}"
    try:
        run_bronze(conn, SAMPLE_DIR, get_rules(), schema=f"{prefix}_raw",
                   verify_manifest_hashes=False)  # fmt: skip
        ok = run_dbt.run(
            ["build", "--target", "test", "--vars", f"{{raw_schema: {prefix}_raw}}"],
            env={"DBT_SCHEMA_PREFIX": prefix},
        )
        assert ok, "dbt build failed on the sample fixture (see dbt output above)"
        yield conn, prefix
    finally:
        schemas = [r[0] for r in conn.execute(
            "SELECT nspname FROM pg_namespace WHERE nspname LIKE %s", (f"{prefix}\\_%",)
        )]  # fmt: skip
        for schema in schemas:
            conn.execute(f'DROP SCHEMA "{schema}" CASCADE')
        conn.close()


@pytest.fixture(scope="module")
def sample_raw():
    return load_raw(SAMPLE_DIR)


def test_marts_built_in_isolated_schema(warehouse):
    conn, prefix = warehouse
    n = conn.execute(f"SELECT count(*) FROM {prefix}_marts.fact_orders").fetchone()[0]
    assert n == 504
    assert conn.execute(
        "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'marts' "
        "AND table_name = 'fact_orders'"
    ).fetchone()[0] in (0, 1)  # dev marts untouched (may or may not exist)


def test_gmv_by_status_matches_python(warehouse, sample_raw):
    conn, prefix = warehouse
    expected = a.status_summary(sample_raw, get_rules())["gmv"].round(2).to_dict()
    actual = dict(conn.execute(
        f"SELECT order_status, sum(gmv) FROM {prefix}_marts.fact_orders GROUP BY 1"
    ).fetchall())  # fmt: skip
    assert {k: float(v) for k, v in actual.items()} == pytest.approx(expected, abs=0.005)


def test_payment_and_item_totals_match_python(warehouse, sample_raw):
    conn, prefix = warehouse
    rc = a.payment_reconciliation(sample_raw, 0.01)
    pay = conn.execute(f"SELECT sum(payment_value) FROM {prefix}_marts.fact_payments").fetchone()
    items = conn.execute(f"SELECT sum(gmv) FROM {prefix}_marts.fact_order_items").fetchone()
    assert float(pay[0]) == pytest.approx(rc["total_payments"], abs=0.005)
    assert float(items[0]) == pytest.approx(rc["total_items_value"], abs=0.005)


def test_late_flag_matches_python(warehouse, sample_raw):
    conn, prefix = warehouse
    expected = a.delivery_frame(sample_raw, get_rules()).set_index("order_id")["is_late"]
    actual = dict(conn.execute(
        f"SELECT order_id, is_late FROM {prefix}_marts.fact_orders "
        "WHERE order_status = 'delivered' AND delivered_to_customer_at IS NOT NULL "
        "AND NOT is_carrier_before_purchase AND NOT is_delivery_before_carrier"
    ).fetchall())  # fmt: skip
    assert actual == expected.to_dict()


def test_selected_review_matches_python(warehouse, sample_raw):
    conn, prefix = warehouse
    expected = a.per_order_review(sample_raw["order_reviews"], "latest_answer")
    actual = dict(conn.execute(
        f"SELECT order_id, review_score FROM {prefix}_marts.fact_orders "
        "WHERE review_score IS NOT NULL"
    ).fetchall())  # fmt: skip
    assert actual == expected.set_index("order_id")["review_score"].to_dict()


def test_analytics_reader_can_select_marts(warehouse):
    conn, prefix = warehouse
    granted = conn.execute(
        "SELECT has_table_privilege('analytics_reader', %s, 'SELECT')",
        (f"{prefix}_marts.fact_orders",),
    ).fetchone()[0]
    assert granted is True
