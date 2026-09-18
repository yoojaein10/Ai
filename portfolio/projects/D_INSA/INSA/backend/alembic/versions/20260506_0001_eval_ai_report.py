"""add insa_eval_ai_report table

PHASE 18 AI 인사평가 리포트 — append-only 버전 관리.

Revision ID: 20260506_0001
Revises: 20260502_0001
Create Date: 2026-05-06
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "20260506_0001"
down_revision: Union[str, None] = "20260502_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "insa_eval_ai_report",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("round_id", sa.Integer(), sa.ForeignKey("insa_eval_round.id"), nullable=False),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("insa_employee.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("is_latest", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("total_score", sa.Numeric(5, 2), nullable=True),
        sa.Column("final_grade", sa.String(5), nullable=True),
        sa.Column("multi_response_count", sa.Integer(), nullable=True),
        sa.Column("multi_included", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("content_strengths", sa.Text(), nullable=True),
        sa.Column("content_improvements", sa.Text(), nullable=True),
        sa.Column("content_coaching", sa.Text(), nullable=True),
        sa.Column("content_interview_guide", sa.Text(), nullable=True),
        sa.Column("model_version", sa.String(50), nullable=False),
        sa.Column("prompt_version", sa.String(20), nullable=False),
        sa.Column("generated_by", sa.Integer(), sa.ForeignKey("insa_user.id"), nullable=False),
        sa.Column("generated_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_eval_ai_report_round_id", "insa_eval_ai_report", ["round_id"])
    op.create_index("ix_eval_ai_report_employee_id", "insa_eval_ai_report", ["employee_id"])
    op.create_index("ix_eval_ai_report_is_latest", "insa_eval_ai_report", ["is_latest"])
    op.create_index(
        "ix_eval_ai_report_round_emp_version",
        "insa_eval_ai_report",
        ["round_id", "employee_id", "version"],
        unique=True,
    )
    op.create_index(
        "ix_eval_ai_report_round_emp_latest",
        "insa_eval_ai_report",
        ["round_id", "employee_id", "is_latest"],
    )


def downgrade() -> None:
    op.drop_index("ix_eval_ai_report_round_emp_latest", table_name="insa_eval_ai_report")
    op.drop_index("ix_eval_ai_report_round_emp_version", table_name="insa_eval_ai_report")
    op.drop_index("ix_eval_ai_report_is_latest", table_name="insa_eval_ai_report")
    op.drop_index("ix_eval_ai_report_employee_id", table_name="insa_eval_ai_report")
    op.drop_index("ix_eval_ai_report_round_id", table_name="insa_eval_ai_report")
    op.drop_table("insa_eval_ai_report")
