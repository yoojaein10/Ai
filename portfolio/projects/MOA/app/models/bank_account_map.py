"""은행 계좌(CB2) ↔ 아마란스 금융거래처 매핑.

seed_bank_account_map 스크립트가 과거 전표·입금 대조(금액+일자 투표)로
채우고, 애매한 계좌만 사람이 확인해 추가한다.
"""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class BankAccountMap(Base):
    __tablename__ = "a10_bank_account_map"
    __table_args__ = (
        UniqueConstraint("bank_cd", "acct_no", name="uq_a10_bank_account_map"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    bank_cd: Mapped[str] = mapped_column(String(8), nullable=False)
    acct_no: Mapped[str] = mapped_column(String(20), nullable=False)
    nickname: Mapped[str | None] = mapped_column(String(100), nullable=True)
    partner_code: Mapped[str] = mapped_column(String(10), nullable=False)
    partner_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    active: Mapped[str] = mapped_column(String(1), nullable=False, default="Y")
    # 일계표 대사에만 쓰는 계좌(지사 계좌 등) — active='N' 이라 입금전표 배치는 쓰지 않고,
    # 대사는 active='Y' OR reconcile_only='Y' 를 읽는다 (2026-08-26).
    reconcile_only: Mapped[str] = mapped_column(String(1), nullable=False, default="N", server_default="N")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
