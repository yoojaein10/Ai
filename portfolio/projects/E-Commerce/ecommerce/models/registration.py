"""상품 마켓 등록 이력 모델"""

import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.session import Base


class RegistrationStatus(str, enum.Enum):
    PENDING = "PENDING"        # 등록 대기
    REGISTERED = "REGISTERED"  # 등록 완료
    FAILED = "FAILED"          # 등록 실패
    DELETED = "DELETED"        # 삭제됨


class MarketPlatform(str, enum.Enum):
    COUPANG = "COUPANG"
    SMARTSTORE = "SMARTSTORE"


class ProductRegistration(Base):
    __tablename__ = "product_registrations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    platform: Mapped[MarketPlatform] = mapped_column(
        Enum(MarketPlatform), nullable=False, comment="등록 플랫폼"
    )
    status: Mapped[RegistrationStatus] = mapped_column(
        Enum(RegistrationStatus), nullable=False, default=RegistrationStatus.PENDING,
        comment="등록 상태"
    )
    platform_product_id: Mapped[str | None] = mapped_column(
        String(200), nullable=True, comment="플랫폼측 상품 ID"
    )
    platform_url: Mapped[str | None] = mapped_column(
        String(500), nullable=True, comment="등록된 상품 URL"
    )
    error_message: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="실패 시 에러 메시지"
    )
    registered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="등록 완료 시각"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    product = relationship("Product", backref="registrations", lazy="joined")

    def __repr__(self) -> str:
        return f"<Registration {self.id} [{self.platform}] product={self.product_id} {self.status}>"
