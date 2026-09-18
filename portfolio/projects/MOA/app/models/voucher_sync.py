"""Amaranth 전표 전송 이력.

PHASE 4의 전표 서비스가 이 테이블을 채우며, 감정서 화면은 management_no(DocID)로
전표를 찾아 표시한다.
"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Date, DateTime, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class VoucherSync(Base):
    __tablename__ = "a10_voucher_sync"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    src_voucher_no: Mapped[str] = mapped_column(
        String(50), nullable=False, unique=True, index=True
    )
    management_no: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    voucher_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    debit_total: Mapped[Decimal] = mapped_column(Numeric(19, 4), nullable=False)
    credit_total: Mapped[Decimal] = mapped_column(Numeric(19, 4), nullable=False)
    status: Mapped[str] = mapped_column(String(1), nullable=False, index=True)
    a10_voucher_no: Mapped[str | None] = mapped_column(String(30), nullable=True)
    request_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    response_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_msg: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), index=True
    )

