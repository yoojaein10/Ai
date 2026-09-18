"""APWorks 발송 완료 이벤트를 받는 전표 생성 Outbox."""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class VoucherOutbox(Base):
    __tablename__ = "a10_voucher_outbox"
    __table_args__ = (
        Index("ix_a10_voucher_outbox_pending", "status", "available_at", "id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    doc_id: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(20), nullable=False, server_default="APWORKS_SEND")
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="PENDING")
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    available_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    requested_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    requested_by: Mapped[str | None] = mapped_column(String(50), nullable=True)
    payload: Mapped[str | None] = mapped_column(Text, nullable=True)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    locked_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    a10_voucher_no: Mapped[str | None] = mapped_column(String(30), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())
