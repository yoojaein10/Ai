"""국민 약식 지점코드(KB_Code) ↔ 아마란스 거래처 매핑.

BANK_KB_REQUEST_MASTER의 지점명(KB_Name)은 APWorks에서 암호화돼 있어
읽을 수 없다. 대신 KB_Code는 평문이고, 같은 400번호가 APW_TS_Master에는
평문 지점명으로 남아 있어 둘을 이어 붙이면 복호화 없이 코드→지점명을
얻는다(seed_kb_branch_map). 암호값도 함께 저장해 TS_Master가 없는 건은
암호값으로 역참조한다.
"""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class KbBranchMap(Base):
    __tablename__ = "a10_kb_branch_map"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    kb_code: Mapped[str] = mapped_column(
        String(10), nullable=False, unique=True, index=True
    )
    branch_name: Mapped[str] = mapped_column(String(100), nullable=False)
    # BANK_KB_REQUEST_MASTER.KB_Name의 암호값 — TS_Master 없는 건의 역참조 키
    encrypted_name: Mapped[str | None] = mapped_column(
        String(200), nullable=True, index=True
    )
    partner_code: Mapped[str | None] = mapped_column(String(10), nullable=True)
    partner_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    active: Mapped[str] = mapped_column(String(1), nullable=False, default="Y")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
