"""add electronic approval tables (PHASE 12)

Revision ID: 20260420_0001
Revises: 20260417_0001
Create Date: 2026-04-20
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260420_0001"
down_revision: Union[str, None] = "20260417_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "insa_approval_doc_type",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("code", sa.String(length=30), nullable=False, unique=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("category", sa.String(length=20), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.CheckConstraint(
            "category IN ('HR','ATTENDANCE','TRAVEL','CONTRACT','OTHER')",
            name="ck_approval_doc_type_category",
        ),
    )
    op.create_index("ix_insa_approval_doc_type_code", "insa_approval_doc_type", ["code"])

    op.create_table(
        "insa_approval_line_template",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("doc_type_id", sa.Integer(), sa.ForeignKey("insa_approval_doc_type.id"), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("scope", sa.String(length=10), nullable=False, server_default=sa.text("'GLOBAL'")),
        sa.Column("scope_ref", sa.Integer(), nullable=True),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.CheckConstraint("scope IN ('GLOBAL','DEPT')", name="ck_approval_line_template_scope"),
    )
    op.create_index(
        "ix_insa_approval_line_template_doc_type_id",
        "insa_approval_line_template",
        ["doc_type_id"],
    )

    op.create_table(
        "insa_approval_line_step",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "template_id",
            sa.Integer(),
            sa.ForeignKey("insa_approval_line_template.id"),
            nullable=False,
        ),
        sa.Column("step_order", sa.Integer(), nullable=False),
        sa.Column("approver_type", sa.String(length=20), nullable=False),
        sa.Column("approver_ref", sa.String(length=50), nullable=True),
        sa.Column("is_required", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.CheckConstraint(
            "approver_type IN ('USER','ROLE','POSITION','DEPT_HEAD','DIRECT_MANAGER')",
            name="ck_approval_line_step_approver_type",
        ),
    )
    op.create_index(
        "ix_insa_approval_line_step_template_id",
        "insa_approval_line_step",
        ["template_id"],
    )

    op.create_table(
        "insa_approval_doc",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("doc_type_id", sa.Integer(), sa.ForeignKey("insa_approval_doc_type.id"), nullable=False),
        sa.Column("doc_no", sa.String(length=30), nullable=True, unique=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("drafter_id", sa.Integer(), sa.ForeignKey("insa_employee.id"), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default=sa.text("'DRAFT'")),
        sa.Column("current_step", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("total_steps", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("drafted_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "status IN ('DRAFT','PENDING','IN_PROGRESS','APPROVED','REJECTED','RECALLED')",
            name="ck_approval_doc_status",
        ),
    )
    op.create_index("ix_insa_approval_doc_drafter_id", "insa_approval_doc", ["drafter_id"])
    op.create_index("ix_insa_approval_doc_status", "insa_approval_doc", ["status"])
    op.create_index("ix_insa_approval_doc_doc_type_id", "insa_approval_doc", ["doc_type_id"])

    op.create_table(
        "insa_approval_step_history",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("doc_id", sa.Integer(), sa.ForeignKey("insa_approval_doc.id"), nullable=False),
        sa.Column("step_order", sa.Integer(), nullable=False),
        sa.Column("approver_id", sa.Integer(), sa.ForeignKey("insa_user.id"), nullable=False),
        sa.Column("action", sa.String(length=20), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("acted_at", sa.DateTime(), server_default=sa.func.now()),
        sa.CheckConstraint(
            "action IN ('PENDING','APPROVED','REJECTED','DELEGATED','COMMENTED','RECALLED')",
            name="ck_approval_step_history_action",
        ),
    )
    op.create_index(
        "ix_insa_approval_step_history_doc_id",
        "insa_approval_step_history",
        ["doc_id"],
    )

    op.create_table(
        "insa_approval_attachment",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("doc_id", sa.Integer(), sa.ForeignKey("insa_approval_doc.id"), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("filesize", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("filepath", sa.String(length=500), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index(
        "ix_insa_approval_attachment_doc_id",
        "insa_approval_attachment",
        ["doc_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_insa_approval_attachment_doc_id", table_name="insa_approval_attachment")
    op.drop_table("insa_approval_attachment")

    op.drop_index("ix_insa_approval_step_history_doc_id", table_name="insa_approval_step_history")
    op.drop_table("insa_approval_step_history")

    op.drop_index("ix_insa_approval_doc_doc_type_id", table_name="insa_approval_doc")
    op.drop_index("ix_insa_approval_doc_status", table_name="insa_approval_doc")
    op.drop_index("ix_insa_approval_doc_drafter_id", table_name="insa_approval_doc")
    op.drop_table("insa_approval_doc")

    op.drop_index("ix_insa_approval_line_step_template_id", table_name="insa_approval_line_step")
    op.drop_table("insa_approval_line_step")

    op.drop_index("ix_insa_approval_line_template_doc_type_id", table_name="insa_approval_line_template")
    op.drop_table("insa_approval_line_template")

    op.drop_index("ix_insa_approval_doc_type_code", table_name="insa_approval_doc_type")
    op.drop_table("insa_approval_doc_type")
