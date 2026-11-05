"""Central settings, loaded from environment variables and the repo-level .env file."""

from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    data_dir: Path = PROJECT_ROOT / "data"

    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "olist_dw"

    etl_db_user: str = "etl_user"
    etl_db_password: SecretStr = SecretStr("")
    analytics_db_user: str = "analytics_ro"
    analytics_db_password: SecretStr = SecretStr("")

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def sample_dir(self) -> Path:
        return self.data_dir / "sample"

    def _credentials(self, role: str) -> tuple[str, SecretStr]:
        users = {
            "etl": (self.etl_db_user, self.etl_db_password),
            "analytics": (self.analytics_db_user, self.analytics_db_password),
        }
        if role not in users:
            raise ValueError(f"Unknown database role {role!r}; expected one of {sorted(users)}")
        return users[role]

    def psycopg_kwargs(self, role: str = "etl") -> dict[str, str | int]:
        """Keyword arguments for psycopg.connect (used where COPY is needed)."""
        user, password = self._credentials(role)
        return {
            "host": self.postgres_host,
            "port": self.postgres_port,
            "dbname": self.postgres_db,
            "user": user,
            "password": password.get_secret_value(),
        }

    def database_url(self, role: str = "etl") -> URL:
        """SQLAlchemy URL for a given role ("etl" or "analytics").

        URL.create escapes special characters in passwords, unlike string formatting.
        """
        user, password = self._credentials(role)
        return URL.create(
            "postgresql+psycopg",
            username=user,
            password=password.get_secret_value(),
            host=self.postgres_host,
            port=self.postgres_port,
            database=self.postgres_db,
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
