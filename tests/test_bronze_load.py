"""Integration tests for the bronze loader (run with `pytest -m db`).

Each test loads the sample fixture into its own throwaway schema; the real `raw` schema is
never touched.
"""

import shutil
import uuid
from datetime import UTC, datetime

import pandas as pd
import psycopg
import pytest

from data_engineering.business_rules import get_rules
from data_engineering.config import PROJECT_ROOT, get_settings
from data_engineering.etl import bronze
from data_engineering.sources import SOURCE_BY_TABLE, SOURCE_FILES

pytestmark = pytest.mark.db

SAMPLE_DIR = PROJECT_ROOT / "data" / "sample"


@pytest.fixture
def conn():
    try:
        connection = psycopg.connect(**get_settings().psycopg_kwargs("etl"), autocommit=True)
    except psycopg.OperationalError as exc:
        pytest.skip(f"database not reachable: {exc}")
    with connection:
        yield connection


@pytest.fixture
def schema(conn):
    name = f"test_bronze_{uuid.uuid4().hex[:8]}"
    yield name
    conn.execute(f"DROP SCHEMA IF EXISTS {name} CASCADE")


def _load(conn, schema, raw_dir=SAMPLE_DIR, **kw):
    return bronze.run_bronze(
        conn, raw_dir, get_rules(), schema=schema, verify_manifest_hashes=False, **kw
    )


def _count(conn, schema, table) -> int:
    return conn.execute(f"SELECT count(*) FROM {schema}.{table}").fetchone()[0]


def test_loads_every_table_with_exact_values(conn, schema):
    results = _load(conn, schema)
    assert {r.status for r in results} == {"loaded"}
    for spec in SOURCE_FILES:
        expected = pd.read_csv(SAMPLE_DIR / spec.filename, dtype=str, keep_default_na=False)
        rows = conn.execute(
            f"SELECT {', '.join(spec.columns)} FROM {schema}.{spec.table} ORDER BY _source_row"
        ).fetchall()
        actual = pd.DataFrame(rows, columns=list(spec.columns)).fillna("")
        pd.testing.assert_frame_equal(actual, expected, obj=spec.table)


def test_metadata_columns_are_populated(conn, schema):
    _load(conn, schema)
    batches, files, min_row, max_row, n = conn.execute(
        f"SELECT count(DISTINCT _batch_id), count(DISTINCT _source_file), min(_source_row), "
        f"max(_source_row), count(*) FROM {schema}.orders"
    ).fetchone()
    assert (batches, files, min_row, max_row) == (1, 1, 1, n)


def test_second_run_skips_unchanged_files(conn, schema):
    _load(conn, schema)
    results = _load(conn, schema)
    assert {r.status for r in results} == {"skipped"}
    assert _count(conn, schema, "orders") == 504


def test_force_reloads_without_duplicating_rows(conn, schema):
    _load(conn, schema)
    _load(conn, schema, force=True)
    assert _count(conn, schema, "orders") == 504
    assert conn.execute(f"SELECT count(DISTINCT _batch_id) FROM {schema}.orders").fetchone()[0] == 1
    statuses = conn.execute(
        f"SELECT status, count(*) FROM {schema}._ingestion_log GROUP BY 1"
    ).fetchall()
    assert dict(statuses) == {"loaded": 2 * len(SOURCE_FILES)}


def test_changed_file_is_reloaded(conn, schema, tmp_path):
    for f in SAMPLE_DIR.glob("*.csv"):
        shutil.copy(f, tmp_path / f.name)
    _load(conn, schema, raw_dir=tmp_path)
    sellers = tmp_path / SOURCE_BY_TABLE["sellers"].filename
    df = pd.read_csv(sellers, dtype=str, keep_default_na=False)
    df.loc[0, "seller_city"] = df.loc[0, "seller_city"] + " (edited)"  # keeps FKs valid
    df.to_csv(sellers, index=False)
    results = {r.table: r.status for r in _load(conn, schema, raw_dir=tmp_path)}
    assert results["sellers"] == "loaded"
    assert {s for t, s in results.items() if t != "sellers"} == {"skipped"}


def test_quality_gate_failure_writes_nothing(conn, schema, tmp_path):
    for f in SAMPLE_DIR.glob("*.csv"):
        shutil.copy(f, tmp_path / f.name)
    items = tmp_path / SOURCE_BY_TABLE["order_items"].filename
    df = pd.read_csv(items, dtype=str, keep_default_na=False)
    df.loc[0, "product_id"] = "f" * 32  # valid format, but no such product: FK violation
    df.to_csv(items, index=False)
    with pytest.raises(bronze.BronzeError, match="order_items.fk_product_id"):
        _load(conn, schema, raw_dir=tmp_path)
    exists = conn.execute(
        "SELECT count(*) FROM information_schema.schemata WHERE schema_name = %s", (schema,)
    ).fetchone()[0]
    assert exists == 0


def test_failed_copy_keeps_previous_version(conn, schema, tmp_path):
    _load(conn, schema)
    spec = SOURCE_BY_TABLE["sellers"]
    bad = tmp_path / spec.filename
    bad.write_text(",".join(spec.columns) + "\na,b,c,d,too-many-fields\n", encoding="utf-8")
    with pytest.raises(psycopg.Error):
        bronze._load_table(conn, schema, spec, bad, "0" * 64, uuid.uuid4(), datetime.now(UTC))
    assert _count(conn, schema, "sellers") == 299


def test_schema_drift_is_detected(conn, schema):
    _load(conn, schema)
    conn.execute(f"ALTER TABLE {schema}.sellers ADD COLUMN unexpected text")
    with pytest.raises(bronze.BronzeError, match="schema drift"):
        _load(conn, schema, force=True)


def test_manifest_mismatch_is_rejected(tmp_path):
    for f in SAMPLE_DIR.glob("*.csv"):
        shutil.copy(f, tmp_path / f.name)
    (tmp_path / "_manifest.json").write_text(
        '{"files": {"olist_orders_dataset.csv": {"sha256": "' + "0" * 64 + '"}}}'
    )
    with pytest.raises(bronze.BronzeError, match="does not match"):
        bronze.verify_manifest(tmp_path)
