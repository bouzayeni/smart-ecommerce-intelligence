"""Assistant audit log.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-05
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "assistant_log",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "occurred_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("user_id", sa.Uuid),
        sa.Column("question", sa.Text, nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("answer", sa.Text),
        sa.Column("model", sa.String(64)),
        sa.Column("tool_calls", sa.JSON),
        sa.Column("iterations", sa.Integer, nullable=False, server_default="0"),
        sa.Column("input_tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Integer),
        sa.Column("request_id", sa.String(64)),
        sa.Column("error", sa.Text),
    )
    op.create_index("ix_assistant_log_occurred_at", "assistant_log", ["occurred_at"])
    op.create_index("ix_assistant_log_user_id", "assistant_log", ["user_id"])


def downgrade() -> None:
    op.drop_table("assistant_log")
