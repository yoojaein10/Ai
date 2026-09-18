"""거래처 Amaranth 동기화 이력."""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class PartnerSync(Base):
    __tablename__ = "a10_partner_sync"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    company_code: Mapped[str] = mapped_column(String(4), nullable=False, index=True)
    business_no: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    partner_name: Mapped[str] = mapped_column(String(60), nullable=False)
    partner_code: Mapped[str | None] = mapped_column(String(10), nullable=True)
    status: Mapped[str] = mapped_column(String(1), nullable=False, index=True)
    request_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    response_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_msg: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), index=True
    )

