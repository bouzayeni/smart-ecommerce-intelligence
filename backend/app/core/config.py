"""API settings from environment variables / the repo-level .env file."""

from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict
from sqlalchemy.engine import URL

REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    environment: str = "development"
    app_name: str = "Smart E-Commerce Intelligence API"

    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "olist_dw"
    # Read-only role for marts/ml (BI, API reads, assistant).
    analytics_db_user: str = "analytics_ro"
    analytics_db_password: SecretStr = SecretStr("")
    # Read/write role for the app schema (users, tokens, audit).
    app_db_user: str = "app_user"
    app_db_password: SecretStr = SecretStr("")
    app_schema: str = "app"

    jwt_secret_key: SecretStr = SecretStr("")
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = Field(15, ge=1, le=120)
    jwt_refresh_token_expire_days: int = Field(7, ge=1, le=90)

    # Comma-separated in .env (NoDecode: skip pydantic-settings JSON parsing for lists).
    cors_allowed_origins: Annotated[list[str], NoDecode] = ["http://localhost:5173"]
    rate_limit_default: str = "120/minute"
    rate_limit_auth: str = "10/minute"

    # AI assistant (Phase 11)
    llm_provider: str = "anthropic"
    anthropic_api_key: SecretStr = SecretStr("")
    anthropic_model: str = "claude-opus-5-5"
    assistant_effort: str = Field("medium", pattern="^(low|medium|high|xhigh|max)$")
    assistant_max_iterations: int = Field(6, ge=1, le=12)
    assistant_timeout_s: float = Field(120, ge=5, le=600)
    rate_limit_assistant: str = "20/minute"

    mlflow_tracking_uri: str = ""
    # Containers: directory of exported champion models (ml/export_serving_models.py).
    serving_models_dir: Path | None = None
    data_quality_results_path: Path = (
        REPO_ROOT / "data" / "processed" / "quality" / "dq_results.json"
    )

    @field_validator("cors_allowed_origins", mode="before")
    @classmethod
    def split_origins(cls, v):
        return [o.strip() for o in v.split(",") if o.strip()] if isinstance(v, str) else v

    @field_validator("jwt_secret_key")
    @classmethod
    def secret_is_strong(cls, v: SecretStr) -> SecretStr:
        if len(v.get_secret_value()) < 32:
            raise ValueError("JWT_SECRET_KEY must be set and at least 32 characters long")
        return v

    def _url(self, user: str, password: SecretStr) -> URL:
        return URL.create(
            "postgresql+psycopg",
            username=user,
            password=password.get_secret_value(),
            host=self.postgres_host,
            port=self.postgres_port,
            database=self.postgres_db,
        )

    @property
    def read_database_url(self) -> URL:
        return self._url(self.analytics_db_user, self.analytics_db_password)

    @property
    def app_database_url(self) -> URL:
        return self._url(self.app_db_user, self.app_db_password)


@lru_cache
def get_settings() -> Settings:
    return Settings()
