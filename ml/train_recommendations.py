"""Train and evaluate product recommenders, write serving tables, regenerate the model card.

Selection (validation window): best model for returning customers by NDCG@K; best cold-start
popularity variant by hit rate@K. Both are then evaluated once on the test window, refit on
all purchases, and used to write:
    ml.product_recommendations   top-K per customer
    ml.popular_products          cold-start lists (global + per state)
    ml.item_neighbours           "customers also bought" per product
    ml.recommendation_metrics    validation + test metrics

Usage (from the repo root):
    uv run --all-groups python -m ml.train_recommendations
"""

import argparse
import logging
import sys
from datetime import UTC, datetime
from itertools import product

import mlflow
import numpy as np
import pandas as pd

from data_engineering.config import PROJECT_ROOT
from ml import tracking
from ml.io import replace_table
from ml.recommend.config import get_rec_config
from ml.recommend.data import ground_truth, load_interactions, user_states
from ml.recommend.evaluation import evaluate
from ml.recommend.models import MODEL_CLASSES, ItemKNN, popularity_ranking

log = logging.getLogger("train_recommendations")
CARD = PROJECT_ROOT / "docs" / "model_cards" / "recommendations.md"
COLD_FAMILIES = ("popularity", "state_popularity")


def grid(spec: dict) -> list[dict]:
    keys = list(spec)
    values = [v if isinstance(v, list) else [v] for v in spec.values()]
    return [dict(zip(keys, combo, strict=True)) for combo in product(*values)]


def build(family: str, params: dict, seed: int):
    cls = MODEL_CLASSES[family]
    return cls(**params, seed=seed) if family == "svd" else cls(**params)


def split_users(data, window, cfg):
    """Truth for returning (warm) and first-time (cold) buyers in the window."""
    train = data.before(window.cutoff)
    test_events = data.between(window.cutoff, window.end)
    known = set(train.events["user_id"])
    truth = ground_truth(test_events)
    warm = {u: s for u, s in truth.items() if u in known}
    cold = {u: s for u, s in truth.items() if u not in known}
    # Cold users: state of their first order in the window (known at request time).
    states = {
        **user_states(train.events),
        **user_states(test_events[~test_events["user_id"].isin(known)]),
    }
    return train, warm, cold, states


def run_window(data, window, cfg, families, label, item_category) -> pd.DataFrame:
    train, warm, cold, states = split_users(data, window, cfg)
    candidates = train.events["item_id"].nunique()
    rows = []
    for family, params in families:
        model = build(family, params, cfg.random_state).fit(train, window.cutoff)
        for segment, truth in (("returning", warm), ("first_time", cold)):
            if segment == "first_time" and family not in COLD_FAMILIES:
                continue  # every non-popularity model falls back to popularity for them
            recs = model.recommend(list(truth), cfg.k, states)
            m = evaluate(
                recs,
                truth,
                cfg.k,
                item_category,
                candidates,
                cfg.bootstrap_resamples,
                cfg.random_state,
            )
            rows.append(
                {
                    "split": label,
                    "segment": segment,
                    "family": family,
                    "params": str(params),
                    "params_dict": params,
                    **m,
                }
            )
            log.info(
                "%-10s %-10s %-17s %-28s hit@%d=%.4f ndcg=%.4f cat_hit=%.3f users=%d",
                label,
                segment,
                family,
                params,
                cfg.k,
                m[f"hit_rate@{cfg.k}"],
                m[f"ndcg@{cfg.k}"],
                m[f"category_hit_rate@{cfg.k}"],
                m["users"],
            )
    return pd.DataFrame(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--no-db-write", action="store_true")
    args = parser.parse_args(argv)

    cfg = get_rec_config()
    data = load_interactions()
    item_category = data.products["category_name"].to_dict()
    k = cfg.k
    tracking.setup("recommendations")
    ts = datetime.now(UTC)

    with mlflow.start_run(run_name=f"recommendations-{ts:%Y%m%d-%H%M}") as run:
        mlflow.log_params(
            {
                "k": k,
                "validation_cutoff": str(cfg.validation.cutoff),
                "test_cutoff": str(cfg.test.cutoff),
                "exclude_purchased": cfg.exclude_purchased,
            }
        )
        mlflow.log_dict(tracking.data_fingerprint(), "data_fingerprint.json")

        all_configs = [(f, p) for f, spec in cfg.models.items() for p in grid(spec)]
        val = run_window(data, cfg.validation, cfg, all_configs, "validation", item_category)

        def best(segment: str, metric: str, families=None):
            rows = val[val["segment"] == segment]
            if families:
                rows = rows[rows["family"].isin(families)]
            return rows.sort_values(metric, ascending=False).iloc[0]

        best_warm = best("returning", f"ndcg@{k}")
        best_cold = best("first_time", f"hit_rate@{k}", COLD_FAMILIES)
        per_family = val[val["segment"] == "returning"].sort_values(f"ndcg@{k}", ascending=False)
        per_family = per_family.drop_duplicates("family")
        test_configs = [(r.family, r.params_dict) for r in per_family.itertuples()]
        test_configs += [(best_cold.family, best_cold.params_dict)]
        test_configs = list({(f, str(p)): (f, p) for f, p in test_configs}.values())
        test = run_window(data, cfg.test, cfg, test_configs, "test", item_category)
        metrics = pd.concat([val, test], ignore_index=True)

        mlflow.log_params(
            {
                "selected_returning": f"{best_warm.family} {best_warm.params}",
                "selected_first_time": f"{best_cold.family} {best_cold.params}",
            }
        )
        for _, r in test.iterrows():
            prefix = f"test_{r['segment']}_{r['family']}"
            mlflow.log_metrics(
                {
                    f"{prefix}_hit_rate": r[f"hit_rate@{k}"],
                    f"{prefix}_ndcg": r[f"ndcg@{k}"],
                    f"{prefix}_category_hit_rate": r[f"category_hit_rate@{k}"],
                }
            )
        run_id = run.info.run_id

    # ------------------------------------------------------------------ serving
    full = data.before(cfg.test.end)
    end = pd.Timestamp(cfg.test.end)
    warm_model = build(best_warm.family, best_warm.params_dict, cfg.random_state).fit(full, end)
    customers = sorted(full.events["user_id"].unique())
    states = user_states(full.events)
    recs = warm_model.recommend(customers, k, states)
    rec_rows = [
        (u, rank, item, score)
        for u, items in recs.items()
        for rank, (item, score) in enumerate(items[:k], start=1)
    ]
    rec_df = pd.DataFrame(rec_rows, columns=["customer_unique_id", "rank", "product_id", "score"])
    rec_df["category_name"] = rec_df["product_id"].map(item_category)
    rec_df = rec_df.assign(
        strategy=f"{best_warm.family} {best_warm.params}", run_id=run_id, generated_at=ts
    )

    cold_window = best_cold.params_dict["window_days"]
    size = cfg.serving.popular_list_size
    groups = [("ALL", full.events), *full.events.groupby("state")]
    popular = []
    for state, events in groups:
        ranking = popularity_ranking(events, end, cold_window).head(size)
        popular += [(state, r, i, float(s)) for r, (i, s) in enumerate(ranking.items(), 1)]
    pop_df = pd.DataFrame(popular, columns=["state", "rank", "product_id", "score"])
    pop_df["category_name"] = pop_df["product_id"].map(item_category)
    pop_df = pop_df.assign(window_days=cold_window, run_id=run_id, generated_at=ts)

    knn = ItemKNN(neighbours=cfg.serving.item_neighbours).fit(full, end)
    nb_rows = []
    for i, item in enumerate(knn.items):
        row = knn.sim.getrow(i)
        for rank, j in enumerate(np.argsort(-row.data, kind="stable"), start=1):
            nb_rows.append((item, rank, knn.items[row.indices[j]], float(row.data[j])))
    nb_df = pd.DataFrame(
        nb_rows, columns=["product_id", "rank", "neighbour_product_id", "similarity"]
    ).assign(run_id=run_id, generated_at=ts)

    if not args.no_db_write:
        for name, df in [
            ("product_recommendations", rec_df),
            ("popular_products", pop_df),
            ("item_neighbours", nb_df),
            (
                "recommendation_metrics",
                metrics.drop(columns="params_dict").assign(run_id=run_id, generated_at=ts),
            ),
        ]:
            log.info("Wrote ml.%s (%d rows)", name, replace_table(df, name))

    write_card(cfg, data, metrics, best_warm, best_cold, rec_df, nb_df, run_id, ts)
    log.info(
        "Done. returning: %s %s | first-time: %s %s | run %s",
        best_warm.family,
        best_warm.params,
        best_cold.family,
        best_cold.params,
        run_id,
    )
    return 0


def _md(df: pd.DataFrame) -> str:
    cols = list(df.columns)
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for row in df.itertuples(index=False):
        lines.append(
            "| " + " | ".join(f"{v:.4f}" if isinstance(v, float) else str(v) for v in row) + " |"
        )
    return "\n".join(lines)


def write_card(cfg, data, metrics, best_warm, best_cold, rec_df, nb_df, run_id, ts):
    k = cfg.k
    cols = [
        "segment",
        "family",
        "params",
        f"hit_rate@{k}",
        f"hit_rate@{k}_ci_low",
        f"hit_rate@{k}_ci_high",
        f"ndcg@{k}",
        f"precision@{k}",
        f"recall@{k}",
        f"map@{k}",
        f"category_hit_rate@{k}",
        "catalog_coverage",
        "users",
    ]
    val = metrics.query("split == 'validation'").sort_values(
        ["segment", f"ndcg@{k}"], ascending=[False, False]
    )[cols]
    test = metrics.query("split == 'test'").sort_values(
        ["segment", f"ndcg@{k}"], ascending=[False, False]
    )[cols]
    t_warm = test.query("segment == 'returning'")
    sel = t_warm[(t_warm["family"] == best_warm.family)
                 & (t_warm["params"] == best_warm.params)].iloc[0]  # fmt: skip
    # Several popularity configs can reach the test (best for returning, best for first-time
    # buyers); compare against the strongest one, the conservative choice.
    pop = t_warm[t_warm["family"] == "popularity"].sort_values(f"hit_rate@{k}").iloc[-1]
    best_cat = t_warm.sort_values(f"category_hit_rate@{k}").iloc[-1]
    if sel[f"hit_rate@{k}_ci_low"] > pop[f"hit_rate@{k}"]:
        outcome = "beats"
    elif pop[f"hit_rate@{k}_ci_low"] > sel[f"hit_rate@{k}"]:
        outcome = "is worse than"
    else:
        outcome = "is not distinguishable from"
    train_test = data.before(cfg.test.cutoff)
    unseen = (
        ~data.between(cfg.test.cutoff, cfg.test.end)["item_id"].isin(
            set(train_test.events["item_id"])
        )
    ).mean()
    CARD.write_text(
        f"""# Model card — Product recommendations

> Generated by `ml/train_recommendations.py` on {ts:%Y-%m-%d} from MLflow run `{run_id}`.
> Re-run to refresh.

## Task

- **Recommend {k} products per customer**, from purchases of revenue orders in the analysis
  window.
- **Products are anonymised in Olist**: there are no names, only ids, categories and
  physical attributes.

## Evaluation design

- **Temporal split.** Models are fitted on purchases before the cutoff and evaluated on purchases
  in [cutoff, end).
  - Validation window: {cfg.validation.cutoff} → {cfg.validation.end}, used for selection.
  - Test window: {cfg.test.cutoff} → {cfg.test.end}, used once.
- **Candidates are only products sold before the cutoff.** A product's listing date is
  unknown, so recommending one first sold later would leak its existence. In the test window
  **{unseen:.1%} of purchased items were never sold before the cutoff**, which caps
  product-level recall for every model.
- **Two segments:**
  - **returning** customers have purchases before the cutoff. All models are evaluated on them.
  - **first-time** customers have no history; they get popularity (global or by the state of
    their order).
- **Already-bought products remain eligible** (`exclude_purchased: {cfg.exclude_purchased}`):
  11.5% of returning buyers in the test window re-bought a product they had bought before.
- **Metrics:**
  - hit rate (one or more bought items in the top {k}), Precision, Recall, MAP and NDCG @{k}
  - **category hit rate**: one or more of the top-{k} items' categories was bought
  - catalogue coverage
  - 95% bootstrap CIs over users

## Validation

{_md(val)}

**Selected:**
- returning customers: **{best_warm.family} {best_warm.params}** (best NDCG@{k})
- first-time customers: **{best_cold.family} {best_cold.params}** (best hit rate@{k})

## Test

{_md(test)}

**Verdict (returning customers):** the selected model ({best_warm.family}, hit rate@{k}
{sel[f"hit_rate@{k}"]:.3f}, CI {sel[f"hit_rate@{k}_ci_low"]:.3f}–{sel[f"hit_rate@{k}_ci_high"]:.3f})
**{outcome}** plain popularity (hit rate@{k} {pop[f"hit_rate@{k}"]:.3f}, CI
{pop[f"hit_rate@{k}_ci_low"]:.3f}–{pop[f"hit_rate@{k}_ci_high"]:.3f}), on
{int(sel["users"])} returning buyers. Product-level hit rates are very low for every model, as
the data predicts: about 97% of customers buy once and co-purchase data is extremely sparse.

**Trade-off at category level:** {best_cat["family"]} {best_cat["params"]} has the highest
category hit rate ({best_cat[f"category_hit_rate@{k}"]:.1%}) vs
{sel[f"category_hit_rate@{k}"]:.1%} for the selected model. Personalised models find the
exact product more often; broad best-seller lists land in a category the customer buys more
often. A UI can use both: personalised products plus "popular in categories you like".

## Serving tables (refit on all purchases up to {cfg.test.end})

- `ml.product_recommendations`: {rec_df["customer_unique_id"].nunique():,} customers ×
  {k} products, from the selected returning-customer model.
- `ml.popular_products`: cold-start lists, global ("ALL") and per state.
- `ml.item_neighbours`: "customers also bought" lists ({len(nb_df):,} pairs). Most products
  have no co-purchase neighbours.

## Limitations

- **Small evaluation population.** Only a few hundred returning buyers are evaluable per
  window, hence the wide CIs.
- **Implicit feedback only.** Purchases, no views or carts, so negatives are unknown and the
  metrics are pessimistic.
- **State-based cold start** uses the state of the order being placed, assumed known at
  request time (shipping address).
- **Historical data.** The recommendations describe the end of the 2018 extract.
""",
        encoding="utf-8",
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("mlflow").setLevel(logging.WARNING)
    sys.exit(main())
