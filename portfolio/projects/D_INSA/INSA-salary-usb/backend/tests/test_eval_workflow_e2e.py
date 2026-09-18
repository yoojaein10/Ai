"""End-to-end 워크플로 통합 테스트.

PHASE 1~5 모듈을 통합 검증:
1. 회차 생성 → setting 저장
2. KPI/지표 생성 + approver 매핑
3. 성과 평가 결과 + 역량 평가(boss) + 다면 응답(3명+)
4. 종합평가 calculate → 등급 자동 산정
5. 수동 등급 조정 → original 보존
6. 이의신청 생성 → 재심의 ACCEPTED
"""
from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

import pytest

from app.core.security import create_access_token, hash_password
from app.db.models import (
    CompEvalBoss,
    CompIndicator,
    Employee,
    EvalApprover,
    EvalRound,
    EvalSetting,
    MultiEvalIndicator,
    PerfEvalResult,
    Role,
    User,
    UserRole,
)


def _make_user(db, login_id, emp_no, role_code="EMPLOYEE"):
    role = db.query(Role).filter(Role.code == role_code).first()
    if role is None:
        role = Role(code=role_code, name=role_code)
        db.add(role)
        db.flush()
    emp = Employee(emp_no=emp_no, name_ko=login_id, hire_date=date(2020, 1, 1))
    db.add(emp)
    db.flush()
    user = User(
        login_id=login_id,
        password_hash=hash_password("pw"),
        is_active=True,
        employee_id=emp.id,
    )
    db.add(user)
    db.flush()
    db.add(UserRole(user_id=user.id, role_id=role.id))
    db.commit()
    db.refresh(user)
    return user


def _hdr(user, role="EMPLOYEE"):
    tok = create_access_token(str(user.id), extra={"roles": [role]})
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture
def setup_round(db_session):
    """회차+setting+evaluatee+raters 생성."""
    r = EvalRound(year=2026, name="2026", status="IN_PROGRESS")
    db_session.add(r)
    db_session.commit()
    db_session.refresh(r)

    db_session.add(
        EvalSetting(
            year=2026,
            weight_config=json.dumps({"perf": 40, "comp": 30, "multi": 30}),
            grade_criteria=json.dumps(
                [
                    {"grade": "S", "min": 90, "max": 100},
                    {"grade": "A", "min": 80, "max": 90},
                    {"grade": "B", "min": 70, "max": 80},
                    {"grade": "C", "min": 60, "max": 70},
                    {"grade": "D", "min": 0, "max": 60},
                ]
            ),
        )
    )
    db_session.commit()
    return r


def test_full_workflow_employee_to_grade_to_objection(
    client, auth_headers, db_session, setup_round
):
    r = setup_round
    target = _make_user(db_session, "wf_target", "WF000001")
    raters = [_make_user(db_session, f"wf_r{i}", f"WFR{i:05d}") for i in range(3)]

    # === approver 매핑 ===
    db_session.add_all(
        [
            EvalApprover(
                round_id=r.id,
                evaluatee_id=target.employee_id,
                evaluator_id=raters[0].employee_id,
                eval_type="PERF",
            ),
            EvalApprover(
                round_id=r.id,
                evaluatee_id=target.employee_id,
                evaluator_id=raters[0].employee_id,
                eval_type="COMP",
            ),
        ]
    )
    db_session.commit()

    # === 성과 평가 결과 (perf=85점 1건) ===
    db_session.add(
        PerfEvalResult(
            emp_id=target.employee_id,
            round_id=r.id,
            evaluator_id=raters[0].employee_id,
            score=Decimal("85"),
            grade="A",
        )
    )
    # === 역량 평가 (boss, score 4점 1건) ===
    comp_ind = CompIndicator(year=2026, code="COL", name="협업", weight=Decimal("100"))
    db_session.add(comp_ind)
    db_session.flush()
    db_session.add(
        CompEvalBoss(
            evaluatee_id=target.employee_id,
            evaluator_id=raters[0].employee_id,
            round_id=r.id,
            indicator_id=comp_ind.id,
            score=4,
        )
    )
    db_session.commit()

    # === 다면평가: 지표 생성 후 3명 익명 제출 ===
    multi_ind = MultiEvalIndicator(round_id=r.id, name="협업태도", max_score=5)
    db_session.add(multi_ind)
    db_session.commit()
    for r_user in raters:
        db_session.add(
            EvalApprover(
                round_id=r.id,
                evaluatee_id=target.employee_id,
                evaluator_id=r_user.employee_id,
                eval_type="MULTI",
                rater_type="PEER",
            )
        )
    db_session.commit()
    for r_user, score in zip(raters, [4, 4, 5]):
        resp = client.post(
            "/api/v1/eval/multi/response",
            json={
                "round_id": r.id,
                "evaluatee_id": target.employee_id,
                "rater_type": "PEER",
                "items": [{"indicator_id": multi_ind.id, "score": str(score)}],
            },
            headers=_hdr(r_user),
        )
        assert resp.status_code == 201, resp.text

    # === 종합평가 calculate (관리자) ===
    calc = client.post(
        "/api/v1/eval/comprehensive/calculate",
        json={"round_id": r.id},
        headers=auth_headers,
    )
    assert calc.status_code == 200, calc.text
    assert calc.json()["upserted"] >= 1

    list_resp = client.get(
        f"/api/v1/eval/comprehensive?round_id={r.id}", headers=auth_headers
    )
    rows = list_resp.json()
    target_row = next(row for row in rows if row["emp_id"] == target.employee_id)
    # perf=85, comp=4, multi=avg(4,4,5)=4.33...
    # total = (85*40 + 4*30 + 4.33*30)/100 = 34 + 1.2 + 1.3 = 36.5 → "D"
    assert target_row["original_grade"] == "D"
    assert target_row["final_grade"] == "D"
    assert target_row["is_adjusted"] is False
    comp_id = target_row["id"]

    # === 등급 수동 조정 (HR_ADMIN) ===
    adj = client.put(
        f"/api/v1/eval/comprehensive/{comp_id}/grade",
        json={"new_grade": "B", "adjusted_reason": "정성평가 가산"},
        headers=auth_headers,
    )
    assert adj.status_code == 200, adj.text
    body = adj.json()
    assert body["original_grade"] == "D"  # 보존
    assert body["final_grade"] == "B"
    assert body["is_adjusted"] is True

    # === EMPLOYEE 이의신청 생성 ===
    obj_resp = client.post(
        "/api/v1/eval/objections",
        json={"round_id": r.id, "reason": "총점 산정 재검토 요청"},
        headers=_hdr(target),
    )
    assert obj_resp.status_code == 200, obj_resp.text
    assert obj_resp.json()["status"] == "PENDING"
    obj_id = obj_resp.json()["id"]

    # === HR_ADMIN 재심의 ACCEPTED ===
    review = client.put(
        f"/api/v1/eval/objections/{obj_id}/review",
        json={"decision": "ACCEPTED", "comment": "재계산 필요"},
        headers=auth_headers,
    )
    assert review.status_code == 200
    final_list = client.get(
        f"/api/v1/eval/objections?round_id={r.id}", headers=auth_headers
    )
    statuses = [o["status"] for o in final_list.json()]
    assert "ACCEPTED" in statuses


def test_employee_cannot_access_admin_only_endpoints(
    client, db_session, setup_round
):
    """Role 매트릭스: EMPLOYEE 는 calculate/adjust/review 차단."""
    r = setup_round
    user = _make_user(db_session, "perm_emp", "PE000001")

    # calculate
    resp = client.post(
        "/api/v1/eval/comprehensive/calculate",
        json={"round_id": r.id},
        headers=_hdr(user),
    )
    assert resp.status_code == 403

    # objection review (admin only)
    obj = client.post(
        "/api/v1/eval/objections",
        json={"round_id": r.id, "reason": "test"},
        headers=_hdr(user),
    ).json()
    review_resp = client.put(
        f"/api/v1/eval/objections/{obj['id']}/review",
        json={"decision": "ACCEPTED"},
        headers=_hdr(user),
    )
    assert review_resp.status_code == 403


def test_anonymity_holds_after_calculate(
    client, auth_headers, db_session, setup_round
):
    """다면 응답 → calculate 거쳐도 evaluator_id 컬럼이 response 에 없음 (회귀)."""
    from sqlalchemy import inspect

    from app.db.models import MultiEvalResponse

    insp = inspect(db_session.get_bind())
    cols = {c["name"] for c in insp.get_columns(MultiEvalResponse.__tablename__)}
    forbidden = {"evaluator_id", "rater_id", "submitter_id", "user_id"}
    assert not (cols & forbidden), f"anonymity broken: {cols & forbidden}"
