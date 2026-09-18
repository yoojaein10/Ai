"""2715 국민 구분건물 발송본 정정 반영(2026-08-31): 호별 용도 우선 물건종류·동 칸 지움·점검항목 콤보 계획."""
from bankon.mapping import kookmin
from bankon.ui import form


def test_unit_object_type_ignores_spaces_in_unit_use():
    # 호별 표 용도 '제2종근린 생활시설 (청소년 게임제공업소)' → 집합상가-근린 (건물 전체 '업무시설(사무소), 근린생활시설'은 빌딩)
    assert kookmin.unit_object_type("제2종근린 생활시설 (청소년 게임제공업소)") == "집합상가-근린(점포)상가"
    assert kookmin.unit_object_type("업무시설(사무소), 근린생활시설") == "빌딩(사무실)"


def test_plan_checklist_only_differences():
    answers = tuple(["아니오"] * 19 + ["예"])
    plan = kookmin.plan_checklist(["아니오"] * 20, answers)
    assert len(plan) == 20
    assert [p for p in plan if p[1] != "일치"] == [(19, "선택(덮어씀)", "예", "아니오")]
    assert kookmin.plan_checklist([""] * 20, answers)[19] == (19, "선택", "예", "")
    assert kookmin.plan_checklist(["아니오"] * 19, answers) == []      # 콤보 수 다르면 안 건드림


def test_clear_fields_only_building_name_fragment(monkeypatch):
    class Ctl:
        pass

    state = {"current": "두산더랜드파", "written": []}
    monkeypatch.setattr(form, "plan_field", lambda f, label, v: ("덮어씀", state["current"], Ctl()))
    monkeypatch.setattr(form.driver, "set_text", lambda c, v: state["written"].append(v))

    r = form.clear_fields(object(), {"물건:동": "두산더랜드파크"}, live=True)
    assert (r[0].action, r[0].wrote) == ("지움", True) and state["written"] == [""]

    state["current"] = "103"                                   # 사람이 넣은 실제 동 → 유지
    r = form.clear_fields(object(), {"물건:동": "두산더랜드파크"}, live=True)
    assert (r[0].action, r[0].wrote) == ("유지", False)

    state["current"] = ""
    assert form.clear_fields(object(), {"물건:동": "두산더랜드파크"})[0].action == "일치"

    state["current"] = "두산더랜드파"
    assert form.clear_fields(object(), {"물건:동": "두산더랜드파크"}, live=False)[0].wrote is False   # 드라이런
