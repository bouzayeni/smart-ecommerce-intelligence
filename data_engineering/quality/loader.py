"""Load raw Olist CSVs into typed DataFrames, recording values that failed to parse."""

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from data_engineering.sources import SOURCE_FILES

# Identifiers and zip prefixes stay strings: zip prefixes have leading zeros ("01037").
ID_COLUMNS = {
    "customer_id", "customer_unique_id", "customer_zip_code_prefix", "order_id", "product_id",
    "seller_id", "seller_zip_code_prefix", "review_id", "geolocation_zip_code_prefix",
}  # fmt: skip
TIMESTAMP_COLUMNS = {
    "orders": [
        "order_purchase_timestamp", "order_approved_at", "order_delivered_carrier_date",
        "order_delivered_customer_date", "order_estimated_delivery_date",
    ],
    "order_items": ["shipping_limit_date"],
    "order_reviews": ["review_creation_date", "review_answer_timestamp"],
}  # fmt: skip
NUMERIC_COLUMNS = {
    "order_items": ["order_item_id", "price", "freight_value"],
    "order_payments": ["payment_sequential", "payment_installments", "payment_value"],
    "order_reviews": ["review_score"],
    "products": [
        "product_name_lenght", "product_description_lenght", "product_photos_qty",
        "product_weight_g", "product_length_cm", "product_height_cm", "product_width_cm",
    ],
    "geolocation": ["geolocation_lat", "geolocation_lng"],
}  # fmt: skip


@dataclass
class RawTables:
    tables: dict[str, pd.DataFrame]
    # (table, column) -> number of non-empty raw values that could not be parsed
    parse_failures: dict[tuple[str, str], int] = field(default_factory=dict)

    def __getitem__(self, table: str) -> pd.DataFrame:
        return self.tables[table]

    def __contains__(self, table: str) -> bool:
        return table in self.tables


def load_raw(directory: Path) -> RawTables:
    """Load every present source file. Missing optional files are simply absent."""
    tables: dict[str, pd.DataFrame] = {}
    failures: dict[tuple[str, str], int] = {}
    for spec in SOURCE_FILES:
        path = directory / spec.filename
        if not path.is_file():
            if spec.required:
                raise FileNotFoundError(f"Required source file missing: {path}")
            continue
        df = pd.read_csv(path, dtype=str, keep_default_na=False, na_values=[""])
        for col in TIMESTAMP_COLUMNS.get(spec.table, []):
            parsed = pd.to_datetime(df[col], errors="coerce", format="ISO8601")
            failures[(spec.table, col)] = int((parsed.isna() & df[col].notna()).sum())
            df[col] = parsed
        for col in NUMERIC_COLUMNS.get(spec.table, []):
            parsed = pd.to_numeric(df[col], errors="coerce")
            failures[(spec.table, col)] = int((parsed.isna() & df[col].notna()).sum())
            df[col] = parsed
        tables[spec.table] = df
    return RawTables(tables, failures)
