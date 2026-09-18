import re

import httpx

from core.exceptions import CollectorException
from services.base_collector import BaseCollector, CollectedProduct
from utils.logger import logger

BASE_URL = "https://domeggook.com"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        'Chrome/192.0.2.10 Safari/537.36'
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "ko-KR,ko;q=0.9",
    "Referer": "https://domeggook.com/",
}


class DomemeCollector(BaseCollector):
    """도매꾹(domeggook.com) 상품 수집기 — httpx 기반"""

    @property
    def source_name(self) -> str:
        return "DOMEME"

    async def collect(self, item_no: str) -> CollectedProduct:
        url = f"{BASE_URL}/{item_no}"
        logger.info(f"[도매꾹] 수집 시작: {url}")

        async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True, timeout=15) as client:
            resp = await client.get(url)

        if resp.status_code != 200:
            raise CollectorException(f"도매꾹 페이지 요청 실패 (HTTP {resp.status_code})")

        html = resp.text

        # 에러 페이지 감지
        if "error_403_404" in str(resp.url) or "페이지를 표시할 수 없습니다" in html:
            raise CollectorException(f"도매꾹 상품을 찾을 수 없습니다: {item_no}")

        title = self._parse_title(html)
        cost_price = self._parse_price(html)
        images = self._parse_images(html)
        stock = self._parse_stock(html)
        category = self._parse_category(html)

        if not title:
            raise CollectorException(f"도매꾹 상품 정보를 파싱할 수 없습니다: {item_no}")

        product = CollectedProduct(
            source=self.source_name,
            origin_code=f"DM_{item_no}",
            title=title,
            cost_price=cost_price,
            stock=stock,
            images=images,
            category_code=category,
            detail_url=url,
        )
        logger.info(f"[도매꾹] 수집 완료: {title} / {cost_price}원")
        return product

    async def health_check(self) -> bool:
        try:
            async with httpx.AsyncClient(headers=HEADERS, timeout=20) as client:
                resp = await client.get(BASE_URL)
            return resp.status_code == 200
        except Exception:
            return False

    # ── 파싱 메서드 ─────────────────────────────────

    @staticmethod
    def _parse_title(html: str) -> str:
        # og:title 우선
        m = re.search(r'property="og:title"[^>]*content="(.*?)"', html, re.I)
        if not m:
            m = re.search(r'content="(.*?)"[^>]*property="og:title"', html, re.I)
        if m:
            title = m.group(1).strip()
            # "[도매꾹] " 접두어 제거
            return re.sub(r"^\[도매꾹\]\s*", "", title)

        # fallback: <title> 태그
        m = re.search(r"<title>(.*?)</title>", html, re.I)
        if m:
            return m.group(1).split("|")[0].strip()
        return ""

    @staticmethod
    def _parse_price(html: str) -> float:
        # 1순위: JS 변수 itemPrice
        m = re.search(r'var\s+itemPrice\s*=\s*["\']?(\d+)', html)
        if m:
            return float(m.group(1))

        # 2순위: og:description "890원 / 최소 10개"
        m = re.search(r'property="og:description"[^>]*content="(.*?)"', html, re.I)
        if not m:
            m = re.search(r'content="(.*?)"[^>]*property="og:description"', html, re.I)
        if m:
            price_m = re.search(r"([\d,]+)원", m.group(1))
            if price_m:
                return float(price_m.group(1).replace(",", ""))

        # 3순위: 판매가/공급가 라벨 근처에서 가격 추출
        for label in ["판매가", "공급가", "도매가", "단가"]:
            m = re.search(rf"{label}[^0-9]*?([\d,]+)\s*원", html[:30000])
            if m:
                val = float(m.group(1).replace(",", ""))
                if val >= 100:
                    return val

        return 0.0

    @staticmethod
    def _parse_images(html: str) -> list[str]:
        # _img_ 패턴 (메인 상품 이미지) - 가장 큰 사이즈 우선
        pattern = r'(https?://cdn\d*\.domeggook\.com/upload/item/[^"\'\s\)]+_img_\d+[^"\'\s\)]*)'
        found = re.findall(pattern, html)

        # 중복 제거 + 큰 이미지 우선 (760 > 330)
        seen_bases: dict[str, str] = {}
        for url in found:
            base = re.sub(r"_img_\d+.*", "", url)
            if base not in seen_bases:
                seen_bases[base] = url
            else:
                # 더 큰 사이즈로 교체
                current_size = int(re.search(r"_img_(\d+)", seen_bases[base]).group(1))
                new_size = int(re.search(r"_img_(\d+)", url).group(1))
                if new_size > current_size:
                    seen_bases[base] = url

        images = list(seen_bases.values())[:5]

        # fallback: og:image
        if not images:
            m = re.search(r'property="og:image"[^>]*content="(.*?)"', html, re.I)
            if not m:
                m = re.search(r'content="(.*?)"[^>]*property="og:image"', html, re.I)
            if m and m.group(1):
                images.append(m.group(1))

        return images

    @staticmethod
    def _parse_stock(html: str) -> int:
        # JS 변수 stockQty
        m = re.search(r'var\s+stockQty\s*=\s*["\']?(\d+)', html)
        if m:
            return int(m.group(1))

        # itemStatus로 판매 상태 확인
        m = re.search(r'var\s+itemStatus\s*=\s*["\']?(.*?)["\';]', html)
        if m:
            status = m.group(1).strip()
            if status in ("판매중단", "기간종료", "품절"):
                return 0
            if status == "진행중":
                return -1  # 재고 수량 미확인, 판매 중

        return -1

    @staticmethod
    def _parse_category(html: str) -> str:
        # 카테고리 코드 추출 시도
        m = re.search(r'var\s+(?:cateCode|categoryCode)\s*=\s*["\']?(\w+)', html)
        if m:
            return m.group(1)
        return ""
