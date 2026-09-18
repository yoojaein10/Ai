"""수익성 분석 엔진 — 시장 최저가 조회 & 마진 계산"""

import asyncio
import re
from dataclasses import dataclass, field

import httpx

from core.config import settings
from utils.logger import logger

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        'Chrome/192.0.2.10 Safari/537.36'
    ),
    "Accept-Language": "ko-KR,ko;q=0.9",
}

# 네이버 쇼핑 검색 API
NAVER_SHOPPING_API_URL = "https://openapi.naver.com/v1/search/shop.json"

# 마진 3000원 + 배송비 3000원, 수수료율 12% (÷ 0.88)
DEFAULT_MARGIN = 3000
DEFAULT_SHIPPING = 3000
COMMISSION_RATE = 0.88

# 마진 TOP 10 공식: 예상 수익 = (시장 최저가 * 0.9) - (도매가 + 3000)
MARKET_FEE_RATE = 0.9
EXTRA_COST = 3000


@dataclass
class MarketPrice:
    platform: str
    price: int
    seller: str
    url: str


@dataclass
class ProfitAnalysis:
    product_id: int
    title: str
    cost_price: float
    our_sale_price: float
    market_lowest_price: float
    estimated_margin: float
    margin_rate: float


@dataclass
class MarginTopItem:
    """마진 TOP 10 분석 결과 아이템"""
    source: str
    item_no: str
    title: str
    image: str
    cost_price: int          # 도매가
    market_lowest: int       # 시장 최저가
    estimated_profit: int    # 예상 수익 = (시장최저가*0.9) - (도매가+3000)
    margin_rate: float       # 마진율 (%)
    ai_summary: str = ""     # AI 판매 소구점
    category: str = ""       # 상품 카테고리


def calc_target_price(
    cost_price: float,
    margin: float = DEFAULT_MARGIN,
    shipping: float = DEFAULT_SHIPPING,
) -> float:
    """목표 판매가 계산: (도매가 + 마진 + 배송비) / 0.88"""
    return round((cost_price + margin + shipping) / COMMISSION_RATE)


def calc_margin_profit(cost_price: float, market_lowest: float) -> int:
    """마진 TOP 10 공식: (시장 최저가 × 0.9) - (도매가 + 3000)"""
    return round(market_lowest * MARKET_FEE_RATE - (cost_price + EXTRA_COST))


# ══════════════════════════════════════════════════════
# 네이버 쇼핑 검색 API
# ══════════════════════════════════════════════════════

async def _search_naver_api(keyword: str) -> MarketPrice | None:
    """네이버 쇼핑 검색 API로 최저가를 조회합니다."""
    if not settings.NAVER_CLIENT_ID or not settings.NAVER_CLIENT_SECRET:
        logger.warning("[분석] 네이버 API 키가 설정되지 않았습니다.")
        return None

    try:
        search_keyword = _extract_search_keyword(keyword)

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                NAVER_SHOPPING_API_URL,
                params={
                    "query": search_keyword,
                    "display": 40,
                    "sort": "sim",  # 관련도순 (asc는 미끼상품만 나옴)
                    "exclude": "used:cbshop",  # 중고/해외직구 제외
                },
                headers={
                    "X-Naver-Client-Id": settings.NAVER_CLIENT_ID,
                    "X-Naver-Client-Secret": settings.NAVER_CLIENT_SECRET,
                },
            )

            if resp.status_code != 200:
                logger.warning(f"[분석] 네이버 API 응답 오류: {resp.status_code}")
                return None

            data = resp.json()
            items = data.get("items", [])

            if not items:
                logger.debug(f"[분석] 네이버 API '{search_keyword}' 결과 없음")
                return None

            # 1) 1,000원 미만 미끼 상품 제거
            valid_items = [
                it for it in items
                if int(it.get("lprice", "0") or "0") >= 1000
            ]

            if not valid_items:
                logger.debug(f"[분석] 네이버 API '{search_keyword}' 유효 결과 없음")
                return None

            # 2) IQR 기반 이상치 제거 (극단적 저가만 정확히 제거)
            valid_items.sort(key=lambda x: int(x.get("lprice", "0") or "0"))
            prices = [int(it.get("lprice", "0") or "0") for it in valid_items]
            n = len(prices)
            q1 = prices[n // 4] if n >= 4 else prices[0]
            q3 = prices[(3 * n) // 4] if n >= 4 else prices[-1]
            iqr = q3 - q1
            lower_bound = q1 - 1.5 * iqr
            trimmed = [it for it in valid_items if int(it.get("lprice", "0") or "0") >= lower_bound]
            if not trimmed:
                trimmed = valid_items

            # 3) 절삭 후 최저가 추출
            lowest_item = trimmed[0]
            lowest_price = int(lowest_item.get("lprice", "0") or "0")

            if lowest_price <= 0:
                return None

            logger.info(
                f"[분석] 네이버 API '{search_keyword}' -> {lowest_price:,}원 "
                f"(전체 {len(items)}개 → 유효 {len(valid_items)}개 → 절삭 후 {len(trimmed)}개)"
            )
            return MarketPrice(
                platform="NAVER",
                price=lowest_price,
                seller=re.sub(r'<[^>]+>', '', lowest_item.get("mallName", "")),
                url=lowest_item.get("link", ""),
            )
    except Exception as e:
        logger.error(f"[분석] 네이버 API 호출 실패: {e}")
        return None


def _extract_search_keyword(title: str) -> str:
    """긴 상품명에서 검색에 적합한 키워드를 추출합니다."""
    clean = re.sub(r'[\(\[【].*?[\)\]】]', '', title)
    clean = re.sub(r'[^\w\s가-힣]', ' ', clean)
    clean = re.sub(r'\s+', ' ', clean).strip()
    words = clean.split()

    # 수식어/불용어 제거 후 핵심 단어 추출
    stopwords = {
        '신상', '신제품', '모음전', '개별포장', '당일발송', '무료배송',
        '간절기', '사계절', '여성', '여자', '남성', '남자', '중년', '청소년',
        '사은품', '세트', '묶음', '대량', '도매', '특가', '할인', '인기',
        '추천', '베스트', '히트', '국내', '해외', '수입', '국산',
    }
    filtered = [w for w in words if w not in stopwords and len(w) >= 2]
    if not filtered:
        filtered = words

    if len(filtered) > 5:
        filtered = filtered[:5]
    return ' '.join(filtered)


# ══════════════════════════════════════════════════════
# 통합 시장 최저가 조회
# ══════════════════════════════════════════════════════

async def get_market_lowest_price(keyword: str) -> int:
    """시장 최저가를 조회합니다. 조회 실패 시 0 반환."""
    result = await _search_naver_api(keyword)
    if result:
        return result.price
    return 0


# ══════════════════════════════════════════════════════
# 마진 TOP 10 자동 추천
# ══════════════════════════════════════════════════════

async def get_margin_top_10(
    products: list[dict],
    progress_callback=None,
) -> list[MarginTopItem]:
    """추천 상품 리스트를 입력받아 시장 최저가를 조회하고
    마진 상위 10개를 반환합니다.

    Args:
        products: [{"source", "item_no", "title", "price", "image"}, ...]
            - price: 도매가 (0이면 제외)
        progress_callback: 진행 상황 콜백 (current, total, title)

    Returns:
        마진 상위 10개 MarginTopItem 리스트
    """
    results: list[MarginTopItem] = []
    total = len(products)

    for idx, p in enumerate(products):
        cost = p.get("price", 0)
        if cost <= 0:
            continue

        title = p.get("title", "")
        if progress_callback:
            progress_callback(idx + 1, total, title[:30])

        # 시장 최저가 조회
        market_price = await get_market_lowest_price(title)

        if market_price <= 0:
            logger.debug(f"[마진] '{title[:30]}' 시장가 조회 실패 → 제외")
            continue

        profit = calc_margin_profit(cost, market_price)
        rate = round(profit / market_price * 100, 1) if market_price > 0 else 0

        results.append(MarginTopItem(
            source=p.get("source", ""),
            item_no=p.get("item_no", ""),
            title=title,
            image=p.get("image", ""),
            cost_price=cost,
            market_lowest=market_price,
            estimated_profit=profit,
            margin_rate=rate,
            category=p.get("category", ""),
        ))

        # 네이버 요청 간격
        await asyncio.sleep(0.5)

    # 예상 수익 내림차순 정렬 → 상위 10개
    results.sort(key=lambda x: x.estimated_profit, reverse=True)
    return results[:10]


# ══════════════════════════════════════════════════════
# 수익성 분석 (기존 호환)
# ══════════════════════════════════════════════════════

def analyze_product(
    product_id: int,
    title: str,
    cost_price: float,
    market_lowest_price: float,
) -> ProfitAnalysis:
    """단일 상품 수익성 분석"""
    our_price = calc_target_price(cost_price)
    margin = calc_margin_profit(cost_price, market_lowest_price) if market_lowest_price > 0 else 0
    margin_rate = (margin / market_lowest_price * 100) if market_lowest_price > 0 else 0

    return ProfitAnalysis(
        product_id=product_id,
        title=title,
        cost_price=cost_price,
        our_sale_price=our_price,
        market_lowest_price=market_lowest_price,
        estimated_margin=margin,
        margin_rate=round(margin_rate, 1),
    )


def get_best_margin_products(
    products: list[dict],
    top_n: int = 10,
) -> list[ProfitAnalysis]:
    """마진 상위 N개 상품 반환."""
    analyses = []
    for p in products:
        mlp = p.get("market_lowest_price") or 0
        if mlp <= 0:
            continue
        analyses.append(analyze_product(
            product_id=p["id"],
            title=p["title"],
            cost_price=float(p["cost_price"]),
            market_lowest_price=float(mlp),
        ))

    analyses.sort(key=lambda a: a.estimated_margin, reverse=True)
    return analyses[:top_n]
