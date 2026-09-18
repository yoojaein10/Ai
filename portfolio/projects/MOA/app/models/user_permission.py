"""APWorks 사용자별 A10BRIDGE 추가 권한 (기본: 본사=전체, 그 외=자기 지사)."""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class UserPermission(Base):
    __tablename__ = "a10_user_permission"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    usr_id: Mapped[str] = mapped_column(String(50), nullable=False, unique=True, index=True)
    view_all_offices: Mapped[str] = mapped_column(String(1), nullable=False, server_default="N")
    memo: Mapped[str | None] = mapped_column(String(200), nullable=True)
    active: Mapped[str] = mapped_column(String(1), nullable=False, server_default="Y")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())
