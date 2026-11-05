"""Pandera file contracts: the structure each raw CSV must have before it is ingested.

Scope: structure and identifier formats of each file on its own. Relational and business
checks (foreign keys, timestamp ordering, reconciliation) live in data_engineering/quality.
Values are validated as raw strings, exactly as they will be stored in bronze.
"""

import csv
from pathlib import Path

import pandas as pd
import pandera.pandas as pa

from data_engineering.sources import SourceFile

HEX32 = r"[0-9a-f]{32}"  # Olist hashed identifiers
ZIP5 = r"\d{5}"
UF = r"[A-Z]{2}"  # Brazilian state code
TIMESTAMP = r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}"
INTEGER = r"-?\d+"
DECIMAL = r"-?\d+(\.\d+)?"

# column -> (regex, nullable). Columns not listed are free text and nullable.
COLUMN_RULES: dict[str, tuple[str, bool]] = {
    "customer_id": (HEX32, False),
    "customer_unique_id": (HEX32, False),
    "order_id": (HEX32, False),
    "product_id": (HEX32, False),
    "seller_id": (HEX32, False),
    "review_id": (HEX32, False),
    "customer_zip_code_prefix": (ZIP5, False),
    "seller_zip_code_prefix": (ZIP5, False),
    "geolocation_zip_code_prefix": (ZIP5, False),
    "customer_state": (UF, False),
    "seller_state": (UF, False),
    "geolocation_state": (UF, False),
    "order_status": (r"[a-z_]+", False),
    "order_purchase_timestamp": (TIMESTAMP, False),
    "order_approved_at": (TIMESTAMP, True),
    "order_delivered_carrier_date": (TIMESTAMP, True),
    "order_delivered_customer_date": (TIMESTAMP, True),
    "order_estimated_delivery_date": (TIMESTAMP, False),
    "shipping_limit_date": (TIMESTAMP, False),
    "review_creation_date": (TIMESTAMP, False),
    "review_answer_timestamp": (TIMESTAMP, False),
    "order_item_id": (INTEGER, False),
    "payment_sequential": (INTEGER, False),
    "payment_installments": (INTEGER, False),
    "review_score": (INTEGER, False),
    "price": (DECIMAL, False),
    "freight_value": (DECIMAL, False),
    "payment_value": (DECIMAL, False),
    "payment_type": (r"[a-z_]+", False),
    "geolocation_lat": (DECIMAL, False),
    "geolocation_lng": (DECIMAL, False),
    "product_category_name": (r"[a-z0-9_]+", True),
    "product_category_name_english": (r"[a-z0-9_]+", False),
    **{
        c: (INTEGER, True)
        for c in (
            "product_name_lenght",
            "product_description_lenght",
            "product_photos_qty",
            "product_weight_g",
            "product_length_cm",
            "product_height_cm",
            "product_width_cm",
        )
    },
}


class ContractError(ValueError):
    pass


def read_header(path: Path) -> list[str]:
    # utf-8-sig strips the BOM that product_category_name_translation.csv starts with.
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return next(csv.reader(fh))


def schema_for(spec: SourceFile) -> pa.DataFrameSchema:
    columns = {}
    for col in spec.columns:
        regex, nullable = COLUMN_RULES.get(col, (None, True))
        checks = [pa.Check.str_matches(f"^(?:{regex})$")] if regex else []
        columns[col] = pa.Column(str, checks=checks, nullable=nullable)
    return pa.DataFrameSchema(columns, strict=True, ordered=True, name=spec.table)


def validate_file(spec: SourceFile, path: Path) -> int:
    """Validate one source file against its contract; return the data row count.

    Raises ContractError with a readable summary of the first failures.
    """
    header = read_header(path)
    if header != list(spec.columns):
        raise ContractError(
            f"{path.name}: header mismatch; expected {list(spec.columns)}, got {header}"
        )
    df = pd.read_csv(path, dtype=str, keep_default_na=False, na_values=[""], encoding="utf-8-sig")
    try:
        schema_for(spec).validate(df, lazy=True)
    except pa.errors.SchemaErrors as exc:
        cases = exc.failure_cases
        summary = (
            cases.groupby(["column", "check"], dropna=False)
            .agg(n=("failure_case", "size"), example=("failure_case", "first"))
            .reset_index()
            .to_string(index=False)
        )
        raise ContractError(f"{path.name}: contract violations\n{summary}") from None
    return len(df)
