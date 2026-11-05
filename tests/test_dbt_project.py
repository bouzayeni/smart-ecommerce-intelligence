"""Static checks on the dbt project (no database needed)."""

import csv

import yaml

from data_engineering.business_rules import get_rules
from data_engineering.config import PROJECT_ROOT

DBT_DIR = PROJECT_ROOT / "warehouse" / "dbt"


def _yaml(path):
    return yaml.safe_load((DBT_DIR / path).read_text(encoding="utf-8"))


def test_dbt_vars_mirror_business_rules():
    v = _yaml("dbt_project.yml")["vars"]
    r = get_rules()
    assert v["analysis_start"] == str(r.analysis_window.start)
    assert v["analysis_end"] == str(r.analysis_window.end_override)
    assert v["revenue_statuses"] == r.revenue.include_statuses
    assert v["payment_reconciliation_tolerance_brl"] == r.payments.reconciliation_tolerance_brl
    assert v["payment_type_map"] == r.payments.payment_type_map
    assert v["delivery_cohort_maturity_days"] == r.delivery.cohort_maturity_days
    assert (
        v["shipping_limit_max_days_after_purchase"]
        == r.quality.shipping_limit_max_days_after_purchase
    )
    assert v["brazil_bbox"] == r.quality.brazil_bbox.model_dump()
    assert v["unknown_category"] == r.products.unknown_category


def test_translation_seed_mirrors_business_rules():
    with (DBT_DIR / "seeds" / "category_translation_extra.csv").open(encoding="utf-8") as fh:
        seed = {row["product_category_name"]: row["product_category_name_english"]
                for row in csv.DictReader(fh)}  # fmt: skip
    assert seed == get_rules().products.extra_translations


def test_payment_type_seed_covers_mapped_types():
    with (DBT_DIR / "seeds" / "payment_types.csv").open(encoding="utf-8") as fh:
        seeded = {row["payment_type"] for row in csv.DictReader(fh)}
    mapped = set(get_rules().payments.payment_type_map.values())
    assert mapped | {"credit_card", "debit_card", "boleto", "voucher"} == seeded


def test_every_dimension_and_fact_has_enforced_contract_and_primary_key():
    models = {m["name"]: m for m in _yaml("models/marts/_marts.yml")["models"]}
    star = [n for n in models if n.startswith(("dim_", "fact_"))]
    assert len(star) == 10
    for name in star:
        m = models[name]
        assert m["config"]["contract"]["enforced"] is True, name
        assert any(c["type"] == "primary_key" for c in m["constraints"]), name
        assert all("data_type" in col for col in m["columns"]), name
        sql_file = DBT_DIR / "models" / "marts" / f"{name}.sql"
        assert sql_file.is_file(), name


def test_profiles_contain_no_literal_credentials():
    outputs = _yaml("profiles.yml")["olist_warehouse"]["outputs"]
    for target in outputs.values():
        for key in ("user", "password", "dbname"):
            assert "env_var(" in str(target[key]), f"{key} must come from env_var"
