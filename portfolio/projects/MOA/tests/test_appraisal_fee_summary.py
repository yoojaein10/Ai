

def test_특별용역비는_0이어도_실비_아래에_보인다():
    """2026-08-20 사용자 요청 — '없음'을 눈으로 확인하는 자리다.

    값이 붙는 건은 73만 건 중 8,289건뿐이라, 0일 때 숨기면 그 칸이 있는지조차
    모른다. 토지조사비·절사금액은 종전대로 있을 때만 보인다.
    """
    from pathlib import Path

    script = (
        Path(__file__).resolve().parent.parent / "desktop" / "ui" / "dashboard.js"
    ).read_text(encoding="utf-8")

    block = script[script.index("function renderFeeSummary"):]
    block = block[:block.index("$('feeSummaryRows')")]

    assert "['특별용역비', fee.special_service_fee]," in block, (
        "true(있을 때만) 가 붙으면 0인 건에서 사라진다"
    )
    # 실비 바로 다음 줄이어야 한다
    assert block.index("['실비'") < block.index("['특별용역비'") < block.index("['절사금액'")
    # 이 둘은 그대로 숨긴다
    assert "['토지조사비', fee.land_survey_fee, true]," in block
    assert "['절사금액', fee.rounding_off, true]," in block
