import re

import httpx

from core.exceptions import CollectorException
from services.base_collector import BaseCollector, CollectedProduct
from utils.logger import logger

BASE_URL = "https://ownerclan.com"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        'Chrome/192.0.2.10 Safari/537.36'
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "ko-KR,ko;q=0.9",
    "Referer": "https://ownerclan.com/",
}


class OwnerclanCollector(BaseCollector):
    """오너클랜(ownerclan.com) 상품 수집기 — httpx 기반

    오너클랜은 AJAX 기반으로 상품 목록을 렌더링하지만,
    개별 상품 상세 페이지(/V2/product/view.php?selfcode=XXX)는
    서버사이드 렌더링되므로 httpx로 수집 가능합니다.

    로그인이 필요한 경우 CollectorException을 발생시킵니다.
    향후 쿠키 인증 방식으로 확장할 수 있도록 설계되었습니다.
    """

    def __init__(self, cookies: dict | None = None):
        self._cookies = cookies or {}

    @property
    def source_name(self) -> str:
        return "OWNERCLAN"

    async def collect(self, item_no: str) -> CollectedProduct:
        """상품 수집. item_no = selfcode (오너클랜 상품 고유코드)"""
        url = f"{BASE_URL}/V2/product/view.php?selfcode={item_no}"
        logger.info(f"[오너클랜] 수집 시작: {url}")

        async with httpx.AsyncClient(
            headers=HEADERS, cookies=self._cookies,
            follow_redirects=True, timeout=15,
        ) as client:
            resp = await client.get(url)

        if resp.status_code == 404 or resp.status_code != 200:
            raise CollectorException(f"오너클랜 상품을 찾을 수 없습니다: {item_no}")

        html = resp.text

        # 로그인 리다이렉트 / 에러 페이지 감지
        if "errorPage.php" in str(resp.url):
            raise CollectorException(f"오너클랜 상품을 찾을 수 없습니다: {item_no}")
        if "login" in str(resp.url).lower() or "로그인" in html[:3000]:
            raise CollectorException(
                "오너클랜 로그인이 필요합니다. "
                "쿠키를 설정하거나 공개 상품을 조회해 주세요."
            )

        title = self._parse_title(html)
        cost_price = self._parse_price(html)
        images = self._parse_images(html)
        stock = self._parse_stock(html)
        category = self._parse_category(html)

        if not title:
            raise CollectorException(
                f"오너클랜 상품 정보를 파싱할 수 없습니다: {item_no}. "
                "로그인이 필요한 상품이거나 페이지 구조가 변경되었을 수 있습니다."
            )

        product = CollectedProduct(
            source=self.source_name,
            origin_code=f"OC_{item_no}",
            title=title,
            cost_price=cost_price,
            stock=stock,
            images=images,
            category_code=category,
            detail_url=url,
        )
        logger.info(f"[오너클랜] 수집 완료: {title} / {cost_price}원")
        return product

    async def health_check(self) -> bool:
        try:
            async with httpx.AsyncClient(headers=HEADERS, timeout=10) as client:
                resp = await client.get(BASE_URL)
            return resp.status_code == 200
        except Exception:
            return False

    # ── 파싱 메서드 ─────────────────────────────────

    @staticmethod
    def _parse_title(html: str) -> str:
        # og:title
        m = re.search(r'property="og:title"[^>]*content="(.*?)"', html, re.I)
        if not m:
            m = re.search(r'content="(.*?)"[^>]*property="og:title"', html, re.I)
        if m:
            return m.group(1).strip()

        # <title>
        m = re.search(r"<title>(.*?)</title>", html, re.I)
        if m:
            title = m.group(1).strip()
            if title and title != "Document":
                return title

        # class 기반 상품명
        m = re.search(r'class="[^"]*product[_-]?name[^"]*"[^>]*>(.*?)</(?:div|span|h\d)', html, re.S | re.I)
        if m:
            return re.sub(r"<[^>]+>", "", m.group(1)).strip()

        return ""

    @staticmethod
    def _parse_price(html: str) -> float:
        # 공급가 / 판매가 패턴
        for label in ["공급가", "판매가", "도매가", "원가"]:
            m = re.search(rf"{label}[^0-9]*?([\d,]+)\s*원", html[:30000])
            if m:
                return float(m.group(1).replace(",", ""))

        # JS 변수
        for var in ["supplyPrice", "salePrice", "productPrice", "price"]:
            m = re.search(rf'{var}["\s:=]+["\']?(\d[\d,]*)', html)
            if m:
                return float(m.group(1).replace(",", ""))

        # og:description에서 가격
        m = re.search(r'property="og:description"[^>]*content="(.*?)"', html, re.I)
        if m:
            price_m = re.search(r"([\d,]+)원", m.group(1))
            if price_m:
                return float(price_m.group(1).replace(",", ""))

        return 0.0

    @staticmethod
    def _parse_images(html: str) -> list[str]:
        images: list[str] = []
        seen: set[str] = set()

        # og:image
        m = re.search(r'property="og:image"[^>]*content="(.*?)"', html, re.I)
        if not m:
            m = re.search(r'content="(.*?)"[^>]*property="og:image"', html, re.I)
        if m and m.group(1):
            url = m.group(1)
            if not url.startswith("http"):
                url = "https:" + url if url.startswith("//") else f"https://ownerclan.com{url}"
            images.append(url)
            seen.add(url)

        # 이미지 URL 패턴 (오너클랜 CDN)
        for pattern in [
            r'(https?://[^"\'\s]+ownerclan[^"\'\s]+\.(?:jpg|jpeg|png|webp))',
            r'(https?://[^"\'\s]+/product[^"\'\s]+\.(?:jpg|jpeg|png|webp))',
            r'src="(https?://[^"\s]+\.(?:jpg|jpeg|png|webp))"[^>]*class="[^"]*product',
        ]:
            for url in re.findall(pattern, html, re.I):
                if url not in seen and "banner" not in url.lower() and "icon" not in url.lower():
                    seen.add(url)
                    images.append(url)
                    if len(images) >= 5:
                        return images

        return images

    @staticmethod
    def _parse_stock(html: str) -> int:
        # 재고 수량
        m = re.search(r"재고[^0-9]*?(\d[\d,]*)\s*(?:개|EA)", html[:30000], re.I)
        if m:
            return int(m.group(1).replace(",", ""))

        for var in ["stockQty", "stock", "qty"]:
            m = re.search(rf'{var}["\s:=]+["\']?(\d+)', html, re.I)
            if m:
                return int(m.group(1))

        # 품절 감지
        if re.search(r"품절|sold\s*out|재고\s*없음", html[:30000], re.I):
            return 0

        return -1

    @staticmethod
    def _parse_category(html: str) -> str:
        m = re.search(r'categoryCode["\s:=]+["\']?(\w+)', html, re.I)
        if m:
            return m.group(1)
        return ""
