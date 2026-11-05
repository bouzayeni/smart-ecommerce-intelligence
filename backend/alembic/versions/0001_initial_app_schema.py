"""Initial app schema: users, refresh tokens, audit log, prediction log.

Revision ID: 0001
Revises:
Create Date: 2026-11-05
"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("email", sa.String(320), nullable=False, unique=True),
        sa.Column("full_name", sa.String(200), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", sa.String(20), nullable=False, server_default="viewer"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("last_login_at", TS),
        sa.CheckConstraint("role in ('viewer', 'analyst', 'admin')", name="ck_users_role"),
    )
    op.create_index("ix_users_email", "users", ["email"])
    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "user_id", sa.Uuid, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("family_id", sa.Uuid, nullable=False),
        sa.Column("expires_at", TS, nullable=False),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("revoked_at", TS),
        sa.Column("replaced_by_id", sa.Integer),
    )
    op.create_index("ix_refresh_tokens_user_id", "refresh_tokens", ["user_id"])
    op.create_index("ix_refresh_tokens_token_hash", "refresh_tokens", ["token_hash"])
    op.create_index("ix_refresh_tokens_family_id", "refresh_tokens", ["family_id"])
    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("occurred_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("user_id", sa.Uuid),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("request_id", sa.String(64)),
        sa.Column("ip_address", sa.String(64)),
        sa.Column("details", sa.JSON),
    )
    op.create_index("ix_audit_log_occurred_at", "audit_log", ["occurred_at"])
    op.create_index("ix_audit_log_user_id", "audit_log", ["user_id"])
    op.create_index("ix_audit_log_action", "audit_log", ["action"])
    op.create_table(
        "prediction_log",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("occurred_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("user_id", sa.Uuid),
        sa.Column("model_name", sa.String(100), nullable=False),
        sa.Column("model_version", sa.String(20)),
        sa.Column("mode", sa.String(20), nullable=False),
        sa.Column("customer_unique_id", sa.String(32)),
        sa.Column("inputs", sa.JSON),
        sa.Column("output", sa.JSON),
        sa.Column("latency_ms", sa.Integer),
        sa.Column("request_id", sa.String(64)),
        sa.Column("notes", sa.Text),
    )
    op.create_index("ix_prediction_log_occurred_at", "prediction_log", ["occurred_at"])
    op.create_index("ix_prediction_log_model_name", "prediction_log", ["model_name"])


def downgrade() -> None:
    for table in ("prediction_log", "audit_log", "refresh_tokens", "users"):
        op.drop_table(table)
