"""form.is_blank(0/빈값 가드)·라벨@N 해석."""
from bankon.ui import form


def test_is_blank_zero_and_empty():
    assert form.is_blank(None) and form.is_blank("") and form.is_blank("  ")
    assert form.is_blank(0) and form.is_blank("0") and form.is_blank("0.00") and form.is_blank("0,000")
    assert not form.is_blank("356") and not form.is_blank("0356") and not form.is_blank("경기도")
    assert not form.is_blank("2026-08-20")


def test_label_index_syntax(monkeypatch):
    seen = {}

    def fake_find(handle, name, class_name=None, index=0, region=None):
        seen["name"], seen["index"] = name, index
        return None

    monkeypatch.setattr(form.driver, "find_by_label", fake_find)

    class F:
        handle = 1

    assert form.plan_field(F(), "평가사명1@2", "홍현석")[0] == "미발견"
    assert seen == {"name": "평가사명1", "index": 1}
    form.plan_field(F(), "본번지", "356")
    assert seen == {"name": "본번지", "index": 0}


def test_plan_field_treats_prefilled_zero_as_blank(monkeypatch):
    """은행 폼 선입력 '0'/'0.00' 은 '채움'(기본 모드에서도 쓴다) — 2703·2715 LIVE 미기록 회귀(2026-08-31)."""
    class Ctl:
        class element_info:
            class_name = "TcxCustomInnerTextEdit"

    state = {"current": "0"}
    monkeypatch.setattr(form.driver, "find_by_label", lambda *a, **k: Ctl())
    monkeypatch.setattr(form.driver, "editable", lambda c: c)
    monkeypatch.setattr(form.driver, "read", lambda c: state["current"])

    class F:
        handle = 1

    assert form.plan_field(F(), "감정평가(순)수수료", "1281200")[0] == "채움"
    state["current"] = "0.00"
    assert form.plan_field(F(), "세부:공부면적(전용면적)", "53.10")[0] == "채움"
    state["current"] = ""
    assert form.plan_field(F(), "세부:사정면적", "53.10")[0] == "채움"
    state["current"] = "1,281,200"
    assert form.plan_field(F(), "감정평가(순)수수료", "1281200")[0] == "일치"
    state["current"] = "5"
    assert form.plan_field(F(), "총층수/층수", "13")[0] == "덮어씀"
