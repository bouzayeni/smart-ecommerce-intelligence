"""Recommenders with a common interface.

fit(train: Interactions, cutoff) -> self
recommend(users, k, states) -> {user: [(item_id, score), ...]}

Every model sees only interactions before the cutoff, and only products sold before it are
candidates. Users without usable history are filled from a popularity ranking, so every
model returns k items for every user.
"""

import numpy as np
import pandas as pd
import scipy.sparse as sp
from sklearn.decomposition import TruncatedSVD
from sklearn.preprocessing import normalize

from ml.recommend.data import Interactions, safe_log


def popularity_ranking(events: pd.DataFrame, cutoff, window_days: int) -> pd.Series:
    """Item -> score: purchases in the window, ties broken by all-time purchases."""
    recent = events[events["purchased_at"] >= pd.Timestamp(cutoff) - pd.Timedelta(days=window_days)]
    score = recent["item_id"].value_counts().reindex(events["item_id"].unique(), fill_value=0)
    tiebreak = events["item_id"].value_counts().reindex(score.index) / 1e6
    ranked = (score + tiebreak).sort_values(ascending=False, kind="stable")
    return ranked


def _fill(recs: list, ranking: pd.Series, k: int, exclude: set | None = None) -> list:
    """Append items from a ranking until k unique items (fallback for thin histories)."""
    seen = {i for i, _ in recs} | (exclude or set())
    for item, score in ranking.items():
        if len(recs) >= k:
            break
        if item not in seen:
            recs.append((item, float(score) * 1e-9))  # below any model score
            seen.add(item)
    return recs


class Popularity:
    name = "popularity"

    def __init__(self, window_days: int = 90, **_):
        self.window_days = window_days

    def fit(self, train: Interactions, cutoff):
        self.ranking = popularity_ranking(train.events, cutoff, self.window_days)
        return self

    def recommend(self, users, k, states=None) -> dict:
        top = list(self.ranking.head(k).items())
        return {u: [(i, float(s)) for i, s in top] for u in users}


class StatePopularity(Popularity):
    """Popularity within the user's state; states with few sales use the global ranking."""

    name = "state_popularity"

    def __init__(self, window_days: int = 90, min_state_sales: int = 30, **_):
        super().__init__(window_days)
        self.min_state_sales = min_state_sales

    def fit(self, train: Interactions, cutoff):
        super().fit(train, cutoff)
        self.by_state = {}
        for state, group in train.events.groupby("state"):
            if len(group) >= self.min_state_sales:
                self.by_state[state] = popularity_ranking(group, cutoff, self.window_days)
        return self

    def recommend(self, users, k, states=None) -> dict:
        states = states or {}
        out = {}
        for u in users:
            ranking = self.by_state.get(states.get(u), self.ranking)
            out[u] = _fill(list(ranking.head(k).items()), self.ranking, k)
        return out


class _MatrixModel:
    """Shared user-item matrix (binary: bought or not) for CF models."""

    def _build(self, train: Interactions, cutoff):
        e = train.events
        self.items = pd.Index(e["item_id"].unique())
        self.users = pd.Index(e["user_id"].unique())
        rows = self.users.get_indexer(e["user_id"])
        cols = self.items.get_indexer(e["item_id"])
        x = sp.csr_matrix((np.ones(len(e)), (rows, cols)), shape=(len(self.users), len(self.items)))
        x.data[:] = 1.0  # duplicates summed -> binarise
        self.x = x
        self.fallback = popularity_ranking(e, cutoff, 90)

    def _top(self, scores: np.ndarray, k: int) -> list:
        k_eff = min(k, int((scores > 0).sum()))
        if k_eff == 0:
            return []
        idx = np.argpartition(-scores, k_eff - 1)[:k_eff]
        idx = idx[np.argsort(-scores[idx], kind="stable")]
        return [(self.items[i], float(scores[i])) for i in idx]


class ItemKNN(_MatrixModel):
    """Item-item collaborative filtering: cosine similarity of co-purchase vectors, keeping
    each item's top `neighbours`. User score = sum of similarities to items they bought."""

    name = "item_knn"

    def __init__(self, neighbours: int = 50, **_):
        self.neighbours = neighbours

    def fit(self, train: Interactions, cutoff):
        self._build(train, cutoff)
        xn = normalize(self.x.T.tocsr(), norm="l2", axis=1)  # items x users
        sim = (xn @ xn.T).tocsr()
        sim.setdiag(0)
        sim.eliminate_zeros()
        self.sim = self._prune(sim, self.neighbours)
        return self

    @staticmethod
    def _prune(sim: sp.csr_matrix, n: int) -> sp.csr_matrix:
        rows, cols, vals = [], [], []
        for i in range(sim.shape[0]):
            start, end = sim.indptr[i], sim.indptr[i + 1]
            if end == start:
                continue
            data, idx = sim.data[start:end], sim.indices[start:end]
            keep = np.argsort(-data, kind="stable")[:n]
            rows += [i] * len(keep)
            cols += list(idx[keep])
            vals += list(data[keep])
        return sp.csr_matrix((vals, (rows, cols)), shape=sim.shape)

    def neighbours_of(self, item_id: str, n: int) -> list:
        i = self.items.get_loc(item_id)
        row = self.sim.getrow(i)
        order = np.argsort(-row.data, kind="stable")[:n]
        return [(self.items[row.indices[j]], float(row.data[j])) for j in order]

    def recommend(self, users, k, states=None) -> dict:
        out = {}
        for u in users:
            if u in self.users:
                history = self.x.getrow(self.users.get_loc(u))
                scores = np.asarray((history @ self.sim).todense()).ravel()
                recs = self._top(scores, k)
            else:
                recs = []
            out[u] = _fill(recs, self.fallback, k)
        return out


class SVDRecommender(_MatrixModel):
    """Matrix factorisation of the binary user-item matrix (truncated SVD)."""

    name = "svd"

    def __init__(self, components: int = 32, seed: int = 0, **_):
        self.components, self.seed = components, seed

    def fit(self, train: Interactions, cutoff):
        self._build(train, cutoff)
        n = min(self.components, min(self.x.shape) - 1)
        self.svd = TruncatedSVD(n_components=n, random_state=self.seed)
        self.user_factors = self.svd.fit_transform(self.x)
        self.item_factors = self.svd.components_.T
        return self

    def recommend(self, users, k, states=None) -> dict:
        out = {}
        for u in users:
            if u in self.users:
                scores = self.item_factors @ self.user_factors[self.users.get_loc(u)]
                recs = self._top(np.clip(scores, 0, None), k)
            else:
                recs = []
            out[u] = _fill(recs, self.fallback, k)
        return out


class ContentBased:
    """Item vectors from category, price band, weight, volume and photo count; user profile =
    mean of the vectors of items they bought; score = cosine(profile, item), weighted by the
    item's recent popularity so obscure lookalikes do not dominate."""

    name = "content"

    def __init__(self, price_bands: int = 10, **_):
        self.price_bands = price_bands

    def fit(self, train: Interactions, cutoff):
        e = train.events
        self.items = pd.Index(e["item_id"].unique())
        price = e.groupby("item_id")["price"].median().reindex(self.items)  # price seen before T
        attrs = train.products.reindex(self.items)
        cats = pd.get_dummies(attrs["category_name"].fillna("unknown")).astype(float)
        band = pd.qcut(price.rank(method="first"), self.price_bands, labels=False)
        bands = pd.get_dummies(band, prefix="price").astype(float).set_axis(self.items)
        numeric = pd.DataFrame(
            {
                "log_weight": safe_log(attrs["product_weight_g"]),
                "log_volume": safe_log(attrs["product_volume_cm3"]),
                "photos": attrs["product_photos_qty"].fillna(1).to_numpy(dtype=float),
            },
            index=self.items,
        )
        numeric = (numeric - numeric.mean()) / numeric.std().replace(0, 1)
        features = pd.concat([cats * 2.0, bands, numeric * 0.5], axis=1).fillna(0)
        self.vectors = normalize(features.to_numpy())
        self.history = e.groupby("user_id")["item_id"].agg(list).to_dict()
        pop = popularity_ranking(e, cutoff, 180).reindex(self.items).fillna(0).to_numpy()
        self.pop_weight = np.log1p(pop)
        self.fallback = popularity_ranking(e, cutoff, 90)
        return self

    def recommend(self, users, k, states=None) -> dict:
        out = {}
        index = {item: i for i, item in enumerate(self.items)}
        for u in users:
            hist = [index[i] for i in self.history.get(u, []) if i in index]
            if hist:
                profile = self.vectors[hist].mean(axis=0)
                scores = (self.vectors @ profile) * self.pop_weight
                k_eff = min(k, int((scores > 0).sum()))
                idx = np.argpartition(-scores, max(k_eff - 1, 0))[:k_eff] if k_eff else []
                idx = sorted(idx, key=lambda j: -scores[j])
                recs = [(self.items[j], float(scores[j])) for j in idx]
            else:
                recs = []
            out[u] = _fill(recs, self.fallback, k)
        return out


class CategoryPopular:
    """Most popular recent products in the categories the user bought (most recent category
    first), filled with global popularity."""

    name = "category_popular"

    def __init__(self, window_days: int = 180, **_):
        self.window_days = window_days

    def fit(self, train: Interactions, cutoff):
        e = train.events
        self.fallback = popularity_ranking(e, cutoff, 90)
        self.by_category = {
            c: popularity_ranking(g, cutoff, self.window_days)
            for c, g in e.groupby("category_name")
        }
        last = e.sort_values("purchased_at", ascending=False)
        self.user_categories = (
            last.drop_duplicates(["user_id", "category_name"])
            .groupby("user_id")["category_name"]
            .agg(list)
            .to_dict()
        )
        return self

    def recommend(self, users, k, states=None) -> dict:
        out = {}
        for u in users:
            recs: list = []
            for cat in self.user_categories.get(u, []):
                recs = _fill(recs, self.by_category[cat], k)
                if len(recs) >= k:
                    break
            out[u] = _fill(recs, self.fallback, k)
        return out


MODEL_CLASSES = {
    "popularity": Popularity,
    "state_popularity": StatePopularity,
    "item_knn": ItemKNN,
    "svd": SVDRecommender,
    "content": ContentBased,
    "category_popular": CategoryPopular,
}
