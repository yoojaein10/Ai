"""외부 API 요청/응답 감사 로그 모델."""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ApiLog(Base):
    __tablename__ = "a10_api_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    direction: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    endpoint: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    req_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    res_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    elapsed_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_msg: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), index=True
    )

