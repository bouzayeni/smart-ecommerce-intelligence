"""Smoke-check the PostgreSQL setup: connectivity, schemas, and read-only enforcement.

Usage (from the repo root, after `docker compose up -d postgres`):
    uv run python -m data_engineering.scripts.check_db
"""

import logging
import sys

from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from data_engineering.config import get_settings

log = logging.getLogger("check_db")

EXPECTED_SCHEMAS = {"raw", "staging", "intermediate", "marts", "ml", "app"}


def main() -> int:
    settings = get_settings()
    ok = True

    etl = create_engine(settings.database_url("etl"))
    with etl.connect() as conn:
        version = conn.execute(text("SHOW server_version")).scalar_one()
        schemas = set(
            conn.execute(text("SELECT schema_name FROM information_schema.schemata")).scalars()
        )
    log.info("Connected as %s, PostgreSQL %s", settings.etl_db_user, version)
    missing = EXPECTED_SCHEMAS - schemas
    if missing:
        log.error("Missing schemas: %s", sorted(missing))
        ok = False
    else:
        log.info("All schemas present: %s", sorted(EXPECTED_SCHEMAS))

    analytics = create_engine(settings.database_url("analytics"))
    with analytics.connect() as conn:
        read_only = conn.execute(text("SHOW default_transaction_read_only")).scalar_one()
        timeout = conn.execute(text("SHOW statement_timeout")).scalar_one()
        log.info("Analytics role: read_only=%s statement_timeout=%s", read_only, timeout)
        try:
            conn.execute(text("CREATE TABLE marts._write_probe (id int)"))
            log.error("Analytics role was able to create a table: read-only NOT enforced")
            ok = False
        except DBAPIError:
            log.info("Analytics role write attempt rejected, as expected")
        conn.rollback()

    return 0 if ok else 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sys.exit(main())
