"""Load the raw Olist CSVs into the bronze (raw) schema.

Usage (from the repo root):
    uv run python -m data_engineering.etl.load_bronze              # load changed files
    uv run python -m data_engineering.etl.load_bronze --force      # reload everything
    uv run python -m data_engineering.etl.load_bronze --print-ddl  # print bronze DDL

Exit codes: 0 success, 1 a gate failed (nothing written), 2 one or more tables failed to load.
"""

import argparse
import logging
import sys
from pathlib import Path

import psycopg

from data_engineering.business_rules import get_rules
from data_engineering.config import get_settings
from data_engineering.etl.bronze import BronzeError, render_ddl, run_bronze
from data_engineering.validation.contracts import ContractError

log = logging.getLogger("load_bronze")


def main(argv: list[str] | None = None) -> int:
    settings = get_settings()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--raw-dir", type=Path, default=settings.raw_dir)
    parser.add_argument("--schema", default="raw")
    parser.add_argument("--force", action="store_true", help="reload even if file is unchanged")
    parser.add_argument(
        "--no-manifest", action="store_true",
        help="skip manifest hash verification (for fixtures without a manifest)",
    )  # fmt: skip
    parser.add_argument("--print-ddl", action="store_true", help="print DDL and exit")
    args = parser.parse_args(argv)

    if args.print_ddl:
        sys.stdout.write(render_ddl(args.schema))
        return 0

    try:
        with psycopg.connect(**settings.psycopg_kwargs("etl"), autocommit=True) as conn:
            results = run_bronze(
                conn, args.raw_dir.resolve(), get_rules(), schema=args.schema,
                force=args.force, verify_manifest_hashes=not args.no_manifest,
            )  # fmt: skip
    except (BronzeError, ContractError) as exc:
        log.error("%s", exc)
        log.error("Nothing was written.")
        return 1

    loaded = sum(r.status == "loaded" for r in results)
    skipped = sum(r.status == "skipped" for r in results)
    failed = [r.table for r in results if r.status == "failed"]
    log.info("Done: %d loaded, %d skipped, %d failed", loaded, skipped, len(failed))
    return 2 if failed else 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sys.exit(main())
