"""add insa_salary_vault_policy table

연봉 금고 허용 IP 정책. 활성 행은 1개만 존재한다 (스펙 §9.2.2).

Revision ID: 20260819_0002
Revises: 20260819_0001
Create Date: 2026-08-19
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "20260819_0002"
down_revision: Union[str, None] = "20260819_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "insa_salary_vault_policy",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "owner_user_id",
            sa.Integer(),
            sa.ForeignKey("insa_user.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("allowed_ip", sa.String(45), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("updated_by", sa.Integer(), sa.ForeignKey("insa_user.id"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("insa_salary_vault_policy")
