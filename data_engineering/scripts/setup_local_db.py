"""Create the warehouse database, roles and schemas on a natively installed PostgreSQL.

Equivalent of the Docker init script, for machines without Docker. Idempotent: re-running
keeps existing objects and resyncs role passwords with .env.

Reads POSTGRES_SUPERUSER / POSTGRES_SUPERUSER_PASSWORD and the role credentials from .env.
Secrets are passed to psql through environment variables only.

Usage (from the repo root):
    uv run python -m data_engineering.scripts.setup_local_db [--psql PATH]
"""

import argparse
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

from dotenv import dotenv_values

from data_engineering.config import PROJECT_ROOT

log = logging.getLogger("setup_local_db")

SQL_FILE = PROJECT_ROOT / "infrastructure" / "postgres" / "init_roles_schemas.sql"
REQUIRED_VARS = (
    "POSTGRES_HOST", "POSTGRES_PORT", "POSTGRES_DB",
    "POSTGRES_SUPERUSER", "POSTGRES_SUPERUSER_PASSWORD",
    "ETL_DB_USER", "ETL_DB_PASSWORD",
    "ANALYTICS_DB_USER", "ANALYTICS_DB_PASSWORD",
    "APP_DB_USER", "APP_DB_PASSWORD",
)  # fmt: skip
WINDOWS_DEFAULT_PSQL = Path(r"C:\Program Files\PostgreSQL\16\bin\psql.exe")


def find_psql(explicit: str | None) -> str:
    candidate = explicit or shutil.which("psql")
    if not candidate and WINDOWS_DEFAULT_PSQL.is_file():
        candidate = str(WINDOWS_DEFAULT_PSQL)
    if not candidate:
        raise FileNotFoundError("psql not found; pass --psql PATH")
    return candidate


def load_config() -> dict[str, str]:
    values = {**dotenv_values(PROJECT_ROOT / ".env"), **os.environ}
    missing = [k for k in REQUIRED_VARS if not values.get(k)]
    if missing:
        raise KeyError(f"Missing in .env: {', '.join(missing)}")
    return {k: values[k] for k in REQUIRED_VARS}


def run_psql(
    psql: str, cfg: dict[str, str], database: str, *args: str, sql: str | None = None
) -> str:
    """Run psql as the superuser. SQL given via stdin gets psql :'var' interpolation."""
    env = {**os.environ, **cfg, "PGPASSWORD": cfg["POSTGRES_SUPERUSER_PASSWORD"]}
    cmd = [
        psql, "-X", "-q", "-v", "ON_ERROR_STOP=1",
        "-h", cfg["POSTGRES_HOST"], "-p", cfg["POSTGRES_PORT"],
        "-U", cfg["POSTGRES_SUPERUSER"], "-d", database, *args,
    ]  # fmt: skip
    result = subprocess.run(cmd, env=env, input=sql, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"psql failed ({result.returncode}): {result.stderr.strip()}")
    return result.stdout.strip()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--psql", help="path to psql (default: PATH, then standard install dir)")
    args = parser.parse_args(argv)

    cfg = load_config()
    psql = find_psql(args.psql)
    db = cfg["POSTGRES_DB"]

    db_var = ("-v", f"db={db}")
    exists = run_psql(
        psql, cfg, "postgres", "-tA", *db_var,
        sql="SELECT 1 FROM pg_database WHERE datname = :'db';",
    )  # fmt: skip
    if exists == "1":
        log.info("Database %s already exists", db)
    else:
        run_psql(psql, cfg, "postgres", *db_var, sql='CREATE DATABASE :"db";')
        log.info("Created database %s", db)

    run_psql(psql, cfg, db, "-f", str(SQL_FILE))
    log.info("Applied %s to %s", SQL_FILE.relative_to(PROJECT_ROOT), db)
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        sys.exit(main())
    except (FileNotFoundError, KeyError, RuntimeError) as exc:
        log.error("%s", exc)
        sys.exit(1)
