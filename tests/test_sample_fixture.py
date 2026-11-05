"""Integrity checks on the committed sample fixture in data/sample (used by CI)."""

import pandas as pd
import pytest

from data_engineering.config import PROJECT_ROOT
from data_engineering.sources import SOURCE_FILES, missing_files

SAMPLE_DIR = PROJECT_ROOT / "data" / "sample"

pytestmark = pytest.mark.skipif(
    not (SAMPLE_DIR / "olist_orders_dataset.csv").exists(), reason="sample fixture not generated"
)


@pytest.fixture(scope="module")
def tables() -> dict[str, pd.DataFrame]:
    return {
        s.table: pd.read_csv(SAMPLE_DIR / s.filename, dtype=str, keep_default_na=False)
        for s in SOURCE_FILES
        if (SAMPLE_DIR / s.filename).exists()
    }


def test_all_files_present():
    assert missing_files(SAMPLE_DIR) == ([], [])


@pytest.mark.parametrize(
    ("child", "child_col", "parent", "parent_col"),
    [
        ("orders", "customer_id", "customers", "customer_id"),
        ("order_items", "order_id", "orders", "order_id"),
        ("order_items", "product_id", "products", "product_id"),
        ("order_items", "seller_id", "sellers", "seller_id"),
        ("order_payments", "order_id", "orders", "order_id"),
        ("order_reviews", "order_id", "orders", "order_id"),
    ],
)
def test_foreign_keys_resolve(tables, child, child_col, parent, parent_col):
    orphans = ~tables[child][child_col].isin(set(tables[parent][parent_col]))
    assert not orphans.any(), f"{orphans.sum()} orphan {child}.{child_col}"


def test_sample_keeps_repeat_customers_and_all_statuses(tables):
    merged = tables["orders"].merge(tables["customers"], on="customer_id")
    orders_per_customer = merged.groupby("customer_unique_id")["order_id"].nunique()
    assert (orders_per_customer >= 2).sum() >= 10
    assert tables["orders"]["order_status"].nunique() == 8


def test_sample_is_small(tables):
    assert len(tables["orders"]) < 2_000
