"""Leakage and correctness tests for snapshot features, labels, splits and RFM.

Uses a small synthetic history so each expected value can be checked by hand.
"""

from datetime import date, timedelta

import pandas as pd
import pytest
from pydantic import ValidationError

from ml.config import ML_CONFIG_PATH, RfmConfig, Segment, get_ml_config, load_ml_config
from ml.customer.features import CATEGORICAL_FEATURES, NUMERIC_FEATURES, build_snapshot
from ml.customer.rfm import compute_rfm, frequency_score
from ml.data import CustomerHistory

T = date(2018, 1, 1)
H = timedelta(days=90)


def _order(oid, cust, purchased, gmv=100.0, delivered=None, late=False):
    return {
        "order_id": oid, "customer_unique_id": cust, "purchased_at": pd.Timestamp(purchased),
        "gmv": gmv, "price_total": gmv * 0.8, "freight_total": gmv * 0.2, "item_count": 1,
        "max_installments": 1, "primary_payment_type": "credit_card",
        "customer_state_at_order": "SP",
        "delivered_to_customer_at": pd.Timestamp(delivered) if delivered else pd.NaT,
        "is_late": late if delivered else None,
        "delivery_days": (pd.Timestamp(delivered) - pd.Timestamp(purchased)).days
        if delivered else None,
    }  # fmt: skip


@pytest.fixture
def history() -> CustomerHistory:
    orders = pd.DataFrame([
        _order("o1", "alice", "2017-06-01", 100, delivered="2017-06-10"),
        _order("o2", "alice", "2017-12-20", 50, delivered="2018-01-05", late=True),  # after T
        _order("o3", "alice", "2018-02-01", 70, delivered="2018-02-08"),  # future: label
        _order("o4", "bob", "2017-11-01", 200, delivered="2017-11-09"),
        _order("o5", "bob", "2018-06-01", 300),  # outside horizon
        _order("o6", "carol", "2018-01-15", 80),  # new after T: not in population
    ])  # fmt: skip
    categories = pd.DataFrame({
        "order_id": ["o1", "o2", "o3", "o4", "o5", "o6"],
        "category_name": ["toys", "books", "toys", "garden", "garden", "toys"],
    })  # fmt: skip
    reviews = pd.DataFrame({
        "order_id": ["o1", "o2", "o4"],
        "review_score": [5, 1, 4],
        "review_answered_at": pd.to_datetime(["2017-06-15", "2018-01-10", "2017-11-20"]),
    })  # fmt: skip
    return CustomerHistory(orders, categories, reviews, pd.Timestamp("2018-08-21"))


def _row(df, cust):
    return df.set_index("customer_unique_id").loc[cust]


def test_population_is_customers_active_before_cutoff(history):
    snap = build_snapshot(history, T, H)
    assert set(snap["customer_unique_id"]) == {"alice", "bob"}


def test_features_use_only_pre_cutoff_orders(history):
    a = _row(build_snapshot(history, T, H), "alice")
    assert a["frequency"] == 2
    assert a["monetary"] == pytest.approx(150)
    assert a["recency_days"] == pytest.approx(12)  # 2017-12-20 -> 2018-01-01


def test_delivery_and_review_must_be_known_before_cutoff(history):
    a = _row(build_snapshot(history, T, H), "alice")
    # o2 was delivered (late) and reviewed (score 1) only after T: neither may be used.
    assert a["n_delivered"] == 1
    assert a["late_share"] == 0
    assert a["last_order_delivered"] == 0
    assert a["n_reviews"] == 1
    assert a["last_review_score"] == 5


def test_labels_count_only_the_horizon_window(history):
    snap = build_snapshot(history, T, H)
    a, b = _row(snap, "alice"), _row(snap, "bob")
    assert (a["repurchase"], a["future_orders"], a["future_gmv"]) == (1, 1, 70)
    assert (b["repurchase"], b["future_gmv"]) == (0, 0)  # o5 is after T + 90 days


def test_features_do_not_change_when_future_data_changes(history):
    before = build_snapshot(history, T, None)
    mutated = CustomerHistory(
        pd.concat([history.orders, pd.DataFrame([_order("o9", "bob", "2018-01-02", 999)])]),
        history.order_categories, history.reviews, history.window_end,
    )  # fmt: skip
    after = build_snapshot(mutated, T, None)
    cols = ["customer_unique_id", *NUMERIC_FEATURES, *CATEGORICAL_FEATURES]
    pd.testing.assert_frame_equal(before[cols], after[cols])


def test_label_window_beyond_data_is_rejected(history):
    with pytest.raises(ValueError, match="ends after the data"):
        build_snapshot(history, date(2018, 7, 1), H)


def test_project_config_splits_do_not_overlap():
    cfg = get_ml_config()
    s = cfg.snapshots
    assert max(s.train) + cfg.horizon <= s.validation
    assert s.validation + cfg.horizon <= s.test


def test_overlapping_splits_are_rejected(tmp_path):
    bad = tmp_path / "ml.yaml"
    bad.write_text(
        ML_CONFIG_PATH.read_text(encoding="utf-8").replace("validation: 2018-01-01",
                                                           "validation: 2017-11-01"),
        encoding="utf-8",
    )  # fmt: skip
    with pytest.raises(ValidationError, match="validation cutoff"):
        load_ml_config(bad)


def test_frequency_score_thresholds():
    scores = {1: 1, 2: 3, 3: 5}
    assert [frequency_score(n, scores) for n in (1, 2, 3, 17)] == [1, 3, 5, 5]


def test_rfm_segments_first_matching_rule_wins(history):
    cfg = RfmConfig(
        reference_date=date(2018, 8, 22),
        frequency_scores={1: 1, 2: 3, 3: 5},
        segments=[Segment(name="Repeat", f_min=3), Segment(name="Everyone else")],
    )
    rfm = compute_rfm(history, cfg).set_index("customer_unique_id")
    assert rfm.loc["alice", "frequency"] == 3
    assert rfm.loc["alice", "segment"] == "Repeat"
    assert rfm.loc["carol", "segment"] == "Everyone else"
    assert set(rfm["r_score"]) <= set(range(1, 6))


def test_risk_band_covers_every_decile():
    bands = get_ml_config().repurchase.risk_bands
    assert [bands.band(d) for d in range(1, 11)] == ["high"] * 5 + ["medium"] * 3 + ["low"] * 2
