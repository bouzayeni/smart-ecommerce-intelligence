"""Specification of the Olist source files the pipeline expects (the file contract)."""

from dataclasses import dataclass
from pathlib import Path

KAGGLE_DATASET = "olistbr/brazilian-ecommerce"
KAGGLE_DOWNLOAD_URL = f"https://www.kaggle.com/api/v1/datasets/download/{KAGGLE_DATASET}"


@dataclass(frozen=True)
class SourceFile:
    table: str
    filename: str
    # Exact header, in file order. Source typos (e.g. "lenght") are kept: bronze is untouched.
    columns: tuple[str, ...]
    # Optional files degrade features (maps, English category names) but don't block the pipeline.
    required: bool = True


SOURCE_FILES: tuple[SourceFile, ...] = (
    SourceFile(
        "customers",
        "olist_customers_dataset.csv",
        (
            "customer_id",
            "customer_unique_id",
            "customer_zip_code_prefix",
            "customer_city",
            "customer_state",
        ),
    ),
    SourceFile(
        "orders",
        "olist_orders_dataset.csv",
        (
            "order_id",
            "customer_id",
            "order_status",
            "order_purchase_timestamp",
            "order_approved_at",
            "order_delivered_carrier_date",
            "order_delivered_customer_date",
            "order_estimated_delivery_date",
        ),
    ),
    SourceFile(
        "order_items",
        "olist_order_items_dataset.csv",
        (
            "order_id",
            "order_item_id",
            "product_id",
            "seller_id",
            "shipping_limit_date",
            "price",
            "freight_value",
        ),
    ),
    SourceFile(
        "order_payments",
        "olist_order_payments_dataset.csv",
        ("order_id", "payment_sequential", "payment_type", "payment_installments", "payment_value"),
    ),
    SourceFile(
        "order_reviews",
        "olist_order_reviews_dataset.csv",
        (
            "review_id",
            "order_id",
            "review_score",
            "review_comment_title",
            "review_comment_message",
            "review_creation_date",
            "review_answer_timestamp",
        ),
    ),
    SourceFile(
        "products",
        "olist_products_dataset.csv",
        (
            "product_id",
            "product_category_name",
            "product_name_lenght",
            "product_description_lenght",
            "product_photos_qty",
            "product_weight_g",
            "product_length_cm",
            "product_height_cm",
            "product_width_cm",
        ),
    ),
    SourceFile(
        "sellers",
        "olist_sellers_dataset.csv",
        ("seller_id", "seller_zip_code_prefix", "seller_city", "seller_state"),
    ),
    SourceFile(
        "geolocation",
        "olist_geolocation_dataset.csv",
        (
            "geolocation_zip_code_prefix",
            "geolocation_lat",
            "geolocation_lng",
            "geolocation_city",
            "geolocation_state",
        ),
        required=False,
    ),
    SourceFile(
        "category_translation",
        "product_category_name_translation.csv",
        ("product_category_name", "product_category_name_english"),
        required=False,
    ),
)

SOURCE_BY_TABLE = {s.table: s for s in SOURCE_FILES}


def missing_files(directory: Path) -> tuple[list[str], list[str]]:
    """Return (missing required filenames, missing optional filenames) in a directory."""
    missing = [s for s in SOURCE_FILES if not (directory / s.filename).is_file()]
    return (
        [s.filename for s in missing if s.required],
        [s.filename for s in missing if not s.required],
    )
