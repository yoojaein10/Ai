from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from database.session import get_db
from models.product import Product
from schemas.product_schema import ProductCreate, ProductResponse, SourceType
from services.base_collector import BaseCollector, CollectedProduct
from services.domeme_collector import DomemeCollector
from services.ownerclan_collector import OwnerclanCollector
from utils.logger import logger

router = APIRouter(prefix="/collector", tags=["Collector"])

# ── 의존성 주입: source별 collector 매핑 ──

_collectors: dict[str, BaseCollector] = {
    "DOMEME": DomemeCollector(),
    "OWNERCLAN": OwnerclanCollector(),
}


def get_collector(source: str) -> BaseCollector:
    source_upper = source.upper()
    if source_upper not in _collectors:
        from core.exceptions import CollectorException
        raise CollectorException(f"지원하지 않는 도매처입니다: {source}")
    return _collectors[source_upper]


# ── 상품 수집 → DB 저장 ──

@router.post("/crawl", response_model=ProductResponse)
async def crawl_product(
    source: SourceType,
    item_no: str,
    db: Session = Depends(get_db),
):
    """도매처 상품을 수집하고 DB에 저장합니다.

    - source: DOMEME (도매꾹) 또는 OWNERCLAN (오너클랜)
    - item_no: 도매처 상품 고유번호
    """
    collector = get_collector(source.value)
    collected = await collector.collect(item_no)

    # 기존 상품 존재 여부 확인 (origin_code 기준)
    existing = db.query(Product).filter(
        Product.origin_code == collected.origin_code
    ).first()

    if existing:
        # 업데이트
        existing.title = collected.title
        existing.cost_price = collected.cost_price
        existing.stock = collected.stock if collected.stock >= 0 else existing.stock
        existing.category_code = collected.category_code or existing.category_code
        db.commit()
        db.refresh(existing)
        logger.info(f"[Collector] 기존 상품 업데이트: {existing.origin_code}")
        return existing

    # 신규 저장
    product = Product(
        source=collected.source,
        origin_code=collected.origin_code,
        title=collected.title,
        cost_price=collected.cost_price,
        sale_price=0,  # 판매가는 별도 설정
        stock=collected.stock if collected.stock >= 0 else 0,
        category_code=collected.category_code,
        is_active=True,
    )
    db.add(product)
    db.commit()
    db.refresh(product)
    logger.info(f"[Collector] 신규 상품 저장: {product.origin_code}")
    return product


# ── 도매처 헬스체크 ──

@router.get("/health/{source}")
async def collector_health(source: str):
    """도매처 사이트 접근 가능 여부를 확인합니다."""
    collector = get_collector(source)
    ok = await collector.health_check()
    return {
        "source": source.upper(),
        "status": "ok" if ok else "unreachable",
    }
