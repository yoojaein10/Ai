import json
from datetime import date
from decimal import Decimal

import pytest

from app.core.security import create_access_token, hash_password
from app.db.models import (
    CompEvalBoss,
    Employee,
    EvalApprover,
    EvalComprehensive,
    EvalRound,
    EvalSetting,
    MultiEvalIndicator,
    MultiEvalResult,
    PerfEvalResult,
    Role,
    User,
    UserRole,
)


def _make_user(db_session, login_id: str, emp_no: str, role_code: str = "EMPLOYEE") -> User:
    role = db_session.query(Role).filter(Role.code == role_code).first()
    if role is None:
        role = Role(code=role_code, name=role_code)
        db_session.add(role)
        db_session.flush()
    emp = Employee(emp_no=emp_no, name_ko=login_id, hire_date=date(2021, 1, 1))
    db_session.add(emp)
    db_session.flush()
    user = User(
        login_id=login_id,
        password_hash=hash_password("password123"),
        is_active=True,
        employee_id=emp.id,
    )
    db_session.add(user)
    db_session.flush()
    db_session.add(UserRole(user_id=user.id, role_id=role.id))
    db_session.commit()
    db_session.refresh(user)
    return user


def _headers(user: User, role: str = "EMPLOYEE") -> dict:
    token = create_access_token(str(user.id), extra={"roles": [role]})
    return {"Authorization": f"Bearer {token}"}


def _seed_round(db_session, year: int = 2026) -> EvalRound:
    r = EvalRound(year=year, name=f"{year}-종합", status="IN_PROGRESS")
    db_session.add(r)
    db_session.commit()
    db_session.refresh(r)
    return r


def _seed_setting(
    db_session,
    year: int,
    weight: dict | None = None,
    criteria: list[dict] | None = None,
) -> EvalSetting:
    s = EvalSetting(
        year=year,
        weight_config=json.dumps(weight) if weight else None,
        grade_criteria=json.dumps(criteria) if criteria else None,
    )
    db_session.add(s)
    db_session.commit()
    return s


def _seed_scores(db_session, emp_id: int, round_id: int, perf, comp, multi):
    """perf 90, comp 80, multi 70 같은 평균 점수를 만들기 위해 단일 행만 삽입."""
    if perf is not None:
        db_session.add(
            PerfEvalResult(
                emp_id=emp_id,
                round_id=round_id,
                evaluator_id=emp_id,
                score=Decimal(str(perf)),
                grade="A",
            )
        )
    if comp is not None:
        # CompEvalBoss.score 는 Integer (1~5). 평균 점수 모형을 맞추기 위해 직접 score=comp 대입.
        db_session.add(
            CompEvalBoss(
                evaluatee_id=emp_id,
                evaluator_id=emp_id,
                round_id=round_id,
                indicator_id=1,
                score=int(comp),
            )
        )
    if multi is not None:
        # MultiEvalResult 는 indicator_id FK 가 있지만 SQLite 테스트라 없는 indicator 도 허용됨.
        # 안전하게 indicator 행을 만든다.
        ind = MultiEvalIndicator(round_id=round_id, name="X", max_score=5)
        db_session.add(ind)
        db_session.flush()
        db_session.add(
            MultiEvalResult(
                round_id=round_id,
                evaluatee_id=emp_id,
                indicator_id=ind.id,
                avg_score=Decimal(str(multi)),
                response_count=3,
            )
        )
    db_session.commit()


@pytest.fixture
def admin_with_emp(db_session, admin_user):
    """기존 admin_user 에 employee 를 매핑."""
    emp = Employee(emp_no="ADM00001", name_ko="admin", hire_date=date(2020, 1, 1))
    db_session.add(emp)
    db_session.flush()
    admin_user.employee_id = emp.id
    db_session.commit()
    db_session.refresh(admin_user)
    return admin_user


def test_calculate_weight_must_sum_to_100(client, auth_headers, db_session):
    r = _seed_round(db_session)
    _seed_setting(db_session, r.year, weight={"perf": 50, "comp": 30, "multi": 30})
    resp = client.post(
        "/api/v1/eval/comprehensive/calculate",
        json={"round_id": r.id},
        headers=auth_headers,
    )
    assert resp.status_code == 400
    assert "100" in resp.json()["detail"]


def test_calculate_assigns_grade_at_boundary(client, auth_headers, db_session, admin_with_emp):
    r = _seed_round(db_session)
    _seed_setting(
        db_session,
        r.year,
        weight={"perf": 100, "comp": 0, "multi": 0},
        criteria=[
            {"grade": "S", "min": 90, "max": 100},
            {"grade": "A", "min": 80, "max": 90},
            {"grade": "B", "min": 0, "max": 80},
        ],
    )
    emp = admin_with_emp.employee_id
    db_session.add(
        EvalApprover(
            round_id=r.id, evaluatee_id=emp, evaluator_id=emp, eval_type="PERF"
        )
    )
    db_session.commit()
    _seed_scores(db_session, emp, r.id, perf=90, comp=None, multi=None)

    resp = client.post(
        "/api/v1/eval/comprehensive/calculate",
        json={"round_id": r.id},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    row = (
        db_session.query(EvalComprehensive)
        .filter(EvalComprehensive.round_id == r.id, EvalComprehensive.emp_id == emp)
        .first()
    )
    assert row is not None
    assert float(row.total_score) == 90.0
    # 90 은 S(90~100 inclusive 상한) 구간
    assert row.original_grade == "S"
    assert row.final_grade == "S"
    assert row.is_adjusted is False


def test_calculate_total_uses_weights(client, auth_headers, db_session, admin_with_emp):
    r = _seed_round(db_session)
    _seed_setting(
        db_session,
        r.year,
        weight={"perf": 50, "comp": 30, "multi": 20},
        criteria=[
            {"grade": "S", "min": 90, "max": 100},
            {"grade": "A", "min": 80, "max": 90},
            {"grade": "B", "min": 0, "max": 80},
        ],
    )
    emp = admin_with_emp.employee_id
    db_session.add(
        EvalApprover(
            round_id=r.id, evaluatee_id=emp, evaluator_id=emp, eval_type="PERF"
        )
    )
    db_session.commit()
    # perf 100, comp 5(*1=5점 척도 내 만점이지만 종합엔 그대로 사용), multi 5
    # total = (100*50 + 5*30 + 5*20)/100 = 52.5 → "B"
    _seed_scores(db_session, emp, r.id, perf=100, comp=5, multi=5)

    client.post(
        "/api/v1/eval/comprehensive/calculate",
        json={"round_id": r.id},
        headers=auth_headers,
    )
    row = (
        db_session.query(EvalComprehensive)
        .filter(EvalComprehensive.round_id == r.id, EvalComprehensive.emp_id == emp)
        .first()
    )
    assert float(row.total_score) == 52.5
    assert row.original_grade == "B"


def test_manual_adjust_requires_reason(client, auth_headers, db_session, admin_with_emp):
    r = _seed_round(db_session)
    _seed_setting(db_session, r.year)
    emp = admin_with_emp.employee_id
    db_session.add(
        EvalComprehensive(
            emp_id=emp,
            round_id=r.id,
            total_score=Decimal("85"),
            original_grade="A",
            final_grade="A",
            is_adjusted=False,
        )
    )
    db_session.commit()
    comp_id = (
        db_session.query(EvalComprehensive.id)
        .filter(EvalComprehensive.emp_id == emp)
        .scalar()
    )

    # 빈 reason 은 422 (Pydantic min_length=1)
    resp = client.put(
        f"/api/v1/eval/comprehensive/{comp_id}/grade",
        json={"new_grade": "S", "adjusted_reason": ""},
        headers=auth_headers,
    )
    assert resp.status_code == 422


def test_manual_adjust_preserves_original_grade(
    client, auth_headers, db_session, admin_with_emp
):
    r = _seed_round(db_session)
    _seed_setting(db_session, r.year)
    emp = admin_with_emp.employee_id
    db_session.add(
        EvalComprehensive(
            emp_id=emp,
            round_id=r.id,
            total_score=Decimal("85"),
            original_grade="A",
            final_grade="A",
            is_adjusted=False,
        )
    )
    db_session.commit()
    comp_id = (
        db_session.query(EvalComprehensive.id)
        .filter(EvalComprehensive.emp_id == emp)
        .scalar()
    )

    resp = client.put(
        f"/api/v1/eval/comprehensive/{comp_id}/grade",
        json={"new_grade": "S", "adjusted_reason": "공정성 보정"},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["original_grade"] == "A"
    assert body["final_grade"] == "S"
    assert body["is_adjusted"] is True
    assert body["adjusted_reason"] == "공정성 보정"


def test_employee_only_sees_own_row(client, db_session, admin_with_emp):
    r = _seed_round(db_session)
    _seed_setting(db_session, r.year)
    other = _make_user(db_session, "other_emp", "OE000001")
    # admin_with_emp 행 + other 행 두 개
    db_session.add(
        EvalComprehensive(
            emp_id=admin_with_emp.employee_id,
            round_id=r.id,
            total_score=Decimal("80"),
            original_grade="A",
            final_grade="A",
            is_adjusted=False,
        )
    )
    db_session.add(
        EvalComprehensive(
            emp_id=other.employee_id,
            round_id=r.id,
            total_score=Decimal("70"),
            original_grade="B",
            final_grade="B",
            is_adjusted=False,
        )
    )
    db_session.commit()

    resp = client.get(
        f"/api/v1/eval/comprehensive?round_id={r.id}",
        headers=_headers(other),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["emp_id"] == other.employee_id
