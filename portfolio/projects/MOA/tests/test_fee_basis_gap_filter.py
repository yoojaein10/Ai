"""격차율 필터 — 재무팀이 "격차가 난 건만" 보려고 요청했다(2026-09-04).

축이 두 군데(조회·엑셀)에 복제돼 있으면 화면 건수와 파일 행수가 갈린다. 여기서는
그 둘이 같은 함수를 쓰는지, 그리고 화면이 0.0% 로 뭉개는 값과 문턱이 같은지 본다.
"""

import re
from pathlib import Path

from app.services.fee_basis import (
    DEVIATION_ABOVE,
    DEVIATION_BELOW,
    DEVIATION_WITHIN,
    GAP_EPSILON,
    apply_filter,
)

UI = Path(__file__).parents[1] / "desktop" / "ui" / "fee-basis.html"


def _row(doc, gap, direction=DEVIATION_WITHIN):
    return {"doc_id": doc, "reference_gap_rate": gap, "deviation_direction": direction}


ROWS = [
    _row("a", None),                       # 요율 미상 — 격차율 칸이 빈칸
    _row("b", 0.0),                         # 정확히 기준대로
    _row("c", 0.0000023),                   # 원 단위 반올림 오차 (화면에 0.0%)
    _row("d", -0.31, DEVIATION_BELOW),      # 하한 미만
    _row("e", 0.42, DEVIATION_ABOVE),       # 상한 초과
    _row("f", 0.03, DEVIATION_WITHIN),      # 기준 안이지만 격차는 났다
]


def _ids(flt):
    return [i["doc_id"] for i in apply_filter(ROWS, flt)]


def test_all_passes_everything_through():
    assert _ids("전체") == ["a", "b", "c", "d", "e", "f"]


def test_has_gap_excludes_blank_and_rounded_zero():
    """요율 미상(빈칸)과 화면에 0.0% 로 찍히는 행은 '격차 있음'이 아니다.

    빈칸을 빼는 건 사용자 확인 사항이다(2026-09-04): 요율을 모르면 기준선 자체가
    없어서 격차가 났다고 부를 수 없다. 0.0% 를 빼는 건 화면과 건수를 맞추기 위해서다.
    """
    assert _ids("격차있음") == ["d", "e", "f"]


def test_has_gap_keeps_within_band_rows():
    """기준 안(하한~상한)이어도 격차가 났으면 잡힌다 — '금액이탈'과 다른 축이다."""
    assert "f" in _ids("격차있음")
    assert "f" not in _ids("금액이탈")


def test_direction_filters_split_the_two_colours():
    assert _ids("하한미만") == ["d"]
    assert _ids("상한초과") == ["e"]
    assert _ids("금액이탈") == ["d", "e"]


def test_threshold_matches_the_screen():
    """서버 문턱과 화면 문턱이 같아야 한다 — 다르면 눈으로 센 건수와 목록이 어긋난다."""
    assert GAP_EPSILON == 0.0005
    html = UI.read_text(encoding="utf-8")
    m = re.search(r"const GAP_EPSILON = ([0-9.]+);", html)
    assert m, "화면에 GAP_EPSILON 이 없다"
    assert float(m.group(1)) == GAP_EPSILON

    # 경계 바로 아래/위
    just_under = [_row("x", 0.00049)]
    just_over = [_row("y", 0.00051)]
    assert apply_filter(just_under, "격차있음") == []
    assert len(apply_filter(just_over, "격차있음")) == 1


def test_both_call_sites_share_one_filter():
    """조회와 스냅숏(엑셀)이 같은 함수를 쓴다 — 한쪽만 고치면 두 목록이 갈린다."""
    import inspect

    from app.services import fee_basis

    for fn in (fee_basis.build_fee_basis_report, fee_basis.select_view):
        src = inspect.getsource(fn)
        assert "apply_filter(items, flt)" in src, f"{fn.__name__} 이 공용 필터를 안 쓴다"
        assert 'flt == "불일치"' not in src, f"{fn.__name__} 에 옛 복제 분기가 남았다"


def test_new_filter_values_are_accepted_by_the_api():
    """드랍박스가 보내는 값이 라우터 Filter 타입에 들어 있어야 422 가 안 난다."""
    from typing import get_args

    from app.services.fee_basis import Filter

    allowed = set(get_args(Filter))
    for value in ("전체", "격차있음", "하한미만", "상한초과"):
        assert value in allowed, f"{value} 를 라우터가 거부한다"


def test_screen_hides_rows_instead_of_redrawing():
    """행을 다시 그리면 입력 중인 의견이 날아간다 — 감추기만 해야 한다."""
    html = UI.read_text(encoding="utf-8")
    body = html.split("function applyGapFilter(){", 1)[1].split("\n  }", 1)[0]
    assert "tr.hidden" in body, "감추기 방식이 아니다"
    assert "innerHTML" not in body, "필터가 표를 다시 그리면 의견 입력이 날아간다"
    # 감춘 행이 CSS 로도 확실히 사라져야 한다
    assert ".fb-table tbody tr[hidden]{display:none}" in html
