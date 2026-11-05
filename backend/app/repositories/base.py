"""Query helpers. All values are bound parameters; identifiers (sort columns, filters) come
only from fixed allowlists in the repositories, never from request strings."""

import datetime as dt
import math
from decimal import Decimal

import sqlalchemy as sa


def _clean(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


def rows(conn: sa.Connection, sql: str, **params) -> list[dict]:
    result = conn.execute(sa.text(sql), params)
    return [{k: _clean(v) for k, v in r._mapping.items()} for r in result]


def one(conn: sa.Connection, sql: str, **params) -> dict | None:
    found = rows(conn, sql, **params)
    return found[0] if found else None


def month_bounds(
    date_from: str | None, date_to: str | None
) -> tuple[dt.date | None, dt.date | None]:
    """'YYYY-MM' -> (first day of from-month, first day after to-month)."""
    start = dt.date.fromisoformat(f"{date_from}-01") if date_from else None
    end = None
    if date_to:
        y, m = map(int, date_to.split("-"))
        end = dt.date(y + (m == 12), m % 12 + 1, 1)
    return start, end
