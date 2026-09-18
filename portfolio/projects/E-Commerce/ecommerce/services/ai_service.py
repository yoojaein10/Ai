"""AI 분석 서비스 — Gemini를 활용한 가격 경쟁력 분석"""

import asyncio
import os

import httpx

from utils.logger import logger

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/models"

GEMINI_MODELS = [
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-2.0-flash-001",
]


async def _call_gemini(prompt: str) -> str:
    """여러 모델을 순서대로 시도하여 Gemini API를 호출합니다."""
    async with httpx.AsyncClient(timeout=30) as client:
        for model in GEMINI_MODELS:
            url = f"{GEMINI_BASE}/{model}:generateContent?key={GEMINI_API_KEY}"
            resp = await client.post(
                url,
                json={
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {
                        "temperature": 0.7,
                        "maxOutputTokens": 1024,
                    },
                },
            )
            if resp.status_code == 200:
                data = resp.json()
                return data["candidates"][0]["content"]["parts"][0]["text"]
            elif resp.status_code == 429:
                logger.warning(f"[AI] {model} 요청 한도 초과, 다음 모델 시도")
                continue
            elif resp.status_code == 404:
                logger.debug(f"[AI] {model} 사용 불가, 다음 모델 시도")
                continue
            else:
                logger.warning(f"[AI] {model} 오류: {resp.status_code}")
                continue

    return ""


async def refine_title(raw_title: str) -> str:
    """도매몰 원본 상품명을 스토어 등록용 상품명으로 정제합니다."""
    if not GEMINI_API_KEY:
        return raw_title

    prompt = (
        f"아래 도매몰 상품명을 쿠팡/스마트스토어에 등록할 깔끔한 상품명으로 변환해줘.\n"
        f"원본: {raw_title}\n\n"
        f"규칙:\n"
        f"- 도매처 표시([도매꾹], [오너클랜] 등), 상품번호, 배송 안내 제거\n"
        f"- 핵심 키워드(브랜드, 제품명, 스펙, 색상)만 남기기\n"
        f"- 검색에 잘 걸리도록 자연스러운 한국어\n"
        f"- 50자 이내\n"
        f"- 상품명만 출력 (설명 없이)"
    )

    result = await _call_gemini(prompt)
    refined = result.strip().strip('"').strip("'") if result else raw_title
    # 혹시 여러 줄이면 첫 줄만
    return refined.split("\n")[0].strip()


async def refine_titles_batch(
    titles: list[str],
    progress_callback=None,
) -> list[str]:
    """여러 상품명을 일괄 정제합니다 (1초 간격)."""
    results = []
    total = len(titles)

    for idx, title in enumerate(titles):
        if progress_callback:
            progress_callback(idx + 1, total)
        refined = await refine_title(title)
        results.append(refined)
        if idx < total - 1:
            await asyncio.sleep(1)

    return results


async def generate_selling_point(title: str, cost_price: int, market_lowest: int) -> str:
    """개별 상품에 대한 판매 소구점을 생성합니다."""
    if not GEMINI_API_KEY:
        return "API 키 없음"

    prompt = (
        f"이커머스 위탁판매 상품의 판매 소구점을 1~2문장으로 작성해줘.\n"
        f"상품명: {title}\n"
        f"도매가: {cost_price:,}원 / 시장 최저가: {market_lowest:,}원\n"
        f"쿠팡/스마트스토어에 올릴 때 소비자를 끌어들일 핵심 포인트만 간결하게. 한국어로."
    )

    result = await _call_gemini(prompt)
    return result.strip() if result else "분석 실패"


async def generate_selling_points_batch(
    items: list[dict],
    progress_callback=None,
) -> list[str]:
    """마진 TOP 10 상품들의 판매 소구점을 2초 간격으로 생성합니다.

    Args:
        items: [{"title", "cost_price", "market_lowest"}, ...]
        progress_callback: 진행 콜백 (current, total)

    Returns:
        판매 소구점 리스트 (같은 인덱스)
    """
    results = []
    total = len(items)

    for idx, item in enumerate(items):
        if progress_callback:
            progress_callback(idx + 1, total)

        summary = await generate_selling_point(
            title=item["title"],
            cost_price=item["cost_price"],
            market_lowest=item["market_lowest"],
        )
        results.append(summary)

        # Rate limit 보호: 2초 간격
        if idx < total - 1:
            await asyncio.sleep(2)

    return results


async def analyze_price_competitiveness(products: list[dict]) -> str:
    """Gemini에게 가격 경쟁력 분석을 요청합니다."""
    if not GEMINI_API_KEY:
        return "GEMINI_API_KEY가 설정되지 않았습니다. `.env` 파일에 추가해 주세요."

    if not products:
        return "분석할 상품 데이터가 없습니다."

    product_table = "\n".join(
        f"- {p['title'][:50]}: 도매가 {p['cost_price']:,.0f}원, "
        f"우리 판매가 {p['our_sale_price']:,.0f}원, "
        f"시장 최저가 {p['market_lowest_price']:,.0f}원, "
        f"예상 수익 {p['estimated_margin']:,.0f}원"
        for p in products
    )

    prompt = f"""당신은 이커머스 가격 분석 전문가입니다.
아래 위탁판매 상품들의 가격 경쟁력을 분석해 주세요.

판매가 공식: (도매가 + 마진 3,000원 + 배송비 3,000원) ÷ 0.88
수수료율: 쿠팡/네이버 약 12%

상품 목록:
{product_table}

다음을 포함하여 분석해 주세요:
1. 전체 요약 (수익성 좋은 상품 / 나쁜 상품)
2. 가격 경쟁력 평가 (우리 판매가 vs 시장 최저가)
3. 추천 전략 (어떤 상품을 우선 등록할지)
4. 주의사항 (마진이 너무 낮거나 역마진 가능성)

한국어로 간결하게 답변해 주세요."""

    try:
        return await _call_gemini(prompt)
    except Exception as e:
        logger.error(f"[AI] Gemini 호출 실패: {e}")
        return f"AI 분석 오류: {e}"
