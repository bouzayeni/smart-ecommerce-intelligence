"""Static checks on the Power BI measure catalog and the generated semantic model."""

import json
import re

import yaml

from data_engineering.config import PROJECT_ROOT
from data_engineering.scripts import build_powerbi_model as b

PBI = PROJECT_ROOT / "powerbi"
CATALOG = yaml.safe_load((PBI / "measures.yaml").read_text(encoding="utf-8"))["measures"]
DAX_FUNCTIONS = {"TOPN", "FILTER", "VALUES", "CALCULATE", "SUM", "COUNT", "RANK", "MEDIAN"}


def test_every_measure_has_required_fields_and_a_target():
    for m in CATALOG:
        for key in ("name", "table", "folder", "format", "kpi", "description", "expression"):
            assert m.get(key), f"{m.get('name')}: missing {key}"
        assert m["table"] in b.TABLES, m["name"]
        assert "sql" in m["target"], m["name"]


def test_measure_names_are_unique():
    names = [m["name"] for m in CATALOG]
    assert len(names) == len(set(names))


def test_variables_do_not_shadow_dax_functions():
    # A VAR named like a function (e.g. "TopN") is a DAX syntax error (found in Phase 5).
    for m in CATALOG:
        for var in re.findall(r"\bVAR\s+(\w+)", m["expression"]):
            assert var.upper() not in DAX_FUNCTIONS, f"{m['name']}: VAR {var}"


def test_referenced_measures_exist():
    names = {m["name"] for m in CATALOG}
    for m in CATALOG:
        for ref in re.findall(r"(?<![\w\]])\[([^\]]+)\]", m["expression"]):
            if not ref.startswith("@"):
                assert ref in names, f"{m['name']} references unknown measure [{ref}]"


def test_revenue_measures_apply_standard_filters():
    # Base revenue aggregations must carry both standard filters (BR-02, BR-03).
    for m in CATALOG:
        expr = m["expression"]
        if re.search(r"SUM \( fact_(orders|order_items)\[(gmv|price_total)\]", expr):
            assert "is_revenue_order] = TRUE" in expr, m["name"]
            assert "is_in_analysis_window] = TRUE" in expr, m["name"]


def test_relationships_form_a_star_without_fact_to_fact_links():
    for frm, to, _ in b.RELATIONSHIPS:
        assert not (frm.startswith("fact_") and to.startswith("fact_")), (frm, to)
        assert frm.split(".")[0] in b.TABLES and to.split(".")[0] in b.TABLES


def test_generated_model_matches_catalog():
    tables_dir = PBI / f"{b.NAME}.SemanticModel" / "definition" / "tables"
    text = "\n".join(p.read_text(encoding="utf-8") for p in tables_dir.glob("*.tmdl"))
    for m in CATALOG:
        assert f"measure {b.quote(m['name'])} =" in text, f"{m['name']} missing: regenerate"
    targets = json.loads((PBI / "documentation" / "reconciliation_targets.json").read_text())
    assert {t["check"].split("  [")[0] for t in targets["targets"] if t["kind"] == "measure"} == {
        m["name"] for m in CATALOG
    }


def test_quote_handles_special_names():
    assert b.quote("fact_orders") == "fact_orders"
    assert b.quote("GMV (BRL)") == "'GMV (BRL)'"
    assert b.quote("O'Brien") == "'O''Brien'"
