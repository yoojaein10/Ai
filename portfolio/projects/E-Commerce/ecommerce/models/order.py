import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.session import Base


class OrderStatus(str, enum.Enum):
    WAITING = "WAITING"
    ORDERED = "ORDERED"
    SHIPPED = "SHIPPED"
    CANCELLED = "CANCELLED"


class Platform(str, enum.Enum):
    COUPANG = "COUPANG"
    SMARTSTORE = "SMARTSTORE"


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    market_order_id: Mapped[str] = mapped_column(
        String(100), nullable=False, index=True,
        comment="쇼핑몰 주문번호"
    )
    platform: Mapped[Platform] = mapped_column(
        Enum(Platform), nullable=False, comment="판매처: COUPANG, SMARTSTORE"
    )
    product_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[OrderStatus] = mapped_column(
        Enum(OrderStatus), nullable=False, default=OrderStatus.WAITING,
        comment="발주 상태"
    )
    recipient_info: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True,
        comment="수령인 정보: name, phone, address, zip_code"
    )
    domeme_order_id: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="도매몰 발주 번호"
    )
    tracking_number: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="송장 번호"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    product = relationship("Product", backref="orders", lazy="joined")

    def __repr__(self) -> str:
        return f"<Order {self.id} [{self.platform}] {self.market_order_id} -> {self.status}>"
