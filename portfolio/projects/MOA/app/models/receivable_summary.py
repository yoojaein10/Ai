"""감정서별 청구·입금·미수 집계 요약 캐시.

입금·미수금 화면이 매 조회마다 a10_voucher_cache 전체(157만 행)를 집계하지 않도록,
전표 캐시 동기화 직후 receivable_status_cte 결과를 통째로 저장해 둔다.
"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, Integer, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ReceivableSummary(Base):
    __tablename__ = "a10_receivable_summary"

    # a10_voucher_cache.management_no와 같은 폭. 감정서번호 외의 장문 관리값도 그대로 담는다.
    doc_id: Mapped[str] = mapped_column(String(500), primary_key=True)
    billed_amount: Mapped[Decimal] = mapped_column(Numeric(19, 4), nullable=False)
    received_amount: Mapped[Decimal] = mapped_column(Numeric(19, 4), nullable=False)
    advance_amount: Mapped[Decimal] = mapped_column(Numeric(19, 4), nullable=False)
    suspense_amount: Mapped[Decimal] = mapped_column(Numeric(19, 4), nullable=False)
    outstanding_amount: Mapped[Decimal] = mapped_column(Numeric(19, 4), nullable=False)
    overpaid_amount: Mapped[Decimal] = mapped_column(Numeric(19, 4), nullable=False)
    last_received_date: Mapped[date | None] = mapped_column(Date)
    receipt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    refreshed_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
