"""Alembic environment: migrates the configured app schema as the app_user role."""

import sqlalchemy as sa
from alembic import context

from app.core.config import get_settings
from app.models.entities import Base

settings = get_settings()
SCHEMA = settings.app_schema
target_metadata = Base.metadata


def run_migrations_online() -> None:
    engine = sa.create_engine(
        settings.app_database_url, connect_args={"options": f"-c search_path={SCHEMA}"}
    )
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            version_table_schema=SCHEMA,
            include_schemas=False,
        )
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
