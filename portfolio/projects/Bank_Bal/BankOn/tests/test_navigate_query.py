from __future__ import annotations

import pytest

from bankon.ui import driver, navigate


class FakeMain:
    handle = 123


def test_query_documents_sets_filters_and_clears_document(monkeypatch):
    session = navigate.Session(FakeMain())
    controls = {
        "담보": object(),
        "직접입력": object(),
        "조 회": object(),
        "조회시작일": object(),
        "조회종료일": object(),
        "감정서조회": object(),
        "의뢰번호조회": object(),
    }
    clicks = []
    message_clicks = []
    writes = []

    monkeypatch.setattr(
        driver, "by_text", lambda handle, text, class_name=None: controls.get(text))
    monkeypatch.setattr(
        driver, "find_by_label", lambda handle, text, class_name=None: controls.get(text))
    monkeypatch.setattr(driver, "click", clicks.append)
    monkeypatch.setattr(driver, "click_message", message_clicks.append)
    monkeypatch.setattr(
        driver, "set_text",
        lambda control, value, verify=True: writes.append((control, value, verify)))

    navigate.query_documents(
        session, start="2026-08-18", end="2026-08-18", settle=0)

    # 라디오는 BM_CLICK 메시지, 버튼은 마우스 클릭.
    assert message_clicks == [controls["담보"], controls["직접입력"]]
    assert clicks == [controls["조 회"]]
    assert writes == [
        (controls["조회시작일"], "2026-08-18", False),
        (controls["조회종료일"], "2026-08-18", False),
        (controls["감정서조회"], "", False),
        (controls["의뢰번호조회"], "", False),
    ]


@pytest.mark.parametrize(
    ("start", "end"),
    [("2026/08/18", "2026-08-18"), ("2026-08-19", "2026-08-18")],
)
def test_query_documents_rejects_invalid_range(start, end):
    with pytest.raises(navigate.NavigationError):
        navigate.query_documents(navigate.Session(FakeMain()), start=start, end=end)


def test_form_norm_zero_padding_and_decimals():
    from bankon.ui.form import _norm
    assert _norm("0356") == _norm("356")
    assert _norm("4,227.40") == _norm("4227.4")
    assert _norm("0000") == "0"
    assert _norm("경기도  안성시") == _norm("경기도 안성시")   # 공백은 비교에서 무시(2026-08-26)
    assert _norm("100-025-471640") == "100-025-471640"
