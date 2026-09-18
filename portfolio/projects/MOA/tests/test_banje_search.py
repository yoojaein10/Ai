"""반제 리스트 감정서번호 검색 (2026-08-21 사용자 요청).

핵심은 "번호를 넣으면 기간을 안 건다"는 것이다. 반제가 언제 됐는지 몰라서
찾는 것이라, 기간 안에서만 걸러 주면 작년에 반제된 건이 빠져 검색이 쓸모없다.
회계가 관리번호를 제각각 적어 놔서(‘012603-1-0109-1’, ‘매출 01-…’) 사람이
어떻게 치든 걸려야 한다.
"""

from datetime import date
from pathlib import Path

import pytest

from app.services.banje import _doc_matches, _search_key

UI = Path(__file__).resolve().parent.parent / "desktop" / "ui"


# ── 번호 대조 ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("typed", [
    "01-2603-1-0109",      # 화면에 보이는 그대로
    "012603-1-0109",       # 회계가 실제로 적어 둔 표기
    "01260310109",         # 구분기호 없이
    " 01-2603-1-0109 ",    # 붙여넣기하면 공백이 따라온다
    "0109",                # 뒤 4자리만
])
def test_사람이_어떻게_치든_같은_감정서를_찾는다(typed):
    key = _search_key(typed)
    assert _doc_matches(key, "01-2603-1-0109", ["01-2603-1-0109"], "01-2603-1-0109")


def test_원본_관리번호로도_찾힌다():
    """'012603-1-0109-1' 은 표준형이 아니라 대표번호가 원본 그대로 남는다.

    이걸 못 찾으면 정작 회계가 잘못 적어 넣은 건을 검색으로 못 뒤진다.
    """
    key = _search_key("01-2603-1-0109")
    assert _doc_matches(key, "012603-1-0109-1", [], "012603-1-0109-1")
    # 군더더기가 붙은 표기도 원본으로 대조된다
    assert _doc_matches(key, "01-2603-1-0109", ["01-2603-1-0109"], "매출 01-2603-1-0109")


def test_다른_감정서는_안_걸린다():
    key = _search_key("01-2603-1-0109")
    assert not _doc_matches(key, "01-2603-1-0110", ["01-2603-1-0110"], "01-2603-1-0110")


def test_검색어가_비면_전부_통과한다():
    """빈 검색어가 필터로 동작하면 평소 조회가 0건이 된다."""
    assert _doc_matches("", "무엇이든", [], "")


# ── 기간을 안 거는 것 ─────────────────────────────────────────────────────

def test_번호_검색은_SQL에서_기간을_빼야_한다():
    """기간 SQL이 살아 있으면 '작년에 반제된 건'이 안 나와 검색이 무의미하다."""
    body = (Path(__file__).resolve().parent.parent / "app" / "services" / "banje.py").read_text(
        encoding="utf-8"
    )

    assert 'if not search and date_basis != "gen":' in body, (
        "번호 검색일 때도 기간을 걸면 전 기간 검색이 안 된다"
    )
    # 화면이 안 걸린 기간을 써 붙이면 거짓말이 되므로 period 를 비운다
    assert "None if search or date_from is None or date_to is None" in body


def test_기간_없이도_요청이_통과한다():
    """번호가 기간을 대신하므로 라우터가 기간을 필수로 막으면 안 된다."""
    body = (Path(__file__).resolve().parent.parent / "app" / "routers" / "banje.py").read_text(
        encoding="utf-8"
    )

    assert "if not doc and (date_from is None or date_to is None):" in body
    assert "elif not doc and (date_from is None or date_to is None):" in body, (
        "엑셀 내보내기도 같은 조건이어야 화면과 결과가 갈리지 않는다"
    )


def test_미반제_검색은_비표준_제외보다_먼저_건다():
    """찾는 번호가 비표준이라고 검색 결과에서 통째로 사라지면 '왜 안 나오냐'가 된다."""
    body = (Path(__file__).resolve().parent.parent / "app" / "services" / "banje.py").read_text(
        encoding="utf-8"
    )

    assert "if not single and not include_nonstd and not search:" in body
    # 잔액 0이라 목록에서 빠진 건 수를 알려 줘야 '반제 내역에서 보라'고 안내할 수 있다
    assert '"settled_only": settled_only' in body


# ── 화면 ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("page", ["banje-receivable.html", "banje-advance.html"])
def test_두_화면_모두_검색칸을_갖는다(page):
    """외상매출금·선수금은 같은 banje.js 를 쓴다 — 한쪽만 고치면 다른 쪽이 깨진다."""
    html = (UI / page).read_text(encoding="utf-8")

    assert 'id="docQuery"' in html
    assert 'placeholder="예: 01-2603-1-0109"' in html


def test_검색_중에는_기간을_보내지_않는다():
    script = (UI / "banje.js").read_text(encoding="utf-8")

    query = script[script.index("function buildQuery()"):]
    query = query[:query.index("\n}")]
    assert "const period = (open || q) ? ''" in query, "검색 중에 기간을 보내면 서버 조건과 어긋난다"
    assert "encodeURIComponent(q)" in query, "번호에 공백이 섞이면 주소가 깨진다"


def test_조회와_내보내기가_같은_조건을_쓴다():
    """엑셀만 기간이 걸리면 화면과 파일이 달라진다 — 대사에서 바로 사고가 난다."""
    script = (UI / "banje.js").read_text(encoding="utf-8")

    assert script.count("buildQuery()") >= 2
    assert "/api/banje/export.xlsx?${buildQuery()}" in script


def test_검색_중에는_기간칸을_흐리게_해_잠근다():
    """조건이 살아 있는 것처럼 보이면 '기간을 바꿨는데 왜 그대로냐'가 된다."""
    script = (UI / "banje.js").read_text(encoding="utf-8")

    assert "function applyDocMode()" in script
    assert "el.disabled = searching" in script
    assert "$('docQuery').addEventListener('input', applyDocMode);" in script
    assert "if (e.key === 'Enter')" in script, "번호를 치고 엔터가 자연스럽다"


def test_모드를_바꿔도_검색_상태가_유지된다():
    """applyMode 가 기간칸을 다시 켜 놓으면 검색 중인데 조건이 살아난 것처럼 보인다."""
    script = (UI / "banje.js").read_text(encoding="utf-8")

    apply_mode = script[script.index("function applyMode()"):]
    apply_mode = apply_mode[:apply_mode.index("\n}")]
    assert "applyDocMode();" in apply_mode


def test_잔액이_없으면_왜_없는지_말해_준다():
    """미반제 화면에서 다 반제된 번호를 찾으면 0건이다 — 안 알려 주면 고장으로 오해한다."""
    script = (UI / "banje.js").read_text(encoding="utf-8")

    assert "p.data.settled_only" in script
    assert "반제 완료" in script


# ── 실제 데이터 (연결된 DB에서만) ──────────────────────────────────────────

@pytest.mark.integration
def test_실데이터_번호검색이_기간_밖의_반제를_찾는다():
    from app.database import get_session_factory
    from app.services.banje import banje_list

    db = get_session_factory()()
    try:
        data = banje_list(db, "receivable", date(2026, 8, 1), date(2026, 8, 31), "10", "settle",
                          "01-2603-1-0109")
        assert data["period"] is None, "검색 중엔 기간을 알리지 않는다"
        assert data["doc_query"] == "01-2603-1-0109"
        assert data["count"] >= 1
        for item in data["items"]:
            joined = item["doc"] + (item["raw"] or "")
            assert "0109" in joined.replace("-", "")
    finally:
        db.close()
