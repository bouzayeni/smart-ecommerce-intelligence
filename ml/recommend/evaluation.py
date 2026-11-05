"""Ranking metrics at K, at product and category level, with bootstrap CIs over users."""

import numpy as np
import pandas as pd


def user_metrics(recommended: list[str], relevant: set[str], k: int) -> dict[str, float]:
    rec = recommended[:k]
    hits = [1.0 if r in relevant else 0.0 for r in rec]
    n_hit = sum(hits)
    dcg = sum(h / np.log2(i + 2) for i, h in enumerate(hits))
    idcg = sum(1 / np.log2(i + 2) for i in range(min(len(relevant), k)))
    precisions = [sum(hits[: i + 1]) / (i + 1) for i, h in enumerate(hits) if h]
    return {
        "precision": n_hit / k,
        "recall": n_hit / len(relevant) if relevant else 0.0,
        "ndcg": dcg / idcg if idcg else 0.0,
        "map": sum(precisions) / min(len(relevant), k) if relevant else 0.0,
        "hit_rate": float(n_hit > 0),
    }


def _dedupe(values: list) -> list:
    seen, out = set(), []
    for v in values:
        if v not in seen:
            seen.add(v)
            out.append(v)
    return out


def evaluate(
    recs: dict,
    truth: dict[str, set],
    k: int,
    item_category: dict,
    candidate_count: int,
    n_boot: int = 500,
    seed: int = 0,
) -> dict:
    """Mean metrics over users in `truth`; category-level metrics use the categories of the
    recommended items (deduplicated) against the categories bought."""
    rows = []
    for user, relevant in truth.items():
        items = [i for i, _ in recs[user]]
        m = user_metrics(items, relevant, k)
        rec_cats = _dedupe([item_category.get(i) for i in items[:k]])
        rel_cats = {item_category.get(i) for i in relevant}
        c = user_metrics(rec_cats, rel_cats, k)
        rows.append({**m, "category_hit_rate": c["hit_rate"], "category_ndcg": c["ndcg"]})
    df = pd.DataFrame(rows)
    out = {f"{m}@{k}": float(df[m].mean()) for m in df.columns}
    rng = np.random.default_rng(seed)
    for metric in ("hit_rate", "ndcg", "category_hit_rate"):
        values = df[metric].to_numpy()
        boots = [values[rng.integers(0, len(values), len(values))].mean() for _ in range(n_boot)]
        out[f"{metric}@{k}_ci_low"], out[f"{metric}@{k}_ci_high"] = map(
            float, np.quantile(boots, [0.025, 0.975])
        )
    recommended_items = {i for r in recs.values() for i, _ in r[:k]}
    out["catalog_coverage"] = len(recommended_items) / candidate_count if candidate_count else 0.0
    out["users"] = len(df)
    return out
