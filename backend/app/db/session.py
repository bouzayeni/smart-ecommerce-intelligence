"""Two engines with different privileges:

read_engine  analytics_ro: SELECT on marts/ml, read-only transactions, 15 s statement timeout
app_engine   app_user:     read/write on the app schema (users, tokens, audit, predictions)
"""

from collections.abc import Iterator
from functools import lru_cache

import sqlalchemy as sa
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings


@lru_cache
def read_engine() -> sa.Engine:
    return sa.create_engine(
        get_settings().read_database_url, pool_pre_ping=True, pool_size=5, max_overflow=5
    )


@lru_cache
def app_engine() -> sa.Engine:
    s = get_settings()
    return sa.create_engine(
        s.app_database_url,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
        # Unqualified ORM table names resolve to the configured app schema (tests isolate it).
        connect_args={"options": f"-c search_path={s.app_schema}"},
    )


@lru_cache
def _session_factory() -> sessionmaker:
    return sessionmaker(bind=app_engine(), expire_on_commit=False)


def get_app_session() -> Iterator[Session]:
    session = _session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_read_connection() -> Iterator[sa.Connection]:
    with read_engine().connect() as conn:
        yield conn
