"""지사(Office) ↔ 감정서번호 접두사 ↔ Amaranth 회계단위 매핑."""

from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class OfficeMap(Base):
    __tablename__ = "a10_office_map"
    __table_args__ = (
        Index("ux_a10_office_map_prefix", "docid_prefix", unique=True),
    )

    office_id: Mapped[str] = mapped_column(String(10), primary_key=True)
    office_name: Mapped[str] = mapped_column(String(50), nullable=False)
    docid_prefix: Mapped[str] = mapped_column(String(5), nullable=False)
    division_code: Mapped[str | None] = mapped_column(String(10), nullable=True)
    division_name: Mapped[str | None] = mapped_column(String(50), nullable=True)
    active: Mapped[str] = mapped_column(String(1), nullable=False, server_default="Y")
    sort_order: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())
