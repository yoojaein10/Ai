"""TAMS TAX_CASH.DB 현금영수증 발행내역 읽기 캐시."""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, Index, Integer, Numeric, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class TamsCashReceiptCache(Base):
    __tablename__ = "a10_tams_cash_receipt_cache"
    __table_args__ = (
        UniqueConstraint("send_date", "seq_no", name="uq_a10_tams_cash_receipt_source"),
        Index("ix_a10_tams_cash_receipt_appraisal", "appraisal_no"),
        Index("ix_a10_tams_cash_receipt_approval", "approval_no"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    send_date: Mapped[date] = mapped_column(Date, nullable=False)
    seq_no: Mapped[int] = mapped_column(Integer, nullable=False)
    approval_no: Mapped[str | None] = mapped_column(String(20))
    user_type: Mapped[str | None] = mapped_column(String(2))
    transaction_type: Mapped[str | None] = mapped_column(String(2))
    transaction_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    transaction_time: Mapped[str | None] = mapped_column(String(6))
    transaction_seq: Mapped[int | None] = mapped_column(Integer)
    company_name: Mapped[str | None] = mapped_column(String(100))
    business_no: Mapped[str | None] = mapped_column(String(20))
    total_amount: Mapped[Decimal] = mapped_column(Numeric(19, 4), nullable=False)
    supply_amount: Mapped[Decimal] = mapped_column(Numeric(19, 4), nullable=False)
    vat_amount: Mapped[Decimal] = mapped_column(Numeric(19, 4), nullable=False)
    service_fee: Mapped[Decimal] = mapped_column(Numeric(19, 4), nullable=False)
    goods_name: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(String(100))
    nts_status: Mapped[str | None] = mapped_column(String(2))
    nts_response_at: Mapped[str | None] = mapped_column(String(14))
    nts_error_message: Mapped[str | None] = mapped_column(String(100))
    appraisal_no: Mapped[str | None] = mapped_column(String(30))
    original_approval_no: Mapped[str | None] = mapped_column(String(20))
    original_transaction_date: Mapped[date | None] = mapped_column(Date)
    issue_type: Mapped[str | None] = mapped_column(String(2))
    gubun: Mapped[str | None] = mapped_column(String(2))
    report_yn: Mapped[str | None] = mapped_column(String(1))
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

