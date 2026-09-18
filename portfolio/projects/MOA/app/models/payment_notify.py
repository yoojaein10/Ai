"""입금 알림 큐 — 새로 들어온 입금을 발송 시스템이 집어갈 수 있게 쌓아둔다.

요약 테이블(a10_receivable_summary)에 '갱신 시각'을 두는 방식은 쓸 수 없다.
야간 심층 배치가 51만 행을 통째로 DELETE + INSERT 하므로 매일 밤 전 행이
'변경됨'으로 찍혀, 발송 시스템이 전원에게 재발송하게 된다.

그래서 재집계 때 직전 누적 입금액과 비교해 **실제로 늘어난 감정서만** 이 표에 넣는다.
발송 쪽은 sent_at IS NULL 인 행만 집어가고, 보낸 뒤 sent_at을 채우면 된다.
"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, Index, Numeric, String, Unicode, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class PaymentNotify(Base):
    __tablename__ = "a10_payment_notify"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    # a10_receivable_summary.doc_id와 같은 폭
    doc_id: Mapped[str] = mapped_column(String(500), nullable=False)
    # 이번에 늘어난 금액 = received_amount - previous_amount
    delta_amount: Mapped[Decimal] = mapped_column(Numeric(19, 4), nullable=False)
    previous_amount: Mapped[Decimal] = mapped_column(Numeric(19, 4), nullable=False)
    received_amount: Mapped[Decimal] = mapped_column(Numeric(19, 4), nullable=False)
    billed_amount: Mapped[Decimal] = mapped_column(Numeric(19, 4), nullable=False)
    outstanding_amount: Mapped[Decimal] = mapped_column(Numeric(19, 4), nullable=False)
    last_received_date: Mapped[date | None] = mapped_column(Date)
    detected_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    # 발송 시스템이 채운다. NULL이면 아직 안 보낸 건.
    sent_at: Mapped[datetime | None] = mapped_column(DateTime)
    send_result: Mapped[str | None] = mapped_column(String(200))

    # 발송 시스템이 큐만 보고 처리할 수 있게 담는 비정규화 정보 (2026-07-31,
    # dev DB에 Leeilwoo가 확장해 둔 컬럼을 모델·적재에 반영).
    manager: Mapped[str | None] = mapped_column(String(100))    # 담당자(유치자)
    charge: Mapped[str | None] = mapped_column(String(200))     # 수금담당(masterex.Charge)
    cust_name: Mapped[str | None] = mapped_column(String(200))  # 거래처명
    office: Mapped[str | None] = mapped_column(String(10))      # 지사 office_id
    overpaid_amount: Mapped[Decimal | None] = mapped_column(Numeric(19, 4))
    status: Mapped[str | None] = mapped_column(Unicode(20))     # 완납/부분입금

    # 발송 대기 목록 조회(sent_at IS NULL)가 이 표의 유일한 뜨거운 경로다.
    __table_args__ = (
        Index("IX_a10_payment_notify_pending", "sent_at", "detected_at"),
    )
