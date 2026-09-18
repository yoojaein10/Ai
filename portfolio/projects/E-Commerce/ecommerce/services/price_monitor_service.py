"""가격 모니터링 서비스 — DB 저장 상품의 시장최저가를 일괄 갱신하고 변동을 감지합니다."""

import asyncio
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

from services.analyzer_service import get_market_lowest_price, calc_margin_profit
from utils.logger import logger


@dataclass
class PriceChange:
    """가격 변동 정보"""
    product_id: int
    title: str
    old_price: int
    new_price: int
    change_pct: float  # 변동률 (%)
    old_margin: int
    new_margin: int


async def refresh_market_prices(
    db: Session,
    progress_callback=None,
) -> list[PriceChange]:
    """DB에 저장된 모든 활성 상품의 시장최저가를 갱신합니다.

    Returns:
        가격이 변동된 상품 목록
    """
    rows = db.execute(
        text(
            "SELECT id, title, cost_price, market_lowest_price "
            "FROM products WHERE is_active = true ORDER BY id"
        )
    ).fetchall()

    if not rows:
        return []

    changes: list[PriceChange] = []
    total = len(rows)

    for idx, row in enumerate(rows):
        pid, title, cost_price, old_price = row
        old_price = int(old_price or 0)
        cost = int(cost_price or 0)

        if progress_callback:
            progress_callback(idx + 1, total, title[:25])

        # 네이버 API 호출
        new_price = await get_market_lowest_price(title)

        if new_price <= 0:
            logger.debug(f"[모니터링] #{pid} '{title[:30]}' 가격 조회 실패, 스킵")
            await asyncio.sleep(0.5)
            continue

        new_margin = calc_margin_profit(cost, new_price)
        old_margin = calc_margin_profit(cost, old_price) if old_price > 0 else 0

        # DB 업데이트
        db.execute(
            text(
                "UPDATE products SET market_lowest_price = :mlp, "
                "estimated_margin = :margin, updated_at = NOW() WHERE id = :id"
            ),
            {"mlp": new_price, "margin": new_margin, "id": pid},
        )

        # 가격 변동 감지 (기존 가격이 있고, 변동이 있을 때)
        if old_price > 0 and new_price != old_price:
            change_pct = round((new_price - old_price) / old_price * 100, 1)
            changes.append(PriceChange(
                product_id=pid,
                title=title,
                old_price=old_price,
                new_price=new_price,
                change_pct=change_pct,
                old_margin=old_margin,
                new_margin=new_margin,
            ))

        # 네이버 API rate limit (0.5초 간격)
        await asyncio.sleep(0.5)

    db.commit()
    logger.info(f"[모니터링] {total}개 상품 갱신 완료, {len(changes)}개 가격 변동 감지")
    return changes
