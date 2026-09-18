"""APWorks(델파이)가 조회하는 감정서별 입금 결과 테이블.

감정서번호당 1행. 입금이 추가로 들어와 청구액을 채우면 분할입금 → 입금완료로
갱신된다. 매일 밤 배치(app.batch.payment_status_sync)가 a10_receivable_summary
집계를 MERGE로 반영한다.

sms_sent_at/sms_sent_by: 입금문자내역 화면의 문자 전송 기록 (2026-07-30 컬럼 추가,
기존 테이블에는 수동 ALTER 필요 — docs/SERVER_DEPLOY.md 참고). 전송/미전송은
sms_sent_at 유무로 판정한다 — boolean 대신 시각·처리자를 남겨 감사 추적이 되게 한다.
"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, Integer, Numeric, String, Unicode, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class PaymentStatus(Base):
    __tablename__ = "a10_payment_status"

    doc_id: Mapped[str] = mapped_column(String(500), primary_key=True)
    paid_date: Mapped[date | None] = mapped_column(Date)
    paid_amount: Mapped[Decimal] = mapped_column(Numeric(19, 4), nullable=False)
    pay_result: Mapped[str] = mapped_column(Unicode(20), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    sms_sent_at: Mapped[datetime | None] = mapped_column(DateTime)
    sms_sent_by: Mapped[int | None] = mapped_column(Integer)
