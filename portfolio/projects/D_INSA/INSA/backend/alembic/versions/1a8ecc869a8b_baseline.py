"""baseline

Revision ID: 1a8ecc869a8b
Revises:
Create Date: 2026-04-17 14:10:48.822925
"""
from typing import Sequence, Union

revision: str = '1a8ecc869a8b'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# 빈 baseline. DB는 이미 모든 모델 테이블을 보유하고 있고,
# 모델에 정의되지 않은 외부 테이블(TMWCMN_USR_BAC_INFO 등)은 보존해야 한다.
def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
