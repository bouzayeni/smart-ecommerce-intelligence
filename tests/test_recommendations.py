"""Recommender tests on a hand-built purchase history (no database)."""

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from ml.recommend.config import REC_CONFIG_PATH, load_rec_config
from ml.recommend.data import Interactions, ground_truth
from ml.recommend.evaluation import evaluate, user_metrics
from ml.recommend.models import MODEL_CLASSES, CategoryPopular, ItemKNN, StatePopularity

CUTOFF = pd.Timestamp("2018-03-01")


def _events(rows):
    return pd.DataFrame(rows, columns=["user_id", "item_id", "category_name", "purchased_at",
                                       "state", "price"]).assign(
        purchased_at=lambda d: pd.to_datetime(d["purchased_at"]))  # fmt: skip


@pytest.fixture
def data() -> Interactions:
    rows = [
        # u1 and u2 both bought A and B: A and B are co-purchased.
        ("u1", "A", "toys", "2018-01-05", "SP", 50), ("u1", "B", "toys", "2018-01-06", "SP", 60),
        ("u2", "A", "toys", "2018-02-01", "RJ", 50), ("u2", "B", "toys", "2018-02-02", "RJ", 60),
        ("u3", "A", "toys", "2018-02-10", "SP", 50),
        ("u4", "C", "garden", "2018-02-15", "RJ", 200),
        ("u5", "C", "garden", "2018-02-20", "RJ", 200),
        ("u6", "D", "books", "2018-02-25", "SP", 20),
        # after the cutoff: E is a new product that must never be recommended in evaluation
        ("u3", "B", "toys", "2018-03-10", "SP", 60), ("u7", "E", "books", "2018-03-12", "SP", 30),
    ]  # fmt: skip
    products = pd.DataFrame({
        "item_id": list("ABCDE"), "category_name": ["toys", "toys", "garden", "books", "books"],
        "product_weight_g": [100, 120, 2000, 300, 300], "product_volume_cm3": [1000] * 5,
        "product_photos_qty": [1, 2, 3, 1, 1],
    }).set_index("item_id")  # fmt: skip
    return Interactions(_events(rows), products)


def test_user_metrics_known_values():
    m = user_metrics(["x", "a", "y", "b"], {"a", "b", "c"}, k=4)
    assert m["precision"] == pytest.approx(2 / 4)
    assert m["recall"] == pytest.approx(2 / 3)
    assert m["hit_rate"] == 1.0
    dcg = 1 / np.log2(3) + 1 / np.log2(5)
    idcg = 1 / np.log2(2) + 1 / np.log2(3) + 1 / np.log2(4)
    assert m["ndcg"] == pytest.approx(dcg / idcg)
    assert m["map"] == pytest.approx((1 / 2 + 2 / 4) / 3)


@pytest.mark.parametrize("family", list(MODEL_CLASSES))
def test_every_model_returns_k_items_and_never_a_future_product(data, family):
    model = MODEL_CLASSES[family]().fit(data.before(CUTOFF), CUTOFF)
    recs = model.recommend(["u1", "u3", "unknown-user"], k=3, states={"u3": "SP"})
    for user, items in recs.items():
        ids = [i for i, _ in items]
        assert len(ids) == 3 and len(set(ids)) == 3, (family, user)
        assert "E" not in ids, f"{family} recommended a product first sold after the cutoff"


def test_item_knn_recommends_the_co_purchased_item(data):
    knn = ItemKNN(neighbours=5).fit(data.before(CUTOFF), CUTOFF)
    assert knn.recommend(["u3"], k=1)["u3"][0][0] == "B"  # bought A; A co-occurs with B
    assert [i for i, _ in knn.neighbours_of("A", 1)] == ["B"]


def test_state_popularity_uses_the_users_state_with_global_fallback(data):
    model = StatePopularity(window_days=365, min_state_sales=2).fit(data.before(CUTOFF), CUTOFF)
    rj = model.recommend(["new"], k=1, states={"new": "RJ"})["new"][0][0]
    assert rj == "C"  # most bought in RJ
    anywhere = model.recommend(["new"], k=1, states={"new": "XX"})["new"][0][0]
    assert anywhere == "A"  # global top seller


def test_category_popular_starts_with_the_users_last_category(data):
    model = CategoryPopular(window_days=365).fit(data.before(CUTOFF), CUTOFF)
    assert model.recommend(["u4"], k=1)["u4"][0][0] == "C"


def test_evaluate_counts_category_hits(data):
    truth = ground_truth(data.between(CUTOFF, "2018-04-01"))
    recs = {"u3": [("A", 1.0)], "u7": [("D", 1.0)]}  # u7 bought E (books): D is also books
    item_category = data.products["category_name"].to_dict()
    m = evaluate(recs, truth, k=1, item_category=item_category, candidate_count=4, n_boot=20)
    assert m["hit_rate@1"] == 0.0
    assert m["category_hit_rate@1"] == 1.0  # both users' categories were hit


def test_windows_must_be_chronological(tmp_path):
    bad = tmp_path / "r.yaml"
    bad.write_text(REC_CONFIG_PATH.read_text(encoding="utf-8").replace(
        "validation: {cutoff: 2018-03-01, end: 2018-06-01}",
        "validation: {cutoff: 2018-03-01, end: 2018-07-01}"), encoding="utf-8")  # fmt: skip
    with pytest.raises(ValidationError, match="before the test cutoff"):
        load_rec_config(bad)
