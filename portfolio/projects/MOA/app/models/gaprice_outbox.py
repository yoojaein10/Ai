"""수수료 배분(Apw_Mae_GaPrice) 승인 대기함.

야간 배치가 입금 확인된 감정서의 배분 초안을 만들어 두면,
재무팀이 화면에서 금액을 확인·수정 후 승인했을 때만 APWorks의
Apw_Mae_GaPrice에 새 행으로 INSERT된다 (기존 0원 선등록 행은 사용자 결정으로 무시).
"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Date, DateTime, Integer, Numeric, String, Unicode, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class GapriceOutbox(Base):
    __tablename__ = "a10_gaprice_outbox"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    doc_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    masterid: Mapped[int] = mapped_column(Integer, nullable=False)
    manager: Mapped[str] = mapped_column(Unicode(30), nullable=False)
    usr_seq: Mapped[int | None] = mapped_column(Integer)
    ratio: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    pung_price: Mapped[Decimal | None] = mapped_column(Numeric(19, 4))
    basic_susu: Mapped[Decimal | None] = mapped_column(Numeric(19, 4))
    in_price: Mapped[Decimal] = mapped_column(Numeric(19, 4), nullable=False)
    in_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(Unicode(10), nullable=False, default="PENDING", index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    approved_by: Mapped[int | None] = mapped_column(Integer)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime)
    # 승인 시 GaPrice에 INSERT된 행의 Seq
    applied_ga_seq: Mapped[int | None] = mapped_column(Integer)
