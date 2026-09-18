"""add travel order detail + companion + report (PHASE 16)

Revision ID: 20260424_0001
Revises: 20260423_0001
Create Date: 2026-04-24
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260424_0001"
down_revision: Union[str, None] = "20260423_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "insa_travel_order_detail",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "doc_id",
            sa.Integer(),
            sa.ForeignKey("insa_approval_doc.id"),
            nullable=False,
        ),
        sa.Column(
            "travel_type",
            sa.String(length=10),
            nullable=False,
            server_default="DOMESTIC",
        ),
        sa.Column("purpose", sa.String(length=500), nullable=False),
        sa.Column("destination", sa.String(length=200), nullable=False),
        sa.Column("client_company", sa.String(length=200), nullable=True),
        sa.Column("start_at", sa.DateTime(), nullable=False),
        sa.Column("end_at", sa.DateTime(), nullable=False),
        sa.Column("transportation", sa.String(length=100), nullable=True),
        sa.Column("estimated_cost", sa.Numeric(12, 0), nullable=True),
        sa.Column("project_code", sa.String(length=50), nullable=True),
        sa.Column("appraisal_case_no", sa.String(length=100), nullable=True),
        sa.Column("remarks", sa.String(length=500), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=True,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("doc_id", name="uq_travel_order_doc"),
    )
    op.create_index(
        "ix_insa_travel_order_detail_doc_id",
        "insa_travel_order_detail",
        ["doc_id"],
    )
    op.create_index(
        "ix_insa_travel_order_detail_start_at",
        "insa_travel_order_detail",
        ["start_at"],
    )
    op.create_index(
        "ix_insa_travel_order_detail_end_at",
        "insa_travel_order_detail",
        ["end_at"],
    )
    op.create_index(
        "ix_insa_travel_order_detail_case_no",
        "insa_travel_order_detail",
        ["appraisal_case_no"],
    )

    op.create_table(
        "insa_travel_companion",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "travel_id",
            sa.Integer(),
            sa.ForeignKey("insa_travel_order_detail.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "emp_id",
            sa.Integer(),
            sa.ForeignKey("insa_employee.id"),
            nullable=False,
        ),
        sa.UniqueConstraint("travel_id", "emp_id", name="uq_travel_companion"),
    )
    op.create_index(
        "ix_insa_travel_companion_travel_id",
        "insa_travel_companion",
        ["travel_id"],
    )
    op.create_index(
        "ix_insa_travel_companion_emp_id",
        "insa_travel_companion",
        ["emp_id"],
    )

    op.create_table(
        "insa_travel_report",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "travel_id",
            sa.Integer(),
            sa.ForeignKey("insa_travel_order_detail.id"),
            nullable=False,
        ),
        sa.Column(
            "doc_id",
            sa.Integer(),
            sa.ForeignKey("insa_approval_doc.id"),
            nullable=True,
        ),
        sa.Column("report_content", sa.Text(), nullable=False),
        sa.Column("actual_cost", sa.Numeric(12, 0), nullable=True),
        sa.Column("receipts_url", sa.String(length=500), nullable=True),
        sa.Column("reported_at", sa.DateTime(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=True,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("travel_id", name="uq_travel_report_travel"),
    )
    op.create_index(
        "ix_insa_travel_report_travel_id", "insa_travel_report", ["travel_id"]
    )
    op.create_index(
        "ix_insa_travel_report_doc_id", "insa_travel_report", ["doc_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_insa_travel_report_doc_id", table_name="insa_travel_report")
    op.drop_index("ix_insa_travel_report_travel_id", table_name="insa_travel_report")
    op.drop_table("insa_travel_report")

    op.drop_index(
        "ix_insa_travel_companion_emp_id", table_name="insa_travel_companion"
    )
    op.drop_index(
        "ix_insa_travel_companion_travel_id", table_name="insa_travel_companion"
    )
    op.drop_table("insa_travel_companion")

    op.drop_index(
        "ix_insa_travel_order_detail_case_no",
        table_name="insa_travel_order_detail",
    )
    op.drop_index(
        "ix_insa_travel_order_detail_end_at",
        table_name="insa_travel_order_detail",
    )
    op.drop_index(
        "ix_insa_travel_order_detail_start_at",
        table_name="insa_travel_order_detail",
    )
    op.drop_index(
        "ix_insa_travel_order_detail_doc_id",
        table_name="insa_travel_order_detail",
    )
    op.drop_table("insa_travel_order_detail")
