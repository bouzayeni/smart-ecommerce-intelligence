from datetime import date

import pandas as pd
import pytest
from pydantic import ValidationError

from data_engineering.business_rules import BusinessRules, get_rules, load_rules
from data_engineering.config import PROJECT_ROOT
from data_engineering.quality import analysis as a
from data_engineering.quality.checks import run_checks
from data_engineering.quality.loader import RawTables, load_raw

SAMPLE_DIR = PROJECT_ROOT / "data" / "sample"


@pytest.fixture(scope="module")
def sample() -> RawTables:
    return load_raw(SAMPLE_DIR)


@pytest.fixture(scope="module")
def rules() -> BusinessRules:
    return get_rules()


# --- business rules -------------------------------------------------------------------------


def test_rules_file_is_valid(rules):
    assert rules.customer_key == "customer_unique_id"
    assert rules.analysis_window.start < (rules.analysis_window.end_override or date.max)


def test_revenue_statuses_must_partition_known_statuses(tmp_path):
    text = (PROJECT_ROOT / "config" / "business_rules.yaml").read_text(encoding="utf-8")
    bad = tmp_path / "rules.yaml"
    bad.write_text(
        text.replace(
            "exclude_statuses: [canceled, unavailable, created]",
            "exclude_statuses: [canceled, unavailable]",
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValidationError, match="missing \\['created'\\]"):
        load_rules(bad)


# --- loader ---------------------------------------------------------------------------------


def test_loader_keeps_zip_prefix_leading_zeros(tmp_path, sample):
    assert sample["customers"]["customer_zip_code_prefix"].str.len().eq(5).all()


def test_loader_counts_unparseable_values(tmp_path):
    for f in SAMPLE_DIR.glob("*.csv"):
        (tmp_path / f.name).write_bytes(f.read_bytes())
    orders = tmp_path / "olist_orders_dataset.csv"
    df = pd.read_csv(orders, dtype=str, keep_default_na=False)
    df.loc[0, "order_purchase_timestamp"] = "not-a-date"
    df.to_csv(orders, index=False)
    raw = load_raw(tmp_path)
    assert raw.parse_failures[("orders", "order_purchase_timestamp")] == 1


def test_loader_requires_required_files(tmp_path):
    with pytest.raises(FileNotFoundError, match="Required source file missing"):
        load_raw(tmp_path)


# --- checks on the sample fixture -----------------------------------------------------------


def test_sample_passes_all_error_checks(sample, rules):
    failed = [
        r.check_id for r in run_checks(sample, rules) if r.severity == "error" and not r.passed
    ]
    assert failed == []


def test_check_ids_are_unique(sample, rules):
    ids = [r.check_id for r in run_checks(sample, rules)]
    assert len(ids) == len(set(ids))


def test_duplicate_primary_key_is_detected(sample, rules):
    tables = dict(sample.tables)
    tables["orders"] = pd.concat([tables["orders"], tables["orders"].head(1)])
    results = {r.check_id: r for r in run_checks(RawTables(tables, sample.parse_failures), rules)}
    assert results["orders.pk_unique"].failed == 2


def test_orphan_foreign_key_is_detected(sample, rules):
    tables = dict(sample.tables)
    items = tables["order_items"].copy()
    items.loc[items.index[0], "product_id"] = "does-not-exist"
    tables["order_items"] = items
    results = {r.check_id: r for r in run_checks(RawTables(tables, sample.parse_failures), rules)}
    assert results["order_items.fk_product_id"].failed == 1


# --- analysis -------------------------------------------------------------------------------


def _series(values: list[int]) -> pd.Series:
    return pd.Series(values, index=pd.date_range("2018-01-01", periods=len(values), freq="D"))


def test_detect_window_end_finds_last_complete_day():
    daily = _series([100] * 40 + [95, 60, 20, 5, 0])
    assert a.detect_window_end(daily, 0.7, 28, 10) == date(2018, 2, 10)  # the "95" day


def test_detect_window_end_ignores_near_empty_tail():
    daily = _series([100] * 40 + [0] * 30 + [1])  # trailing baseline collapses to 0
    assert a.detect_window_end(daily, 0.7, 28, 10) == date(2018, 2, 9)


def test_detect_window_end_raises_when_volume_too_low():
    with pytest.raises(ValueError):
        a.detect_window_end(_series([1] * 60), 0.7, 28, 10)


def test_payment_reconciliation_components_sum_to_total(sample):
    rc = a.payment_reconciliation(sample, 0.01)
    explained = (
        rc["total_items_value"]
        + rc["payments_without_items_amount"]
        - rc["items_without_payments_amount"]
        + rc["paid_more_amount"]
        + rc["paid_less_amount"]
        + rc["matched_orders_diff_amount"]
    )
    assert explained == pytest.approx(rc["total_payments"], abs=0.005)


def test_per_order_review_latest_answer():
    reviews = pd.DataFrame(
        {
            "review_id": ["r1", "r2", "r3"],
            "order_id": ["o1", "o1", "o2"],
            "review_score": [1, 5, 3],
            "review_answer_timestamp": pd.to_datetime(["2018-01-02", "2018-01-05", "2018-01-03"]),
        }
    )
    out = a.per_order_review(reviews, "latest_answer").set_index("order_id")["review_score"]
    assert out.to_dict() == {"o1": 5, "o2": 3}
    assert a.per_order_review(reviews, "mean").set_index("order_id")["review_score"]["o1"] == 3


def test_delivery_frame_excludes_inconsistent_timestamps_and_uses_calendar_date(sample, rules):
    d = a.delivery_frame(sample, rules)
    assert (d["order_status"] == "delivered").all()
    assert not (d["order_delivered_customer_date"] < d["order_delivered_carrier_date"]).any()
    same_day = (
        d["order_delivered_customer_date"].dt.normalize() == d["order_estimated_delivery_date"]
    )
    assert not d.loc[same_day, "is_late"].any()
