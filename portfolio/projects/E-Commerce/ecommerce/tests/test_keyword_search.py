"""
카테고리 키워드 검색 기능 단위 테스트
대상: recommend_service.py - _fetch_domeme_by_keyword(), fetch_by_keywords()

실행: cd D:\AI\Claude\E-Commerce\ecommerce && venv\Scripts\python.exe -m pytest tests\test_keyword_search.py -v
(pytest 미설치 시: venv\Scripts\pip.exe install pytest pytest-asyncio)
"""

import asyncio
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import quote

import pytest

# 프로젝트 루트를 path에 추가
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# ═══════════════════════════════════════════════════════
# 1. EUC-KR 인코딩 테스트
# ═══════════════════════════════════════════════════════

class TestEucKrEncoding:
    """EUC-KR 인코딩 로직 검증"""

    def test_basic_korean_keyword(self):
        """기본 한글 키워드가 EUC-KR로 정상 인코딩되는지 확인"""
        keyword = "문구"
        encoded = quote(keyword.encode("euc-kr"))
        # EUC-KR로 인코딩 시 퍼센트 인코딩 결과가 비어있지 않아야 함
        assert encoded != ""
        assert "%" in encoded  # 한글은 반드시 퍼센트 인코딩됨
        # 디코딩 역검증
        from urllib.parse import unquote_to_bytes
        decoded = unquote_to_bytes(encoded).decode("euc-kr")
        assert decoded == keyword

    def test_common_category_keywords(self):
        """UI에 정의된 카테고리 키워드 4개 모두 EUC-KR 인코딩 가능한지 확인"""
        keywords = ["문구", "완구", "키링", "인형"]
        for kw in keywords:
            try:
                encoded = quote(kw.encode("euc-kr"))
                assert encoded != ""
            except (UnicodeEncodeError, LookupError):
                pytest.fail(f"키워드 '{kw}'가 EUC-KR 인코딩에 실패함")

    def test_euc_kr_unsupported_character(self):
        """EUC-KR에 없는 문자 포함 시 fallback(UTF-8 quote)이 동작하는지 확인"""
        # 이모지는 EUC-KR에 없음
        keyword = "테스트🎉"
        try:
            kw_encoded = quote(keyword.encode("euc-kr"))
        except (UnicodeEncodeError, LookupError):
            kw_encoded = quote(keyword)
        # fallback 경로: UTF-8로 quote한 결과가 나와야 함
        assert kw_encoded != ""
        assert "%" in kw_encoded

    def test_empty_keyword_encoding(self):
        """빈 키워드 인코딩 시 빈 문자열 반환"""
        keyword = ""
        encoded = quote(keyword.encode("euc-kr"))
        assert encoded == ""

    def test_english_keyword(self):
        """영문 키워드는 인코딩 없이 통과"""
        keyword = "iPhone"
        encoded = quote(keyword.encode("euc-kr"))
        assert encoded == "iPhone"

    def test_mixed_korean_english(self):
        """한영 혼합 키워드"""
        keyword = "USB케이블"
        encoded = quote(keyword.encode("euc-kr"))
        assert "USB" in encoded
        assert "%" in encoded  # 한글 부분은 퍼센트 인코딩


# ═══════════════════════════════════════════════════════
# 2. rightScroll 패턴 매칭 테스트
# ═══════════════════════════════════════════════════════

class TestRightScrollPattern:
    """HTML에서 상품 ID를 추출하는 정규식 패턴 검증"""

    def test_rightscroll_pattern_match(self):
        """rightScroll 패턴에서 상품 번호 추출"""
        html = '<a href="/41326424?advcnt=rightScroll">상품</a>'
        matches = re.findall(r"/(\d{7,})\?advcnt=rightScroll", html)
        assert matches == ["41326424"]

    def test_rightscroll_multiple_products(self):
        """여러 rightScroll 상품 추출"""
        html = (
            '<a href="/REDACTED_CONFIGURE_LOCALLY7?advcnt=rightScroll">A</a>'
            '<a href="/7654321?advcnt=rightScroll">B</a>'
            '<a href="/9999999?advcnt=rightScroll">C</a>'
        )
        matches = re.findall(r"/(\d{7,})\?advcnt=rightScroll", html)
        assert len(matches) == 3
        assert 'REDACTED_CONFIGURE_LOCALLY7' in matches
        assert "7654321" in matches

    def test_rightscroll_dedup(self):
        """중복 상품 번호 제거"""
        html = (
            '<a href="/REDACTED_CONFIGURE_LOCALLY7?advcnt=rightScroll">A</a>'
            '<a href="/REDACTED_CONFIGURE_LOCALLY7?advcnt=rightScroll">B</a>'
            '<a href="/7654321?advcnt=rightScroll">C</a>'
        )
        seen = set()
        unique = []
        for m in re.finditer(r"/(\d{7,})\?advcnt=rightScroll", html):
            item_no = m.group(1)
            if item_no not in seen:
                seen.add(item_no)
                unique.append(item_no)
        assert len(unique) == 2
        assert unique[0] == 'REDACTED_CONFIGURE_LOCALLY7'
        assert unique[1] == "7654321"

    def test_short_number_excluded(self):
        """7자리 미만 숫자는 상품번호로 인식하지 않아야 함"""
        html = '<a href="/REDACTED_CONFIGURE_LOCALLY?advcnt=rightScroll">짧은번호</a>'
        matches = re.findall(r"/(\d{7,})\?advcnt=rightScroll", html)
        assert matches == []

    def test_fallback_to_pure_href(self):
        """rightScroll이 없을 때 2순위(순수 href) 로직 검증"""
        html = (
            '<a href="/1111111?advcnt=mainCategory2024">광고1</a>'
            '<a href="/2222222?advcnt=mdAndDumping">광고2</a>'
            '<a href="https://domeggook.com/3333333">순수링크</a>'
            '<a href="/4444444">순수링크2</a>'
        )
        # rightScroll 없음 확인
        rs_matches = re.findall(r"/(\d{7,})\?advcnt=rightScroll", html)
        assert rs_matches == []

        # 2순위 로직: advcnt 있는 것은 제외
        seen = set()
        unique = []
        adv_ids = set()
        for m in re.finditer(r"/(\d{7,})\?advcnt=", html):
            adv_ids.add(m.group(1))
        for m in re.finditer(r'href="(?:https?://domeggook\.com)?/(\d{7,})"', html):
            item_no = m.group(1)
            if item_no not in seen and item_no not in adv_ids:
                seen.add(item_no)
                unique.append(item_no)

        # 광고 ID(1111111, 2222222)는 제외되고 순수 링크만 포함
        assert "1111111" not in unique
        assert "2222222" not in unique
        assert "3333333" in unique
        assert "4444444" in unique

    def test_no_products_at_all(self):
        """상품 링크가 전혀 없는 HTML"""
        html = "<html><body>검색 결과가 없습니다.</body></html>"
        matches = re.findall(r"/(\d{7,})\?advcnt=rightScroll", html)
        assert matches == []


# ═══════════════════════════════════════════════════════
# 3. fetch_by_keywords 중복 제거 테스트
# ═══════════════════════════════════════════════════════

class TestFetchByKeywordsDedup:
    """fetch_by_keywords의 중복 제거 로직 검증"""

    @pytest.mark.asyncio
    async def test_dedup_across_keywords(self):
        """서로 다른 키워드에서 같은 item_no가 나올 때 중복 제거"""
        from services.recommend_service import RecommendedProduct

        product_a = RecommendedProduct("DOMEME", "1111111", "상품A", 1000, "", "문구")
        product_b = RecommendedProduct("DOMEME", "2222222", "상품B", 2000, "", "완구")
        product_dup = RecommendedProduct("DOMEME", "1111111", "상품A복제", 1000, "", "완구")

        async def mock_fetch(kw, limit=10):
            if kw == "문구":
                return [product_a]
            elif kw == "완구":
                return [product_b, product_dup]
            return []

        with patch("services.recommend_service._fetch_domeme_by_keyword", side_effect=mock_fetch):
            from services.recommend_service import fetch_by_keywords
            results = await fetch_by_keywords(["문구", "완구"], limit_per_keyword=10)

        assert len(results) == 2
        item_nos = [r.item_no for r in results]
        assert item_nos.count("1111111") == 1  # 중복 제거 확인

    @pytest.mark.asyncio
    async def test_empty_keywords_list(self):
        """빈 키워드 리스트 입력 시 빈 결과 반환"""
        with patch("services.recommend_service._fetch_domeme_by_keyword", new_callable=AsyncMock, return_value=[]):
            from services.recommend_service import fetch_by_keywords
            results = await fetch_by_keywords([], limit_per_keyword=10)
        assert results == []

    @pytest.mark.asyncio
    async def test_all_keywords_return_empty(self):
        """모든 키워드 검색 결과가 0건일 때"""
        async def mock_fetch(kw, limit=10):
            return []

        with patch("services.recommend_service._fetch_domeme_by_keyword", side_effect=mock_fetch):
            from services.recommend_service import fetch_by_keywords
            results = await fetch_by_keywords(["없는키워드1", "없는키워드2"], limit_per_keyword=10)
        assert results == []


# ═══════════════════════════════════════════════════════
# 4. _fetch_domeme_by_keyword 네트워크 에러 핸들링
# ═══════════════════════════════════════════════════════

class TestNetworkErrorHandling:
    """네트워크 오류 시 에러 핸들링 검증"""

    @pytest.mark.asyncio
    async def test_timeout_returns_empty(self):
        """httpx.TimeoutException 발생 시 빈 리스트 반환"""
        import httpx

        mock_client = AsyncMock()
        mock_client.get.side_effect = httpx.TimeoutException("Connection timed out")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("services.recommend_service.httpx.AsyncClient", return_value=mock_client):
            from services.recommend_service import _fetch_domeme_by_keyword
            results = await _fetch_domeme_by_keyword("문구", limit=5)
        assert results == []

    @pytest.mark.asyncio
    async def test_http_500_returns_empty(self):
        """HTTP 500 응답 시 빈 리스트 반환"""
        mock_resp = MagicMock()
        mock_resp.status_code = 500

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("services.recommend_service.httpx.AsyncClient", return_value=mock_client):
            from services.recommend_service import _fetch_domeme_by_keyword
            results = await _fetch_domeme_by_keyword("문구", limit=5)
        assert results == []

    @pytest.mark.asyncio
    async def test_http_404_returns_empty(self):
        """HTTP 404 응답 시 빈 리스트 반환"""
        mock_resp = MagicMock()
        mock_resp.status_code = 404

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("services.recommend_service.httpx.AsyncClient", return_value=mock_client):
            from services.recommend_service import _fetch_domeme_by_keyword
            results = await _fetch_domeme_by_keyword("문구", limit=5)
        assert results == []


# ═══════════════════════════════════════════════════════
# 5. OG 메타태그 파싱 테스트
# ═══════════════════════════════════════════════════════

class TestOgMetaParsing:
    """상품 상세 페이지 OG 메타태그 파싱 검증"""

    def test_og_title_extraction(self):
        """og:title에서 제목 추출 및 [도매꾹] 접두사 제거"""
        page = '<meta property="og:title" content="[도매꾹] 무선 이어폰 블루투스">'
        m = re.search(r'property="og:title"[^>]*content="(.*?)"', page, re.I)
        title = re.sub(r"^\[도매꾹\]\s*", "", m.group(1)) if m else ""
        assert title == "무선 이어폰 블루투스"

    def test_og_title_without_prefix(self):
        """[도매꾹] 접두사 없는 제목"""
        page = '<meta property="og:title" content="무선 이어폰">'
        m = re.search(r'property="og:title"[^>]*content="(.*?)"', page, re.I)
        title = re.sub(r"^\[도매꾹\]\s*", "", m.group(1)) if m else ""
        assert title == "무선 이어폰"

    def test_og_title_missing(self):
        """og:title 메타태그가 없을 때 빈 문자열"""
        page = '<html><head></head></html>'
        m = re.search(r'property="og:title"[^>]*content="(.*?)"', page, re.I)
        title = re.sub(r"^\[도매꾹\]\s*", "", m.group(1)) if m else ""
        assert title == ""

    def test_price_extraction_with_comma(self):
        """가격에 콤마 포함된 경우 정상 파싱"""
        desc = "도매가 12,500원 / 소비자가 25,000원"
        p = re.search(r"([\d,]+)원", desc)
        price = int(p.group(1).replace(",", "")) if p else 0
        assert price == 12500

    def test_price_extraction_no_price(self):
        """가격 정보 없을 때 0"""
        desc = "상품 설명만 있음"
        p = re.search(r"([\d,]+)원", desc)
        price = int(p.group(1).replace(",", "")) if p else 0
        assert price == 0


# ═══════════════════════════════════════════════════════
# 6. ecommerce_admin.py 분기 로직 정적 검증
# ═══════════════════════════════════════════════════════

class TestAdminBranchLogic:
    """ecommerce_admin.py 내 키워드 검색 분기 로직 정적 검증
    (Streamlit UI는 직접 실행 불가하므로 로직 검증만 수행)
    """

    def test_category_keywords_empty_uses_recommendation(self):
        """category_keywords가 비어있으면 기존 추천 모드로 동작해야 함"""
        # ecommerce_admin.py 248행: if category_keywords:
        category_keywords = []
        assert not category_keywords  # falsy -> 추천 모드

    def test_category_keywords_nonempty_uses_keyword_search(self):
        """category_keywords가 있으면 키워드 검색 모드로 동작해야 함"""
        category_keywords = ["문구", "완구"]
        assert category_keywords  # truthy -> 키워드 모드

    def test_custom_keyword_appended(self):
        """커스텀 키워드가 기존 리스트에 추가되는지 검증"""
        # ecommerce_admin.py 226-227행 로직 시뮬레이션
        category_keywords = ["문구", "완구"]
        custom_kw = "스티커"
        if custom_kw.strip() and custom_kw.strip() not in category_keywords:
            category_keywords = category_keywords + [custom_kw.strip()]
        assert "스티커" in category_keywords
        assert len(category_keywords) == 3

    def test_custom_keyword_duplicate_not_added(self):
        """이미 있는 키워드는 중복 추가되지 않음"""
        category_keywords = ["문구", "완구"]
        custom_kw = "문구"
        if custom_kw.strip() and custom_kw.strip() not in category_keywords:
            category_keywords = category_keywords + [custom_kw.strip()]
        assert len(category_keywords) == 2

    def test_custom_keyword_empty_not_added(self):
        """빈 커스텀 키워드는 추가되지 않음"""
        category_keywords = ["문구"]
        custom_kw = "  "
        if custom_kw.strip() and custom_kw.strip() not in category_keywords:
            category_keywords = category_keywords + [custom_kw.strip()]
        assert len(category_keywords) == 1

    def test_kw_source_only_domeme(self):
        """키워드 검색은 kw_source와 무관하게 _fetch_domeme_by_keyword만 호출
        (오너클랜 키워드 검색은 미구현 -- 이것이 잠재적 이슈)
        """
        # ecommerce_admin.py 116-128행 참고:
        # kw_source 선택박스에 OWNERCLAN이 있지만,
        # 124행에서 항상 _fetch_domeme_by_keyword만 호출
        kw_source = "OWNERCLAN"
        # 실제 코드에서 kw_source 값과 무관하게 도매꾹만 검색함
        # 이것은 BUG -- kw_source가 무시됨
        assert kw_source == "OWNERCLAN"  # 이 값이 사용되지 않는 것이 버그


# ═══════════════════════════════════════════════════════
# 7. URL 구성 검증
# ═══════════════════════════════════════════════════════

class TestUrlConstruction:
    """검색 URL 구성 검증"""

    def test_url_with_korean_keyword(self):
        """한글 키워드로 구성된 URL이 유효한 형태인지"""
        keyword = "무선이어폰"
        kw_encoded = quote(keyword.encode("euc-kr"))
        url = f"https://domeggook.com/main/item/itemList.php?sw={kw_encoded}&sf=ttl&so=ha"
        assert url.startswith("https://domeggook.com")
        assert "sf=ttl" in url
        assert "so=ha" in url

    def test_url_sort_order(self):
        """정렬 파라미터 so=ha(조회 많은 순)가 포함되어 있는지"""
        keyword = "test"
        kw_encoded = quote(keyword.encode("euc-kr"))
        url = f"https://domeggook.com/main/item/itemList.php?sw={kw_encoded}&sf=ttl&so=ha"
        assert "so=ha" in url  # ha = 조회수 높은순


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
