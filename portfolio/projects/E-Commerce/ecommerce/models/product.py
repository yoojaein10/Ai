from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from database.session import Base


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(
        String(20), nullable=False, comment="도매처 구분: DOMEME, OWNERCLAN"
    )
    origin_code: Mapped[str] = mapped_column(
        String(100), nullable=False, unique=True, index=True,
        comment="도매몰 상품번호"
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False, comment="원문 상품명")
    refined_title: Mapped[str | None] = mapped_column(
        String(500), nullable=True, comment="AI 정제 상품명"
    )
    cost_price: Mapped[float] = mapped_column(
        Numeric(12, 2), nullable=False, default=0, comment="도매 원가"
    )
    sale_price: Mapped[float] = mapped_column(
        Numeric(12, 2), nullable=False, default=0, comment="쇼핑몰 판매가"
    )
    stock: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="현재 재고")
    category_code: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="카테고리 코드"
    )
    market_lowest_price: Mapped[float | None] = mapped_column(
        Numeric(12, 2), nullable=True, comment="시장 최저가 (쿠팡/네이버)"
    )
    estimated_margin: Mapped[float | None] = mapped_column(
        Numeric(12, 2), nullable=True, comment="예상 수익 (시장최저가 - 도매가)"
    )
    selling_point: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="AI 생성 판매 소구점"
    )
    category: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="상품 카테고리 (수납정리, 주방용품 등)"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, comment="판매 중 여부"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return f"<Product {self.id} [{self.source}] {self.origin_code}>"
