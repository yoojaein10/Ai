"""add insa_notification

Revision ID: 20260417_0001
Revises: 1a8ecc869a8b
Create Date: 2026-04-17
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260417_0001"
down_revision: Union[str, None] = "1a8ecc869a8b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "insa_notification",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("insa_user.id"), nullable=False),
        sa.Column("type", sa.String(length=50), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("message", sa.String(length=500), nullable=True),
        sa.Column("link", sa.String(length=300), nullable=True),
        sa.Column("is_read", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_insa_notification_user_id", "insa_notification", ["user_id"])
    op.create_index("ix_insa_notification_is_read", "insa_notification", ["is_read"])
    op.create_index("ix_insa_notification_created_at", "insa_notification", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_insa_notification_created_at", table_name="insa_notification")
    op.drop_index("ix_insa_notification_is_read", table_name="insa_notification")
    op.drop_index("ix_insa_notification_user_id", table_name="insa_notification")
    op.drop_table("insa_notification")
