"""도매꾹 + 오너클랜 오늘의 추천 상품 수집 서비스"""

import asyncio
import re
from dataclasses import dataclass

import httpx

from utils.logger import logger

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        'Chrome/192.0.2.10 Safari/537.36'
    ),
    "Accept-Language": "ko-KR,ko;q=0.9",
}

# ── 정렬 옵션 ──────────────────────────────────────
SORT_OPTIONS = {
    "sales": "🔥 판매 많은 순",
    "views": "👀 조회 많은 순",
    "newest": "✨ 신상품순",
}

# 도매꾹 정렬별 URL
DOMEME_SORT_CONFIG = {
    "sales": {
        "url": "https://domeggook.com/main/item/itemPopular.php",
        "label": "인기상품",
    },
    "views": {
        "url": "https://domeggook.com/main/item/itemList.php?sw=&sf=ttl&so=ha",
        "label": "인기상품순",
    },
    "newest": {
        "url": "https://domeggook.com/main/item/itemList.php?sw=&sf=ttl&so=da",
        "label": "최근등록순",
    },
}

# 오너클랜 정렬별 rankType
OWNERCLAN_SORT_CONFIG = {
    "sales": {"rankType": "rankUp", "label": "랭킹순"},
    "views": {"rankType": "rankUp", "label": "랭킹순"},
    "newest": {"rankType": "date", "label": "신상품순"},
}

# 도매꾹 메인 상품 유형 (fallback용)
DOMEME_LABELS = {
    "mainCategory2024": "카테고리 인기",
    "mainCenter2024": "메인 추천",
    "mdAndDumping": "MD 추천 / 덤핑",
    "rightScroll": "실시간 인기",
    "ohggook": "오꾹 추천",
    "myChoice": "맞춤 추천",
    "myHotTag": "인기 태그",
}


@dataclass
class RecommendedProduct:
    source: str        # DOMEME | OWNERCLAN
    item_no: str
    title: str
    price: int
    image: str
    category: str      # 추천 유형 라벨


# ══════════════════════════════════════════════════════
# 도매꾹 공통 헬퍼
# ══════════════════════════════════════════════════════

def _parse_domeme_detail(page: str, item_no: str, category: str) -> RecommendedProduct | None:
    """도매꾹 상품 상세 페이지 HTML에서 상품 정보를 파싱합니다."""
    m = re.search(r'property="og:title"[^>]*content="(.*?)"', page, re.I)
    title = re.sub(r"^\[도매꾹\]\s*", "", m.group(1)) if m else ""
    if not title:
        return None

    price = 0
    m = re.search(r'property="og:description"[^>]*content="(.*?)"', page, re.I)
    if m:
        p = re.search(r"([\d,]+)원", m.group(1))
        if p:
            price = int(p.group(1).replace(",", ""))

    m = re.search(r'property="og:image"[^>]*content="(.*?)"', page, re.I)
    image = m.group(1) if m else ""

    return RecommendedProduct(
        source="DOMEME",
        item_no=item_no,
        title=title,
        price=price,
        image=image,
        category=category,
    )


# ══════════════════════════════════════════════════════
# 도매꾹
# ══════════════════════════════════════════════════════

async def _fetch_domeme(limit: int, sort_by: str = "sales") -> list[RecommendedProduct]:
    config = DOMEME_SORT_CONFIG.get(sort_by, DOMEME_SORT_CONFIG["sales"])
    url = config["url"]
    label = config["label"]
    logger.info(f"[추천] 도매꾹 스캔 시작 ({label})")

    async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True, timeout=15) as client:
        resp = await client.get(url)

    # 정렬 페이지 실패 시 메인 페이지 fallback
    if resp.status_code != 200:
        logger.warning(f"[추천] 도매꾹 {url} 실패({resp.status_code}), 메인으로 대체")
        async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True, timeout=15) as client:
            resp = await client.get("https://domeggook.com")
        if resp.status_code != 200:
            return []

    html = resp.text

    # 여러 패턴으로 상품 ID 추출
    seen: set[str] = set()
    unique: list[tuple[str, str]] = []

    # 패턴 1: /REDACTED_CONFIGURE_LOCALLY7?advcnt=xxx (메인 페이지)
    for m in re.finditer(r"/(\d{7,})\?advcnt=(\w+)", html):
        item_no, adv_type = m.group(1), m.group(2)
        if item_no not in seen:
            seen.add(item_no)
            unique.append((item_no, DOMEME_LABELS.get(adv_type, adv_type)))

    # 패턴 2: href 속성 내 7자리 이상 숫자 (리스트 페이지)
    for m in re.finditer(r'href="(?:https?://domeggook\.com)?/(\d{7,})"', html):
        item_no = m.group(1)
        if item_no not in seen:
            seen.add(item_no)
            unique.append((item_no, label))

    # 패턴 3: 일반 링크 내 상품 번호
    for m in re.finditer(r'/(\d{7,})(?=[?"\s>\'&])', html):
        item_no = m.group(1)
        if item_no not in seen:
            seen.add(item_no)
            unique.append((item_no, label))

    if not unique:
        logger.warning(f"[추천] 도매꾹 상품 링크 없음 ({url})")
        return []

    targets = unique[:limit]
    results: list[RecommendedProduct] = []

    sem = asyncio.Semaphore(5)

    async def _fetch_one(client: httpx.AsyncClient, item_no: str, cat_label: str) -> RecommendedProduct | None:
        async with sem:
            try:
                r = await client.get(f"https://domeggook.com/{item_no}")
                if r.status_code != 200 or "error_403_404" in str(r.url):
                    return None
                page = r.text
                return _parse_domeme_detail(page, item_no, cat_label)
            except Exception as e:
                logger.debug(f"[추천] 도매꾹 {item_no} 실패: {e}")
                return None

    async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True, timeout=10) as client:
        tasks = [_fetch_one(client, item_no, cat_label) for item_no, cat_label in targets]
        fetched = await asyncio.gather(*tasks)
        results = [r for r in fetched if r is not None]

    logger.info(f"[추천] 도매꾹 {len(results)}개 수집 ({label})")
    return results


# ══════════════════════════════════════════════════════
# 오너클랜
# ══════════════════════════════════════════════════════

async def _fetch_ownerclan(limit: int, sort_by: str = "sales") -> list[RecommendedProduct]:
    config = OWNERCLAN_SORT_CONFIG.get(sort_by, OWNERCLAN_SORT_CONFIG["sales"])
    rank_type = config["rankType"]
    label = config["label"]
    logger.info(f"[추천] 오너클랜 스캔 시작 ({label})")

    selfcodes: list[str] = []

    # AJAX API로 정렬된 셀프코드 목록 가져오기
    try:
        async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True, timeout=15) as client:
            resp = await client.post(
                "https://ownerclan.com/V2/_ajax/getSelfcodes.php",
                data={
                    "categoryCode": "",
                    "rankType": rank_type,
                    "pageNum": "1",
                    "listNum": str(limit),
                    "listType": "img",
                    "searchKeyword": "",
                    "searchType": "",
                },
            )
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, list):
                    selfcodes = data[:limit]
                    logger.info(f"[추천] 오너클랜 AJAX {len(selfcodes)}개 셀프코드 ({label})")
    except Exception as e:
        logger.debug(f"[추천] 오너클랜 AJAX 실패: {e}")

    # AJAX 실패 시 메인 페이지 fallback
    if not selfcodes:
        logger.info("[추천] 오너클랜 AJAX 실패, 메인 페이지로 대체")
        async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True, timeout=15) as client:
            resp = await client.get("https://ownerclan.com")
        if resp.status_code != 200:
            return []
        html = resp.text
        seen: set[str] = set()
        for m in re.finditer(r"selfcode=(\w+)", html):
            sc = m.group(1)
            if sc not in seen:
                seen.add(sc)
                selfcodes.append(sc)
        selfcodes = selfcodes[:limit]

    results: list[RecommendedProduct] = []

    # 각 selfcode 상세 페이지에서 정보 추출
    async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True, timeout=10) as client:
        for selfcode in selfcodes:
            try:
                r = await client.get(
                    f"https://ownerclan.com/V2/product/view.php?selfcode={selfcode}"
                )
                if r.status_code != 200 or "errorPage" in str(r.url):
                    continue

                page = r.text

                tm = re.search(r'property="og:title"[^>]*content="(.*?)"', page, re.I)
                title = tm.group(1).strip() if tm else ""
                title = re.sub(r"^오너클랜\s*-\s*", "", title)
                if not title:
                    continue

                im = re.search(r'property="og:image"[^>]*content="(.*?)"', page, re.I)
                image = im.group(1) if im else ""

                price = 0
                for plabel in ["공급가", "판매가", "도매가"]:
                    pm = re.search(rf"{plabel}[^0-9]*?([\d,]+)", page[:30000])
                    if pm:
                        price = int(pm.group(1).replace(",", ""))
                        break

                results.append(RecommendedProduct(
                    source="OWNERCLAN",
                    item_no=selfcode,
                    title=title,
                    price=price,
                    image=image,
                    category=f"오너클랜 {label}",
                ))
            except Exception as e:
                logger.debug(f"[추천] 오너클랜 {selfcode} 실패: {e}")
                continue

    logger.info(f"[추천] 오너클랜 {len(results)}개 수집 ({label})")
    return results


# ══════════════════════════════════════════════════════
# 도매꾹 키워드 검색
# ══════════════════════════════════════════════════════

async def _fetch_domeme_by_keyword(keyword: str, limit: int = 20) -> list[RecommendedProduct]:
    """키워드로 도매꾹을 검색하여 상품 목록을 반환합니다."""
    if not keyword.strip():
        return []

    from urllib.parse import quote

    # 도매꾹은 EUC-KR 인코딩 키워드를 사용해야 실제 검색 결과가 반환됨
    try:
        kw_encoded = quote(keyword.encode("euc-kr"))
    except (UnicodeEncodeError, LookupError):
        kw_encoded = quote(keyword)

    url = f"https://domeggook.com/main/item/itemList.php?sw={kw_encoded}&sf=ttl&so=ha"
    logger.info(f"[추천] 도매꾹 키워드 검색: '{keyword}'")

    async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True, timeout=15) as client:
        try:
            resp = await client.get(url)
        except Exception as e:
            logger.warning(f"[추천] 도매꾹 키워드 검색 요청 실패: {e}")
            return []

    if resp.status_code != 200:
        logger.warning(f"[추천] 도매꾹 키워드 '{keyword}' 실패({resp.status_code})")
        return []

    html = resp.text

    # 검색 결과 상품은 advcnt=rightScroll 타입으로 표시됨
    # mainCategory2024, mdAndDumping 등은 고정 추천 영역이므로 제외
    seen: set[str] = set()
    unique: list[str] = []

    # 1순위: lstGen (실제 검색 결과 영역)
    for m in re.finditer(r"/(\d{7,})\?from=lstGen", html):
        item_no = m.group(1)
        if item_no not in seen:
            seen.add(item_no)
            unique.append(item_no)

    # 2순위: lstGen이 없으면 advcnt/광고 제외한 순수 링크
    if not unique:
        adv_ids: set[str] = set()
        for m in re.finditer(r"/(\d{7,})\?(?:advcnt|from)=", html):
            adv_ids.add(m.group(1))
        for m in re.finditer(r'href="(?:https?://domeggook\.com)?/(\d{7,})"', html):
            item_no = m.group(1)
            if item_no not in seen and item_no not in adv_ids:
                seen.add(item_no)
                unique.append(item_no)

    if not unique:
        logger.warning(f"[추천] 도매꾹 키워드 '{keyword}' 검색 결과 없음")
        return []

    targets = unique[:limit]
    results: list[RecommendedProduct] = []

    sem = asyncio.Semaphore(5)

    async def _fetch_one(client: httpx.AsyncClient, item_no: str) -> RecommendedProduct | None:
        async with sem:
            try:
                r = await client.get(f"https://domeggook.com/{item_no}")
                if r.status_code != 200 or "error_403_404" in str(r.url):
                    return None
                page = r.text
                return _parse_domeme_detail(page, item_no, keyword)
            except Exception as e:
                logger.debug(f"[추천] 도매꾹 키워드 '{keyword}' {item_no} 실패: {e}")
                return None

    async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True, timeout=10) as client:
        tasks = [_fetch_one(client, item_no) for item_no in targets]
        fetched = await asyncio.gather(*tasks)
        results = [r for r in fetched if r is not None]

    logger.info(f"[추천] 도매꾹 키워드 '{keyword}' {len(results)}개 수집")
    return results


async def fetch_by_keywords(
    keywords: list[str],
    limit_per_keyword: int = 10,
) -> list[RecommendedProduct]:
    """여러 키워드를 병렬 수집하고 중복 제거 후 반환합니다."""
    seen: set[str] = set()
    results: list[RecommendedProduct] = []

    keyword_results = await asyncio.gather(
        *[_fetch_domeme_by_keyword(kw, limit=limit_per_keyword) for kw in keywords]
    )
    for items in keyword_results:
        for item in items:
            if item.item_no not in seen:
                seen.add(item.item_no)
                results.append(item)

    logger.info(f"[추천] 키워드 통합 수집 완료: {len(results)}개 (키워드 {len(keywords)}개)")
    return results


# ══════════════════════════════════════════════════════
# 통합 API
# ══════════════════════════════════════════════════════

async def fetch_recommendations(
    limit: int = 20,
    sources: list[str] | None = None,
    sort_by: str = "sales",
) -> list[RecommendedProduct]:
    """도매꾹 + 오너클랜 추천 상품을 통합 수집합니다.

    Args:
        limit: 사이트당 최대 수집 수
        sources: ["DOMEME", "OWNERCLAN"] 중 선택. None이면 둘 다.
        sort_by: 정렬 기준 ("sales", "views", "newest")
    """
    if sources is None:
        sources = ["DOMEME", "OWNERCLAN"]

    results: list[RecommendedProduct] = []

    if "DOMEME" in sources:
        results.extend(await _fetch_domeme(limit, sort_by))
    if "OWNERCLAN" in sources:
        results.extend(await _fetch_ownerclan(limit, sort_by))

    return results
