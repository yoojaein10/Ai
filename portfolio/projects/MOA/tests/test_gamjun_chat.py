"""감정서 조회 챗봇.

질문 → 필터 추출(Gemini) → 감정서 DB 조회 → 마크다운. 조회는 벤더 모듈
(app/vendor/gamjun_search.py, 본서버 챗봇과 같은 코드)이 하고 여기서 감싼다.
"""

import re
from pathlib import Path

import pytest

from app.services import gamjun_chat

ROOT = Path(__file__).resolve().parent.parent
SERVICE = ROOT / "app" / "services" / "gamjun_chat.py"
SCRIPT = ROOT / "desktop" / "ui" / "gamjun-chat.js"
PAGE = ROOT / "desktop" / "ui" / "gamjun-chat.html"
VENDOR = ROOT / "app" / "vendor" / "gamjun_search.py"


def test_벤더_모듈은_손대지_않는다():
    """본서버가 같은 파일을 쓴다. 고칠 일이 있으면 위에서 감싼다."""
    assert VENDOR.exists(), "app/vendor/gamjun_search.py 사본이 있어야 한다"
    assert (ROOT / "app" / "vendor" / "README.md").exists(), "출처·주의사항을 남겨야 한다"


@pytest.mark.parametrize(
    "spec,dropped",
    [
        ({"region": "청담동", "keywords": ["효성빌라"]}, True),
        ({"region": "청담동", "want_content": True}, True),
        ({"region": "청담동"}, False),
        ({}, False),
    ],
)
def test_본문_검색_조건은_떼어낸다(spec, dropped):
    """벤더의 키워드 절이 `LIKE OR (FTS 서브쿼리 IN)` 이라 20~40초씩 걸린다.

    한 번은 CPU를 35분 태웠다(읽기 508 · CXPACKET). 원본 저자도 평가사 절에는
    같은 문제를 UNION-IN 으로 고쳐 놨는데 키워드 절에는 안 했다.
    """
    trimmed, was_dropped = gamjun_chat._strip_content(spec)
    assert was_dropped is dropped
    assert "keywords" not in trimmed and "want_content" not in trimmed
    # 뗀 뒤에도 나머지 조건은 살아 있어야 한다 — 청담동 검색은 되어야 한다.
    if spec.get("region"):
        assert trimmed["region"] == spec["region"]


def test_조건이_하나도_없으면_조회하지_않는다():
    """'오늘 점심 뭐 먹을까?' 가 '점심'으로 검색되면 사용자가 혼란스럽다."""
    assert gamjun_chat._has_any_filter({}) is False
    assert gamjun_chat._has_any_filter({"limit": 10}) is False, "limit 만으론 조건이 아니다"
    assert gamjun_chat._has_any_filter({"region": "청담동"}) is True
    assert gamjun_chat._has_any_filter({"value_min": 10000000000}) is True


def test_조회_시한이_걸려_있다():
    """시한이 없으면 한 질문이 서버 CPU를 수십 분 문다 (2026-08-04 실측 35분)."""
    service = SERVICE.read_text(encoding="utf-8")
    assert 'os.environ.setdefault("GAMJUN_QUERY_TIMEOUT"' in service


def test_키는_설정에서_읽는다():
    """API 키를 코드에 박으면 안 된다 — .env 는 .gitignore 1번 줄에 있다."""
    service = SERVICE.read_text(encoding="utf-8")
    assert "gemini_api_key" in service
    assert "AIza" not in service, "키가 코드에 박혔다"
    assert "AIza" not in PAGE.read_text(encoding="utf-8")
    assert "AIza" not in SCRIPT.read_text(encoding="utf-8")


def test_화면이_캐시되지_않는다():
    main = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
    index = main.index("def desktop_gamjun_chat(")
    assert "no-cache" in main[index : index + 400]


def test_라우터가_배선되어_있다():
    main = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
    assert "from app.routers.gamjun_chat import router as gamjun_chat_router" in main
    assert "app.include_router(gamjun_chat_router)" in main


def test_답변_렌더링이_주입을_막는다():
    """답변에 표·굵게만 살린다. escape 뒤에 인라인 서식을 붙여야 한다."""
    script = SCRIPT.read_text(encoding="utf-8")
    assert "function inline(" in script
    assert "escapeHtml(text)" in script, "escape 를 먼저 하고 서식을 붙여야 한다"
    # 외부 마크다운 라이브러리를 받지 않는다 (내부망이라 CDN 불가).
    assert "http://" not in PAGE.read_text(encoding="utf-8")
    assert "https://" not in PAGE.read_text(encoding="utf-8")


def test_같은_질문은_캐시로_바로_답한다():
    """응답 1.2초의 대부분(~1초)이 Gemini 왕복이다. 예시 버튼은 늘 같은 질문이라
    캐시가 특히 잘 듣는다. 감정서 DB는 하루 단위 배치라 10분 캐시로 낡을 일이 없다."""
    gamjun_chat._CACHE.clear()
    key = ("화성시 아파트", "")
    gamjun_chat._cache_put(key, {"answer": "x", "note": "", "spec": {}})
    assert gamjun_chat._cache_get(key) == {"answer": "x", "note": "", "spec": {}}
    # 시한이 지나면 버린다
    stamp, ttl, value = gamjun_chat._CACHE[key]
    gamjun_chat._CACHE[key] = (stamp - ttl - 1, ttl, value)
    assert gamjun_chat._cache_get(key) is None
    # 꽉 차면 가장 오래된 것부터 민다
    gamjun_chat._CACHE.clear()
    for index in range(gamjun_chat._CACHE_MAX + 5):
        gamjun_chat._cache_put(("q%d" % index, ""), {"answer": ""})
    assert len(gamjun_chat._CACHE) <= gamjun_chat._CACHE_MAX


@pytest.mark.parametrize(
    "question,expected",
    [
        ("01-2607-3-2235", "01-2607-3-2235"),
        ("01-2607-3-2235 의뢰인이 누구야?", "01-2607-3-2235"),
        ("01-2607-3-2235 이 감정서 내용 알려줘", "01-2607-3-2235"),
        ("01-2603-1-0233-2 내용", "01-2603-1-0233-2"),
        # 번호에 다른 조건이 섞이면 정상 경로(Gemini)로 보낸다.
        ("01-2607-3-2235 말고 성수동 다른 담보 건 알려줘", None),
        ("성수동 감정서 알려줘", None),
    ],
)
def test_감정서번호만_묻는_질문은_Gemini_를_건너뛴다(question, expected):
    assert gamjun_chat._doc_only(question) == expected


def test_집계는_본서버와_같은_빌더를_쓴다():
    """'몇 건이야?'가 목록 10건으로 답하면 틀린 답이다 — 집계 SQL을 태워야 한다."""
    service = SERVICE.read_text(encoding="utf-8")
    assert "build_agg_sql" in service
    assert "build_group_sql" in service
    assert "render_agg_results" in service


def test_화면이_예열을_건다():
    """첫 질문이 어휘 캐시 로딩비(~1초)를 물지 않게 health 가 백그라운드 예열한다."""
    router = (ROOT / "app" / "routers" / "gamjun_chat.py").read_text(encoding="utf-8")
    assert "gamjun_chat.warmup()" in router


# ── 회계(돈) 경로 ──────────────────────────────────────────────────────────

from app.services import money_chat


@pytest.mark.parametrize(
    "question,is_money",
    [
        ("한국투자저축은행 미수금 얼마야?", True),
        ("이번 달 들어온 돈 얼마야?", True),
        ("01-2607-3-2235 입금됐어?", True),
        ("선수금 남은 거 있어?", True),
        # 감정서 쪽 질문이 돈으로 새면 안 된다.
        ("화성시 동탄 아파트 감정서", False),
        ("수수료합계 1억 넘는 감정서 있어?", False),
        ("01-2607-3-2235 의뢰인이 누구야?", False),
    ],
)
def test_돈_질문_판별(question, is_money):
    assert money_chat.is_money_question(question) is is_money


def test_돈_라우팅이_감정서번호_지름길보다_먼저다():
    """'01-xxx 입금됐어?' 는 감정서 카드가 아니라 돈 이력으로 가야 한다."""
    source = SERVICE.read_text(encoding="utf-8")
    assert source.index("money_chat.is_money_question") < source.index("_doc_only(question)")


def test_돈_숫자는_입금현황_계산식에서_나온다():
    """챗봇이 자기만의 계산식을 쓰면 화면과 숫자가 갈라진다 — 미수금 기준(매출총액)은
    2026-08-04 재무팀과 맞춘 값이라 ReceivableService·receivable_status_cte 를 그대로 쓴다."""
    source = (ROOT / "app" / "services" / "money_chat.py").read_text(encoding="utf-8")
    assert "ReceivableService" in source
    assert "_tax_invoice_totals" in source
    # 기간 입금분도 화면과 같은 입금 판정 규칙(CTE)을 재사용한다 — 직접 만든 판정식 금지.
    assert "receivable_status_cte" in source
    assert "a10_receivable_summary" not in source, "요약 테이블 직접 조회 금지"
    assert "1030000" not in source, "입금 판정 규칙을 베껴 쓰지 말 것 (CTE 재사용)"


def test_용도지역_검색도_본문이라_차단된다():
    """zone 절은 jun.chunk 본문 LIKE 전량 스캔이다 — 실측 region 0.3초 vs zone 40초."""
    assert "zone" in gamjun_chat.CONTENT_FILTERS
    assert "zone" not in gamjun_chat.SUPPORTED_FILTERS
    trimmed, dropped = gamjun_chat._strip_content({"zone": "일반상업지역", "region": "강남구"})
    assert dropped and "zone" not in trimmed and trimmed["region"] == "강남구"


def test_소유자_채무자_최근N건도_조건으로_인정한다():
    """벤더가 실제로 지원하는 축인데 게이트에 없으면 '못 알아들었습니다'로 오거부된다."""
    assert gamjun_chat._has_any_filter({"owner": "김철수"}) is True
    assert gamjun_chat._has_any_filter({"debtor": "이영희"}) is True
    assert gamjun_chat._has_any_filter({"_recent": True}) is True
    assert gamjun_chat._has_any_filter({"regions": ["서울", "경기"]}) is True


def test_돈_답변_캐시는_60초다():
    """회계 데이터는 10분 주기 배치 + 화면 라이브 조회 — 600초 캐시면 화면과 갈라진다."""
    assert gamjun_chat._MONEY_CACHE_TTL <= 60.0
    source = SERVICE.read_text(encoding="utf-8")
    assert "ttl=_MONEY_CACHE_TTL" in source


def test_돈_추출값_타입이_이상해도_죽지_않는다():
    """Gemini 가 배열·문자열 숫자를 돌려줘도 503 이 되면 안 된다."""
    assert money_chat._as_str(["한국투자저축은행"]) == "한국투자저축은행"
    assert money_chat._as_str([]) is None
    assert money_chat._as_str(12) == "12"
    assert money_chat._as_int("다섯", 5) == 5
    assert money_chat._as_int("10", 5) == 10
    assert money_chat._parse_date("2026-08-04T00:00:00") == __import__("datetime").date(2026, 8, 4)
    assert money_chat._parse_date("이번달") is None


def test_미수금_답변은_기간_의미를_밝힌다():
    """기간이 최근 입금일 기준이라 옛 미수 건이 빠진다 — 숨기면 과소 보고가 된다."""
    source = (ROOT / "app" / "services" / "money_chat.py").read_text(encoding="utf-8")
    assert "최근 입금일" in source
    assert "전체 기간" in source, "옛 건까지 보는 길을 안내해야 한다"


def test_오류_원문을_사용자에게_흘리지_않는다():
    """벤더 예외에 SQL 조각·DB 호스트가 섞인다 — 로그로만 남긴다."""
    router = (ROOT / "app" / "routers" / "gamjun_chat.py").read_text(encoding="utf-8")
    assert "logger.exception" in router
    assert "str(exc)" not in router


def test_돈_추출_실패해도_죽지_않는다():
    """Gemini 가 죽으면 규칙 어림으로라도 의도를 잡는다."""
    import asyncio
    saved = dict(__import__("os").environ)
    __import__("os").environ["GEMINI_API_KEY"] = ""
    try:
        spec = asyncio.run(money_chat._extract("미수금 큰 거 알려줘"))
        assert spec.get("intent") == "top"
        spec = asyncio.run(money_chat._extract("이번 달 입금 얼마야?"))
        assert spec.get("intent") == "received"
    finally:
        __import__("os").environ.clear()
        __import__("os").environ.update(saved)


def test_메뉴는_한_곳에서만_정한다():
    """예전에는 16개 화면 HTML 이 저마다 <nav class="side-nav"> 를 통째로
    품고 있었다. 메뉴 하나 고치려면 16곳을 똑같이 손대야 했고, 화면이
    늘수록 어긋날 게 뻔했다. 이제 context.js 의 A10_MENU 한 곳에서 그린다
    (2026-08-07)."""
    ui = ROOT / "desktop" / "ui"
    ctx = (ui / "context.js").read_text(encoding="utf-8")
    assert "const A10_MENU" in ctx and "function a10RenderMenu(" in ctx

    # 화면 HTML 에는 빈 껍데기만 남아야 한다
    for f in sorted(ui.glob("*.html")):
        html = f.read_text(encoding="utf-8")
        if 'class="side-nav"' not in html:
            continue
        nav = html[html.index('<nav class="side-nav">'):]
        nav = nav[:nav.index("</nav>") + 6]
        assert "<a" not in nav, f"{f.name} 에 메뉴가 아직 박혀 있다"


def test_메뉴_구성이_업무_갈래를_따른다():
    """감정서 LIST 는 묶음 밖 맨 위(기본 화면), 나머지는 네 갈래.
    16개 항목이 하나도 빠지지 않아야 한다 (2026-08-07 개편)."""
    ctx = (ROOT / "desktop" / "ui" / "context.js").read_text(encoding="utf-8")
    menu = ctx[ctx.index("const A10_MENU"):ctx.index("function a10MenuActive(")]
    for group in ("수금·미수", "매출·실적", "전표·반제", "관리·점검"):
        assert f"group: '{group}'" in menu, group
    for href in ("/desktop", "/desktop/receivables?mode=received",
                 "/desktop/payment-sms", "/desktop/receivables?mode=outstanding",
                 "/desktop/collection", "/desktop/gamjun-chat",
                 "/desktop/sales-stats", "/desktop/work-report",
                 "/desktop/allocation", "/desktop/bonus",
                 "/desktop/card-vouchers", "/desktop/banje-receivable",
                 "/desktop/banje-advance", "/desktop/reconcile",
                 "/desktop/data-quality", "/desktop/fee-basis",
                 "/desktop/permissions"):
        assert f"href: '{href}'" in menu, href
    # 감정서 LIST 는 묶음 밖 첫 줄
    assert menu.index("감정서 LIST") < menu.index("group:")


def test_묶음은_접힌_채로_시작한다():
    """대분류만 먼저 보이고 누르면 아래로 열린다 (2026-08-07 요청).

    두 가지는 예외다 — 지금 보고 있는 화면이 든 묶음은 언제나 열어 둔다
    (안 그러면 내가 어디 있는지 알 수 없다). 사람이 직접 열어 둔 묶음은
    기억한다 (매번 다시 여는 것이 제일 성가시다)."""
    ui = ROOT / "desktop" / "ui"
    ctx = (ui / "context.js").read_text(encoding="utf-8")
    # 지금 화면이 든 묶음은 연다
    assert "entry.items.some(it => a10MenuActive(it.href))" in ctx
    assert "here || remembered.has(entry.group)" in ctx
    # 열어 둔 것을 기억한다
    assert "A10_NAV_OPEN_KEY" in ctx and "localStorage" in ctx
    assert "function a10NavRemember(" in ctx
    # 머리글은 버튼이라 키보드로도 열린다
    assert '<button type="button" class="nav-group-title"' in ctx
    assert 'aria-expanded' in ctx

    css = (ui / "dashboard.css").read_text(encoding="utf-8")
    assert ".nav-group > a { display: none; }" in css, "접힌 것이 기본"
    assert ".nav-group.open > a { display: flex; }" in css
    # 좁은 화면은 가로 한 줄이라 접을 자리가 없다 — 전부 편다
    narrow = css[css.rindex(".nav-group-title { display: none; }"):]
    assert ".nav-group > a, .nav-group.open > a { display: flex; }" in narrow


def test_대분류가_하위보다_크다():
    """menu_reference 참조 교정 (2026-08-10) — 전에는 대분류가 10px 회색 눈썹
    라벨이라 하위 메뉴보다 작아 위계가 뒤집혀 보였다.

    2026-08-11 운영 배포된 모양을 계약으로 삼는다. 권한 브랜치가 따로 잡아 둔
    치수(대분류 13px/44px · 하위 21px 들여쓰기 · 묶음 위 실선)가 있었지만,
    사용자가 화면을 보고 한 단 줄인 쪽이 운영에 나갔다 — 그쪽을 따른다.
    """
    css = (ROOT / "desktop" / "ui" / "dashboard.css").read_text(encoding="utf-8")
    top = css[css.index(".side-nav > a {"):]
    top = top[: top.index("}")]
    sub = css[css.index(".nav-group > a { padding-left"):]
    sub = sub[: sub.index("}")]
    def px(block, key):
        m = re.search(key + r": ([\d.]+)px", block)
        return float(m.group(1)) if m else None
    assert px(top, "font-size") > px(sub, "font-size"), "대분류가 하위보다 커야 한다"
    assert px(top, "min-height") > px(sub, "min-height")
    assert "padding-left: 24px" in sub, "하위 메뉴 들여쓰기"
    # 묶음을 가르는 선은 있어야 한다(운영은 아래 테두리로 긋는다).
    assert ".nav-group { display: grid; gap: 2px; margin: 0; border-bottom:" in css
    # 권한으로 메뉴가 숨을 때를 위한 둘.
    assert ".side-nav > a.hidden + .nav-group { border-top: 0; }" in css
    assert ".nav-group:has(a.active) > .nav-group-title" in css


def test_빈_묶음은_머리글까지_감춘다():
    """항목만 숨기면 '전표·반제' 같은 제목만 덩그러니 남는다 (2026-08-07).

    2026-08-08 권한 브랜치와 합치면서 판단 근거가 바뀌었다. 종전에는
    `hq: true` 로 본사/지사만 갈랐는데, 그러면 같은 본사 안에서 재무와
    총무를 못 가른다. 이제 메뉴 키 권한으로 링크를 감추고, 그 **뒤에**
    빈 묶음을 접는다 — 순서가 뒤집히면 아무 효과가 없다.
    """
    ctx = (ROOT / "desktop" / "ui" / "context.js").read_text(encoding="utf-8")
    assert "function a10HideEmptyGroups(" in ctx
    hide = ctx.index("if(!key || !window.A10_CAN(key)) link.classList.add('hidden');")
    collapse = ctx.index("a10HideEmptyGroups();")
    assert hide < collapse, "링크를 감춘 뒤에 묶음을 접어야 한다"


def test_메뉴는_소속이_아니라_메뉴_권한으로_갈린다():
    """`hq: true` 로 되돌아가면 안 된다 (2026-08-08).

    소속만 보면 본사 전 직원이 카드전표·권한관리를 보게 된다. 실측으로
    본사 136명 중 전 메뉴가 정당한 사람은 8명(재무 4·전산정보팀 4)뿐이다.
    """
    ctx = (ROOT / "desktop" / "ui" / "context.js").read_text(encoding="utf-8")
    menu = ctx[ctx.index("const A10_MENU"):ctx.index("function a10MenuActive")]
    assert "hq: true" not in menu, "메뉴 노출을 소속으로 되돌리면 안 된다"
    assert "menuKeyForUrl" in ctx and "window.A10_CAN(key)" in ctx


def test_메뉴에_있는_주소는_모두_메뉴_키가_있다():
    """A10_MENU 에 화면을 더하면서 menuKeyForUrl 매핑을 빠뜨리면, 그 메뉴는
    fail-closed 규칙에 걸려 **전원에게 사라진다**. 실측: 내 매출실적이
    메뉴 통합 때 A10_MENU 에서 통째로 빠져 84명이 못 볼 뻔했다.
    """
    ctx = (ROOT / "desktop" / "ui" / "context.js").read_text(encoding="utf-8")
    menu = ctx[ctx.index("const A10_MENU"):ctx.index("function a10MenuActive")]
    hrefs = {h.split("?")[0] for h in re.findall(r"href: '([^']+)'", menu)}
    keyblock = ctx[ctx.index("const menuKeyForUrl"):ctx.index("// 메뉴 표시는")]
    mapped = set(re.findall(r"'(/desktop[^']*)'", keyblock)) | {"/desktop"}
    missing = sorted(hrefs - mapped)
    assert not missing, f"menuKeyForUrl 매핑이 없어 전원에게 숨는다: {missing}"


def test_감정서_조회는_입금_대사로_불린다():
    """하는 일이 통장 입금에 감정서를 붙이는 대사라 이름을 바꿨다
    (2026-08-07). 주소(/desktop/gamjun-chat)는 그대로 둔다 — 북마크와
    EXE 가 물고 있어 주소까지 바꾸면 위험 대비 얻는 게 적다."""
    ctx = (ROOT / "desktop" / "ui" / "context.js").read_text(encoding="utf-8")
    line = [x for x in ctx.splitlines() if "/desktop/gamjun-chat" in x][0]
    assert "입금 대사" in line and "감정서 조회" not in line
    page = PAGE.read_text(encoding="utf-8")
    assert "<h1>입금 대사</h1>" in page
    assert "MOA · 입금 대사" in page
    # 주소는 그대로
    assert "/desktop/gamjun-chat" in ctx


def test_연결_상태는_상단바에_있고_겹치지_않는다():
    """대화 패널 안에 절대배치로 띄웠더니 첫 질문·답변과 겹쳤다 (2026-08-05).
    상단바 flex 항목으로 올려 어떤 폭에서도 겹치지 않게 한다."""
    page = PAGE.read_text(encoding="utf-8")
    topbar = page[page.index('class="topbar"'):page.index("</header>")]
    assert 'id="chatState"' in topbar, "상태 알약은 상단바에 있어야 한다"
    body = page[page.index("</header>"):]
    assert 'id="chatState"' not in body, "본문 안에 남아 있으면 안 된다"
    css = (ROOT / "desktop" / "ui" / "gamjun-chat.css").read_text(encoding="utf-8")
    state = css[css.index(".chat-state{"):css.index(".chat-state.ok")]
    assert "position:absolute" not in state, "절대배치는 겹침의 원인"
    assert "margin-left:auto" in state, "flex 로 오른쪽에 붙인다"



def test_감정서_검색_경로가_화면에_없다():
    """이 화면은 입금 대사 하나만 한다 (2026-08-06 확정). 검색칸은 적요 필터라
    감정서 검색·더보기·조건 칩은 배선 자체가 없어야 한다 — 남겨 두면
    '본문 내용 검색은 아직 준비 중' 같은 챗봇 안내가 새어 나온다."""
    script = SCRIPT.read_text(encoding="utf-8")
    for gone in ("runSearch", "attachMore", "specChips", "requeryWithout",
                 "'/api/gamjun-chat/page'", "'/api/gamjun-chat/requery'"):
        assert gone not in script, f"감정서 검색 잔재: {gone}"

def test_소속_지사로_조회_범위를_강제한다():
    """본사 사용자는 본사(01-) 건만. spec.office 를 서버가 덮어쓴다."""
    source = SERVICE.read_text(encoding="utf-8")
    assert 'spec["office"] = label' in source, "목록·집계 경로 강제"
    assert source.count('clean["office"] = label') >= 2, "더보기·칩 재조회도 강제"
    # 캐시 키에 소속이 들어가야 지사끼리 답이 섞이지 않는다.
    assert 'f"{office_code}|{question}"' in source


def test_office_scope_는_지사_코드를_라벨과_접두사로_바꾼다():
    from app.services import money_chat
    money_chat._OFFICE_CACHE["99t"] = ("동부지사", "13")
    assert money_chat.office_scope("99t") == ("동부지사", "13")
    money_chat._OFFICE_CACHE.pop("99t", None)


import asyncio as _asyncio


def test_다른_지사_감정서_카드는_열지_않는다():
    from app.services import money_chat
    money_chat._OFFICE_CACHE["10"] = ("본사", "01")
    result = _asyncio.run(gamjun_chat.doc_detail("10-2607-3-0742", "10"))
    assert result["answer"] == ""
    assert "본사" in result["note"] and "다른 지사" in result["note"]


def test_돈_경로도_소속을_따른다():
    source = (ROOT / "app" / "services" / "money_chat.py").read_text(encoding="utf-8")
    assert 'office_code=office_code' in source, "ReceivableService 에 소속 전달"
    assert '_inflow_sync, date_from, date_to, office_code' in source, "기간 입금도 소속"
    assert 'if not doc_id.startswith(prefix + "-")' in source, "번호 게이트"



def test_화면은_사용자와_선택_지사를_함께_보낸다():
    """조회 범위는 서버가 usr_seq 로 다시 판정하지만, 화면도 식별자를 보낸다."""
    script = SCRIPT.read_text(encoding="utf-8")
    assert script.count("usr_seq:USR(),office_code:OFFICE()") >= 2, (
        "목록 조회와 감정서 찾기 둘 다 식별자를 보낸다")

def test_소속은_서버가_usr_seq_로_푼다():
    source = SERVICE.read_text(encoding="utf-8")
    assert "TMWCMN_USR_BAC_INFO" in source, "사용자 원장에서 직접"
    assert 'row["use_yn"] == "Y" and row["rtrm_fl"] == "0"' in source, "재직자만 (fail-closed)"
    router = (ROOT / "app" / "routers" / "gamjun_chat.py").read_text(encoding="utf-8")
    assert router.count("await _office_of(") >= 6, "stream·ask·page·requery·suggest·doc 전부"
    assert "사용자 확인이 안 되어" in router, "무효 사용자는 거부"


def test_권한_밖_지사는_서버가_되돌린다():
    """지사 사용자가 개발자도구로 office_code 를 바꿔도 자기 지사만 보여야 한다.
    전체조회 권한 판정은 다른 화면과 같다 (본사이거나 view_all_offices='Y')."""
    source = SERVICE.read_text(encoding="utf-8")
    assert "async def resolve_office(" in source
    assert "return want if await can_view_all(usr_seq) else own" in source, (
        "권한 없으면 소속으로 되돌린다")
    assert "UserPermission" in source and "view_all_offices" in source
    router = (ROOT / "app" / "routers" / "gamjun_chat.py").read_text(encoding="utf-8")
    assert "gamjun_chat.resolve_office(usr_seq, requested)" in router


def test_전체_선택은_지사로_좁히지_않는다():
    """'all' 은 다른 조회 화면과 같은 규약 — 범위를 안 좁힌다는 뜻이다."""
    from app.services.money_chat import office_scope

    assert office_scope("all") == ("", "")
    source = SERVICE.read_text(encoding="utf-8")
    assert 'spec.pop("office", None)' in source, "전체면 office 조건을 빼야 한다"
    assert "if not prefix:  # 전체 조회 권한으로 보는 중" in source, "카드 게이트도 통과"


def test_pymssql_이_requirements_에_있다():
    """venv 에만 깔고 requirements 에 없으면 운영 재배포에서 챗봇이 즉사한다
    (7/22 pypxlib 장애와 같은 유형)."""
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    assert "pymssql" in requirements


# ── 스트리밍·표 UX (2026-08-05) ────────────────────────────────────────────


def test_화면은_타이핑_효과를_쓰지_않는다():
    """조회 화면은 결과를 한 판으로 그린다. SSE 스트리밍·타이핑 점은 대화의
    문법이라 쓰지 않는다."""
    script = SCRIPT.read_text(encoding="utf-8")
    assert "/api/gamjun-chat/stream" not in script
    assert "getReader()" not in script
    assert "'/api/gamjun-chat/deposits'" in script, "목록은 한 번에 받아 그린다"

def test_AI_답변_라벨과_안내_문구가_없다():
    script = SCRIPT.read_text(encoding="utf-8")
    assert "AI 답변" not in script
    page = PAGE.read_text(encoding="utf-8")
    assert "자연어로 물어보세요" not in page


def test_표_정렬은_셀이_아니라_열이_정한다():
    """셀마다 재면 같은 열에서 정렬이 갈린다 — 평가액 열의 '1,000,000,000원'은
    오른쪽인데 '-'만 가운데로 튀고, '약 399조 1,939억원'·'108,638 ▇▇▇' 는
    통째로 왼쪽에 붙어 자릿수가 어긋났다 (2026-08-05 사용자 지적)."""
    script = SCRIPT.read_text(encoding="utf-8")
    assert "function columnPlan(" in script, "열 단위 판정"
    assert "function cellKind(" in script and "function renderCell(" in script
    assert "cellClass" not in script, "셀 단위 추측은 걷어내야 한다"
    # 빈 값은 표결에서 빠져야 '-' 몇 개 때문에 금액 열이 텍스트가 되지 않는다.
    assert "if(kind==='empty')return;" in script
    # 열 계획은 표에 실려 있다 (더보기는 화면에서 빠졌지만 계획 자체는 표가 진다).
    assert "data-plan=" in script



def test_정렬은_감정서_LIST_와_같다():
    """타이포·정렬을 감정서 LIST(dashboard.css:109,117,126-127)에 맞춘다
    (2026-08-06 요청: "감정서LIST랑 폰트나 정렬이 좀 다른 것 같은데 맞춰줘").

    **2026-08-05 판단을 뒤집은 것이다** — 그때는 '머리를 내용과 같은 쪽으로'
    붙였는데, 이제 두 화면을 나란히 쓰다 보니 서로 다른 게 더 눈에 띈다.
    LIST 관례는 '머릿말은 가운데, 데이터 셀만 우측 정렬'이다."""
    css = (ROOT / "desktop" / "ui" / "gamjun-chat.css").read_text(encoding="utf-8")
    # 숫자 데이터 셀 — 오른쪽 + tabular-nums (이건 그대로)
    assert "td.num,.detail-body td.num{text-align:right;font-variant-numeric:tabular-nums" in css
    # 머리 — LIST 와 같은 10px·750·자간 .025em·가운데
    assert "font-weight:750;color:#59645f;font-size:10px;letter-spacing:.025em;text-align:center" in css
    assert "thead th.num,.detail-body thead th.num{text-align:center}" in css, (
        "LIST 관례: 머릿말은 가운데")

    def rule(selector: str) -> str:
        start = css.index(selector)
        return css[css.index("{", start):css.index("}", start)]

    # 날짜 열은 정렬을 건드리지 않는다 — 폭이 같아 왼쪽으로도 자릿수가 맞는다.
    assert "text-align" not in rule(".result-body td.date"), "MOA 에 날짜 가운데 정렬 선례가 없다"
    # 빈 칸은 색만 흐리게 — 정렬을 주면 그 칸만 열에서 어긋난다.
    assert "text-align" not in rule(".result-body td.dim")

def test_숫자에_꼬리가_붙은_열은_숫자부를_맞춘다():
    """'108,638 ▇▇▇▇' 의 막대와 '약 54.8억원 (기재 72,854)' 의 주석은 길이가
    행마다 달라, 통째로 오른쪽 정렬하면 정작 금액이 어긋난다."""
    script = SCRIPT.read_text(encoding="utf-8")
    assert "function splitCell(" in script
    assert "tailCls:'bar'" in script and "tailCls:'hint'" in script
    assert "min-width:${plan.width}ch" in script, "숫자부를 같은 폭으로 맞춘다"
    css = (ROOT / "desktop" / "ui" / "gamjun-chat.css").read_text(encoding="utf-8")
    assert "td.numsplit{text-align:left" in css
    assert "td.numsplit .v{display:inline-block;text-align:right" in css


def test_집계축_열은_질문에_따라_정렬이_바뀌지_않는다():
    """group_by 에 따라 첫 열이 '2025'(연도)·'2025-07'(연월)·'경기도 화성시'로
    바뀐다. 연도는 순수 숫자라 그대로 두면 오른쪽으로 붙어, 같은 자리 같은
    역할의 열이 질문마다 다른 정렬이 된다."""
    script = SCRIPT.read_text(encoding="utf-8")
    assert "if(i===0)type='text';" in script


def test_한글_단위_금액도_정렬로_읽힌다():
    """'약 399조 1,939억원' 이 텍스트로 빠지면 금액 열이 통째로 왼쪽이 된다.
    음수(-450,000)·소요일(11.7일)·횟수(3회)·단가(5,053,000원/㎡)도 숫자다."""
    script = SCRIPT.read_text(encoding="utf-8")
    assert "조|억|천만|백만|만|천|원|건|개월|개" in script, "한글 단위"
    assert script.count("NUM_BODY_RE=/^[-+]?") == 1, "음수·양수 부호 허용"
    # 감정서번호(01-2507-6-0389)는 숫자로 잡히면 안 된다 — 식별자는 왼쪽.
    assert "식별자·범위는 텍스트로 남아야 한다" in script


def test_표_정렬_기능이_한글_단위를_환산한다():
    """머리 클릭 정렬에서 '약 399조 1,939억원' 의 숫자만 추려 붙이면 3991939 가
    되어 조 단위와 억 단위가 뒤섞인다."""
    script = SCRIPT.read_text(encoding="utf-8")
    assert "UNIT_MUL=" in script and "'조':1e12" in script
    assert "return ex?1:-1;" in script, "값 없는 행은 항상 아래로"


# ── 상세 카드 개선 (2026-08-05 2차) ────────────────────────────────────────

def test_카드_머리에_아이콘이_없다():
    script = SCRIPT.read_text(encoding="utf-8")
    assert '<span class="ico">' not in script


def test_카드_항목은_두_단으로_깔린다():
    """카드가 세로로 길어 답이 멀었다 — kv 는 2단, 표·안내는 전체 폭."""
    css = (ROOT / "desktop" / "ui" / "gamjun-chat.css").read_text(encoding="utf-8")
    assert "grid-template-columns:1fr 1fr" in css
    assert ".doc-card-body>.kv{grid-column:auto}" in css


@pytest.mark.parametrize(
    "question,expected",
    [
        ("01-2607-3-2235 요약해줘", True),
        ("01-2607-3-2235 의견 알려줘", True),
        ("01-2607-3-2235 내용 알려줘", False),
        ("01-2607-3-2235", False),
    ],
)
def test_요약_질문은_카드가_아니라_요약으로_간다(question, expected):
    """카드 스스로 '요약해줘'를 안내하는데 그 질문이 다시 카드로 돌면 막다른길이다."""
    assert gamjun_chat._doc_summary_intent(question) is expected


def test_카드에_입금_요약_한_줄이_붙는다():
    """카드만 보고 돈 이력은 또 물어야 했다 — 입금현황과 같은 숫자로 한 줄 끼운다."""
    source = SERVICE.read_text(encoding="utf-8")
    assert "doc_money_brief" in source
    money = (ROOT / "app" / "services" / "money_chat.py").read_text(encoding="utf-8")
    assert "async def doc_money_brief" in money
    assert "실패하면 조용히 생략" in money, "돈 조회 실패가 카드를 죽이면 안 된다"


def test_이름에_붙은_조사를_떼고_재시도한다():
    """'채무자가 곽한성인 건' → debtor='곽한성인'(0건)이 되는 실측 버그 보정."""
    assert gamjun_chat._strip_copula({"debtor": "곽한성인"}) == {"debtor": "곽한성"}
    assert gamjun_chat._strip_copula({"owner": "홍길동인", "region": "화성시"}) == {
        "owner": "홍길동", "region": "화성시"}
    # '인'으로 안 끝나면 재시도 없음 · 두 글자 값('법인' 오탐)도 보호
    assert gamjun_chat._strip_copula({"debtor": "곽한성"}) is None
    assert gamjun_chat._strip_copula({"client": "법인"}) is None
    source = SERVICE.read_text(encoding="utf-8")
    assert "if not rows:" in source and "_strip_copula" in source, "0건일 때만 재시도"


# ── 전문 검색창 ①② (2026-08-05) ───────────────────────────────────────────

def test_자동완성이_배선되어_있다():
    """거래처·평가사·지역·물건종별을 입력 중에 제안 — 벤더 사전 재활용 + 거래처 라이브."""
    router = (ROOT / "app" / "routers" / "gamjun_chat.py").read_text(encoding="utf-8")
    assert '"/suggest"' in router
    source = SERVICE.read_text(encoding="utf-8")
    assert "async def suggest(" in source
    assert "client_name LIKE" in source, "거래처는 라이브 접두사 조회"
    assert "prefix + \"-%\"" in source.replace("'", '"'), "거래처도 소속 범위"
    script = SCRIPT.read_text(encoding="utf-8")
    assert "suggest-box" in script and "ArrowDown" in script, "키보드 탐색"
    assert "setTimeout" in script, "디바운스"


def test_대화_흔적이_남아_있지_않다():
    """감정서 조회는 **표 조회 화면**이지 챗봇이 아니다 (2026-08-05 사용자 확정).

    말풍선·타이핑 점·'무엇이든 물어보세요' 히어로·후속 질문 칩은 결과를 기다리게
    만드는 대화의 문법이다. 조회 화면은 조건을 받고 표를 내놓는다.
    """
    script = SCRIPT.read_text(encoding="utf-8")
    page = PAGE.read_text(encoding="utf-8")
    for gone in ("addUser(", "addBot(", "followupsFor(", "attachFollowups",
                 "TYPING", "chatLog", "hideHero"):
        assert gone not in script, f"대화 잔재: {gone}"
    for gone in ("msg-user", "msg-ai", "chat-app", "chat-scroll", "hero",
                 "무엇이든 물어보세요"):
        assert gone not in page, f"대화 잔재: {gone}"
    css = (ROOT / "desktop" / "ui" / "gamjun-chat.css").read_text(encoding="utf-8")
    assert ".dots" not in css and "@keyframes blink" not in css, "타이핑 점"


# ── 완성도 보강 (2026-08-05: 보안·성능·신뢰) ───────────────────────────────


def test_파싱_전_감정서는_원장으로_대신_답한다():
    """원문 DB(전일 반영)에 없어도 원장(apw_masterex)에 있으면 기본 정보 + 사유.
    '못 찾음'으로 끝내면 사용자가 챗봇 자체를 의심한다."""
    source = SERVICE.read_text(encoding="utf-8")
    assert "_ledger_lookup_sync" in source
    assert "정리 전" in source and "접수분까지 들어와 있습니다" in source
    assert "_source_view" in source, "감정서 LIST 화면과 같은 원장 뷰"


def test_구번호_감정서도_소속이면_열린다():
    """OB1·400·200… 구번호(2007~2018 아카이브)는 접두사가 없다 — 원장 LOffice 로
    판정한다. 목록(LOffice 기준)에는 나오는데 카드는 못 여는 모순 방지."""
    source = SERVICE.read_text(encoding="utf-8")
    assert "async def _office_gate(" in source
    assert "APWORKSDW.dbo.APW_MASTEREX WHERE DocID" in source, "인덱스(ix_apw_docid) 시크"
    assert source.count("_office_gate(vendor") >= 2, "카드·요약 두 경로 모두"


def test_오피스_필터는_스냅샷으로_가속한다():
    """벤더의 MASTEREX 서브쿼리(HEAP 전량 스캔 ~0.4초)를 우리 DB 스냅샷으로 치환.
    벤더 파일은 그대로, 스냅샷이 없으면 원본 SQL 로 동작한다."""
    source = SERVICE.read_text(encoding="utf-8")
    assert "a10_office_doc" in source
    assert "_swap_office_sql" in source and "_office_snapshot_ready" in source
    assert "MERGE dbo.a10_office_doc" in source, "갱신은 MERGE (증분)"
    assert "COLLATE DATABASE_DEFAULT" in source, "크로스 DB 콜레이션 가드"
    # 벤더 원문에 남아 있는 서브쿼리 문자열과 정확히 일치해야 치환이 된다.
    vendor = VENDOR.read_text(encoding="utf-8")
    assert "SELECT axo.DocID FROM APWORKSDW.dbo.APW_MASTEREX axo" in vendor


def test_필터_추출은_캐시된다():
    """같은 날 같은 질문의 Gemini 왕복(~1초)은 한 번만. 키에 날짜가 들어가
    '이번 달'류가 자정을 넘겨 낡지 않는다."""
    source = SERVICE.read_text(encoding="utf-8")
    assert "_extract_cached" in source
    assert "dt.date.today().isoformat()" in source, "날짜가 캐시 키"
    money = (ROOT / "app" / "services" / "money_chat.py").read_text(encoding="utf-8")
    assert "_XCACHE" in money
    assert money.count("dt.date.today().isoformat()") >= 2, "돈 추출도 날짜 키"


def test_미수금_합계와_큰_건_목록은_동시에_돈다():
    money = (ROOT / "app" / "services" / "money_chat.py").read_text(encoding="utf-8")
    assert "asyncio.gather(" in money, "합계·정렬 목록 동시 실행 (체감 절반)"


def test_질문_로그를_남긴다():
    """무엇을 몇 초에 답했는지 a10_api_log 에 — 다음 개선을 데이터로 정한다."""
    source = SERVICE.read_text(encoding="utf-8")
    assert "_audit_sync" in source
    assert 'direction="chatbot"' in source
    assert "except Exception:\n        pass" in source, "로그 실패가 답변을 막으면 안 된다"


def test_표_정렬과_복사가_있다():
    script = SCRIPT.read_text(encoding="utf-8")
    assert "function sortTable(" in script and "localeCompare" in script
    assert "sort-asc" in script and "sort-desc" in script
    assert "function copyTable(" in script and "fallbackCopy" in script, "내부망 http 폴백"
    css = (ROOT / "desktop" / "ui" / "gamjun-chat.css").read_text(encoding="utf-8")
    assert "tbl-copy" in css and "sort-asc" in css



def test_조회조건에_기간과_전체조회와_키워드가_있다():
    """조회 조건: 본·지사 | 시작일 | 종료일 | 전체조회 | 키워드 검색.
    체크를 풀면 감정서번호가 안 적힌 것만(그게 일감), 키워드는 적요 부분일치다
    ('세연스틸'을 넣으면 그 기간에 적요에 세연스틸이 든 행만, 2026-08-06 확정)."""
    page = PAGE.read_text(encoding="utf-8")
    assert 'id="dateFrom" type="date"' in page and 'id="dateTo" type="date"' in page
    assert 'id="allRows" type="checkbox"' in page
    assert "전체조회" in page and "키워드 · 번호" in page, (
        "번호만 넣어도 찾을 수 있다는 것을 칸 이름이 말해야 한다")
    script = SCRIPT.read_text(encoding="utf-8")
    assert "only_blank:!$('allRows').checked" in script
    assert "keyword:$('question').value.trim()" in script, "키워드는 목록 필터로 간다"
    # 조회 버튼은 언제나 목록 조회다 — 감정서 검색으로 갈라지지 않는다
    assert "loadDeposits();" in script and "runSearch" not in script

def test_조건_없는_질문_안내가_살아_있다():
    """office 는 항상 주입되므로 조건으로 세면 '무엇을 찾을지…' 안내가 죽는다."""
    assert not gamjun_chat._has_any_filter({"office": "본사"})
    assert gamjun_chat._has_any_filter({"office": "본사", "region": "강남구"})


def test_오피스_치환은_LIKE_의미를_보존한다():
    """LIKE '%라벨%' 가 맞출 값을 실측 값 목록에서 미리 골라 IN(등호 시크)으로.
    제주지사는 구제주지사까지 포함해야 하고(옛 명칭), 값·파라미터가 안 맞으면
    원본 그대로 나가야 한다 (무해 폴백)."""
    saved = gamjun_chat._SNAPSHOT["values"]
    gamjun_chat._SNAPSHOT["values"] = ["본사", "제주지사", "구제주지사", "경북지사", "대구경북지사"]
    try:
        sql = "SELECT x FROM jun.apw_case a WHERE " + gamjun_chat._OFFICE_SUBQ + " ORDER BY 1"
        # 본사: 등호 하나로
        s, p = gamjun_chat._swap_office_sql(sql, ("%본사%",), "본사")
        assert "a10_office_doc" in s and "APW_MASTEREX" not in s
        assert p == ("본사",)
        # 제주지사: 구제주지사(옛 명칭)까지 IN 으로 — LIKE 와 같은 집합
        s, p = gamjun_chat._swap_office_sql(sql, ("%제주지사%",), "제주지사")
        assert set(p) == {"제주지사", "구제주지사"} and "IN (%s, %s)" in s
        # 다른 파라미터(지역 등)는 자리 그대로
        s, p = gamjun_chat._swap_office_sql(
            "SELECT x WHERE a.region LIKE %s AND " + gamjun_chat._OFFICE_SUBQ,
            ("%강남구%", "%본사%"), "본사")
        assert p == ("%강남구%", "본사")
        # 값 목록에 없는 라벨 → 원본 그대로
        s, p = gamjun_chat._swap_office_sql(sql, ("%없는지사%",), "없는지사")
        assert "APW_MASTEREX" in s and p == ("%없는지사%",)
        # 서브쿼리가 없는 SQL → 그대로
        s, p = gamjun_chat._swap_office_sql("SELECT 1", ("%본사%",), "본사")
        assert s == "SELECT 1"
    finally:
        gamjun_chat._SNAPSHOT["values"] = saved


# ── 이름 검색 복원·오타 보정 (2026-08-05 사용자 신고) ──────────────────────

def test_축을_안_밝힌_이름도_찾는다():
    """'신한은행' 한 단어는 Gemini 가 본문 키워드로 넣는데, 본문 검색을 막아 놔서
    조건이 통째로 사라져 '못 알아들었습니다'가 나왔다. 이름을 축으로 되살린다."""
    source = SERVICE.read_text(encoding="utf-8")
    assert "async def _resolve_names(" in source
    assert "_NAME_AXES" in source and '"client_name"' in source
    # 어느 축인지는 추측이 아니라 건수로 정한다 (실측: 신한은행 = 의뢰인 17,863 · 채무자 2).
    assert "async def _axis_hits(" in source and "hits.sort(key=lambda x: -x[1])" in source


def test_이름_오타를_자모로_잡는다():
    """'신한안행'→'신한은행'. 음절로 재면 0.75 라 '김철수→김수영'(0.67)과 안 갈린다.
    자모로 재야 0.92 대 0.62 로 갈린다."""
    from app.services.gamjun_chat import _closest, _jamo

    assert _jamo("신한은행") == "ㅅㅣㄴㅎㅏㄴㅇㅡㄴㅎㅐㅇ"
    names = ["신한은행 미금동지점장", "국민은행 강남지점", "김수영", "우리은행"]
    hit = _closest("신한안행", names, 0.85)
    assert hit and hit[0].startswith("신한은행"), hit
    # 사람 이름은 문턱을 높여 남의 자료가 새지 않게 한다
    assert _closest("김철수", names, 0.94) is None


def test_축_이름_자체는_조건이_되지_않는다():
    """'채무자 조회'의 '채무자'를 거래처명으로 착각해 엉뚱한 2건이 나갔다."""
    from app.services.gamjun_chat import _STOP_TERMS, _leftover_terms

    for word in ("채무자", "의뢰인", "소유자", "평가사", "감정서"):
        assert word in _STOP_TERMS, word
    assert _leftover_terms("채무자 조회", {}) == []
    assert _leftover_terms("신한은행 담보 감정서", {"purpose": "담보"}) == ["신한은행"]


def test_더보기가_채무자_조건을_잃지_않는다():
    """벤더 _PAGE_STR_FIELDS 에 owner·debtor 가 없어, 채무자로 찾은 목록의 2페이지가
    조건을 잃고 전체 목록을 붙였다 (실측: {'debtor':'곽한성'} → {} 로 위생됨).
    그래서 페이징을 벤더에 맡기지 않고 직접 만든다."""
    vendor_src = VENDOR.read_text(encoding="utf-8")
    fields = vendor_src[vendor_src.index("_PAGE_STR_FIELDS = ("):][:220]
    assert '"debtor"' not in fields and '"owner"' not in fields, "벤더가 고쳤으면 이 우회를 걷어내라"
    source = SERVICE.read_text(encoding="utf-8")
    assert "vendor.fetch_search_page(" not in source, "벤더 페이징을 쓰면 조건이 사라진다"
    assert "vendor.build_search_sql(clean, offset=" in source
    assert "k in SUPPORTED_FILTERS" in source, "클라이언트발 spec 은 우리가 위생"


def test_적재_지연을_답변이_밝힌다():
    """원문 DB 적재가 7/21 이후 멈춰 최근 3주가 통째로 빠졌다. 안 밝히면
    사용자가 '최근 건이 왜 없지?' 하고 챗봇을 못 믿는다."""
    source = SERVICE.read_text(encoding="utf-8")
    assert "async def _jun_coverage(" in source and "async def _coverage_note(" in source
    assert "receipt_date <= GETDATE()" in source, "미래 오류값(2070년)을 최신으로 잡으면 안 된다"
    assert "if behind < 3:" in source, "하루치 지연까지 떠들지 않는다"


def test_원문이_없어도_원장으로_답한다():
    """벤더는 못 찾아도 {'master': None, ...} 를 돌려준다 — truthy 라 폴백이 죽어
    '찾지 못했어요'로 끝났다 (2026-08-05 실측)."""
    from app.services.gamjun_chat import _has_doc

    assert _has_doc({"master": {"DocID": "x"}}) is True
    assert _has_doc({"master": None, "tables": [], "opinions": []}) is False
    assert _has_doc({}) is False and _has_doc(None) is False
    source = SERVICE.read_text(encoding="utf-8")
    assert source.count("_has_doc(data)") >= 2, "카드·요약 두 경로 모두"


# ── 입금 적요 → 감정서 후보 (2026-08-05 재무팀 업무 자동화) ────────────────

def test_적요를_붙여넣으면_감정서_후보를_찾는다():
    """재무팀이 통장 적요의 낱말을 하나씩 원장에서 찾아 감정서번호를 고르던 일을
    챗봇이 대신한다. 표본 200건 실측: 1순위 정답 62%, 후보 안 포함까지 72%."""
    from app.services.gamjun_chat import _deposit_intent

    assert _deposit_intent("적요: 이혜일/타행MB/(하나)/ 입금액 2,247,300")[:2] == (
        "이혜일/타행MB/(하나)/", 2247300)
    # 라벨이 없어도 슬래시 2개면 적요로 본다
    assert _deposit_intent("260732241/타행환/")[:2] == ("260732241/타행환/", 0)
    # 보통 질문을 적요로 오인하면 안 된다
    assert _deposit_intent("강남구 아파트 감정서 보여줘") is None
    assert _deposit_intent("미수금 얼마야?") is None


def test_적요_판정이_돈_질문보다_먼저다():
    """'입금액 6,586,800' 의 '입금' 때문에 회계 경로로 새면 적요 조회가 안 된다."""
    source = SERVICE.read_text(encoding="utf-8")
    assert source.index("_deposit_intent(question)") < source.index(
        "money_chat.is_money_question")


def test_적요_숫자에서_감정서번호만_골라낸다():
    """여신(4005…)·가상계좌(3021…)·카드(7458…) 번호를 감정서번호로 읽으면 안 된다.
    연월·구분 관문 하나로 실측 노이즈 2,700여 건이 전부 걸러졌다."""
    from app.services.deposit_match import _compacts

    assert _compacts("260732241/타행환/") == ["260732241"]
    assert _compacts("2603A0039/타행이체/SC은행/") == ["2603A0039"]
    assert _compacts("400578562/대체입금/") == [], "여신 가상계좌"
    assert _compacts("302186812/대체입금/") == [], "은행 내부번호"
    assert _compacts("BC-745827823//WON뱅킹사") == [], "카드 정산"


def test_적요에서_이름만_추린다():
    from app.services.deposit_match import _names

    assert "이혜일" in _names("이혜일/타행MB/(하나)/")
    assert "상주시산림조합" in _names("상주시산림조합/타행환/(산림)/")
    # 거래유형·전산어는 이름이 아니다
    for noise in ("타행환", "대체입금", "인터넷입금이체", "전자금융"):
        assert noise not in _names(f"홍길동/{noise}/")


def test_통장에는_절대_쓰지_않는다():
    """CB2_ACCT_HIS.Memo 는 자유 메모가 아니라 남의 시스템 입력이다 —
    SP_IW_I_MAECULDOCID 가 `memo like '01%'` 로 읽어 매출배분(Apw_Mae_GaPrice)에
    직접 쓴다. 그 잡은 꺼져 있을 뿐 지워지지 않았고 되돌릴 이력 컬럼도 없다.
    게다가 우리는 그 DB 에 sa 로 붙어 있다."""
    source = (ROOT / "app" / "services" / "deposit_match.py").read_text(encoding="utf-8")
    # 주석·독스트링을 걷어내고 실제 코드만 본다
    plain = [l for l in source.splitlines() if not l.lstrip().startswith("#")]
    body = "".join(chr(10).join(plain).split(chr(34) * 3)[::2])
    for forbidden in ("UPDATE", "INSERT", "DELETE", "MERGE"):
        assert forbidden not in body.upper(), f"쓰기 구문이 있다: {forbidden}"
    # 통장 DB 에도 접속하지만 **읽기만** 한다 (CyberToDocid 매핑표 SELECT).
    # CB2_ACCT_HIS 는 아예 건드리지 않는다 — 거기 쓰면 매출이 계상된다.
    # 통장 거래내역은 **읽기만** 한다 (적요로 금액·거래일을 찾아 채운다).
    for statement in ("UPDATE dbo.CB2_ACCT_HIS", "INSERT INTO dbo.CB2_ACCT_HIS",
                      "DELETE FROM dbo.CB2_ACCT_HIS"):
        assert statement not in body, statement
    assert "SELECT TOP 1 TX_AMT, ACCT_TXDAY" in body, "통장은 SELECT 만"
    assert "SELECT TOP 1 Docid FROM CyberToDocid" in body, "매핑표도 SELECT 만"
    assert "apw_masterex" in body
    assert "읽기 전용" in source, "왜 안 쓰는지 파일에 남겨 둔다"


def test_사람_이름은_채무자에서도_찾는다():
    """개인 입금자는 대개 의뢰인이 아니라 채무자다 — 의뢰인은 '한국주택금융공사
    사장' 같은 기관이고 돈을 부친 사람은 채무자 칸에 있다.
    실측(정답지 250건): 이름이 발견된 칸은 의뢰인 88 · 채무자 7 · 소유자 0 · 유치자 0.
    유치자(Manager)는 우리 직원이라 입금자와 무관해 뺐다."""
    source = (ROOT / "app" / "services" / "deposit_match.py").read_text(encoding="utf-8")
    assert '("CustName", "의뢰인"), ("Debtor", "채무자")' in source
    assert "a.Manager LIKE" not in source, "유치자 검색은 오탐만 는다"
    # 후보 표는 입금현황과 같은 회계 열로 보여준다 (2026-08-05 요청)
    assert "| 감정서번호 | 거래처명 | 접수일 | 매출총액 | 입금액 | 미수금 | 근거 |" in source


def test_후보를_고른_이유를_답변에_밝힌다():
    """재무팀이 손으로 하던 판단을 대신하는 것이라 결과만 던지면 믿고 쓸 수 없다.
    적요를 어떻게 읽었는지·무엇으로 찾았는지·각 후보가 왜 뽑혔는지를 밝힌다."""
    source = (ROOT / "app" / "services" / "deposit_match.py").read_text(encoding="utf-8")
    assert "적요를 이렇게 읽었습니다" in source
    assert "이렇게 찾았습니다" in source and '"steps"' in source
    assert "def _reason(" in source
    # 이유는 짧은 꼬리표로 — 문장으로 쓰면 표가 좌우로 늘어난다 (2026-08-05)
    assert 'return " + ".join(tags)' in source
    assert "money_ok = bool(amount)" in source, "금액 일치는 라벨이 아니라 실제 값으로"


def test_괄호_안_은행약칭은_약한_근거로만_쓴다():
    """'(하나)' 를 이름으로 잡으면 'KEB하나은행' 이 진짜 이름을 제친다.
    아주 버리면 의뢰인이 실제로 그 은행인 건을 놓친다(실측 -2%p). 그래서 뒤로 민다."""
    from app.services.deposit_match import _read

    names, dropped = _read("이혜일/타행MB/(하나)/")
    assert names[0] == "이혜일", "진짜 이름이 먼저"
    assert "하나" in names and names.index("하나") > 0, "은행 약칭은 뒤"
    assert "타행MB" in dropped
    # 번호로 쓴 숫자를 '뺀 말' 에도 적으면 모순으로 읽힌다
    names, dropped = _read("260732241/타행환/")
    assert not any("260732241" in d for d in dropped)


def test_적요_자동인식이_체크박스를_대신한다():
    """모드 선택 칸을 따로 두지 않는다. 실측(2026년 입금 6,640건): 적요는 100%가
    슬래시 2~3개라 그 하나로 전부 잡히고, 못 알아본 건 0건이다.
    다만 슬래시를 나열 기호로 쓴 질문('담보/일반거래/경매 비교해줘')은 걸러야 한다."""
    from app.services.gamjun_chat import _deposit_intent

    assert _deposit_intent("이혜일/타행MB/(하나)/") is not None
    assert _deposit_intent("여비교통비수수료_성지은/대체/서울숲/") is not None
    # 묻는 말투가 섞이면 적요가 아니다
    assert _deposit_intent("담보/일반거래/경매 비교해줘") is None
    assert _deposit_intent("서울/경기/인천 감정서 몇 건이야?") is None
    # '적요:' 를 붙이면 무조건 적요로 — 자동 판정이 틀렸을 때의 탈출구
    assert _deposit_intent("적요: 담보/일반거래/경매")[:2] == ("담보/일반거래/경매", 0)


def test_슬래시_없이_조각만_넣어도_찾는다():
    """재무팀은 적요를 통째로 붙여넣기도 하고, 앞 조각만 떼어 물어보기도 한다.
    금액을 함께 줬거나 감정서번호로 보이는 숫자가 있으면 입금 조회로 본다."""
    from app.services.gamjun_chat import _deposit_intent

    assert _deposit_intent("260732241")[:2] == ("260732241", 0), "번호 조각만"
    assert _deposit_intent("이혜일 2,247,300원")[:2] == ("이혜일", 2247300)
    assert _deposit_intent("상주시산림조합 2576200")[:2] == ("상주시산림조합", 2576200), "라벨 없는 금액"
    # 이름만 덜렁 넣은 건 평소 감정서 검색이 낫다
    assert _deposit_intent("신한은행") is None
    assert _deposit_intent("이혜일") is None
    # 완전한 감정서번호는 카드로 가야 한다
    assert _deposit_intent("01-2607-3-2237") is None
    # 여신 가상계좌 번호는 감정서번호가 아니다
    assert _deposit_intent("400578562") is None


def test_이름_표기_차이를_흡수한다():
    """통장은 '상주시산림조합', 원장은 '상주산림조합장' — 행정구역 한 글자가 다르다."""
    source = (ROOT / "app" / "services" / "deposit_match.py").read_text(encoding="utf-8")
    assert 'trimmed = re.sub(r"(?<=.)[시군구도](?=.)", "", name)' in source
    assert "base -= 8" in source, "줄여 맞춘 건 원본 일치보다 약한 근거"


def test_감정서가_없는_입금은_그렇다고_말한다():
    """'400578562/대체입금/' 나 '하나카드기업/하나카드/서초/' 는 아무리 뒤져도 감정서가
    안 나온다 — 애초에 없기 때문이다. 실측: 2026년 400xxxxxx 입금 2,111건 중
    감정서번호가 적힌 건 0건. 헛수고시키지 않고 무엇인지 알려준다."""
    from app.services.deposit_match import _classify

    kind = _classify("400578562/대체입금/")
    assert kind and kind[0] == "약식평가"
    assert _classify("하나카드기업/하나카드/서초/")[0] == "카드"
    assert _classify("(주)대화감정평가법인/대체/")[0] == "자사이체"
    # 진짜 감정서 입금은 건드리지 않는다
    assert _classify("이혜일/타행MB/(하나)/") is None
    assert _classify("260732241/타행환/") is None


def test_약식평가는_전표로_무엇인지_알려준다():
    """감정서번호는 없어도 전표에는 '약식평가수수료 400578052 / 국민은행 상무지점' 으로
    잡힌다. 실측: 7월 이후 433건 중 94%가 전표를 갖고 있고 대부분 당일이다."""
    source = (ROOT / "app" / "services" / "deposit_match.py").read_text(encoding="utf-8")
    assert "_va_voucher_sync" in source
    assert "management_no = :va" in source, "가상계좌 번호가 곧 전표 관리번호다"
    assert "회계 전표에는 이렇게 잡혀 있습니다" in source


def test_회계_전표를_경유해_찾는다():
    """적요의 이름이 원장과 아예 다른 경우(입금자와 의뢰인이 다른 기관)가 실패의
    67%였다. 같은 날 같은 금액으로 보통예금에 꽂힌 전표의 관리번호가 그걸 잇는
    유일한 끈이다. 표본 200건: 1순위 65% → 82%, 도달 74% → 94%."""
    source = (ROOT / "app" / "services" / "deposit_match.py").read_text(encoding="utf-8")
    assert "_voucher_docs_sync" in source
    assert "account_code = '1030000'" in source, "보통예금 라인 금액으로 전표를 찾는다"
    assert "management_no LIKE '__-____-_-____'" in source, "감정서 형식 관리번호만"
    assert "당일 입금에는 침묵한다" in source, "전표는 입금 뒤에 생긴다 — 한계를 남긴다"
    assert 'tags.append("전표")' in source


def test_표의_한_행을_통째로_붙여넣어도_읽는다():
    """재무팀은 CB2_ACCT_HIS 를 보면서 행을 통째로 복사해 넣는다.
    적요 칸은 슬래시가 있는 조각이고, 금액은 나머지 숫자 칸 중 가장 작은 값이다
    — 잔액(574,539,214)과 계좌번호가 훨씬 크므로 그걸 금액으로 읽으면 안 된다."""
    from app.services.gamjun_chat import _deposit_intent

    row = ("400578562/대체입금/\t2\t55000.00\t574539214.00\tY\t대출실"
           "\t0448420101128982202608050")
    # 거래일은 UNIQUE_FIELD 안에 박혀 있다 — 그것까지 읽어야 전표를 찾는다
    assert _deposit_intent(row) == ("400578562/대체입금/", 55000, "2026-08-05")


def test_적요_안의_숫자를_금액으로_읽지_않는다():
    """'400563506/대체입금/' 의 가상계좌 번호를 4억으로 읽어, 있지도 않은 금액으로
    검색하다 '찾지 못했습니다' 를 뱉던 사고 (2026-08-05)."""
    from app.services.gamjun_chat import _deposit_intent

    assert _deposit_intent("400563506/대체입금/")[:2] == ("400563506/대체입금/", 0)
    assert _deposit_intent("260732241/타행환/")[:2] == ("260732241/타행환/", 0)
    # 슬래시가 없으면(=적요를 붙여넣은 게 아니면) 라벨 없는 금액을 읽어도 된다
    assert _deposit_intent("상주시산림조합 2576200")[:2] == ("상주시산림조합", 2576200)


def test_거래일을_입력에서_읽는다():
    """거래일이 없으면 오늘로 보는데, 지난 입금을 조회하면 ±3일 전표 창을 벗어나
    적중률이 82%에서 47%로 떨어진다 (실측). 표를 붙여넣으면 UNIQUE_FIELD 안에
    거래일이 박혀 있으니 그것까지 읽는다."""
    from app.services.gamjun_chat import _deposit_day

    assert _deposit_day("0448420101128982202608050") == "2026-08-05", "UNIQUE_FIELD 안"
    assert _deposit_day("2026-08-05") == "2026-08-05"
    assert _deposit_day("20260805") == "2026-08-05"
    assert _deposit_day("날짜없음/대체/") == ""
    # 미래 날짜·너무 먼 과거는 버린다
    assert _deposit_day("2099-01-01") == ""


def test_사이버브랜치_매핑표를_최우선으로_본다():
    """Branch DB 의 CyberToDocid 는 통장 행(UNIQUE_FIELD) ↔ 감정서번호 매핑표다.
    2023-02~2024-06 까지만 쌓였지만(9,046행), Memo 가 빈 채로 번호가 남아 있는 행이
    2,146건이라 그 시기 건은 바로 정답이 나온다."""
    source = (ROOT / "app" / "services" / "deposit_match.py").read_text(encoding="utf-8")
    assert "_cyber_docid_sync" in source
    assert 'keep(row, "사이버브랜치 매핑", 120)' in source, "다른 근거보다 높은 점수"
    # 표를 붙여넣으면 UNIQUE_FIELD 가 들어 있으니 그걸 열쇠로 넘긴다
    chat = SERVICE.read_text(encoding="utf-8")
    assert "deposit_match._UNIQUE_RE.search(question" in chat


def test_약식평가는_어디에도_감정서번호가_없다():
    """세 군데를 다 뒤진 결론이다 (2026-08-05 실측).
    apw_masterex · 사이버브랜치 매핑표 · 회계 전표 — 400xxxxxx 입금에 감정서번호가
    붙은 사례는 전체 34,711건 중 0건이다. 전표의 관리번호는 가상계좌 번호 자체다."""
    source = (ROOT / "app" / "services" / "deposit_match.py").read_text(encoding="utf-8")
    assert "약식평가에는 감정서번호가 없습니다" in source
    assert "_va_voucher_sync" in source, "대신 어느 은행·지점 건인지는 전표로 알려준다"


def test_지사_실적회비도_감정서가_없다():
    """'대화충남 업무실적비', '호남 업무실적회비' 는 지사 단위 정산이라 감정서번호가
    없다. 이걸 안 거르면 '못 찾음' 으로 쌓여 재무팀이 헛되이 뒤진다."""
    from app.services.deposit_match import _classify

    for jeokyo in ("대화충남 업무실적비/인터넷입금이체/", "호남 업무실적회비/인터넷입금이체/",
                   "충청실적비/인터넷입금이체/", "울산1분기실적회비/전자금융/"):
        kind = _classify(jeokyo)
        assert kind and kind[0] == "지사 실적회비", jeokyo


def test_미수_잔액으로도_찾는다():
    """전표가 아직 없는 당일 입금에도 쓸 수 있는 축이다. 청구금액과는 안 맞지만
    미수 잔액과는 딱 맞는 분납·부분입금을 여기서 줍는다."""
    source = (ROOT / "app" / "services" / "deposit_match.py").read_text(encoding="utf-8")
    assert "a10_receivable_summary" in source
    assert "s.outstanding_amount = :amt" in source
    assert 'tags.append("미수 잔액")' in source


def test_안내_문구를_붙이지_않는다():
    """'통장 Memo 는 자동으로 바뀌지 않습니다' 같은 상시 문구는 뺐다 (2026-08-05 요청)."""
    source = (ROOT / "app" / "services" / "deposit_match.py").read_text(encoding="utf-8")
    assert "자동으로 바뀌지 않습니다" not in source
    assert "귀속 표시를 적는 자리" not in source


def test_상세는_회계_행으로_채운다():
    """제목·목적만 보여주면 돈을 다시 물어야 한다. 입금현황과 같은 항목을
    표로 편다 (2026-08-05 요청)."""
    money = (ROOT / "app" / "services" / "money_chat.py").read_text(encoding="utf-8")
    assert "**회계 (입금현황과 같은 기준)**" in money
    for label in ("순수수료", "여비·기타실비", "매출액", "부가세", "**매출총액**",
                  "선수금 받은 금액", "입금액", "선수금 잔액", "**미수금**"):
        assert label in money, label


def test_읽을_수_없는_표는_뺀다():
    """원문 파싱이 어긋난 물건내역 표가 '| - | - | - |' 만 늘어놓아 카드를 덮었다.
    머리행에 이름이 하나도 없으면 열이 무엇인지 알 수 없는 표다."""
    from app.services.gamjun_chat import _drop_broken_tables

    broken = "## 제목\n\n### 물건 내역\n\n| - | - |\n|---|---|\n| - | - |\n\n### 문서 구성\n- 명세표"
    out = _drop_broken_tables(broken)
    assert "| - | - |" not in out
    assert "### 물건 내역" not in out, "표를 버렸으면 빈 제목도 지운다"
    assert "### 문서 구성" in out and "명세표" in out, "멀쩡한 내용은 남긴다"
    # 이름이 있는 표는 그대로 둔다
    good = "| 구분 | 금액 |\n|---|---|\n| 매출총액 | 100원 |"
    assert _drop_broken_tables(good) == good


def test_의뢰문서번호로_찾는다():
    """은행이 자기 관리번호를 적요에 적어 보낸다 — '2026200027/수수료/증평/' 의
    2026200027 이 원장 CustDocID 와 통째로 같다. 청구금액이 안 맞아도 정확히 찾는다
    (실측: 홍천 11-2604-3-0332, 증평 04-2607-3-0327). 원장 CustDocID 채움율 79%."""
    source = (ROOT / "app" / "services" / "deposit_match.py").read_text(encoding="utf-8")
    assert "LTRIM(RTRIM(a.CustDocID)) = :r" in source
    assert 'keep(row, "의뢰문서번호 일치", 110)' in source, "적요 파싱 다음으로 강한 근거"
    assert 'tags.append("의뢰문서번호")' in source


def test_법인_표기는_이름에서_뺀다():
    """'주식회사 지엔스인터내' 의 '주식회사' 를 이름으로 잡으면 온 세상 법인이
    후보로 딸려 온다. 앞에 붙든 뒤에 붙든 잘라낸다."""
    from app.services.deposit_match import _read

    assert _read("주식회사 지엔스인터내")[0] == ["지엔스인터내"]
    assert _read("(주)하우징프로젝트")[0] == ["하우징프로젝트"]
    assert _read("정우에이치앤디주식회사")[0] == ["정우에이치앤디"]
    assert _read("재단법인 경희대학교총동문장학회")[0] == ["경희대학교총동문장학회"]


def test_상세에서_안내_문구를_뺀다():
    """'물건 내역 표는 원문이 정리된 감정서에서 보여드려요', '문서 구성',
    '요약해줘 라고 물어봐 주세요' — 회계를 보러 온 사람에게는 군더더기다
    (2026-08-05 요청)."""
    from app.services.gamjun_chat import _trim_card

    raw = ("## 감정서 상세: 01-2607-A-0104\n\n- **의뢰인**: 최유미\n\n"
           "> 상세에 물건 내역 표는 원문이 정리된 감정서에서 보여드려요 — 이 건은 아직 정리 전\n\n"
           "### 문서 구성\n- 등기사항 (p.7)\n- 명세표 (p.1)\n\n"
           "> 감정평가 의견 내용이 궁금하시면 **\"01-2607-A-0104 요약해줘\"** 라고 물어봐 주세요.\n")
    out = _trim_card(raw)
    assert "물건 내역 표는 원문이 정리된" not in out
    assert "문서 구성" not in out and "등기사항" not in out
    assert "요약해줘" not in out
    assert "최유미" in out, "본문은 남긴다"



def test_표_골격도_감정서_LIST_와_같다():
    """셀 여백·경계선·호버색까지 LIST 와 같은 값을 쓴다. sticky 머리를 쓰려면
    border-collapse 는 separate 여야 한다(collapse 면 경계선이 스크롤에 남는다)."""
    css = (ROOT / "desktop" / "ui" / "gamjun-chat.css").read_text(encoding="utf-8")
    assert "border-collapse:separate;border-spacing:0" in css
    assert "padding:12px 10px" in css, "LIST 와 같은 셀 여백"
    assert "padding:11px 10px" in css, "LIST 와 같은 머리 여백"
    assert "rgba(229,242,248,.55)" in css, "LIST 와 같은 호버색"
    # 열 계획(숫자/날짜 판정)은 그대로 — 표 안의 값 정렬을 정하는 축이다
    script = SCRIPT.read_text(encoding="utf-8")
    assert "const cls=(p.type==='num'&&!p.split)?' class=\"num\"'" in script

def test_적요만_넣어도_금액을_통장에서_채운다():
    """금액이 있고 없고가 정확도를 가른다 (실측: 1순위 82% vs 43%).
    사용자가 '302210489/대체입금/' 처럼 적요만 붙여넣어도 우리가 통장에서
    그 입금 행을 찾아 금액·거래일을 채운다 — 표 전체를 복사할 필요가 없다."""
    source = (ROOT / "app" / "services" / "deposit_match.py").read_text(encoding="utf-8")
    assert "_lookup_deposit_sync" in source
    assert "WHERE INOUT_GUBUN = '2' AND JEOKYO = ?" in source
    assert "(통장에서 찾아 채움)" in source, "찾아 채웠다는 사실을 답에 밝힌다"


def test_목록_답변에도_회계_열을_붙인다():
    """감정서 정보만 있는 벤더 표에 매출총액·미수금을 덧댄다 (2026-08-05 요청).
    숫자는 입금현황이 쓰는 요약이라 화면과 갈리지 않는다."""
    source = SERVICE.read_text(encoding="utf-8")
    assert "async def _add_money_columns(" in source
    assert '" 매출총액 | 미수금 |"' in source
    assert "await _add_money_columns(vendor.render_search_results" in source


def test_적재_지연_안내를_붙이지_않는다():
    """매 답변에 붙이던 '원문 DB는 2026-07-15 접수분까지…' 안내는 뺐다.
    번호로 물으면 원장 폴백이 그 자리에서 말해 준다 (2026-08-05 요청)."""
    source = SERVICE.read_text(encoding="utf-8")
    assert 'result["note"] = (result.get("note") + " " if result.get("note")' not in source


def test_집계_답변에_회계_합계를_붙인다():
    """건수·평가액만 말하면 회계 쪽 사람에겐 반쪽이다 (2026-08-05 요청).
    같은 조건의 감정서를 모아 입금현황 요약에서 합친다."""
    source = SERVICE.read_text(encoding="utf-8")
    assert "async def _money_summary(" in source
    assert 'answer + await _money_summary(vendor, spec)' in source
    # 벤더는 목록용이라 TOP 50 으로 자른다 — 안 풀면 '50건만 더한 값'이 전체인 척 나간다
    assert 'sql = re.sub(r"^SELECT TOP ' + chr(92) + 'd+ "' in source
    # 조건이 너무 넓으면 반쪽 합계를 보여주느니 생략한다
    assert "회계 합계는 생략했습니다" in source
    # 실패를 조용히 삼키면 버그를 못 본다 (실제로 NameError 가 여기 숨어 있었다)
    assert '[gamjun-chat] 회계 합계 실패' in source


def test_상세에서_원문_발췌_절을_뺀다():
    """'### 물건 내역 (원문 p.1)', '### 금액 산출 (원문 p.21)' 같은 절은 파싱 표가
    '-' 투성이라 읽기 어렵고, 회계를 보러 온 사람에겐 방해다 (2026-08-05 요청)."""
    from app.services.gamjun_chat import _trim_card

    raw = "\n".join([
        "## 감정서 상세", "", "- **의뢰인**: 최유미", "",
        "### 금액 산출 (원문 p.21)", "", "| a | b |", "|---|---|", "| 301/ 1-1 | 560,000,000 |", "",
        "### 물건 내역 (원문 p.5)", "", "| c | d |", "|---|---|", "| x | y |", "",
        "**회계 (입금현황과 같은 기준)**", "", "| 구분 | 금액 |", "|---|---|", "| 미수금 | 0원 |",
    ])
    out = _trim_card(raw)
    assert "금액 산출" not in out and "560,000,000" not in out
    assert "물건 내역" not in out
    assert "최유미" in out and "회계 (입금현황과 같은 기준)" in out, "본문·회계는 남긴다"


# ── 기간 입금 목록 (2026-08-05 개편: 표 조회 화면) ─────────────────────────


def test_기간은_통장_거래일_기준으로_자른다():
    """조회 조건의 시작일·종료일은 CB2_ACCT_HIS.ACCT_TXDAY 기준이다.
    출금은 아예 뺀다(감정서 수수료가 아니다 — 2026-08-06 지시). 키워드는
    적요 LIKE 로 좁히되 와일드카드를 이스케이프한다."""
    from app.services import deposit_list

    source = (ROOT / "app" / "services" / "deposit_list.py").read_text(encoding="utf-8")
    assert "ACCT_TXDAY BETWEEN ? AND ?" in source
    assert "INOUT_GUBUN = '2'" in source, "출금은 조회에서 제외"
    assert "AND JEOKYO LIKE ?" in source, "키워드는 적요 부분일치"
    assert '"[[]"' in source.replace("'", '"'), "LIKE 와일드카드 이스케이프"
    assert 'date_from.replace("-", "")' in source
    assert deposit_list._bank("10000088") == "신한"

def test_Memo_빈_것만_거를_수_있다():
    """재무팀이 실제로 쓰는 화면은 '아직 안 채운 것'이다 — 공백·NULL 둘 다 뺀다."""
    source = (ROOT / "app" / "services" / "deposit_list.py").read_text(encoding="utf-8")
    assert "Memo IS NULL OR LTRIM(RTRIM(Memo)) = ''" in source
    assert "if only_blank:" in source, "체크했을 때만 거른다"
    router = (ROOT / "app" / "routers" / "gamjun_chat.py").read_text(encoding="utf-8")
    assert '"/deposits"' in router and "only_blank" in router


def test_목록_칸은_사이버브랜치_화면을_따른다():
    """재무팀이 보던 '거래내역조회'와 같은 칸에, 손으로 채우던 감정서번호를
    덧붙인다 — 눈이 이미 아는 자리라야 옮겨 적을 수 있다."""
    script = SCRIPT.read_text(encoding="utf-8")
    for column in ("거래일자", "시간", "금융기관", "취급점", "적요"):
        assert column in script, column
    # 통장이 가진 값만 남긴다 — 우리가 찾아낸 것은 아래 표로 뺐다 (2026-08-05).
    for column in ("입출금여부", "거래금액", "감정서번호"):
        assert column in script, column
    head = script[script.index("const DEPOSIT_HEAD="):script.index("const MEMO_DOC=")]
    for gone in ("찾은 감정서번호", "거래처명", "미수금", "근거", "현재 Memo"):
        assert gone not in head, f"목록에서 뺀 칸: {gone}"


def test_감정서가_없는_유형은_뒤지지_않는다():
    """약식평가 가상계좌·카드 정산·자사이체·실적회비는 감정서번호가 아예 없다.
    34,711건 중 0건. 그걸 매번 세 DB 뒤지는 건 시간만 버리고, 화면에도
    '못 찾음'으로 남아 진짜 미결을 가린다."""
    source = (ROOT / "app" / "services" / "deposit_search.py").read_text(encoding="utf-8")
    block = source[source.index("def _search_sync("):]
    assert "deposit_match._classify(jeokyo, amount)" in block
    assert "if kind:" in block, "감정서번호가 없는 유형은 그 자리에서 돌려보낸다"
    # 그 판정이 세 DB 를 뒤지기 **전에** 와야 의미가 있다
    assert block.index("if kind:") < block.index("_number_sync("), "뒤지기 전에 가른다"


def test_첫_조회는_통장_값만_그린다():
    """감정서 찾기는 한 건마다 세 DB 를 두드려 1초쯤 걸린다. 하루치 23건이면
    5초를 기다리는데 실제로 손대는 건 몇 줄뿐이다 — 목록은 바로 띄우고,
    찾기는 누른 줄에만 건다 (2026-08-05 사용자 요청)."""
    source = (ROOT / "app" / "services" / "deposit_list.py").read_text(encoding="utf-8")
    listing = source[source.index("async def list_deposits("):source.index("async def match_one(")]
    assert "deposit_match.find" not in listing, "목록 조회는 감정서를 찾지 않는다"
    assert "_classify" not in listing
    router = (ROOT / "app" / "routers" / "gamjun_chat.py").read_text(encoding="utf-8")
    assert '"/deposit-match"' in router, "줄 하나를 찾는 엔드포인트"
    script = SCRIPT.read_text(encoding="utf-8")
    assert "async function matchRow(" in script
    assert "tbody tr[data-row]" in script, "줄을 누르면 그 줄만 찾는다"


def test_한_줄_찾기도_권한을_본다():
    """목록과 같은 문지기 — 통장은 지사로 나눌 수 없으니 전체조회 권한자만."""
    router = (ROOT / "app" / "routers" / "gamjun_chat.py").read_text(encoding="utf-8")
    block = router[router.index('@router.post("/deposit-match"'):]
    assert "_office_of(body.usr_seq, body.office_code)" in block
    assert "can_view_all(body.usr_seq)" in block


def test_목록도_통장에_쓰지_않는다():
    """deposit_match 와 같은 이유다 — CB2_ACCT_HIS.Memo 는 남의 시스템 입력이고
    우리는 그 DB 에 sa 로 붙어 있다."""
    source = (ROOT / "app" / "services" / "deposit_list.py").read_text(encoding="utf-8")
    plain = [l for l in source.splitlines() if not l.lstrip().startswith("#")]
    body = "".join(chr(10).join(plain).split(chr(34) * 3)[::2])
    for forbidden in ("UPDATE", "INSERT", "DELETE", "MERGE"):
        assert forbidden not in body.upper(), f"쓰기 구문이 있다: {forbidden}"
    assert "읽기 전용" in source, "왜 안 쓰는지 파일에 남겨 둔다"


def test_목록_조회도_소속을_따른다():
    """다른 조회와 같은 규칙 — usr_seq 로 소속을 풀고, 화면이 고른 지사는
    전체조회 권한이 있을 때만 받는다."""
    router = (ROOT / "app" / "routers" / "gamjun_chat.py").read_text(encoding="utf-8")
    block = router[router.index('@router.post("/deposits"'):]
    assert "_office_of(body.usr_seq, body.office_code)" in block
    assert "if office is None:" in block and "GAMJUN_AUTH" in block



def test_감정서번호_클릭은_클립보드_복사다():
    """재무팀의 목적은 번호를 DB(Memo)에 붙여넣는 것이다 — 상세 패널 대신
    번호만 복사한다 (2026-08-06 요청). 내부망 http 라 textarea 폴백이 필수다."""
    script = SCRIPT.read_text(encoding="utf-8")
    assert "function copyDocId(" in script
    assert "copyDocId(link,link.dataset.doc)" in script
    assert "openDoc" not in script and "detailPane" not in script
    assert "fallbackCopy" in script, "내부망 http 폴백"
    css = (ROOT / "desktop" / "ui" / "gamjun-chat.css").read_text(encoding="utf-8")
    assert ".copied-tip" in css, "복사됐다는 피드백"

def test_통장_목록은_전체조회_권한자만_본다():
    """통장은 지사로 나눌 수 없다 — 한 계좌에 전 지사 수수료가 섞여 들어온다.
    조회 범위를 좁힐 수 없으니 문 앞에서 가른다 (재무팀 = 본사 업무)."""
    router = (ROOT / "app" / "routers" / "gamjun_chat.py").read_text(encoding="utf-8")
    block = router[router.index('@router.post("/deposits"'):]
    assert "can_view_all(body.usr_seq)" in block
    source = SERVICE.read_text(encoding="utf-8")
    assert "async def can_view_all(" in source
    # 판정은 다른 화면과 같은 것을 쓴다 (본사(10) 또는 view_all_offices='Y')
    assert "_view_all_sync" in source and "_VIEWALL_CACHE" in source



def test_이미_채운_Memo_와_맞대_본다():
    """재무팀이 손으로 넣은 번호와 우리가 찾은 번호를 견준다 — 어긋난 건을 잡는 게
    이 화면의 두 번째 쓸모다. Memo 에는 '부산지사'·'잡이익'처럼 감정서번호가 아닌
    처리 표시도 들어가므로(2026-08-05 실측), 번호가 적힌 것만 견준다."""
    script = SCRIPT.read_text(encoding="utf-8")
    assert "const MEMO_DOC=/" in script
    assert "메모와 같음" in script
    block = script[script.index("function candCard("):script.index("function stageLine(")]
    assert "written&&written[0]===c.doc_id" in block, (
        "Memo 에 번호가 적힌 것만, 그것도 같을 때만 표시한다")


def test_합계_줄은_두지_않는다():
    """이 화면은 감정서를 찾는 곳이지 금액을 더하는 곳이 아니다 (2026-08-06 요청).
    건수는 이미 표 머리(listCount)에 있다."""
    script = SCRIPT.read_text(encoding="utf-8")
    # 줄 주석은 빼고 본다 — 왜 없앴는지는 주석으로 남겨 두기 때문이다.
    body = re.sub(r"//.*", "", script)
    assert "tfoot" not in body
    assert "합계" not in body
    css = (ROOT / "desktop" / "ui" / "gamjun-chat.css").read_text(encoding="utf-8")
    assert "tfoot" not in css


def test_표_머리는_스크롤을_따라_내려온다():
    """세로로 스크롤하는 상자는 **표 상자 자신**이어야 한다. 바깥
    .result-body 가 스크롤하면 sticky 머리는 안쪽 .tbl 에 매여 움직이지
    않는다 — .tbl 자체가 overflow:auto 라 nearest scrolling ancestor 가
    되기 때문이다. 감정서 LIST 도 .table-wrap 이 스크롤 주체다
    (dashboard.css:107). 2026-08-06 요청."""
    css = (ROOT / "desktop" / "ui" / "gamjun-chat.css").read_text(encoding="utf-8")
    assert ".result-body>.tbl,.match-body>.tbl{flex:1 1 auto;min-height:0}" in css
    for sel in (".result-body{", ".detail-panel .match-body{"):
        i = css.index(sel)
        block = css[i:css.index("}", i)]
        assert "overflow:hidden" in block, f"{sel} 는 스스로 스크롤하면 안 된다"
        assert "flex-direction:column" in block, f"{sel} 안에서 표가 남은 높이를 먹어야 한다"
    # 머리 고정 자체도 살아 있어야 한다
    assert ".result-body thead th,.detail-body thead th{position:sticky;top:0" in css


def test_카드사_정산은_조회에서_뺀다():
    """출금과 마찬가지로 **조건 없이** 뺀다 (2026-08-06 요청) — 조회 조건으로
    두지 않는다. 카드사 정산은 여러 승인건을 묶은 금액이라 감정서 한 건에
    대응되지 않는다. 실측(2026-06~07, 약식 제외 500건) 14건(2.8%), 전부
    'BC-745827823//WON뱅킹사업부/Ｆ／Ｂ' 꼴이다."""
    source = (ROOT / "app" / "services" / "deposit_list.py").read_text(encoding="utf-8")
    # 출금과 같은 자리에 못 박혀 있어야 한다 — 켜고 끄는 값이 아니다
    head = source[source.index("    sql = ("):source.index("    args: list[Any]")]
    assert "INOUT_GUBUN = '2'" in head, "출금 제외"
    assert "_CARD_SQL" in head, "카드 제외"
    assert "skip_card" not in source, "조회 조건으로 두지 않는다"

    router = (ROOT / "app" / "routers" / "gamjun_chat.py").read_text(encoding="utf-8")
    assert "skip_card" not in router
    page = PAGE.read_text(encoding="utf-8")
    assert 'id="noCard"' not in page
    assert "noCard" not in SCRIPT.read_text(encoding="utf-8")


def test_카드_잣대는_한_곳에서만_정한다():
    """SQL 절을 손으로 '%카드%' 라고 적었더니 카드사가 아닌 거래처
    '이카드밴（주）' 입금까지 SQL 단계에서 사라졌다 (2026-08-06 실측).
    잣대를 두 곳에 적으면 어긋난다 — 규칙은 _classify 의 _CARD_RE 한 곳에만
    두고, SQL 절은 그 패턴에서 만들어 쓴다."""
    from app.services import deposit_list, deposit_match

    words = [w for w in deposit_match._CARD_RE.pattern.split("|") if w]  # noqa: SLF001
    assert deposit_list._CARD_WORDS == words  # noqa: SLF001
    for w in words:
        assert f"NOT LIKE '%{w}%'" in deposit_list._CARD_SQL  # noqa: SLF001

    # SQL 절은 거들기만 한다 — 옮길 수 없는 낱말은 건너뛰되 import 는 살아야
    # 한다. 정규식이 복잡해졌다고 화면 전체가 죽는 편이 더 나쁘다.
    src = (ROOT / "app" / "services" / "deposit_list.py").read_text(encoding="utf-8")
    head = src[:src.index("def _rows_sync(")]
    assert "assert" not in head, "import 단계에서 죽지 않는다"
    # 넓게 자르지 않는다 — 카드사 낱말이 아닌 '카드' 단독은 없어야 한다
    assert "NOT LIKE '%카드%'" not in deposit_list._CARD_SQL  # noqa: SLF001

    # 카드사 정산은 빠지고, 이름에 '카드' 가 든 거래처는 남는다
    for jeokyo, dropped in (
        ("BC-745827823//WON뱅킹사업부/Ｆ／Ｂ", True),
        ("하나카드/정산//", True),
        ("이카드밴（주）/인터넷/기업은행/", False),
    ):
        hit = bool(deposit_match._CARD_RE.search(jeokyo.upper())  # noqa: SLF001
                   or deposit_match._CARD_RE.search(jeokyo))  # noqa: SLF001
        assert hit is dropped, jeokyo


def test_약식은_감정서_대신_본지사와_영업점을_보여준다():
    """약식평가에는 감정서번호가 없다. 재무팀이 필요한 것도 번호가 아니라
    **본/지사와 영업점명**뿐이다 (2026-08-06 요청). 적요의 가상계좌
    (400+6자리)가 곧 국민은행 탁상감정 의뢰번호라 그것 하나로 푼다.

    실측(2025-08~2026-08 약식 입금 4,574건): 본/지사 100.0% · 영업점 99.0%.
    분포는 본사 84.6% · 부산경남 6.5% · 경인 5.6% · 제주 2.3% · 울산 0.9%."""
    src = (ROOT / "app" / "services" / "deposit_search.py").read_text(encoding="utf-8")
    assert "def _yaksik_sync(" in src
    block = src[src.index("def _yaksik_sync("):src.index("def _search_sync(")]
    assert "BANK_KB_MASTER" in block and "BANK_KB_AccOffice" in block, "본/지사"
    assert "_VA_RE" in block, "약식 판정은 _classify 와 같은 잣대로"

    # 약식일 때만 부른다 — 다른 유형에 쓸데없는 조회를 걸지 않는다
    call = src[src.index("kind = deposit_match._classify"):src.index("    words = expand(")]
    assert 'kind[0] == "약식평가"' in call
    assert "_yaksik_sync(jeokyo)" in call

    # 읽기 전용 — 이 DB 에 쓰면 매출이 계상된다
    whole = src[src.index("# ── 약식(KB 탁상)"):src.index("def _search_sync(")]
    for bad in ("INSERT", "UPDATE ", "DELETE", "MERGE"):
        assert bad not in whole.upper(), bad

    # 화면까지 실려야 한다
    lst = (ROOT / "app" / "services" / "deposit_list.py").read_text(encoding="utf-8")
    assert '"yaksik": found.get("yaksik")' in lst
    script = SCRIPT.read_text(encoding="utf-8")
    assert "data.yaksik" in script
    assert "본·지사" in script and "영업점" in script
    css = (ROOT / "desktop" / "ui" / "gamjun-chat.css").read_text(encoding="utf-8")
    assert ".yaksik{" in css


def test_약식_영업점명은_전표와_같은_출처를_쓴다():
    """지점명을 정하는 경로는 이미 있다 (deposit_vouchers._resolve_yak):
    ① APW_TS_Master.CustName ② 없으면 KB_Code → a10_kb_branch_map.
    화면이 다른 출처를 쓰면 같은 입금이 화면과 전표에서 다른 지점으로 보인다.

    특히 BANK_KB_REQUEST_MASTER.BillName 은 세금계산서 **청구처**이지
    영업점이 아니다 — 실측상 둘 다 있는 3,201개 중 91개(2.84%)가 서로 다른
    지점을 가리킨다 ('국민은행 모란역(점)' vs '국민은행－성남종합금융센터').
    매핑표를 ①보다 먼저 쓰는 것도 안 된다: 다수결로 시드한 표라 3,050개 중
    79개(2.59%)에서 갈린다 ('행신동(점)' → '아웃바운드지원부지점').
    이름은 한 곳에서만 정한다."""
    src = (ROOT / "app" / "services" / "deposit_search.py").read_text(encoding="utf-8")
    block = src[src.index("def _yaksik_sync("):src.index("def _search_sync(")]
    loader = src[src.index("def _ts_branches("):src.index("def _yaksik_sync(")]

    assert "APW_TS_Master" in loader and "CustName" in loader, "1순위"
    assert "a10_kb_branch_map" in block, "2순위"
    assert "BillName" not in block and "BillName" not in loader, (
        "BillName 은 청구처다 — 영업점으로 쓰면 전표와 어긋난다")
    # 1순위를 먼저 본다
    assert block.index("_ts_branches()") < block.index("a10_kb_branch_map")


def test_약식_지점명은_통째로_담아_둔다():
    """APW_TS_Master(1,453,159행)에는 HFDocid 인덱스가 없고
    ORDER BY TS_SEQ DESC 가 역방향 스캔을 부른다 — 실측으로 한 건 4~5초다.
    400번호 전체(44,656개)를 한 번에 긁으면 396ms · 861KB 라 담아 두고 쓴다.
    실측: 첫 클릭 481ms, 이후 18~109ms, 같은 계좌 재조회 0ms."""
    src = (ROOT / "app" / "services" / "deposit_search.py").read_text(encoding="utf-8")
    loader = src[src.index("def _ts_branches("):src.index("def _yaksik_sync(")]
    assert "HFDocid LIKE '400%'" in loader, "한 번에 긁는다"
    assert "ORDER BY" not in loader.upper(), "역방향 스캔을 부르는 정렬을 넣지 않는다"
    assert "_TS_BRANCH_TTL" in src, "오래 담아 두지 않는다"
    # 실패해도 옛 값으로 버틴다
    assert "return _TS_BRANCH" in loader

    block = src[src.index("def _yaksik_sync("):src.index("def _search_sync(")]
    assert "_YAKSIK_CACHE" in block, "계좌별 답도 담아 둔다"
    assert "_YAKSIK_CACHE_MAX" in src, "무한정 쌓지 않는다"


def test_약식_조회가_실패해도_화면은_뜬다():
    """BANK_KB_* 는 곁가지다. 그 조회가 깨져도 '약식' 배지까지는 나와야
    한다 — 대사 화면 전체가 500 이 되면 안 된다."""
    src = (ROOT / "app" / "services" / "deposit_search.py").read_text(encoding="utf-8")
    block = src[src.index("def _yaksik_sync("):src.index("def _search_sync(")]
    assert "except Exception:" in block, "조회 실패를 삼킨다"
    assert "logger.exception" in block, "삼키되 흔적은 남긴다"
    assert "finally:" in block and "db.close()" in block, "연결은 반드시 닫는다"
    # 가상계좌가 없으면 DB 를 아예 두드리지 않는다
    assert "if not hit:" in block and "return {}" in block

def test_번호만_넣어도_그_행을_찾는다():
    """재무팀이 의뢰번호밖에 못 받는 일이 있다 — '206732380' 하나만 들고 와서
    그 입금이 어느 줄인지 찾아야 한다 (2026-08-06 요청).

    걸림돌은 기간이었다. 번호만 아는 사람은 그 돈이 언제 들어왔는지 모르는데
    기간을 7월로 잡아 두면 8월 건인 그 번호는 안 나온다
    (실측: 2026-08-03 · 10,718,410원 딱 1건).

    기간을 무시해도 되는 근거도 실측이다 — 통장은 85,817행(2023-01~)뿐이라
    기간 없이 훑어도 350ms 이고, 9~10자리 번호는 전 기간에서 중앙 1건
    (최대 2건)만 걸린다. 자릿수가 짧으면 잡음이 늘어(7자리 중앙 12건 ·
    4자리 중앙 90건·최대 406건) 6자리 이상만 이 규칙을 탄다."""
    from app.services import deposit_list

    # 번호뿐인 검색어만 이 길로 간다
    assert deposit_list._number_of("206732380") == "206732380"  # noqa: SLF001
    assert deposit_list._number_of("20673-2380") == "206732380"  # noqa: SLF001
    assert deposit_list._number_of("206732 380") == "206732380"  # noqa: SLF001
    assert deposit_list._number_of("01-2607-3-2380") == "01260732380"  # noqa: SLF001
    for text_only in ("세연스틸", "2380", "", "세연 206732380"):
        assert deposit_list._number_of(text_only) == "", text_only  # noqa: SLF001

    src = (ROOT / "app" / "services" / "deposit_list.py").read_text(encoding="utf-8")
    assert "_NUMBER_MIN = 6" in src, "4자리는 중앙 90건이라 태우지 않는다"
    # 번호면 기간 조회로 가지 않는다
    body = src[src.index("def _rows_sync("):src.index("# 번호로 콕 집었으면")]
    assert "return _number_rows_sync(number, limit)" in body


def test_번호로_찾을_때는_기간과_약식_카드_거르개를_끈다():
    """찾아 달라고 지목한 줄을 우리가 숨기면 안 된다 — 약식을 걸러 두면
    '400577516' 같은 가상계좌를 넣어도 안 나오고, 카드를 걸러 두면 카드사
    번호가 안 나온다.

    출금은 이 화면 전체와 마찬가지로 뺀다 (2026-08-06 요청). 실측(2025년
    이후) 6자리 이상 번호 15,010개 중 79개가 입금·출금에 같이 있고 그중
    70개가 '취소'인데, 짝이 되는 입금 쪽 적요에 이미 '취소된거래' 가 적혀
    있어 출금을 빼도 취소 사실은 보인다."""
    src = (ROOT / "app" / "services" / "deposit_list.py").read_text(encoding="utf-8")
    fn = src[src.index("def _number_rows_sync("):src.index("async def rows(")]
    for filt in ("_CARD_SQL", "ACCT_TXDAY BETWEEN", "only_blank", "skip_va"):
        assert filt not in fn, f"번호 찾기에는 {filt} 를 걸지 않는다"
    assert "INOUT_GUBUN = '2'" in fn, "출금은 화면 전체와 같이 뺀다"
    # 두 경로가 같은 모양을 낸다
    assert "_row(r)" in fn and "def _row(" in src

def test_번호_찾기는_온전한_일치를_먼저_본다():
    """① 적요에 그대로 → ② 구분자를 걷어내고 → ③ 앞 두 자리를 떼고.

    ②는 1.4초라 ①(350ms)이 빈손일 때만 간다. ③은 감정서번호
    '01-2607-3-2380' 을 넣었는데 적요에는 지사코드를 뺀 '260732380' 만
    있는 경우를 건지는데, 덜 미더운 짐작이라 온전한 일치를 이길 수 없다.
    실측: 그대로 474ms · 감정서번호꼴 2.6초 · 없는 번호 464ms."""
    src = (ROOT / "app" / "services" / "deposit_list.py").read_text(encoding="utf-8")
    fn = src[src.index("def _number_rows_sync("):src.index("async def rows(")]
    plain = fn.index('tries = [("JEOKYO LIKE ?", number)')
    trimmed = fn.index("number[2:]")
    assert plain < trimmed, "온전한 번호를 먼저 다 해 본 뒤에 두 자리를 뗀다"
    assert "len(number) >= 10" in fn, "짧은 번호는 두 자리를 떼지 않는다"
    # 첫 시도에서 걸리면 뒤는 안 간다
    assert "if rows:" in fn and "return [_row(r) for r in rows]" in fn


def test_번호로_찾았으면_화면이_그렇게_말한다():
    """조회 조건에는 7월이 걸려 있는데 8월 건이 나오면 사람이 못 믿는다.
    기간을 안 봤다는 사실을 제목에 밝힌다 (2026-08-06)."""
    lst = (ROOT / "app" / "services" / "deposit_list.py").read_text(encoding="utf-8")
    assert '"number": _number_of(keyword)' in lst, "서버가 알려 준다"
    script = SCRIPT.read_text(encoding="utf-8")
    assert "FOUND_BY=data.number" in script
    assert "번호 찾기" in script and "전체 기간" in script
    # 못 찾았을 때도 '그 기간에' 라고 하면 안 된다
    assert "통장 전체에서" in script
    page = PAGE.read_text(encoding="utf-8")
    assert "번호만 넣어도" in page, "칸 안내로 알려 준다"


def test_약식은_값이_나오면_배지를_빼고_표만_보여준다():
    """무슨 유형인지는 본·지사·영업점이 이미 말해 준다 — 배지만 덩그러니
    있으면 군더더기다 (2026-08-06 요청). 다만 값이 안 나온 나머지(1%)와
    카드·자사이체·실적회비는 배지가 유일한 표시라 그대로 둔다."""
    script = SCRIPT.read_text(encoding="utf-8")
    block = script[script.index("function candTable("):script.index("// 찾은 결과는")]
    assert "if(!y.office&&!y.branch)return head;" in block, "값이 없으면 배지"
    # 값이 있으면 head 를 붙이지 않고 표만 돌려준다
    guard = "if(!y.office&&!y.branch)return head;"
    tail = block[block.index(guard) + len(guard):]
    assert "head" not in tail, "값이 나왔으면 배지를 붙이지 않는다"
    assert "class=\"yaksik\"" in tail, "표는 그대로 낸다"


def test_본지사_칸은_없다():
    """통장 한 계좌에 전 지사 수수료가 섞여 들어와 조회를 지사로 나눌 수 없다.
    서버도 이 값으로 좁히지 않는다 — office 는 사용자 유효성 확인에만 쓰이고,
    진짜 문지기는 전체조회 권한(can_view_all)이다. 그래서 칸 자체를 뺐다
    (2026-08-06 요청). 서버가 usr_seq 로 소속을 다시 푸므로 빈 값을 보내도
    판정은 그대로다."""
    page = PAGE.read_text(encoding="utf-8")
    assert 'id="officeCode"' not in page
    script = SCRIPT.read_text(encoding="utf-8")
    assert "const OFFICE=()=>''" in script, "빈 값을 보낸다 — 서버가 다시 판정한다"
    # 서버 쪽 문지기는 그대로 살아 있어야 한다
    router = (ROOT / "app" / "routers" / "gamjun_chat.py").read_text(encoding="utf-8")
    for endpoint in ('@router.post("/deposits"', '@router.post("/deposit-match"'):
        block = router[router.index(endpoint):]
        assert "can_view_all(body.usr_seq)" in block[:900]


def test_감정서_찾기는_오른쪽_패널에_카드로_뜬다():
    """감정서 LIST 와 같은 2단 골격이다 — 왼쪽 목록, 오른쪽 상세(2026-08-06 요청).

    오른쪽은 **표가 아니라 카드**로 쌓는다 (2026-08-06 판단). 실측(2개월·200건,
    약식 제외): 후보 0건 20.5% · 1건 68.5% · 2건 이상 11.0%. 표가 표인 까닭은
    줄끼리 견주기 위해서인데 견줄 일이 11%뿐이었고, 좁은 오른쪽 패널에서
    11칸 표는 정작 중요한 근거 상세(money_note 중앙값 34자·최대 57자)와
    의뢰인·제출처를 늘 잘랐다. 감정서 LIST 상세도 같은 문제를 카드로 푼다.

    보여 줄 값은 그대로다: 회계팀이 쓰는 의뢰인(CustName)·제출처(Production)·
    채무자·담당자(CustCharge)."""
    page = PAGE.read_text(encoding="utf-8")
    assert 'class="workspace"' in page and 'id="matchSide"' in page
    assert "detail-panel" in page and "detail-placeholder" in page
    script = SCRIPT.read_text(encoding="utf-8")
    assert "function openMatchPanel(" in script and "$('matchSide')" in script
    assert "$('resultBody').after(panel)" not in script, "아래 붙이기는 걷어냈다"

    # 카드 골격 — 접었다 펼 수 있어야 5건 이상(실측 4.5%)일 때도 안 늘어진다
    assert "function candCard(" in script
    assert "<details class=\"cand-card\"" in script
    assert "i===0" in script, "첫 장만 펼친다"
    assert "function candRow(" not in script, "후보 표는 걷어냈다"
    assert "const CAND_HEAD=" not in script, "후보 표 머리도 걷어냈다"

    # 회계팀이 보는 값은 카드에 그대로 남는다
    fields = script[script.index("const CAND_FIELDS="):script.index("function whyLines(")]
    for label, key in (("의뢰인", "cust_name"), ("제출처", "submit_to"),
                       ("채무자", "debtor"), ("담당자", "cust_charge"),
                       ("접수일", "recv_date")):
        assert label in fields and key in fields, label
    card = script[script.index("function candCard("):script.index("function stageLine(")]
    assert "매출총액" in card and "won(c.billed)" in card
    for gone in ("미수금", "outstanding"):
        assert gone not in card, f"뺀 값: {gone}"

    # 근거 상세는 줄이지 않고 그대로 — 카드로 옮긴 이유 자체가 이것이다
    assert "function whyLines(" in script
    assert "const MONEY_SHORT=" not in script, "표 시절의 축약은 더 필요 없다"
    assert "function whereText(" in script and "감정서 원문" in script

    assert "closeMatchPanel" in script
    css = (ROOT / "desktop" / "ui" / "gamjun-chat.css").read_text(encoding="utf-8")
    assert ".workspace{display:grid" in css, "좌우 2단"
    assert "tr.picked" in css and ".kind-big" in css
    assert ".cand-cards{" in css and ".cand-card{" in css
    assert ".cand-why .why-list li" in css and "white-space:normal" in css, (
        "근거는 여러 줄로 풀어 쓴다 — 잘리면 카드로 옮긴 뜻이 없다")


def test_확신_배지는_빼고_경고만_남긴다():
    """근거 조각(금액·이름·회계)이 카드에 바로 나열되므로 '확신'은 같은 말을
    두 번 하는 셈이었다 (2026-08-06 요청). 다만 근거 하나짜리는 실측 정밀도가
    낮아(2개 이상 98% · 금액 단독 44% · 이름 단독 0%) 경고는 남긴다."""
    script = SCRIPT.read_text(encoding="utf-8")
    block = script[script.index("function evBadge("):script.index("function candCard(")]
    assert ">확신<" not in block
    assert "단일 근거" in block and "amber" in block


def test_목록_제목에_군더더기_문구가_없다():
    """'줄을 누르면 감정서를 찾습니다' 같은 안내는 뺀다. 키워드로 좁혔으면
    제목에 그 말만 남긴다."""
    script = SCRIPT.read_text(encoding="utf-8")
    assert "줄을 누르면 감정서를 찾습니다" not in script
    block = script[script.index("function renderDeposits("):script.index("function attachResize(")]
    assert "word?`거래 내역 · ${word}`:'거래 내역'" in block
    assert "FOUND_BY?`번호 찾기" in block, "번호로 찾았으면 그렇게 말한다"

def test_원문_전문검색_인덱스를_예열한다():
    """커넥션을 새로 연 뒤 처음 도는 CONTAINS 는 8~12초까지 튄다(실측). 같은
    쿼리를 데워진 상태로 돌리면 0.02초다 — 느림의 원인이 결과 크기가 아니라
    인덱스 페이지 콜드 리드라, 화면이 열릴 때 아무 말이나 한 번 던져 두면 된다.
    입금 대사에서 줄을 눌렀을 때 11초를 기다리던 게 이 비용이었다."""
    source = SERVICE.read_text(encoding="utf-8")
    assert "def _warm_fulltext_sync(" in source
    assert "_warm_fulltext_sync" in source[source.index("async def warmup("):
                                           source.index("def _warm_fulltext_sync(")]
    block = source[source.index("def _warm_fulltext_sync("):]
    # 독스트링에 '이건 쓰지 마라'를 적어 두므로, 실제 실행문만 본다.
    body = block[block.index('"""', block.index('"""') + 3):]
    assert "CONTAINS(ch.content" in body
    assert "TOP 1" in body, "예열은 한 줄이면 된다"
    # 풀스캔은 절대 넣지 않는다 — COUNT(*) 는 10초짜리다
    assert "COUNT(*)" not in body



def test_출금은_조회에서_아예_빠진다():
    """출금은 감정서 수수료 입금이 아니다 (2026-08-06 지시). 서버가 목록에서
    빼므로 화면 가드도 필요 없다. 섞이면 금액이 우연히 같은 남의 감정서가
    후보로 딸려 온다 — 실측에서 출금 818,400원에 10건이 나왔다."""
    source = (ROOT / "app" / "services" / "deposit_list.py").read_text(encoding="utf-8")
    assert "INOUT_GUBUN = '2'" in source

def test_약식도_기본으로_조회된다():
    """'약식 | 제외' 체크는 없앴다 (2026-08-06 요청) — 약식도 대사 대상이라
    기본으로 나와야 한다. 이제 약식 줄을 누르면 감정서 대신 본/지사와
    영업점을 보여주므로 목록에 있어도 쓸모가 있다."""
    page = PAGE.read_text(encoding="utf-8")
    assert "noVa" not in page and "약식" not in page
    script = SCRIPT.read_text(encoding="utf-8")
    assert "skip_va" not in script and "noVa" not in script
    src = (ROOT / "app" / "services" / "deposit_list.py").read_text(encoding="utf-8")
    assert "skip_va" not in src, "서버에도 남겨 두지 않는다"
    router = (ROOT / "app" / "routers" / "gamjun_chat.py").read_text(encoding="utf-8")
    assert "skip_va" not in router


def test_목록이_상한에서_잘리면_그렇게_말한다():
    """300건 상한에 걸려 **말없이** 795건이 사라지고 있었다 — 실측(2026-07)
    한 달 입금이 1,095건(약식 422 + 나머지 673)인데 300 만 왔다.
    약식을 기본으로 넣으면 더 커지므로 상한을 2,000 으로 올리고, 그래도
    넘치면 넘쳤다고 말한다. 한 장에 20건씩 넘겨 보므로 화면에 그려지는
    줄은 언제나 20개뿐이라 2,000줄을 들고 있어도 무겁지 않다.

    실측: 1주 300건 · 1개월 1,075건(안 잘림) · 7개월 2,000건(잘림)."""
    src = (ROOT / "app" / "services" / "deposit_list.py").read_text(encoding="utf-8")
    assert "_MAX_ROWS = 2000" in src
    # 상한 + 1 을 받아 넘쳤는지 가린다
    assert "_MAX_ROWS + 1" in src
    body = src[src.index("async def list_deposits("):]
    assert "cut = len(items) > cap" in body
    assert '"truncated": cut' in body and '"limit": cap' in body

    script = SCRIPT.read_text(encoding="utf-8")
    assert "CUT=data.truncated" in script
    assert "cut-note" in script, "잘렸으면 화면에 띄운다"
    css = (ROOT / "desktop" / "ui" / "gamjun-chat.css").read_text(encoding="utf-8")
    assert ".cut-note{" in css


def test_줄을_고르면_적요가_검색칸에_들어간다():
    """같은 거래처의 다른 입금을 이어서 훑는 흐름이라, 고른 줄의 적요를
    키워드 칸에 넣어 둔다 — 조회를 누르면 바로 그 적요로 좁혀진다
    (2026-08-06 요청)."""
    script = SCRIPT.read_text(encoding="utf-8")
    block = script[script.index("async function matchRow("):script.index("let DEPOSITS=")]
    assert "$('question').value=r.jeokyo" in block
    # 서버를 부르기 전에 넣는다 — 찾기가 실패해도 검색칸은 채워져 있어야 한다
    assert block.index("$('question').value=r.jeokyo") < block.index("deposit-match")


def test_법인_표기를_붙여_쓴_이름도_벗긴다():
    """'(주)XXX' 는 괄호 처리로 이미 벗겨지지만 '주식회사XXX' 는 통째로 한 단어라
    원장에도 원문에도 없는 말이 된다. 2026년 입금 21건이 이 모양이었다.

    실측(2026-08-07): 12건 표본에서 후보 제시가 11/12 → 12/12 로 늘었고,
    새로 잡힌 '주식회사세종디앤지' 는 정답(01-2604-3-1088)을 1순위로 냈다.
    """
    from app.services.deposit_search import expand

    assert "컨트롤케이앤" in expand("주식회사컨트롤케이앤/대체//")
    assert "세민개발" in expand("주식회사세민개발/타행환/하나은행/")
    assert "두란노서원" in expand("사단법인두란노서원/전자금융/")
    assert "성광의료재" in expand("의료법인성광의료재/타행이체/우리은행/")
    # 원래 말도 남긴다 — 원장에 법인 표기까지 그대로 적힌 건이 있다.
    assert "주식회사세민개발" in expand("주식회사세민개발/타행환/하나은행/")


def test_감정서가_없는_입금_유형을_더_알려준다():
    """'못 찾았습니다' 와 '이건 감정서 건이 아닙니다' 는 다르다.

    앞의 것은 재무팀이 계속 뒤지게 만들고, 뒤의 것은 거기서 끝낸다.
    2026년 미부착 3,307건 실측: 예금이자 29 · 지사 정산 9 · 환급금 4 건이
    새로 걸러진다. 남는 '실제로 찾아야 할' 건은 580건(17.5%)뿐이다.
    """
    from app.services.deposit_match import _classify

    assert _classify("이자세금:47,270원/결산이자/")[0] == "예금이자"
    assert _classify("대화경기/전자금융/")[0] == "지사 정산"
    assert _classify("훈련비고용부/전자금융/")[0] == "환급금"
    assert _classify("국고환급:서초세무서/센타입금/")[0] == "환급금"
    # 겹치는 적요는 더 구체적인 쪽이 이긴다 — '대화충남 업무실적비' 는 지사 정산이
    # 아니라 실적회비다. 그래서 새 규칙은 기존 규칙 뒤에 둔다.
    assert _classify("대화충남 업무실적비/인터넷입금이체/")[0] == "지사 실적회비"
    # 진짜 감정서 건은 그대로 탐색으로 보낸다.
    assert _classify("(주)페이스건축사사/전자금융/") is None


def test_세무서는_환급금으로_가로채지_않는다():
    """세무서가 감정평가를 의뢰한 정상 건이 있다 — '세무서' 만으로 거르면 안 된다.

    실측(2023~2026 입금 71,111건): '세무서' 를 넣었더니 감정서번호가 이미 붙은
    정상 건 7건을 가로챘다 (구로세무서 01-2504-4-0135, 반포세무서 01-2307-4-0333,
    동작세무서 01-2601-4-0017 …). 환급이라고 못 박은 말이 있을 때만 거른다.
    """
    from app.services.deposit_match import _classify

    assert _classify("구로세무서/국고이체/") is None
    assert _classify("반포세무서/재정자금/농협000002/") is None
    assert _classify("동작세무서/재정이체/재정이체/") is None
    assert _classify("국고환급:서초세무서/센타입금/")[0] == "환급금"


def test_원문_감정서번호는_대문자로_맞춘다():
    """원장은 종별 문자를 항상 대문자로 쓴다 — 정상 번호 668,460건 중 소문자 0건.

    원문(jun.case_master)에는 소문자가 343건 있다('01-2602-a-0017'). 그대로 두면
    원장 조회는 대소문자 무시라 행은 찾아지지만, 돌아온 대문자 번호로 by_word 를
    되짚을 때 키가 안 맞아 근거 단어와 섹션이 통째로 사라진다.
    정답지의 9.2%(70/758)가 A·B 종별이라 무시할 수 없다.
    """
    from app.services.deposit_search import _norm_doc_id

    assert _norm_doc_id("01-2602-a-0017") == "01-2602-A-0017"
    assert _norm_doc_id(" 01-2604-A-0054 ") == "01-2604-A-0054"
    assert _norm_doc_id(None) == ""


def test_전표는_마지막_그물이다():
    """전표를 무조건 넣으면 이미 맞히던 조회를 뒤엎는다.

    실측: '신영부동산신탁주식회/인터넷입금이체/' 는 매출총액 일치로 정답
    01-2602-4-0054 를 1순위에 두고 있었는데, 같은 날 같은 금액 전표가 가리킨
    01-2603-4-0084 가 '금액+회계' 두 근거를 얻어 그 위로 올라탔다.
    전표는 하루치 입금을 묶은 장부라 같은 금액이 겹치면 엉뚱한 줄을 짚는다.
    """
    source = (ROOT / "app" / "services" / "deposit_search.py").read_text(encoding="utf-8")
    index = source.index("# ⑧ 전표 발견")
    body = source[index : index + 2200]
    assert "already_sure = any(_tier_precheck(i) for i in items)" in body
    assert "and not already_sure" in body
    # 조회는 _enrich_sync 와 공유한다 — 같은 질의를 두 번 하지 않는다.
    assert "_voucher_docs_cached(amount, day)" in body
    assert "_enrich_sync(items, amount, day, voucher_docs)" in source


def test_원문_축은_항상_열린다():
    """원장 이름이 오답 하나를 물어도 원문이 닫히던 것을 고쳤다.

    '광주중앙새마을금고' 는 원장에서 56건이 걸렸는데 정답이 그 안에 없고
    원문에서는 1건으로 좁혀진다. 실패 33건 중 9건이 원문에 정답을 갖고 있었다.
    다만 표시 규칙은 그대로다 — 원문 단독은 '이름' 신호 하나뿐이라 tier 2 로 숨는다.
    """
    source = (ROOT / "app" / "services" / "deposit_search.py").read_text(encoding="utf-8")
    index = source.index("# ⑥ 원문")
    body = source[index : index + 2500]
    assert "not strong_name_seen" not in body, "게이트가 되살아났다"
    assert "'원문 본문'" in body or "원문 본문" in body
    # 원문 단독 표시는 기각이다 — 어떤 조건에서도 90% 를 못 넘었다(최고 88.5%).
    assert '"원문 본문"' in source[source.index("_NAME_LABELS = "):
                                 source.index("_NAME_LABELS = ") + 300]


def test_표기_교차는_새_후보를_만들지_않는다():
    """이미 뽑힌 후보에 이름 근거만 더한다 — 오탐 표면이 넓어지면 안 된다."""
    from app.services.deposit_search import _canon, _name_echo

    assert _canon("(주)한강이앰피") == _canon("한강이앰피 주식회사")
    assert _canon("신영부동산신탁(주)") == "신영부동산신탁"
    item = {"cust_name": "신영부동산신탁(주)", "submit_to": "", "debtor": "", "cust_charge": ""}
    assert _name_echo(item, {"신영부동산신탁"}) == "신영부동산신탁(주)"
    # 3글자 이하는 남의 상호에 우연히 박힌다 — 하한이 있어야 한다.
    assert _name_echo({"cust_name": "대한전선", "submit_to": "", "debtor": "",
                       "cust_charge": ""}, {"대한"}) == ""

    source = (ROOT / "app" / "services" / "deposit_search.py").read_text(encoding="utf-8")
    index = source.index("# ⑨ 표기 교차")
    body = source[index : index + 1600]
    assert "items.extend" not in body, "후보를 새로 만들면 안 된다"
    assert "_labels" in body


def test_상호에_붙은_숫자는_번호로_믿지_않는다():
    """이 축은 _NUM_LABELS 라 걸리면 tier 0 으로 단독 표시되고, 걸리는 순간
    뒤의 이름·금액 축이 닫힌다 — 오탐이 가장 비싸게 먹히는 자리다.

    실측(정답지 758건, 창 사다리 1·3·6개월 전체):
      상호에 붙은 숫자로 걸린 13건 → 정답 1건 (7.7%)
      독립 칸으로 걸린      5건 → 정답 2건 (40.0%)
    오탐은 거의 다 농협 여신연동의 내부 코드다 — 농협000546·000069·000675·
    000029·000017·001324·000098 …

    그렇다고 **버리면 안 된다.** '계선50018808/여신연동/농협001316/' 은 붙은
    숫자가 정답(01-2605-6-0359)을 물어 온 건이다. 그래서 후보로는 받되 라벨을
    '의뢰문서번호(추정)' 로 낮춰 이름 갈래로 보낸다 — 단독이면 tier 2 로 숨고,
    금액·회계와 겹칠 때만 올라온다.
    """
    from app.services.deposit_search import _glued_digits, expand, _NAME_LABELS

    def split(jeokyo):
        glued = _glued_digits(jeokyo)
        digits = [w for w in expand(jeokyo) if w.isdigit() and len(w) >= 5]
        return ([w for w in digits if w not in glued],
                [w for w in digits if w in glued])

    assert split("김리은평가비/여신연동/농협000546/") == ([], ["000546"])
    assert split("(주)득금26024/타행IB/(기업)/") == ([], ["26024"])
    assert split("동작신협//01174/창구") == (["01174"], [])
    assert split("소공(문창기)감정평가수수료//01093/창구") == (["01093"], [])
    # 붙은 숫자로 찾은 후보는 '번호' 가 아니라 '이름' 갈래여야 한다.
    assert "의뢰문서번호(추정)" in _NAME_LABELS


def test_회계_꼬리말이_금액_근거를_만들지_않는다():
    """'입금 당일 회계 완납 처리됨' 한 문장이 금액·회계 두 신호를 다 만들면
    그것만으로 근거가 둘이 되어 tier 0 으로 올라온다.

    실측 피해: '주식회사 엘앤씨이에' 3,121,800원에서 원문이 물어온 오답
    01-2603-3-0848 이 이 꼬리말만으로 근거 3개를 얻어, 매출총액이 정확히 맞는
    정답 01-2603-3-0706 을 2순위로 밀어냈다.
    """
    from app.services.deposit_search import _signals

    only_tail = {"field_label": "원문 본문",
                 "money_note": "입금 당일 회계 완납 처리됨"}
    assert "금액" not in _signals(only_tail)
    assert "회계" in _signals(only_tail)

    real_money = {"field_label": "원문 본문",
                  "money_note": "입금액 = 매출총액 (완납) · 입금 당일 회계 완납 처리됨"}
    assert {"금액", "회계", "이름"} <= set(_signals(real_money))
    assert "금액" in _signals({"field_label": "", "money_note": "입금액 = 미수 잔액 (잔금)"})
    assert "금액" in _signals({"field_label": "", "money_note": "매출총액과 10원 차이 (사실상 완납)"})


def _classify_cases():
    from app.services.deposit_match import _classify
    return _classify


def test_감정서가_없는_유형을_아홉_가지_더_가려낸다():
    """후보 0건 164건을 훑어 넓힌 분류다 (2026-08-08).

    전부 정답지 전수(2023+ 통장 71,111건 중 Memo 에 감정서번호가 박힌 14,790건)로
    **가로채는 정상 건 0** 을 확인했다. 2023+ 미부착 4,689건 중 601건을 걷어낸다.
    """
    _classify = _classify_cases()
    assert _classify("이자원가 (이자: 275,52//김포지점/")[0] == "예금이자"
    assert _classify("서초구자동차세/전자금융/")[0] == "지방세 환급"
    assert _classify("마티즈 주차장/인터넷입금이체/", 4473182)[0] == "주차장 수입"
    assert _classify("협회보험료지원/전자금융/", 25398000)[0] == "협회 지원금"
    assert _classify("한국주택금융공/전자금융/", 105986100)[0] == "기관 묶음정산"
    assert _classify("주신보집중계좌/전자금융/", 26383500)[0] == "기관 묶음정산"
    assert _classify("(주)정일감정평가/전자금융/", 1331000)[0] == "타법인 정산"
    assert _classify("대일감정원본사/전자금융/", 1663750)[0] == "타법인 정산"
    assert _classify("충청급여/인터넷입금이체/")[0] == "지사 정산"
    assert _classify("경남중앙 3분기/인터넷입금이체/")[0] == "지사 정산"
    assert _classify("북부_대화/인터넷입금이체/")[0] == "지사 정산"
    assert _classify("8월동부급여/대체//")[0] == "지사 정산"
    assert _classify("경기서부/전자금융/")[0] == "지사 정산"


def test_분류를_넓히면_안_되는_자리들():
    """실측이 정면으로 부정한 확장들. 지우지 마라 — 다시 넓히려는 유혹이 반복된다."""
    _classify = _classify_cases()

    # '감정평가' 키워드로 타법인을 잡으면 자사제외 485건 중 372건(76.7%)이 정상 건이다.
    # 은행이 적요에 쓰는 업무 설명이 대부분이다.
    assert _classify("담보물외부감정평가수수료(은행부담)/대체/잠원역/") is None
    assert _classify("230532478/감정평가비/농협201025/") is None
    # 협회가 실제 의뢰인인 감정서가 있다(01-2503-4-0071). 세무서 사고와 같은 구조.
    assert _classify("한국감정평가사협회/전자금융/", 209612) is None
    # 보험사도 담보평가를 의뢰한다 — 이름만으로 거르면 정답지 11건이 죽는다.
    # 침해 최소 금액이 883,300원이라 30만원이 가른다.
    assert _classify("현대해상화재/FBS입금/", 61110)[0] == "보험 정산"
    assert _classify("현대해상화재/FBS입금/", 883300) is None
    # 지사명 단독에 법인 접두를 허용하면 '(주)경인/전자금융/'(01-2304-4-0180)이 죽는다.
    assert _classify("(주)경인/전자금융/") is None
    # 지사명+숫자는 관리번호다 — '동부103848' 같은 정답지가 4건 있다.
    assert _classify("동부103848/대체//") is None
    # 지사 규칙은 이름칸에만 건다. 2·3번째 칸은 은행·지점명이다.
    assert _classify("보관금/동부법/") is None
    assert _classify("//전북/잠실") is None
    # '이자' 부분일치는 정답지 5건을 가로챈다 — 필드 단위로만.
    assert _classify("이자수익금 반려/대체//") is None


def test_자사이체는_이름칸이_우리_회사명일_때만():
    """'대화감정' 이 어디든 있으면 자사이체로 보던 것을 좁혔다.

    남이 낸 돈에 우리 이름이 업무 설명으로 붙은 건까지 덮어, 재무팀이 아예 안 보게
    만들고 있었다. 실측 6건 → 2건. 남는 2건은 적요가 자사이체와 글자까지 같다.
    """
    _classify = _classify_cases()
    # 자사이체 (이름칸이 우리 회사명 — 은행이 14자에서 자른 형태·전각 괄호·지사명 포함)
    assert _classify("(주)대화감정평가법인/전자금융/")[0] == "자사이체"
    assert _classify("(주)대화감정평가법/전자금융/")[0] == "자사이체"
    assert _classify("（주）대화감정평가법/전자금융/")[0] == "자사이체"
    # 지사명이 붙으면 자사이체가 아니라 **지사 정산**이다 — 지사가 본사로 보낸 돈이다.
    assert _classify("대화감정평가법인경기/전자금융/")[0] == "지사 정산"
    assert _classify("대화경기/전자금융/")[0] == "지사 정산"
    # 남이 낸 돈 — 우리 이름은 업무 설명이거나 상대 이름이 같이 있다
    assert _classify("대화감정평가법인 신동아건설/대체/4030-009/") is None
    assert _classify("주식회사으뜸디앤씨 대화감정/대체/4030-009/") is None
    assert _classify("대화감정평가수수료//SC2030/타행-E") is None
    assert _classify("금사리(대화감정평가/우체국/우체국0715450/") is None


def test_개인이_자기_감정을_의뢰하고_스스로_낸_돈():
    """이름 하나뿐이라 숨어 있던 '본인 의뢰' 를 확신 후보로 올린다 (2026-08-08).

    실측(2024+ 정답지 651건, 1개월창, 원장이 그 이름으로 한 건만 낼 때):
      전체 90.4% → **본사(01-)만 97.0% → 본사 + 이름이 의뢰인칸이면 192/192 = 100%**.
    오답이 지사 건으로 몰리는 건 이 통장이 본사 통장이기 때문이다 — 정답 651건이
    전부 01- 이었다(예외 0건).

    '이지안/타행이체/기업은행(2421)/' 807,400원이 이 규칙이 필요한 이유다 —
    원장 01-2605-3-1707 의 의뢰인이 정확히 '이지안' 인데 청구액(779,900)이 달라
    이름 근거 하나뿐이라 tier 2 로 숨어 있었다.
    """
    from app.services.deposit_search import (_person_payer, _self_client_mark,
                                             _signals, _tier)

    assert _person_payer("이지안/타행이체/기업은행(2421)/") == "이지안"
    assert _person_payer("김순애//하나1066/타행환") == "김순애"
    # 성씨로 시작하지 않는 상호 토막은 사람이 아니다 — 남의 감정서를 확신으로 올린다.
    assert _person_payer("대왕/대체/1112-002/") == ""
    assert _person_payer("현대/유동국/FBS입금/") == ""
    assert _person_payer("대체/전자금융/") == ""
    assert _person_payer("(주)페이스건축사사/전자금융/") == ""
    assert _person_payer("우리은행//잠실나루역지점/대체입금") == ""

    def row(doc_id, cust):
        return {"doc_id": doc_id, "cust_name": cust, "field_label": "의뢰처"}

    # 본사 + 의뢰인칸 + 창 안 유일
    items = [row("01-2605-3-1707", "이지안"), row("01-2606-3-1775", "기업은행 김포지점장")]
    assert _self_client_mark(items, "이지안/타행이체/기업은행(2421)/") == 1
    marked = items[0]
    marked["evidence"] = _signals(marked)
    assert "본인" in marked["evidence"]
    assert _tier(marked) == 0

    # 1·3·6개월 창이 같은 감정서를 세 번 담아도 '유일' 이다 — 감정서 단위로 센다.
    dup = [row("01-2605-3-1707", "이지안") for _ in range(3)]
    assert _self_client_mark(dup, "이지안/타행이체/기업은행(2421)/") == 1
    assert all(i.get("_self_client") for i in dup)   # _rank 가 어느 줄을 남기든

    # 서로 다른 감정서가 둘이면 사람이 고른다 — 확신을 주지 않는다.
    two = [row("01-2605-3-1707", "이지안"), row("01-2601-3-0100", "이지안")]
    assert _self_client_mark(two, "이지안/타행이체/기업은행(2421)/") == 0
    assert not any(i.get("_self_client") for i in two)

    # 지사 건은 이 통장의 답이 될 수 없다 (정답 651건 전부 01-, 예외 0건).
    branch = [row("12-2503-3-0186", "이주영")]
    assert _self_client_mark(branch, "이주영/타행이체/국민은행/") == 0

    # 이름이 채무자·소유자 칸에서만 맞은 건 90.5% 라 확신 대상이 아니다.
    debtor_only = [{"doc_id": "01-2509-3-3195", "cust_name": "농협은행 지점장",
                    "debtor": "이상호", "field_label": "채무자"}]
    assert _self_client_mark(debtor_only, "이상호/여신연동/농협001150/") == 0
