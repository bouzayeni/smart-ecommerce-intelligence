"""Generate the Power BI project (PBIP, TMDL semantic model) and reconciliation targets.

Inputs:
    powerbi/measures.yaml              DAX measure catalog
    PostgreSQL marts (analytics role)  column names/types of imported tables; target values
Outputs (all generated, do not edit by hand):
    powerbi/OlistIntelligence.pbip
    powerbi/OlistIntelligence.SemanticModel/...   TMDL: tables, measures, relationships, M sources
    powerbi/OlistIntelligence.Report/...          report shell with the five page names
    powerbi/measures.dax                          all measures as DAX (DEFINE block)
    powerbi/documentation/reconciliation_targets.{json,md}

Usage (from the repo root):
    uv run python -m data_engineering.scripts.build_powerbi_model
"""

import argparse
import json
import logging
import sys
import uuid
from datetime import UTC, datetime
from decimal import Decimal

import psycopg
import yaml

from data_engineering.config import PROJECT_ROOT, get_settings

log = logging.getLogger("build_powerbi_model")

PBI_DIR = PROJECT_ROOT / "powerbi"
NAME = "OlistIntelligence"
MODEL_DIR = PBI_DIR / f"{NAME}.SemanticModel"
REPORT_DIR = PBI_DIR / f"{NAME}.Report"
DOC_DIR = PBI_DIR / "documentation"
NAMESPACE = uuid.UUID("6f1d3c2e-7a4b-4c8e-9a0d-2b5e8f1c3a7d")  # stable lineage tags

TABLES = [  # imported from schema marts
    "dim_date", "dim_customers", "dim_products", "dim_sellers", "dim_payment_type",
    "dim_geolocation", "fact_orders", "fact_order_items", "fact_payments", "fact_reviews",
    "kpi_customer_cohorts", "kpi_customer_concentration",
]  # fmt: skip

# (from_table.column [many side], to_table.column [one side], active)
RELATIONSHIPS = [
    ("fact_orders.customer_unique_id", "dim_customers.customer_unique_id", True),
    ("fact_orders.purchase_date_key", "dim_date.date_key", True),
    ("fact_orders.primary_payment_type", "dim_payment_type.payment_type", False),
    ("fact_order_items.product_id", "dim_products.product_id", True),
    ("fact_order_items.seller_id", "dim_sellers.seller_id", True),
    ("fact_order_items.customer_unique_id", "dim_customers.customer_unique_id", True),
    ("fact_order_items.purchase_date_key", "dim_date.date_key", True),
    ("fact_payments.payment_type", "dim_payment_type.payment_type", True),
    ("fact_payments.customer_unique_id", "dim_customers.customer_unique_id", True),
    ("fact_payments.purchase_date_key", "dim_date.date_key", True),
    ("fact_reviews.customer_unique_id", "dim_customers.customer_unique_id", True),
    ("fact_reviews.review_created_date_key", "dim_date.date_key", True),
    # Snowflake to geolocation through customers only: a second path through sellers
    # would make filters from dim_geolocation to fact_order_items ambiguous.
    ("dim_customers.customer_zip_code_prefix", "dim_geolocation.zip_code_prefix", True),
]

PAGES = [
    "Executive Overview", "Sales Performance", "Customer Analytics", "Product Analytics",
    "Logistics & Operations",
]  # fmt: skip

TYPE_MAP = {  # PostgreSQL type -> (TMDL dataType, formatString)
    "text": ("string", None),
    "character": ("string", None),
    "integer": ("int64", "0"),
    "bigint": ("int64", "0"),
    "numeric": ("double", None),  # double keeps rate precision (fixed decimal is 4 dp)
    "double precision": ("double", None),
    "boolean": ("boolean", None),
    "date": ("dateTime", "yyyy-mm-dd"),
    "timestamp without time zone": ("dateTime", "General Date"),
}


def tag(*parts: str) -> str:
    return str(uuid.uuid5(NAMESPACE, "/".join(parts)))


def quote(name: str) -> str:
    """TMDL object name: quote unless it is a plain identifier."""
    if name.replace("_", "").isalnum() and not name[0].isdigit():
        return name
    return "'" + name.replace("'", "''") + "'"


def read_columns(conn: psycopg.Connection) -> dict[str, list[tuple[str, str]]]:
    rows = conn.execute(
        "SELECT table_name, column_name, data_type FROM information_schema.columns "
        "WHERE table_schema = 'marts' AND table_name = ANY(%s) "
        "ORDER BY table_name, ordinal_position",
        (TABLES,),
    ).fetchall()
    columns: dict[str, list[tuple[str, str]]] = {t: [] for t in TABLES}
    for table, column, dtype in rows:
        columns[table].append((column, dtype))
    missing = [t for t, cols in columns.items() if not cols]
    if missing:
        raise RuntimeError(f"Tables not found in marts (run dbt build first): {missing}")
    return columns


def render_table(table: str, cols: list[tuple[str, str]], measures: list[dict]) -> str:
    lines = [f"table {table}", f"\tlineageTag: {tag('table', table)}"]
    if table == "dim_date":
        lines.append("\tdataCategory: Time")
    lines.append("")
    for m in measures:
        if m.get("description"):
            lines.append(f"\t/// {m['description']}")
        expr = m["expression"].strip()
        if "\n" in expr:
            body = "\n".join(f"\t\t\t{line}" if line else "" for line in expr.splitlines())
            lines.append(f"\tmeasure {quote(m['name'])} = ```\n{body}\n\t\t\t```")
        else:
            lines.append(f"\tmeasure {quote(m['name'])} = {expr}")
        lines.append(f"\t\tformatString: {m['format']}")
        lines.append(f"\t\tdisplayFolder: {m['folder']}")
        if m.get("hidden"):
            lines.append("\t\tisHidden")
        lines += [f"\t\tlineageTag: {tag('measure', m['name'])}", ""]
    for col, pg_type in cols:
        dtype, fmt = TYPE_MAP[pg_type]
        lines.append(f"\tcolumn {quote(col)}")
        lines.append(f"\t\tdataType: {dtype}")
        if fmt:
            lines.append(f"\t\tformatString: {fmt}")
        if table == "dim_date" and col == "date_day":
            lines.append("\t\tisKey")
        if col.endswith("_key") or col.startswith("_"):
            lines.append("\t\tisHidden")
        lines += [
            f"\t\tlineageTag: {tag('column', table, col)}",
            "\t\tsummarizeBy: none",
            f"\t\tsourceColumn: {col}",
            "",
            "\t\tannotation SummarizationSetBy = Automatic",
            "",
        ]
    lines += [
        f"\tpartition {table} = m",
        "\t\tmode: import",
        "\t\tsource =",
        "\t\t\t\tlet",
        "\t\t\t\t    Source = PostgreSQL.Database(PostgresServer, PostgresDatabase),",
        f'\t\t\t\t    Data = Source{{[Schema="marts", Item="{table}"]}}[Data]',
        "\t\t\t\tin",
        "\t\t\t\t    Data",
        "",
        "\tannotation PBI_ResultType = Table",
        "",
    ]
    return "\n".join(lines)


def write_model(columns: dict, measures: list[dict]) -> None:
    definition = MODEL_DIR / "definition"
    (definition / "tables").mkdir(parents=True, exist_ok=True)
    for old in (definition / "tables").glob("*.tmdl"):
        old.unlink()

    (MODEL_DIR / "definition.pbism").write_text(
        json.dumps({"version": "4.0", "settings": {}}, indent=2) + "\n", encoding="utf-8"
    )
    (definition / "database.tmdl").write_text(
        "database\n\tcompatibilityLevel: 1567\n", encoding="utf-8"
    )
    query_order = json.dumps(["PostgresServer", "PostgresDatabase", *TABLES])
    model = [
        "model Model",
        "\tculture: en-US",
        "\tdefaultPowerBIDataSourceVersion: powerBI_V3",
        "\tdiscourageImplicitMeasures",
        "\tsourceQueryCulture: en-US",
        "\tdataAccessOptions",
        "\t\tlegacyRedirects",
        "\t\treturnErrorValuesAsNull",
        "",
        f"annotation PBI_QueryOrder = {query_order}",
        "",
        # Disable Auto date/time: dim_date is the marked date table; hidden per-column date
        # tables would bloat the model and compete with it.
        "annotation __PBI_TimeIntelligenceEnabled = 0",
        "",
        *[f"ref table {t}" for t in TABLES],
        "",
    ]
    (definition / "model.tmdl").write_text("\n".join(model), encoding="utf-8")

    settings = get_settings()
    params = {
        "PostgresServer": f"{settings.postgres_host}:{settings.postgres_port}",
        "PostgresDatabase": settings.postgres_db,
    }
    expressions = []
    for name, value in params.items():
        expressions += [
            f'expression {name} = "{value}" meta [IsParameterQuery=true, Type="Text", '
            "IsParameterQueryRequired=true]",
            f"\tlineageTag: {tag('expression', name)}",
            "",
            "\tannotation PBI_ResultType = Text",
            "",
        ]
    (definition / "expressions.tmdl").write_text("\n".join(expressions), encoding="utf-8")

    rels = []
    for frm, to, active in RELATIONSHIPS:
        rels.append(f"relationship {tag('relationship', frm, to)}")
        if not active:
            rels.append("\tisActive: false")
        rels += [f"\tfromColumn: {frm}", f"\ttoColumn: {to}", ""]
    (definition / "relationships.tmdl").write_text("\n".join(rels), encoding="utf-8")

    by_table: dict[str, list[dict]] = {}
    for m in measures:
        by_table.setdefault(m["table"], []).append(m)
    for table in TABLES:
        (definition / "tables" / f"{table}.tmdl").write_text(
            render_table(table, columns[table], by_table.get(table, [])), encoding="utf-8"
        )


def write_report_shell() -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "definition.pbir").write_text(
        json.dumps(
            {
                "version": "4.0",
                "datasetReference": {"byPath": {"path": f"../{NAME}.SemanticModel"}},
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    sections = [
        {
            "config": "{}",
            "displayName": page,
            "displayOption": 1,
            "filters": "[]",
            "height": 720,
            "name": f"page{i:02d}",
            "ordinal": i,
            "visualContainers": [],
            "width": 1280,
        }
        for i, page in enumerate(PAGES)
    ]
    report = {
        "config": json.dumps({"version": "5.43", "activeSectionIndex": 0}),
        "layoutOptimization": 0,
        "resourcePackages": [],
        "sections": sections,
    }
    (REPORT_DIR / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    pbip = {"version": "1.0", "artifacts": [{"report": {"path": f"{NAME}.Report"}}],
            "settings": {"enableAutoRecovery": True}}  # fmt: skip
    (PBI_DIR / f"{NAME}.pbip").write_text(json.dumps(pbip, indent=2) + "\n", encoding="utf-8")


def write_dax(measures: list[dict]) -> None:
    lines = [
        "// Generated from powerbi/measures.yaml by build_powerbi_model.py. Do not edit.",
        "// Paste into DAX query view or Tabular Editor; definitions: docs/kpi_dictionary.md",
        "DEFINE",
    ]
    for m in measures:
        expr = m["expression"].strip().replace("\n", "\n        ")
        lines += [
            f"    // [{m['kpi']}] {m['folder']} | {m['description']}",
            f"    MEASURE {m['table']}[{m['name']}] =\n        {expr}",
            "",
        ]
    lines.append('EVALUATE ROW ( "GMV (BRL)", [GMV (BRL)] )')
    (PBI_DIR / "measures.dax").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _scalar(conn, sql: str) -> float | None:
    value = conn.execute(sql).fetchone()[0]
    return float(value) if isinstance(value, Decimal | int | float) else value


def write_targets(conn, measures: list[dict], columns: dict) -> list[dict]:
    targets = []
    for m in measures:
        t = m["target"]
        flt = t.get("dax_filter")
        measure_ref = f"[{m['name']}]"
        dax = f"CALCULATE ( {measure_ref}, {flt} )" if flt else measure_ref
        targets.append({
            "check": m["name"] + (f"  [{flt}]" if flt else ""),
            "kind": "measure",
            "dax": dax,
            "expected": _scalar(conn, t["sql"]),
            "tolerance": t.get("tolerance", 0.005),
            "sql": t["sql"],
        })  # fmt: skip
    for table in TABLES:
        targets.append({
            "check": f"row count {table}",
            "kind": "rowcount",
            "dax": f"COUNTROWS ( {table} )",
            "expected": _scalar(conn, f"select count(*) from marts.{table}"),
            "tolerance": 0,
            "sql": f"select count(*) from marts.{table}",
        })  # fmt: skip
    DOC_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"generated_at": datetime.now(UTC).isoformat(timespec="seconds"), "targets": targets}
    (DOC_DIR / "reconciliation_targets.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )
    md = [
        "# Power BI reconciliation targets",
        "",
        "Expected value of every measure in the default (unfiltered) context, computed with SQL",
        "on the warehouse. Generated by `build_powerbi_model.py`; checked against the live model",
        "by `powerbi/tools/Invoke-DaxChecks.ps1`. Do not edit by hand.",
        "",
        "| Check | Expected | Tolerance | SQL |",
        "|---|---|---|---|",
    ]
    for t in targets:
        exp = t["expected"]
        shown = f"{exp:,.6f}".rstrip("0").rstrip(".") if isinstance(exp, float) else exp
        md.append(f"| {t['check']} | {shown} | {t['tolerance']} | `{t['sql']}` |")
    (DOC_DIR / "reconciliation_targets.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    return targets


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--model-only", action="store_true",
        help="regenerate the semantic model, keep the existing report (visuals built in Desktop)",
    )  # fmt: skip
    args = parser.parse_args(argv)
    catalog = yaml.safe_load((PBI_DIR / "measures.yaml").read_text(encoding="utf-8"))
    measures = catalog["measures"]
    names = [m["name"] for m in measures]
    if len(names) != len(set(names)):
        raise ValueError("Duplicate measure names in measures.yaml")
    with psycopg.connect(**get_settings().psycopg_kwargs("analytics")) as conn:
        columns = read_columns(conn)
        write_model(columns, measures)
        if not args.model_only or not (REPORT_DIR / "report.json").exists():
            write_report_shell()
        write_dax(measures)
        targets = write_targets(conn, measures, columns)
    log.info("Wrote %d tables, %d measures, %d relationships, %d targets",
             len(TABLES), len(measures), len(RELATIONSHIPS), len(targets))  # fmt: skip
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sys.exit(main())
