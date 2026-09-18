"""add shared calendar tables (PHASE 13)

Revision ID: 20260421_0001
Revises: 20260420_0001
Create Date: 2026-04-21
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260421_0001"
down_revision: Union[str, None] = "20260420_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "insa_calendar",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column(
            "color_hex",
            sa.String(length=9),
            nullable=False,
            server_default=sa.text("'#1677ff'"),
        ),
        sa.Column(
            "scope",
            sa.String(length=10),
            nullable=False,
            server_default=sa.text("'COMPANY'"),
        ),
        sa.Column("scope_ref", sa.Integer(), nullable=True),
        sa.Column(
            "is_default",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "created_by",
            sa.Integer(),
            sa.ForeignKey("insa_user.id"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.CheckConstraint(
            "scope IN ('COMPANY','DEPT','PERSONAL')", name="ck_calendar_scope"
        ),
    )

    op.create_table(
        "insa_calendar_event",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "calendar_id",
            sa.Integer(),
            sa.ForeignKey("insa_calendar.id"),
            nullable=False,
        ),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "event_type",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'MANUAL'"),
        ),
        sa.Column(
            "source_type",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'MANUAL'"),
        ),
        sa.Column("source_ref", sa.Integer(), nullable=True),
        sa.Column("start_at", sa.DateTime(), nullable=False),
        sa.Column("end_at", sa.DateTime(), nullable=False),
        sa.Column(
            "all_day", sa.Boolean(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "owner_id",
            sa.Integer(),
            sa.ForeignKey("insa_employee.id"),
            nullable=False,
        ),
        sa.Column("location", sa.String(length=200), nullable=True),
        sa.Column(
            "visibility",
            sa.String(length=10),
            nullable=False,
            server_default=sa.text("'PUBLIC'"),
        ),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
        sa.CheckConstraint(
            "event_type IN ('MANUAL','LEAVE','TRAVEL','MEETING','OTHER')",
            name="ck_calendar_event_type",
        ),
        sa.CheckConstraint(
            "source_type IN ('APPROVAL_DOC','MANUAL')",
            name="ck_calendar_event_source_type",
        ),
        sa.CheckConstraint(
            "visibility IN ('PUBLIC','DEPT','PRIVATE')",
            name="ck_calendar_event_visibility",
        ),
    )
    op.create_index(
        "ix_calendar_event_calendar_start",
        "insa_calendar_event",
        ["calendar_id", "start_at"],
    )
    op.create_index(
        "ix_calendar_event_owner_start",
        "insa_calendar_event",
        ["owner_id", "start_at"],
    )
    op.create_index(
        "ix_calendar_event_source",
        "insa_calendar_event",
        ["source_type", "source_ref"],
    )

    op.create_table(
        "insa_calendar_event_participant",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "event_id",
            sa.Integer(),
            sa.ForeignKey("insa_calendar_event.id"),
            nullable=False,
        ),
        sa.Column(
            "emp_id",
            sa.Integer(),
            sa.ForeignKey("insa_employee.id"),
            nullable=False,
        ),
        sa.Column(
            "role",
            sa.String(length=15),
            nullable=False,
            server_default=sa.text("'REQUIRED'"),
        ),
        sa.Column(
            "response",
            sa.String(length=10),
            nullable=False,
            server_default=sa.text("'PENDING'"),
        ),
        sa.CheckConstraint(
            "role IN ('ORGANIZER','REQUIRED','OPTIONAL')",
            name="ck_calendar_event_participant_role",
        ),
        sa.CheckConstraint(
            "response IN ('PENDING','ACCEPTED','DECLINED','TENTATIVE')",
            name="ck_calendar_event_participant_response",
        ),
    )
    op.create_index(
        "ix_cal_event_participant_event",
        "insa_calendar_event_participant",
        ["event_id"],
    )
    op.create_index(
        "ix_cal_event_participant_emp",
        "insa_calendar_event_participant",
        ["emp_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_cal_event_participant_emp",
        table_name="insa_calendar_event_participant",
    )
    op.drop_index(
        "ix_cal_event_participant_event",
        table_name="insa_calendar_event_participant",
    )
    op.drop_table("insa_calendar_event_participant")

    op.drop_index("ix_calendar_event_source", table_name="insa_calendar_event")
    op.drop_index(
        "ix_calendar_event_owner_start", table_name="insa_calendar_event"
    )
    op.drop_index(
        "ix_calendar_event_calendar_start", table_name="insa_calendar_event"
    )
    op.drop_table("insa_calendar_event")

    op.drop_table("insa_calendar")
