import pandas as pd
import pytest

from data_engineering.config import PROJECT_ROOT
from data_engineering.etl.bronze import render_ddl
from data_engineering.sources import SOURCE_BY_TABLE, SOURCE_FILES
from data_engineering.validation.contracts import ContractError, read_header, validate_file

SAMPLE_DIR = PROJECT_ROOT / "data" / "sample"


def test_committed_bronze_ddl_matches_generator():
    committed = (PROJECT_ROOT / "warehouse" / "sql" / "bronze" / "001_raw_tables.sql").read_text(
        encoding="utf-8"
    )
    assert committed == render_ddl("raw"), "regenerate with load_bronze --print-ddl"


@pytest.mark.parametrize("spec", SOURCE_FILES, ids=lambda s: s.table)
def test_sample_files_satisfy_contract(spec):
    assert validate_file(spec, SAMPLE_DIR / spec.filename) > 0


def test_header_reader_strips_bom(tmp_path):
    path = tmp_path / "t.csv"
    path.write_bytes(b"\xef\xbb\xbfproduct_category_name,product_category_name_english\na,b\n")
    assert read_header(path) == ["product_category_name", "product_category_name_english"]


def _copy_with(tmp_path, table, mutate) -> tuple:
    spec = SOURCE_BY_TABLE[table]
    df = pd.read_csv(SAMPLE_DIR / spec.filename, dtype=str, keep_default_na=False)
    df = mutate(df)
    path = tmp_path / spec.filename
    df.to_csv(path, index=False)
    return spec, path


def test_missing_column_is_rejected(tmp_path):
    spec, path = _copy_with(tmp_path, "sellers", lambda d: d.drop(columns="seller_city"))
    with pytest.raises(ContractError, match="header mismatch"):
        validate_file(spec, path)


def test_malformed_identifier_is_rejected(tmp_path):
    def corrupt(d):
        d.loc[0, "order_id"] = "NOT-A-HASH"
        return d

    spec, path = _copy_with(tmp_path, "orders", corrupt)
    with pytest.raises(ContractError, match="order_id"):
        validate_file(spec, path)


def test_zip_prefix_without_leading_zero_is_rejected(tmp_path):
    def corrupt(d):
        d.loc[0, "seller_zip_code_prefix"] = "1037"  # "01037" cast to int and back
        return d

    spec, path = _copy_with(tmp_path, "sellers", corrupt)
    with pytest.raises(ContractError, match="seller_zip_code_prefix"):
        validate_file(spec, path)


def test_null_in_required_column_is_rejected(tmp_path):
    def corrupt(d):
        d.loc[0, "order_purchase_timestamp"] = ""
        return d

    spec, path = _copy_with(tmp_path, "orders", corrupt)
    with pytest.raises(ContractError, match="order_purchase_timestamp"):
        validate_file(spec, path)


def test_nullable_columns_accept_empty_values():
    # The sample contains orders with no delivery date and products with no category.
    spec = SOURCE_BY_TABLE["orders"]
    df = pd.read_csv(SAMPLE_DIR / spec.filename, dtype=str)
    assert df["order_delivered_customer_date"].isna().any()
    assert validate_file(spec, SAMPLE_DIR / spec.filename) == len(df)
