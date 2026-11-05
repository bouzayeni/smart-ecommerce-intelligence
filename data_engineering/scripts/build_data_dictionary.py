"""Generate docs/data_dictionary.md from the live warehouse and the dbt YAML descriptions.

Column names, types and row counts come from information_schema / count(*), so the dictionary
cannot drift from what is actually loaded. Descriptions come from the dbt `schema.yml` files
(marts, KPI views, raw sources) and, for the ml schema, from ML_TABLES below.

    uv run python -m data_engineering.scripts.build_data_dictionary
"""

import argparse
import datetime as dt
from pathlib import Path

import psycopg
import yaml

from data_engineering.config import PROJECT_ROOT, get_settings

DBT_MODELS = PROJECT_ROOT / "warehouse" / "dbt" / "models"
OUT = PROJECT_ROOT / "docs" / "data_dictionary.md"
SCHEMAS = ("raw", "marts", "ml")

SCHEMA_INTRO = {
    "raw": "Bronze: the nine Kaggle CSVs loaded unchanged, plus lineage columns (`_batch_id`, "
    "`_source_sha256`, `_source_row`, `_ingested_at`) ([ETL docs](etl_bronze.md)).",
    "marts": "Gold: the dbt star schema and KPI views ([star schema](star_schema.md), "
    "[KPI dictionary](kpi_dictionary.md)).",
    "ml": "Model outputs written by the `ml/` scripts and read by the API and Power BI "
    "([model cards](model_cards/)).",
}

# (writer, description) for tables that dbt does not build.
ML_TABLES = {
    "customer_rfm": ("ml/train_customer_models.py", "RFM features, scores and segment per "
                     "customer with a revenue order in the analysis window"),
    "customer_repurchase_scores": ("ml/train_customer_models.py", "90-day repurchase "
                                   "probability, churn risk, decile and band per customer"),
    "customer_spend_predictions": ("ml/train_customer_models.py",
                                   "Predicted 90-day spend per customer"),
    "model_metrics": ("ml/train_customer_models.py",
                      "Validation and test metrics of every customer-model candidate"),
    "model_feature_importance": ("ml/train_customer_models.py",
                                 "Mean absolute SHAP value per feature of the selected models"),
    "sales_forecast": ("ml/train_forecasting.py",
                       "Daily GMV forecast for the 90 days after the series end, per "
                       "model; `is_selected` marks the served one"),
    "sales_forecast_test": ("ml/train_forecasting.py",
                            "Forecasts over the held-out test period, for evaluation charts"),
    "forecast_metrics": ("ml/train_forecasting.py", "Backtest and test metrics per model and "
                         "horizon"),
    "daily_anomalies": ("ml/detect_anomalies.py", "Daily GMV, orders, freight per item and "
                        "cancellation rate vs expected, with Isolation Forest, z-rule and "
                        "autoencoder flags and a text explanation"),
    "anomaly_shift_episodes": ("ml/detect_anomalies.py",
                               "Sustained shifts (rolling z-score) grouped into episodes"),
    "product_recommendations": ("ml/train_recommendations.py",
                                "Top-10 products per customer from the selected model"),
    "popular_products": ("ml/train_recommendations.py",
                         "Cold-start best-seller lists, global (`ALL`) and per state"),
    "item_neighbours": ("ml/train_recommendations.py", "\"Customers also bought\" product pairs"),
    "recommendation_metrics": ("ml/train_recommendations.py",
                               "Offline evaluation of every recommender candidate"),
}  # fmt: skip


def dbt_descriptions() -> tuple[dict[str, str], dict[tuple[str, str], str]]:
    """Table and column descriptions from every YAML file under warehouse/dbt/models."""
    tables: dict[str, str] = {}
    columns: dict[tuple[str, str], str] = {}

    def take(name: str, node: dict) -> None:
        if node.get("description"):
            tables[name] = " ".join(node["description"].split())
        for col in node.get("columns") or []:
            if col.get("description"):
                columns[(name, col["name"])] = " ".join(str(col["description"]).split())

    for path in sorted(DBT_MODELS.rglob("*.yml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for model in doc.get("models") or []:
            take(model["name"], model)
        for source in doc.get("sources") or []:
            for table in source.get("tables") or []:
                take(table["name"], table)
    return tables, columns


def md_cell(text: str) -> str:
    return text.replace("|", "\\|")


def build(conn: psycopg.Connection) -> str:
    table_desc, col_desc = dbt_descriptions()
    rows = conn.execute(
        """
        select t.table_schema, t.table_name, t.table_type
        from information_schema.tables t
        where t.table_schema = any(%s)
        order by array_position(%s, t.table_schema::text), t.table_name""",
        (list(SCHEMAS), list(SCHEMAS)),
    ).fetchall()
    cols = conn.execute(
        """
        select table_schema, table_name, column_name, data_type, is_nullable
        from information_schema.columns where table_schema = any(%s)
        order by table_schema, table_name, ordinal_position""",
        (list(SCHEMAS),),
    ).fetchall()
    by_table: dict[tuple[str, str], list] = {}
    for schema, table, name, dtype, nullable in cols:
        by_table.setdefault((schema, table), []).append((name, dtype, nullable))

    out = [
        "# Data dictionary",
        "",
        f"> Generated by `data_engineering/scripts/build_data_dictionary.py` on "
        f"{dt.date.today():%Y-%m-%d} from the loaded `olist_dw` warehouse. Do not edit by hand;"
        " re-run the script after rebuilding the warehouse.",
        "",
        "Types and row counts are read from PostgreSQL. The `staging` (views) and `intermediate` "
        "dbt layers sit between `raw` and `marts` and are described in "
        "[star_schema.md](star_schema.md). "
        "The `app` schema (users, tokens, audit) is described in [api.md](api.md).",
        "",
        "## Tables",
        "",
        "| Schema | Table | Kind | Rows | Description |",
        "|---|---|---|---|---|",
    ]
    details = []
    for schema, table, kind in rows:
        if table.startswith("_"):
            continue  # ingestion bookkeeping
        is_view = kind == "VIEW"
        n = (
            "view"
            if is_view
            else f"{conn.execute(f'select count(*) from {schema}.{table}').fetchone()[0]:,}"
        )
        if schema == "ml":
            writer, desc = ML_TABLES.get(table, ("", ""))
            desc = f"{desc} (`{writer}`)" if writer else desc
        else:
            desc = table_desc.get(table, "")
        anchor = f"{schema}{table}"  # GitHub drops the dot in "schema.table"
        out.append(
            f"| `{schema}` | [{table}](#{anchor}) | {'view' if is_view else 'table'} | {n} | "
            f"{md_cell(desc)} |"
        )
        details.append((schema, table, desc, by_table.get((schema, table), [])))

    for schema in SCHEMAS:
        out += ["", f"## `{schema}`", "", SCHEMA_INTRO[schema]]
        for s, table, desc, columns in details:
            if s != schema:
                continue
            out += ["", f"### {schema}.{table}", ""]
            if desc:
                out += [md_cell(desc), ""]
            out += ["| Column | Type | Nullable | Description |", "|---|---|---|---|"]
            for name, dtype, nullable in columns:
                d = col_desc.get((table, name), "")
                out.append(f"| `{name}` | {dtype} | {'yes' if nullable == 'YES' else 'no'} | "
                           f"{md_cell(d)} |")  # fmt: skip
    return "\n".join(out) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()
    with psycopg.connect(**get_settings().psycopg_kwargs("etl")) as conn:
        text = build(conn)
    args.out.write_text(text, encoding="utf-8")
    print(f"wrote {args.out} ({text.count(chr(10))} lines)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
