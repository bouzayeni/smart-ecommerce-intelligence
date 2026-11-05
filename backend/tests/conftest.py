"""Backend test fixtures.

Auth/audit data goes to an isolated schema (test_app_<hex>) created by the ETL role and
migrated with Alembic as app_user; it is dropped at the end. Analytics reads use the real
marts/ml schemas (read-only role), so expected values are checked against SQL directly.
"""

import os
import uuid
from pathlib import Path

import psycopg
import pytest

from data_engineering.config import get_settings as de_settings

pytestmark = pytest.mark.db
BACKEND = Path(__file__).resolve().parents[1]


def _clear_caches():
    from app.core.config import get_settings
    from app.db import session
    from app.services.model_registry import load_latest

    get_settings.cache_clear()
    for fn in (session.read_engine, session.app_engine, session._session_factory, load_latest):
        fn.cache_clear()


@pytest.fixture(scope="session")
def app_schema():
    try:
        etl = psycopg.connect(**de_settings().psycopg_kwargs("etl"), autocommit=True)
    except psycopg.OperationalError as exc:
        pytest.skip(f"database not reachable: {exc}")
    from app.core.config import get_settings

    schema = f"test_app_{uuid.uuid4().hex[:8]}"
    app_user = get_settings().app_db_user
    etl.execute(f'CREATE SCHEMA "{schema}"')
    etl.execute(f'GRANT USAGE, CREATE ON SCHEMA "{schema}" TO "{app_user}"')
    previous = os.environ.get("APP_SCHEMA")
    os.environ["APP_SCHEMA"] = schema
    _clear_caches()
    from alembic import command
    from alembic.config import Config

    command.upgrade(Config(str(BACKEND / "alembic.ini")), "head")
    try:
        yield schema
    finally:
        if previous is None:
            os.environ.pop("APP_SCHEMA", None)
        else:
            os.environ["APP_SCHEMA"] = previous
        _clear_caches()
        etl.execute(f'DROP SCHEMA "{schema}" CASCADE')
        etl.close()


@pytest.fixture(scope="session")
def app(app_schema):
    from app.main import create_app

    return create_app()


@pytest.fixture
def client(app):
    from fastapi.testclient import TestClient

    from app.core.rate_limit import limiter

    limiter.reset()  # rate-limit counters are per process; isolate tests from each other
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture(scope="session")
def make_user(app_schema):
    """Create a user directly and return (user_id, password, auth headers)."""
    from sqlalchemy.orm import Session

    from app.core.security import create_access_token, hash_password
    from app.db.session import app_engine
    from app.models.entities import User

    def _make(role: str = "viewer", password: str = "Correct-Horse-9-battery"):
        with Session(app_engine()) as s, s.begin():
            user = User(
                email=f"{role}-{uuid.uuid4().hex[:8]}@example.com",
                full_name=role,
                password_hash=hash_password(password),
                role=role,
            )
            s.add(user)
            s.flush()
            uid, email = user.id, user.email
        token, _ = create_access_token(uid, role)
        return {
            "id": uid,
            "email": email,
            "password": password,
            "headers": {"Authorization": f"Bearer {token}"},
        }

    return _make


@pytest.fixture(scope="session")
def warehouse(app_schema):
    """Read-only connection for computing expected values independently of the API."""
    from app.db.session import read_engine

    with read_engine().connect() as conn:
        yield conn
