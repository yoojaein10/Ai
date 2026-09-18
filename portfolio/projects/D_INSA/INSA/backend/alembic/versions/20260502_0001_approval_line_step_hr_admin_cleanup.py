"""migrate legacy HR_ADMIN approver_type to ROLE/HR_ADMIN

Older seed data stored `approver_type='HR_ADMIN'` on approval line steps,
but the service layer only recognizes USER/ROLE/POSITION/DEPT_HEAD/DIRECT_MANAGER.
The response Literal schema matches the service layer, so any stale row causes
a ResponseValidationError on GET /api/v1/approval/lines.

Convert each such row to the ROLE type with approver_ref='HR_ADMIN'; the ROLE
branch of the resolver already looks up users by Role.code and handles it.

Revision ID: 20260502_0001
Revises: 20260501_0001
Create Date: 2026-04-23
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "20260502_0001"
down_revision: Union[str, None] = "20260501_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE insa_approval_line_step
            SET approver_type = 'ROLE',
                approver_ref  = 'HR_ADMIN'
            WHERE approver_type = 'HR_ADMIN'
            """
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE insa_approval_line_step
            SET approver_type = 'HR_ADMIN',
                approver_ref  = NULL
            WHERE approver_type = 'ROLE'
              AND approver_ref  = 'HR_ADMIN'
            """
        )
    )
