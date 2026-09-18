import json
import re
from pathlib import Path
from urllib.parse import urlparse

from playwright.async_api import async_playwright, Page, TimeoutError as PwTimeout

from core.exceptions import CrawlerException
from utils.logger import logger

# ── Stealth & Browser 설정 ──────────────────────────────────

STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN', 'zh', 'en'] });
Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
window.chrome = { runtime: {} };
"""

CHROME_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    'Chrome/192.0.2.10 Safari/537.36'
)

COOKIE_FILE = Path(__file__).resolve().parent.parent / "cookies_1688.json"

# 셀렉터 후보 (1688 페이지 구조 변동 대비 - 우선순위순)
SELECTORS = {
    "title": [
        "h1.title-text",
        "div.title-text",
        ".offer-title-content",
        "div[class*='DetailHeader'] h1",
        "h1",
    ],
    "price": [
        "span.price-text",
        "div.price-text",
        ".offer-price .value",
        "div[class*='Price'] span",
        "span.price",
    ],
    "images": [
        "div.detail-gallery-turn img",
        ".offer-image-list img",
        ".detail-gallery img",
        "div[class*='Gallery'] img",
        ".main-image img",
    ],
    "options": [
        "div.sku-item-name",
        "div.offer-sku .sku-item span",
        ".sku-prop-content span",
        "div[class*='Sku'] span[class*='name']",
        ".obj-sku .unit-detail-spec-operator span",
    ],
    "description": [
        "div.detail-desc-decorate-richtext",
        "div.offer-description",
        "#desc-lazyload-container",
        "div[class*='RichText']",
        ".detail-description",
    ],
}


class CrawlerService:
    """Playwright 기반 1688 상품 크롤러 (쿠키 인증 방식)"""

    def __init__(self, timeout_ms: int = 30_000):
        self._timeout = timeout_ms

    # ── public ──────────────────────────────────────────────

    async def crawl_1688(self, url: str) -> dict:
        """1688 상품 URL에서 원본(중국어) 데이터를 수집합니다."""
        self._validate_url(url)
        logger.info(f"1688 크롤링 시작: {url}")

        browser = None
        pw = None
        try:
            pw = await async_playwright().start()
            browser = await pw.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                ],
            )
            context = await browser.new_context(
                user_agent=CHROME_UA,
                viewport={"width": 1920, "height": 1080},
                locale="zh-CN",
            )

            # 쿠키 주입
            await self._load_cookies(context)

            page = await context.new_page()
            await page.add_init_script(STEALTH_JS)
            await page.goto(url, wait_until="domcontentloaded", timeout=self._timeout)

            # 봇 차단 / 로그인 감지
            await self._detect_block(page)

            # 본문 렌더링 대기
            await self._wait_for_content(page)

            # JS 리다이렉트 대비 재확인
            await self._detect_block(page)

            # 데이터 추출
            title = await self._extract_title(page)
            price = await self._extract_price(page)
            images = await self._extract_images(page)
            options = await self._extract_options(page)
            description = await self._extract_description(page)

            if not title or title in ("", "1688", "全球领先的采购批发平台"):
                raise CrawlerException(
                    "상품 정보를 가져올 수 없습니다. "
                    "쿠키가 만료되었을 수 있습니다. "
                    "브라우저에서 1688에 로그인 후 쿠키를 다시 내보내 주세요."
                )

            result = {
                "title": title,
                "price": price,
                "images": images,
                "options": options,
                "description": description,
            }
            logger.info(f"1688 크롤링 완료: {title} (CNY {price})")
            return result

        except CrawlerException:
            raise
        except PwTimeout:
            logger.error(f"크롤링 타임아웃: {url}")
            raise CrawlerException(
                "페이지 로딩 시간이 초과되었습니다. 잠시 후 다시 시도해 주세요."
            )
        except Exception as e:
            logger.error(f"크롤링 예외: {e}", exc_info=True)
            raise CrawlerException(f"크롤링 중 오류 발생: {str(e)}")
        finally:
            if browser:
                await browser.close()
            if pw:
                await pw.stop()

    # ── cookie management ──────────────────────────────────

    async def _load_cookies(self, context) -> None:
        """cookies_1688.json에서 쿠키를 로드하여 브라우저 컨텍스트에 주입"""
        if not COOKIE_FILE.exists():
            raise CrawlerException(
                f"쿠키 파일이 없습니다: {COOKIE_FILE.name}\n"
                "1688에 로그인한 브라우저에서 쿠키를 내보내 주세요.\n"
                "방법: Chrome 확장 'EditThisCookie' 또는 'Cookie-Editor'로 "
                "JSON 내보내기 후 ecommerce/cookies_1688.json에 저장"
            )

        try:
            raw = json.loads(COOKIE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise CrawlerException(f"쿠키 파일 파싱 오류: {e}")

        # EditThisCookie / Cookie-Editor 형식 모두 지원
        cookies = []
        for c in raw:
            cookie = {
                "name": c.get("name", ""),
                "value": c.get("value", ""),
                "domain": c.get("domain", ".1688.com"),
                "path": c.get("path", "/"),
            }
            if c.get("expirationDate"):
                cookie["expires"] = float(c["expirationDate"])
            elif c.get("expires") and c["expires"] != -1:
                cookie["expires"] = float(c["expires"])
            if c.get("sameSite"):
                ss = c["sameSite"].lower()
                if ss in ("strict", "lax", "none"):
                    cookie["sameSite"] = ss.capitalize() if ss != "none" else "None"
            cookies.append(cookie)

        await context.add_cookies(cookies)
        logger.info(f"쿠키 {len(cookies)}개 로드 완료")

    # ── validation ──────────────────────────────────────────

    @staticmethod
    def _validate_url(url: str) -> None:
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            raise CrawlerException("유효하지 않은 URL 형식입니다.")
        if "1688.com" not in parsed.netloc:
            raise CrawlerException("1688.com 상품 URL만 지원합니다.")

    # ── block detection ─────────────────────────────────────

    async def _detect_block(self, page: Page) -> None:
        """캡차 / 로그인 / 슬라이드 인증 감지"""
        current_url = page.url.lower()

        if "login.taobao.com" in current_url or "login.1688.com" in current_url:
            raise CrawlerException(
                "1688 로그인 페이지로 이동되었습니다. "
                "쿠키가 만료되었습니다. 다시 로그인 후 쿠키를 갱신해 주세요."
            )
        if "punish" in current_url or "tmd" in current_url:
            raise CrawlerException(
                "1688 봇 차단이 감지되었습니다. IP를 변경하거나 잠시 후 재시도해 주세요."
            )

        content = await page.content()
        lower = content.lower()

        if "captcha" in lower or "滑块" in lower:
            raise CrawlerException(
                "1688 캡차가 감지되었습니다. IP를 변경하거나 잠시 후 재시도해 주세요."
            )

    # ── wait ────────────────────────────────────────────────

    async def _wait_for_content(self, page: Page) -> None:
        """상품 정보가 렌더링될 때까지 대기"""
        for sel in SELECTORS["title"]:
            try:
                await page.wait_for_selector(sel, timeout=8_000)
                logger.debug(f"제목 셀렉터 확인: {sel}")
                return
            except PwTimeout:
                continue
        logger.warning("제목 셀렉터 미발견 - 2초 추가 대기 후 진행")
        await page.wait_for_timeout(2_000)

    # ── extractors ──────────────────────────────────────────

    async def _try_selectors(self, page: Page, key: str) -> list:
        """후보 셀렉터 목록을 순회하며 첫 번째 매칭 결과를 반환"""
        for sel in SELECTORS[key]:
            elements = await page.query_selector_all(sel)
            if elements:
                return elements
        return []

    async def _extract_title(self, page: Page) -> str:
        elements = await self._try_selectors(page, "title")
        if elements:
            text = await elements[0].inner_text()
            return text.strip()

        og = await page.query_selector('meta[property="og:title"]')
        if og:
            return (await og.get_attribute("content") or "").strip()

        return await page.title()

    async def _extract_price(self, page: Page) -> float:
        elements = await self._try_selectors(page, "price")
        if elements:
            raw = await elements[0].inner_text()
            numbers = re.findall(r"[\d.]+", raw)
            if numbers:
                return float(numbers[0])

        content = await page.content()
        matches = re.findall(r"[Y\u00a5\uffe5]\s*([\d.]+)", content)
        if matches:
            prices = [float(m) for m in matches if float(m) > 0]
            if prices:
                return min(prices)

        logger.warning("가격 추출 실패 - 0 반환")
        return 0.0

    async def _extract_images(self, page: Page) -> list[str]:
        elements = await self._try_selectors(page, "images")
        urls: list[str] = []
        seen: set[str] = set()

        for el in elements:
            src = (
                await el.get_attribute("src")
                or await el.get_attribute("data-src")
                or await el.get_attribute("data-lazy-src")
                or ""
            )
            if not src or src in seen:
                continue
            if src.startswith("//"):
                src = "https:" + src
            src = re.sub(r"_(\d+x\d+)\.\w+$", "", src)
            seen.add(src)
            urls.append(src)
            if len(urls) >= 5:
                break

        if not urls:
            og = await page.query_selector('meta[property="og:image"]')
            if og:
                content = await og.get_attribute("content") or ""
                if content:
                    urls.append(
                        content if content.startswith("http") else f"https:{content}"
                    )

        return urls

    async def _extract_options(self, page: Page) -> list[str]:
        elements = await self._try_selectors(page, "options")
        options: list[str] = []
        seen: set[str] = set()

        for el in elements:
            text = (await el.inner_text()).strip()
            if text and text not in seen:
                seen.add(text)
                options.append(text)

        return options

    async def _extract_description(self, page: Page) -> str:
        elements = await self._try_selectors(page, "description")
        if elements:
            text = await elements[0].inner_text()
            cleaned = text.strip()
            if cleaned:
                return cleaned

        og = await page.query_selector('meta[property="og:description"]')
        if og:
            return (await og.get_attribute("content") or "").strip()

        meta = await page.query_selector('meta[name="description"]')
        if meta:
            return (await meta.get_attribute("content") or "").strip()

        return ""


def get_crawler_service() -> CrawlerService:
    return CrawlerService()
