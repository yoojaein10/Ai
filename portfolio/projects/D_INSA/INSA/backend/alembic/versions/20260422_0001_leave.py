"""add leave management tables (PHASE 14)

Revision ID: 20260422_0001
Revises: 20260421_0001
Create Date: 2026-04-22
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260422_0001"
down_revision: Union[str, None] = "20260421_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "insa_leave_type",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("code", sa.String(length=20), nullable=False),
        sa.Column("name", sa.String(length=50), nullable=False),
        sa.Column(
            "deduct_from",
            sa.String(length=10),
            nullable=False,
            server_default=sa.text("'ANNUAL'"),
        ),
        sa.Column(
            "unit", sa.String(length=10), nullable=False, server_default=sa.text("'DAY'")
        ),
        sa.Column("is_paid", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column(
            "requires_evidence",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("code"),
    )
    op.create_index("ix_insa_leave_type_code", "insa_leave_type", ["code"])

    op.create_table(
        "insa_leave_accrual_rule",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column(
            "under_1year_monthly",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column(
            "under_1year_max",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("11"),
        ),
        sa.Column(
            "base_days", sa.Integer(), nullable=False, server_default=sa.text("15")
        ),
        sa.Column(
            "tenure_bonus_start_years",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("3"),
        ),
        sa.Column(
            "tenure_bonus_interval",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("2"),
        ),
        sa.Column(
            "max_days", sa.Integer(), nullable=False, server_default=sa.text("25")
        ),
        sa.Column(
            "carry_over_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("updated_by", sa.Integer(), sa.ForeignKey("insa_user.id"), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("year"),
    )
    op.create_index("ix_insa_leave_accrual_rule_year", "insa_leave_accrual_rule", ["year"])

    op.create_table(
        "insa_leave_balance",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "emp_id",
            sa.Integer(),
            sa.ForeignKey("insa_employee.id"),
            nullable=False,
        ),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column(
            "initial_days",
            sa.Numeric(5, 1),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "carried_over_days",
            sa.Numeric(5, 1),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "additional_days",
            sa.Numeric(5, 1),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "used_days",
            sa.Numeric(5, 1),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "scheduled_days",
            sa.Numeric(5, 1),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "carry_over_exempt",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("emp_id", "year", name="uq_leave_balance_emp_year"),
    )
    op.create_index("ix_insa_leave_balance_emp_id", "insa_leave_balance", ["emp_id"])
    op.create_index("ix_insa_leave_balance_year", "insa_leave_balance", ["year"])

    op.create_table(
        "insa_leave_transaction",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "emp_id",
            sa.Integer(),
            sa.ForeignKey("insa_employee.id"),
            nullable=False,
        ),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("transaction_type", sa.String(length=20), nullable=False),
        sa.Column("amount", sa.Numeric(5, 1), nullable=False),
        sa.Column("reason", sa.String(length=200), nullable=True),
        sa.Column(
            "ref_doc_id",
            sa.Integer(),
            sa.ForeignKey("insa_approval_doc.id"),
            nullable=True,
        ),
        sa.Column("balance_after", sa.Numeric(5, 1), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("insa_user.id"), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_insa_leave_transaction_emp_id", "insa_leave_transaction", ["emp_id"])
    op.create_index("ix_insa_leave_transaction_year", "insa_leave_transaction", ["year"])
    op.create_index(
        "ix_insa_leave_transaction_ref_doc_id",
        "insa_leave_transaction",
        ["ref_doc_id"],
    )

    op.create_table(
        "insa_scheduler_lock",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("job_name", sa.String(length=50), nullable=False),
        sa.Column("run_date", sa.String(length=10), nullable=False),
        sa.Column(
            "acquired_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("job_name", "run_date", name="uq_scheduler_lock_job_date"),
    )
    op.create_index("ix_insa_scheduler_lock_job_name", "insa_scheduler_lock", ["job_name"])


def downgrade() -> None:
    op.drop_index("ix_insa_scheduler_lock_job_name", table_name="insa_scheduler_lock")
    op.drop_table("insa_scheduler_lock")
    op.drop_index("ix_insa_leave_transaction_ref_doc_id", table_name="insa_leave_transaction")
    op.drop_index("ix_insa_leave_transaction_year", table_name="insa_leave_transaction")
    op.drop_index("ix_insa_leave_transaction_emp_id", table_name="insa_leave_transaction")
    op.drop_table("insa_leave_transaction")
    op.drop_index("ix_insa_leave_balance_year", table_name="insa_leave_balance")
    op.drop_index("ix_insa_leave_balance_emp_id", table_name="insa_leave_balance")
    op.drop_table("insa_leave_balance")
    op.drop_index("ix_insa_leave_accrual_rule_year", table_name="insa_leave_accrual_rule")
    op.drop_table("insa_leave_accrual_rule")
    op.drop_index("ix_insa_leave_type_code", table_name="insa_leave_type")
    op.drop_table("insa_leave_type")
