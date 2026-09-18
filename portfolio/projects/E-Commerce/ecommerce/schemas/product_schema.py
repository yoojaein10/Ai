from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


# ── 공통 Enum ──
class SourceType(str, Enum):
    DOMEME = "DOMEME"
    OWNERCLAN = "OWNERCLAN"


class PlatformType(str, Enum):
    COUPANG = "COUPANG"
    SMARTSTORE = "SMARTSTORE"


class OrderStatusType(str, Enum):
    WAITING = "WAITING"
    ORDERED = "ORDERED"
    SHIPPED = "SHIPPED"
    CANCELLED = "CANCELLED"


# ── Product ──
class ProductCreate(BaseModel):
    source: SourceType
    origin_code: str = Field(..., max_length=100, description="도매몰 상품번호")
    title: str = Field(..., max_length=500, description="원문 상품명")
    refined_title: str | None = Field(None, max_length=500, description="AI 정제 상품명")
    cost_price: float = Field(0, ge=0, description="도매 원가")
    sale_price: float = Field(0, ge=0, description="쇼핑몰 판매가")
    stock: int = Field(0, ge=0, description="현재 재고")
    category_code: str | None = None
    is_active: bool = True


class ProductResponse(BaseModel):
    id: int
    source: str
    origin_code: str
    title: str
    refined_title: str | None
    cost_price: float
    sale_price: float
    stock: int
    category_code: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── Order ──
class RecipientInfo(BaseModel):
    name: str = Field(..., description="수령인 이름")
    phone: str = Field(..., description="연락처")
    address: str = Field(..., description="주소")
    zip_code: str = Field(..., description="우편번호")


class OrderCreate(BaseModel):
    market_order_id: str = Field(..., description="쇼핑몰 주문번호")
    platform: PlatformType
    product_id: int
    recipient_info: RecipientInfo | None = None


class OrderResponse(BaseModel):
    id: int
    market_order_id: str
    platform: str
    product_id: int
    status: str
    recipient_info: dict | None
    domeme_order_id: str | None
    tracking_number: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── 기존 크롤러용 (하위 호환) ──
class CrawlRequest(BaseModel):
    url: str


class CrawlResponse(BaseModel):
    title: str
    price: int
    images: list[str]
    options: list[str]
    description: str


# ── 업로드용 (하위 호환) ──
class UploadRequest(BaseModel):
    platform: str
    title: str
    price: int
    images: list[str]
    options: list[str]
    description: str


class UploadResponse(BaseModel):
    platform: str
    status: str
    product_id: str | None = None
    message: str
