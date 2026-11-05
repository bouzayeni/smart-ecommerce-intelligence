"""Run dbt against the warehouse project with credentials loaded from .env.

Everything after the script name is passed to dbt unchanged; project and profiles
directories default to warehouse/dbt.

Usage (from the repo root):
    uv run --group dbt python -m data_engineering.scripts.run_dbt build
    uv run --group dbt python -m data_engineering.scripts.run_dbt build --select marts
    uv run --group dbt python -m data_engineering.scripts.run_dbt docs generate
"""

import os
import sys

from dotenv import load_dotenv

from data_engineering.config import PROJECT_ROOT

DBT_DIR = PROJECT_ROOT / "warehouse" / "dbt"


def run(args: list[str], env: dict[str, str] | None = None) -> bool:
    """Invoke dbt in-process; returns True on success."""
    from dbt.cli.main import dbtRunner  # imported lazily: dbt is an optional dependency group

    load_dotenv(PROJECT_ROOT / ".env", override=False)
    os.environ.update(env or {})
    if args and not any(a.startswith("--project-dir") for a in args):
        args = [*args, "--project-dir", str(DBT_DIR)]
    if args and not any(a.startswith("--profiles-dir") for a in args):
        args = [*args, "--profiles-dir", str(DBT_DIR)]
    return dbtRunner().invoke(args).success


def main(argv: list[str] | None = None) -> int:
    return 0 if run(list(sys.argv[1:] if argv is None else argv)) else 1


if __name__ == "__main__":
    sys.exit(main())
