import pytest
from pydantic import SecretStr

from data_engineering.config import Settings


def test_database_url_escapes_special_characters_in_password():
    settings = Settings(etl_db_user="etl", etl_db_password=SecretStr("p@ss:w/rd#1"))
    url = settings.database_url("etl")
    assert url.password == "p@ss:w/rd#1"
    assert "p%40ss%3Aw%2Frd%231" in url.render_as_string(hide_password=False)


def test_database_url_selects_role_credentials():
    settings = Settings(analytics_db_user="ro", analytics_db_password=SecretStr("x"))
    assert settings.database_url("analytics").username == "ro"


def test_database_url_rejects_unknown_role():
    with pytest.raises(ValueError, match="Unknown database role"):
        Settings().database_url("superuser")
