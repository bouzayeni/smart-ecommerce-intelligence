"""Integration checks against the local warehouse database (run with `pytest -m db`)."""

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError, OperationalError

from data_engineering.config import get_settings
from data_engineering.scripts import check_db

pytestmark = pytest.mark.db


@pytest.fixture(scope="module")
def analytics_engine():
    engine = create_engine(get_settings().database_url("analytics"))
    try:
        with engine.connect():
            pass
    except OperationalError as exc:
        pytest.skip(f"database not reachable: {exc.orig}")
    return engine


def test_check_db_passes(analytics_engine):
    assert check_db.main() == 0


@pytest.mark.parametrize("schema", ["raw", "staging", "intermediate", "app"])
def test_analytics_role_cannot_read_non_curated_schemas(analytics_engine, schema):
    with analytics_engine.connect() as conn:
        allowed = conn.execute(
            text("SELECT has_schema_privilege(current_user, :s, 'USAGE')"), {"s": schema}
        ).scalar_one()
    assert allowed is False


def test_analytics_role_cannot_create_in_public(analytics_engine):
    with analytics_engine.connect() as conn, pytest.raises(DBAPIError):
        conn.execute(text("CREATE TABLE public._write_probe (id int)"))
