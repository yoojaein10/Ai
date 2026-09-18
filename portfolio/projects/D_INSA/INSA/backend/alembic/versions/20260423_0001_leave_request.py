"""add holiday + leave request detail (PHASE 15)

Revision ID: 20260423_0001
Revises: 20260422_0001
Create Date: 2026-04-23
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260423_0001"
down_revision: Union[str, None] = "20260422_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "insa_holiday",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column(
            "is_recurring",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=True,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("date", name="uq_holiday_date"),
    )
    op.create_index("ix_insa_holiday_date", "insa_holiday", ["date"])

    op.create_table(
        "insa_leave_request_detail",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "doc_id",
            sa.Integer(),
            sa.ForeignKey("insa_approval_doc.id"),
            nullable=False,
        ),
        sa.Column(
            "leave_type_id",
            sa.Integer(),
            sa.ForeignKey("insa_leave_type.id"),
            nullable=False,
        ),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("half_type", sa.String(length=3), nullable=True),
        sa.Column("days", sa.Numeric(4, 1), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.Column(
            "delegate_emp_id",
            sa.Integer(),
            sa.ForeignKey("insa_employee.id"),
            nullable=True,
        ),
        sa.Column("contact_during_leave", sa.String(length=50), nullable=True),
        sa.Column("evidence_file_url", sa.String(length=500), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=True,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("doc_id", name="uq_leave_request_doc"),
    )
    op.create_index(
        "ix_insa_leave_request_detail_doc_id",
        "insa_leave_request_detail",
        ["doc_id"],
    )
    op.create_index(
        "ix_insa_leave_request_detail_start_date",
        "insa_leave_request_detail",
        ["start_date"],
    )
    op.create_index(
        "ix_insa_leave_request_detail_end_date",
        "insa_leave_request_detail",
        ["end_date"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_insa_leave_request_detail_end_date",
        table_name="insa_leave_request_detail",
    )
    op.drop_index(
        "ix_insa_leave_request_detail_start_date",
        table_name="insa_leave_request_detail",
    )
    op.drop_index(
        "ix_insa_leave_request_detail_doc_id",
        table_name="insa_leave_request_detail",
    )
    op.drop_table("insa_leave_request_detail")
    op.drop_index("ix_insa_holiday_date", table_name="insa_holiday")
    op.drop_table("insa_holiday")
