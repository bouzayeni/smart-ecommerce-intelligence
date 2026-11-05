"""Build a small, referentially consistent fixture of the raw dataset for tests and CI.

Customers are sampled by customer_unique_id and *all* their orders are kept, so the sample
still contains repeat buyers. Every order status is represented. Values are copied as
untouched strings so the fixture reproduces raw-data quirks (empty fields, duplicates).

Usage (from the repo root):
    uv run python -m data_engineering.scripts.make_sample --customers 400 --seed 42
"""

import argparse
import logging
import sys
from pathlib import Path

import pandas as pd

from data_engineering.config import get_settings
from data_engineering.sources import SOURCE_BY_TABLE

log = logging.getLogger("make_sample")


def read_raw(raw_dir: Path, table: str) -> pd.DataFrame:
    path = raw_dir / SOURCE_BY_TABLE[table].filename
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def build_sample(
    raw_dir: Path, n_customers: int, n_repeat: int, per_status: int, geo_per_zip: int, seed: int
) -> dict[str, pd.DataFrame]:
    customers = read_raw(raw_dir, "customers")
    orders = read_raw(raw_dir, "orders")
    items = read_raw(raw_dir, "order_items")

    orders_c = orders.merge(customers[["customer_id", "customer_unique_id"]], on="customer_id")
    order_counts = orders_c.groupby("customer_unique_id")["order_id"].nunique()

    repeat_ids = (
        order_counts[order_counts >= 2]
        .sample(n=min(n_repeat, int((order_counts >= 2).sum())), random_state=seed)
        .index
    )
    status_ids = orders_c.groupby("order_status", group_keys=False).apply(
        lambda g: g.sample(n=min(per_status, len(g)), random_state=seed)
    )["customer_unique_id"]
    remaining = order_counts.index.difference(repeat_ids.union(pd.Index(status_ids)))
    random_ids = pd.Series(remaining).sample(
        n=max(0, n_customers - len(repeat_ids)), random_state=seed
    )
    chosen = set(repeat_ids) | set(status_ids) | set(random_ids)

    s_orders = orders_c[orders_c["customer_unique_id"].isin(chosen)]
    order_ids = set(s_orders["order_id"])
    s_items = items[items["order_id"].isin(order_ids)]

    out = {
        "orders": orders[orders["order_id"].isin(order_ids)],
        "customers": customers[customers["customer_id"].isin(set(s_orders["customer_id"]))],
        "order_items": s_items,
        "products": read_raw(raw_dir, "products").pipe(
            lambda d: d[d["product_id"].isin(set(s_items["product_id"]))]
        ),
        "sellers": read_raw(raw_dir, "sellers").pipe(
            lambda d: d[d["seller_id"].isin(set(s_items["seller_id"]))]
        ),
    }
    for table in ("order_payments", "order_reviews"):
        df = read_raw(raw_dir, table)
        out[table] = df[df["order_id"].isin(order_ids)]

    optional = {"geolocation", "category_translation"}
    for table in optional:
        if not (raw_dir / SOURCE_BY_TABLE[table].filename).is_file():
            log.warning("Skipping optional table %s (file missing)", table)
            continue
        df = read_raw(raw_dir, table)
        if table == "geolocation":
            zips = set(out["customers"]["customer_zip_code_prefix"]) | set(
                out["sellers"]["seller_zip_code_prefix"]
            )
            df = (
                df[df["geolocation_zip_code_prefix"].isin(zips)]
                .groupby("geolocation_zip_code_prefix", group_keys=False)
                .head(geo_per_zip)
            )
        out[table] = df
    return out


def main(argv: list[str] | None = None) -> int:
    settings = get_settings()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--raw-dir", type=Path, default=settings.raw_dir)
    parser.add_argument("--out-dir", type=Path, default=settings.sample_dir)
    parser.add_argument("--customers", type=int, default=400)
    parser.add_argument("--repeat-customers", type=int, default=60)
    parser.add_argument("--per-status", type=int, default=3)
    parser.add_argument("--geo-per-zip", type=int, default=3)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args(argv)

    tables = build_sample(
        args.raw_dir,
        args.customers,
        args.repeat_customers,
        args.per_status,
        args.geo_per_zip,
        args.seed,
    )
    args.out_dir.mkdir(parents=True, exist_ok=True)
    for table, df in tables.items():
        path = args.out_dir / SOURCE_BY_TABLE[table].filename
        df.to_csv(path, index=False, lineterminator="\n")
        log.info("%-22s %6d rows -> %s", table, len(df), path.name)
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sys.exit(main())
