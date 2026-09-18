"""일계표 대사 화면 — 등록·메뉴 키·권한 배선 (2026-08-26)."""

import re
from pathlib import Path

from app.services.access_policy import HEAD_OFFICE_PRIVILEGED_MENU_KEYS, MENU_KEYS

ROOT = Path(__file__).resolve().parent.parent
UI = ROOT / "desktop" / "ui"
MAIN = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
CONTEXT = (UI / "context.js").read_text(encoding="utf-8")
HTML = (UI / "bank-reconcile.html").read_text(encoding="utf-8")
JS = (UI / "bank-reconcile.js").read_text(encoding="utf-8")


def test_화면은_screen_을_거쳐_등록된다():
    assert '@app.get("/desktop/bank-reconcile", include_in_schema=False)' in MAIN
    assert '_screen("bank-reconcile.html")' in MAIN


def test_html_은_버전_붙은_스크립트를_부른다():
    assert re.search(r'/ui/bank-reconcile\.js\?v=\d{8}-\d+', HTML), "JS 에 ?v= 가 없으면 캐시에 갇힌다"
    assert re.search(r'/ui/context\.js\?v=', HTML)
    assert "<title>MOA · 일계표 대사</title>" in HTML
    assert 'class="side-nav"' in HTML, "사이드바 자리(context.js 가 그린다)가 있어야 한다"


def test_메뉴_키_배선():
    assert "bankReconcile" in MENU_KEYS
    assert "bankReconcile" in HEAD_OFFICE_PRIVILEGED_MENU_KEYS, "본사·개별권한 상한을 통과해야 개인 예외로 켤 수 있다"
    assert "{ label: '일계표 대사', href: '/desktop/bank-reconcile' }" in CONTEXT
    assert "'/desktop/bank-reconcile': 'bankReconcile'" in CONTEXT
    # 어떤 묶음에도 넣지 않는다 — 두 사람에게만 개인 예외로 켠다
    roles = (ROOT / "scripts" / "sql")
    seeds = "\n".join(p.read_text(encoding="utf-8") for p in roles.glob("*seed*role*.sql"))
    assert "bankReconcile" not in seeds


def test_js_는_본사만_열고_API_를_부른다():
    assert "ctx.office_id !== '10'" in JS
    assert "fetch(`/api/bank-reconcile?" in JS
    assert "window.A10_DOWNLOAD(`/api/bank-reconcile/export.xlsx?" in JS
    assert "voucher_only" in JS, "사이버브랜치에 없는 거래처(전표만)를 따로 보여야 한다"
    assert "A10_COLUMN_RESIZE" in JS


def test_대사_대상_아닌_표는_접혀_있고_회계단위_소계_표는_없다():
    """2026-08-26 사용자 결정 — 전표만 있는 거래처 표는 기본 접힘, 회계단위 소계 표는 뺀다."""
    assert 'class="br-card br-collapsed" id="voucherOnlyCard"' in HTML
    assert ".br-collapsed .br-body{display:none}" in HTML
    assert 'id="divisionTotals"' not in HTML and "divisionTotals" not in JS
    # 공통 .table-wrap 높이(화면만큼)를 풀어야 접힌 표가 화면 밖으로 밀리지 않는다
    assert ".br-card .table-wrap{height:auto;min-height:0;max-height:62vh}" in HTML


def test_상세_칸은_양쪽_카드와_머리글_있는_표로_보인다():
    """2026-08-26 사용자 요청 — 행을 눌렀을 때 내용이 한눈에 들어오게."""
    assert "function sideCard(label, side)" in JS
    for text in ("전표 없는 거래", "거래 없는 전표줄", "남는 건 없음", "합계는 같고 건수만 다릅니다"):
        assert text in JS, text
    assert '<th class="t">시각</th><th>적요</th><th>메모</th><th class="num">금액</th>' in JS
    assert '<th class="t">전표/줄</th><th class="t">회계단위</th><th>적요</th><th>관리번호</th><th class="num">금액</th>' in JS
    # 공통 td:first-child(고정폭 초록)가 상세 칸에 번지지 않게 글꼴을 되돌린다
    assert ".br-table tr.detail td{" in HTML and 'font-family:"Pretendard Variable"' in HTML
