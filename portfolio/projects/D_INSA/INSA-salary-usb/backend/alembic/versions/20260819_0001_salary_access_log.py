"""add insa_salary_access_log table

연봉 금고 접근 기록. 금액·직원명 컬럼은 의도적으로 없다 (스펙 §10.2).

Revision ID: 20260819_0001
Revises: 20260502_0001
Create Date: 2026-08-19
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "20260819_0001"
down_revision: Union[str, None] = "20260502_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "insa_salary_access_log",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("insa_user.id"), nullable=False),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column(
            "target_user_id", sa.Integer(), sa.ForeignKey("insa_user.id"), nullable=True
        ),
        sa.Column("record_count", sa.Integer(), nullable=True),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.String(255), nullable=True),
        sa.Column("occurred_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "ix_salary_access_log_user_occurred",
        "insa_salary_access_log",
        ["user_id", "occurred_at"],
    )
    op.create_index(
        "ix_salary_access_log_occurred", "insa_salary_access_log", ["occurred_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_salary_access_log_occurred", table_name="insa_salary_access_log")
    op.drop_index(
        "ix_salary_access_log_user_occurred", table_name="insa_salary_access_log"
    )
    op.drop_table("insa_salary_access_log")
