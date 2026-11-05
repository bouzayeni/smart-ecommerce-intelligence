"""Specification of the Olist source files the pipeline expects."""

from dataclasses import dataclass
from pathlib import Path

KAGGLE_DATASET = "olistbr/brazilian-ecommerce"
KAGGLE_DOWNLOAD_URL = f"https://www.kaggle.com/api/v1/datasets/download/{KAGGLE_DATASET}"


@dataclass(frozen=True)
class SourceFile:
    table: str
    filename: str
    # Optional files degrade features (maps, English category names) but don't block the pipeline.
    required: bool = True


SOURCE_FILES: tuple[SourceFile, ...] = (
    SourceFile("customers", "olist_customers_dataset.csv"),
    SourceFile("orders", "olist_orders_dataset.csv"),
    SourceFile("order_items", "olist_order_items_dataset.csv"),
    SourceFile("order_payments", "olist_order_payments_dataset.csv"),
    SourceFile("order_reviews", "olist_order_reviews_dataset.csv"),
    SourceFile("products", "olist_products_dataset.csv"),
    SourceFile("sellers", "olist_sellers_dataset.csv"),
    SourceFile("geolocation", "olist_geolocation_dataset.csv", required=False),
    SourceFile("category_translation", "product_category_name_translation.csv", required=False),
)

SOURCE_BY_TABLE = {s.table: s for s in SOURCE_FILES}


def missing_files(directory: Path) -> tuple[list[str], list[str]]:
    """Return (missing required filenames, missing optional filenames) in a directory."""
    missing = [s for s in SOURCE_FILES if not (directory / s.filename).is_file()]
    return (
        [s.filename for s in missing if s.required],
        [s.filename for s in missing if not s.required],
    )
