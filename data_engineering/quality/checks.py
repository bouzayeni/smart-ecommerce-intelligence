"""Catalog of data quality checks on the raw Olist tables.

Severity:
    error - breaks the model (duplicate keys, orphan foreign keys, unparseable values).
            The warehouse load must not proceed while any error check fails.
    warn  - a known quality issue. Rows are kept and flagged downstream, never silently dropped.
    info  - a structural fact that downstream logic must account for (not a defect).
"""

from collections.abc import Iterator
from dataclasses import asdict, dataclass
from typing import Literal

import pandas as pd

from data_engineering.business_rules import ORDER_STATUSES, BusinessRules
from data_engineering.quality.analysis import item_totals
from data_engineering.quality.loader import RawTables

Severity = Literal["error", "warn", "info"]

PAYMENT_TYPES = {"credit_card", "boleto", "voucher", "debit_card", "not_defined"}


@dataclass(frozen=True)
class CheckResult:
    check_id: str
    table: str
    severity: Severity
    description: str
    failed: int
    total: int

    @property
    def passed(self) -> bool:
        return self.failed == 0

    def to_dict(self) -> dict:
        return {**asdict(self), "passed": self.passed}


def _result(check_id, table, severity, description, mask: pd.Series) -> CheckResult:
    return CheckResult(check_id, table, severity, description, int(mask.sum()), int(len(mask)))


def _key_checks(raw: RawTables) -> Iterator[CheckResult]:
    primary_keys = {
        "customers": ["customer_id"],
        "orders": ["order_id"],
        "order_items": ["order_id", "order_item_id"],
        "order_payments": ["order_id", "payment_sequential"],
        "order_reviews": ["review_id", "order_id"],
        "products": ["product_id"],
        "sellers": ["seller_id"],
        "category_translation": ["product_category_name"],
    }
    for table, cols in primary_keys.items():
        if table not in raw:
            continue
        df = raw[table]
        yield _result(
            f"{table}.pk_not_null",
            table,
            "error",
            f"{'+'.join(cols)} not null",
            df[cols].isna().any(axis=1),
        )
        yield _result(
            f"{table}.pk_unique",
            table,
            "error",
            f"{'+'.join(cols)} unique",
            df.duplicated(cols, keep=False),
        )

    foreign_keys = [
        ("orders", "customer_id", "customers", "customer_id"),
        ("order_items", "order_id", "orders", "order_id"),
        ("order_items", "product_id", "products", "product_id"),
        ("order_items", "seller_id", "sellers", "seller_id"),
        ("order_payments", "order_id", "orders", "order_id"),
        ("order_reviews", "order_id", "orders", "order_id"),
    ]
    for child, col, parent, pcol in foreign_keys:
        yield _result(
            f"{child}.fk_{col}",
            child,
            "error",
            f"{col} exists in {parent}.{pcol}",
            ~raw[child][col].isin(set(raw[parent][pcol])),
        )


def _domain_checks(raw: RawTables) -> Iterator[CheckResult]:
    o, it, p, r = raw["orders"], raw["order_items"], raw["order_payments"], raw["order_reviews"]
    for (table, col), n in sorted(raw.parse_failures.items()):
        mask = pd.Series([True] * n + [False] * (len(raw[table]) - n))
        yield _result(f"{table}.{col}.parseable", table, "error", f"{col} parses", mask)
    yield _result(
        "orders.purchase_timestamp_not_null",
        "orders",
        "error",
        "purchase timestamp present",
        o["order_purchase_timestamp"].isna(),
    )
    yield _result(
        "orders.status_known",
        "orders",
        "error",
        f"status in {sorted(ORDER_STATUSES)}",
        ~o["order_status"].isin(ORDER_STATUSES),
    )
    yield _result(
        "order_items.price_positive", "order_items", "error", "price > 0", ~(it["price"] > 0)
    )
    yield _result(
        "order_items.freight_non_negative",
        "order_items",
        "error",
        "freight_value >= 0",
        ~(it["freight_value"] >= 0),
    )
    yield _result(
        "order_items.item_id_contiguous",
        "order_items",
        "error",
        "order_item_id runs 1..n within each order",
        it.groupby("order_id")["order_item_id"].transform("max")
        != it.groupby("order_id")["order_item_id"].transform("size"),
    )
    yield _result(
        "order_payments.type_known",
        "order_payments",
        "error",
        "payment_type in known set",
        ~p["payment_type"].isin(PAYMENT_TYPES),
    )
    yield _result(
        "order_reviews.score_1_to_5",
        "order_reviews",
        "error",
        "review_score in 1..5",
        ~r["review_score"].isin([1, 2, 3, 4, 5]),
    )
    for table, col in [
        ("customers", "customer_zip_code_prefix"),
        ("sellers", "seller_zip_code_prefix"),
        ("geolocation", "geolocation_zip_code_prefix"),
    ]:
        if table in raw:
            yield _result(
                f"{table}.zip_prefix_5_digits",
                table,
                "error",
                f"{col} is 5 digits",
                ~raw[table][col].str.fullmatch(r"\d{5}").fillna(False),
            )


def _known_issue_checks(raw: RawTables, rules: BusinessRules) -> Iterator[CheckResult]:
    o, it, p, r = raw["orders"], raw["order_items"], raw["order_payments"], raw["order_reviews"]
    delivered = o["order_status"] == "delivered"
    has_delivery = o["order_delivered_customer_date"].notna()

    yield _result(
        "orders.has_items",
        "orders",
        "warn",
        "order has at least one item",
        ~o["order_id"].isin(set(it["order_id"])),
    )
    yield _result(
        "orders.has_payment",
        "orders",
        "warn",
        "order has at least one payment",
        ~o["order_id"].isin(set(p["order_id"])),
    )
    yield _result(
        "orders.delivered_has_delivery_date",
        "orders",
        "warn",
        "delivered orders have a customer delivery date",
        delivered & ~has_delivery,
    )
    yield _result(
        "orders.undelivered_has_no_delivery_date",
        "orders",
        "warn",
        "non-delivered orders have no customer delivery date",
        ~delivered & has_delivery,
    )
    yield _result(
        "orders.carrier_after_purchase",
        "orders",
        "warn",
        "carrier pickup is not before purchase",
        o["order_delivered_carrier_date"] < o["order_purchase_timestamp"],
    )
    yield _result(
        "orders.delivery_after_carrier",
        "orders",
        "warn",
        "customer delivery is not before carrier pickup",
        o["order_delivered_customer_date"] < o["order_delivered_carrier_date"],
    )
    yield _result(
        "orders.approved_after_purchase",
        "orders",
        "warn",
        "approval is not before purchase",
        o["order_approved_at"] < o["order_purchase_timestamp"],
    )

    max_days = rules.quality.shipping_limit_max_days_after_purchase
    lag = it.merge(o[["order_id", "order_purchase_timestamp"]], on="order_id", how="left")
    yield _result(
        "order_items.shipping_limit_plausible",
        "order_items",
        "warn",
        f"shipping_limit_date <= purchase + {max_days} days",
        (lag["shipping_limit_date"] - lag["order_purchase_timestamp"]).dt.days > max_days,
    )

    yield _result(
        "order_payments.value_positive",
        "order_payments",
        "warn",
        "payment_value > 0",
        ~(p["payment_value"] > 0),
    )
    yield _result(
        "order_payments.type_defined",
        "order_payments",
        "warn",
        "payment_type is not 'not_defined'",
        p["payment_type"] == "not_defined",
    )
    yield _result(
        "order_payments.installments_positive",
        "order_payments",
        "warn",
        "payment_installments >= 1",
        ~(p["payment_installments"] >= 1),
    )

    tol = rules.payments.reconciliation_tolerance_brl
    items = item_totals(it)["gmv"]
    pays = p.groupby("order_id")["payment_value"].sum()
    j = pd.concat([items.rename("items"), pays.rename("pays")], axis=1).dropna()
    yield _result(
        "orders.payments_match_items",
        "orders",
        "warn",
        f"sum(payments) = sum(price + freight) within {tol} BRL",
        (j["pays"] - j["items"]).abs() > tol,
    )

    per_order = r.groupby("order_id")["review_id"].transform("size")
    yield _result(
        "order_reviews.one_review_per_order",
        "order_reviews",
        "warn",
        "order has a single review",
        per_order > 1,
    )
    yield _result(
        "order_reviews.review_id_single_order",
        "order_reviews",
        "info",
        "review_id covers a single order (else: one review for orders placed together)",
        r["review_id"].duplicated(keep=False),
    )
    yield _result(
        "order_reviews.answer_after_creation",
        "order_reviews",
        "warn",
        "review answered on/after creation date",
        r["review_answer_timestamp"] < r["review_creation_date"],
    )

    pr = raw["products"]
    yield _result(
        "products.category_present",
        "products",
        "warn",
        "product has a category",
        pr["product_category_name"].isna(),
    )
    if "category_translation" in raw:
        known = set(raw["category_translation"]["product_category_name"])
        yield _result(
            "products.category_translated",
            "products",
            "warn",
            "category exists in translation table",
            pr["product_category_name"].notna() & ~pr["product_category_name"].isin(known),
        )
    yield _result(
        "products.weight_positive",
        "products",
        "warn",
        "product_weight_g > 0",
        ~(pr["product_weight_g"] > 0),
    )

    if "geolocation" in raw:
        g = raw["geolocation"]
        bb = rules.quality.brazil_bbox
        inside = g["geolocation_lat"].between(bb.lat_min, bb.lat_max) & g[
            "geolocation_lng"
        ].between(bb.lng_min, bb.lng_max)
        yield _result(
            "geolocation.inside_brazil",
            "geolocation",
            "warn",
            "coordinates inside Brazil bounding box",
            ~inside,
        )
        yield _result(
            "geolocation.no_exact_duplicates",
            "geolocation",
            "info",
            "row is not an exact duplicate",
            g.duplicated(),
        )
        zips = set(g["geolocation_zip_code_prefix"])
        for table, col in [("customers", "customer_zip_code_prefix"),
                           ("sellers", "seller_zip_code_prefix")]:  # fmt: skip
            yield _result(
                f"{table}.zip_in_geolocation",
                table,
                "warn",
                f"{col} has coordinates",
                ~raw[table][col].isin(zips),
            )

    c = raw["customers"]
    yield _result(
        "customers.one_customer_id_per_person",
        "customers",
        "info",
        "customer_unique_id has a single customer_id (else: repeat buyer)",
        c["customer_unique_id"].duplicated(keep=False),
    )


def run_checks(raw: RawTables, rules: BusinessRules) -> list[CheckResult]:
    return [*_key_checks(raw), *_domain_checks(raw), *_known_issue_checks(raw, rules)]
