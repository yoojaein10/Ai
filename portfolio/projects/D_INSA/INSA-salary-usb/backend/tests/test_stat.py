from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.db.models import Department, EduCourse, EduRecord, Employee
from app.services import stat as svc


# ── helpers ───────────────────────────────────────────────


@pytest.fixture
def dept_a(db_session):
    d = Department(code="D-A", name="개발팀")
    db_session.add(d)
    db_session.commit()
    return d


@pytest.fixture
def dept_b(db_session):
    d = Department(code="D-B", name="영업팀")
    db_session.add(d)
    db_session.commit()
    return d


def _make_emp(
    db,
    *,
    emp_no: str,
    name: str = "홍길동",
    gender: str | None = "M",
    birth: date | None = None,
    hire: date | None = None,
    dept_id: int | None = None,
    rank: str | None = "사원",
    status: str = "재직",
    resign: date | None = None,
):
    emp = Employee(
        emp_no=emp_no,
        name_ko=name,
        gender=gender,
        birth_date=birth,
        hire_date=hire or date(2020, 1, 1),
        dept_id=dept_id,
        job_rank=rank,
        emp_status=status,
        resign_date=resign,
    )
    db.add(emp)
    db.commit()
    db.refresh(emp)
    return emp


# ── Workforce: pure helpers ───────────────────────────────


def test_age_handles_none():
    assert svc._age(None) is None


def test_age_calculates_birthday_passed():
    today = date.today()
    birth = date(today.year - 30, 1, 1)
    age = svc._age(birth)
    assert 29 <= age <= 30


def test_age_group_buckets():
    assert svc._age_group(None) == "미상"
    assert svc._age_group(20) == "20대 이하"
    assert svc._age_group(30) == "30대"
    assert svc._age_group(45) == "40대"
    assert svc._age_group(55) == "50대"
    assert svc._age_group(70) == "60대+"


def test_tenure_group_buckets():
    today = date.today()
    assert svc._tenure_group(today - timedelta(days=100)) == "1년 미만"
    assert svc._tenure_group(today - timedelta(days=500)) == "1-3년"
    assert svc._tenure_group(today - timedelta(days=4 * 365)) == "3-5년"
    assert svc._tenure_group(today - timedelta(days=8 * 365)) == "5-10년"
    assert svc._tenure_group(today - timedelta(days=12 * 365)) == "10년+"


# ── Workforce: get_workforce ──────────────────────────────


def test_workforce_empty_db(db_session):
    res = svc.get_workforce(db_session)
    assert res.total == 0
    assert res.male == 0
    assert res.female == 0
    assert res.unknown_gender == 0
    assert res.by_dept == []
    assert res.by_rank == []
    assert len(res.trend_12m) == 12


def test_workforce_excludes_resigned(db_session, dept_a):
    _make_emp(db_session, emp_no="A1", dept_id=dept_a.id, gender="M")
    _make_emp(
        db_session, emp_no="A2", dept_id=dept_a.id, gender="F",
        status="퇴직", resign=date.today() - timedelta(days=30),
    )
    res = svc.get_workforce(db_session)
    assert res.total == 1
    assert res.male == 1
    assert res.female == 0


def test_workforce_gender_breakdown(db_session, dept_a):
    _make_emp(db_session, emp_no="M1", dept_id=dept_a.id, gender="M")
    _make_emp(db_session, emp_no="M2", dept_id=dept_a.id, gender="M")
    _make_emp(db_session, emp_no="F1", dept_id=dept_a.id, gender="F")
    _make_emp(db_session, emp_no="U1", dept_id=dept_a.id, gender=None)
    res = svc.get_workforce(db_session)
    assert res.total == 4
    assert res.male == 2
    assert res.female == 1
    assert res.unknown_gender == 1


def test_workforce_by_dept_includes_unassigned(db_session, dept_a):
    _make_emp(db_session, emp_no="X1", dept_id=dept_a.id, gender="M")
    _make_emp(db_session, emp_no="X2", dept_id=None, gender="F")
    res = svc.get_workforce(db_session)
    names = {row.dept_name for row in res.by_dept}
    assert "개발팀" in names
    assert "미지정" in names


def test_workforce_by_dept_sorted_desc(db_session, dept_a, dept_b):
    for i in range(3):
        _make_emp(db_session, emp_no=f"A{i}", dept_id=dept_a.id, gender="M")
    _make_emp(db_session, emp_no="B0", dept_id=dept_b.id, gender="F")
    res = svc.get_workforce(db_session)
    counts = [row.count for row in res.by_dept]
    assert counts == sorted(counts, reverse=True)
    assert res.by_dept[0].count == 3


def test_workforce_by_rank_uses_rank_order(db_session, dept_a):
    _make_emp(db_session, emp_no="R1", dept_id=dept_a.id, rank="부장")
    _make_emp(db_session, emp_no="R2", dept_id=dept_a.id, rank="사원")
    _make_emp(db_session, emp_no="R3", dept_id=dept_a.id, rank="과장")
    res = svc.get_workforce(db_session)
    ranks = [row.rank for row in res.by_rank]
    assert ranks.index("사원") < ranks.index("과장") < ranks.index("부장")


def test_workforce_unknown_rank_assigned_to_미지정(db_session, dept_a):
    _make_emp(db_session, emp_no="N1", dept_id=dept_a.id, rank=None)
    res = svc.get_workforce(db_session)
    ranks = [row.rank for row in res.by_rank]
    assert "미지정" in ranks


def test_workforce_age_groups_only_positive(db_session, dept_a):
    today = date.today()
    _make_emp(
        db_session, emp_no="Y1", dept_id=dept_a.id,
        birth=date(today.year - 25, 1, 1),
    )
    _make_emp(
        db_session, emp_no="Y2", dept_id=dept_a.id,
        birth=date(today.year - 35, 1, 1),
    )
    res = svc.get_workforce(db_session)
    groups = [row.group for row in res.by_age_group]
    assert "20대 이하" in groups
    assert "30대" in groups
    assert "40대" not in groups


def test_workforce_trend_12_buckets(db_session, dept_a):
    today = date.today()
    _make_emp(
        db_session, emp_no="H1", dept_id=dept_a.id,
        hire=date(today.year, today.month, 1),
    )
    res = svc.get_workforce(db_session)
    assert len(res.trend_12m) == 12
    last = res.trend_12m[-1]
    assert last.year == today.year
    assert last.month == today.month
    assert last.hired >= 1


def test_workforce_trend_resigned_counted(db_session, dept_a):
    today = date.today()
    _make_emp(
        db_session, emp_no="R1", dept_id=dept_a.id, status="퇴직",
        hire=date(today.year - 1, today.month, 1),
        resign=date(today.year, today.month, 15),
    )
    res = svc.get_workforce(db_session)
    last = res.trend_12m[-1]
    assert last.resigned >= 1


# ── Education ─────────────────────────────────────────────


@pytest.fixture
def course_법정(db_session):
    c = EduCourse(
        course_code="C-LAW", course_name="법정필수",
        category="법정", hours=Decimal("8.0"),
    )
    db_session.add(c)
    db_session.commit()
    return c


@pytest.fixture
def course_직무(db_session):
    c = EduCourse(
        course_code="C-JOB", course_name="직무교육",
        category="직무", hours=Decimal("4.0"),
    )
    db_session.add(c)
    db_session.commit()
    return c


def _make_record(
    db, *, emp_id, course_id=None, year=2025, month=6,
    hours="8.0", result="수료", end_date=None,
):
    rec = EduRecord(
        employee_id=emp_id,
        course_id=course_id,
        course_name_snapshot="snap",
        start_date=date(year, month, 1),
        end_date=end_date if end_date is not None else date(year, month, 5),
        hours=Decimal(hours),
        result=result,
    )
    db.add(rec)
    db.commit()
    return rec


def test_education_empty_returns_zero(db_session):
    res = svc.get_education(db_session, year=2025)
    assert res.total_records == 0
    assert res.total_hours == 0.0
    assert res.completed == 0
    assert res.completion_rate == 0.0
    assert len(res.by_month) == 12
    assert all(row.count == 0 for row in res.by_month)


def test_education_filters_by_year(db_session, dept_a, course_법정):
    emp = _make_emp(db_session, emp_no="E1", dept_id=dept_a.id)
    _make_record(db_session, emp_id=emp.id, course_id=course_법정.id, year=2025)
    _make_record(db_session, emp_id=emp.id, course_id=course_법정.id, year=2024)
    res = svc.get_education(db_session, year=2025)
    assert res.total_records == 1


def test_education_completion_rate(db_session, dept_a, course_법정):
    emp1 = _make_emp(db_session, emp_no="E1", dept_id=dept_a.id)
    emp2 = _make_emp(db_session, emp_no="E2", dept_id=dept_a.id)
    emp3 = _make_emp(db_session, emp_no="E3", dept_id=dept_a.id)
    _make_record(db_session, emp_id=emp1.id, course_id=course_법정.id, result="수료")
    _make_record(db_session, emp_id=emp2.id, course_id=course_법정.id, result="수료")
    _make_record(db_session, emp_id=emp3.id, course_id=course_법정.id, result="미수료")
    res = svc.get_education(db_session, year=2025)
    assert res.completed == 2
    assert res.completion_rate == round(2 / 3 * 100, 1)


def test_education_total_hours_sum(db_session, dept_a, course_법정):
    emp = _make_emp(db_session, emp_no="E1", dept_id=dept_a.id)
    _make_record(db_session, emp_id=emp.id, course_id=course_법정.id, hours="8.0")
    _make_record(db_session, emp_id=emp.id, course_id=course_법정.id, hours="4.5")
    res = svc.get_education(db_session, year=2025)
    assert res.total_hours == 12.5


def test_education_by_category(db_session, dept_a, course_법정, course_직무):
    emp = _make_emp(db_session, emp_no="E1", dept_id=dept_a.id)
    _make_record(db_session, emp_id=emp.id, course_id=course_법정.id, hours="8.0")
    _make_record(db_session, emp_id=emp.id, course_id=course_직무.id, hours="4.0")
    res = svc.get_education(db_session, year=2025)
    cats = {row.category: row for row in res.by_category}
    assert cats["법정"].total_hours == 8.0
    assert cats["직무"].total_hours == 4.0


def test_education_no_course_assigns_미지정(db_session, dept_a):
    emp = _make_emp(db_session, emp_no="E1", dept_id=dept_a.id)
    _make_record(db_session, emp_id=emp.id, course_id=None, hours="2.0")
    res = svc.get_education(db_session, year=2025)
    cats = [row.category for row in res.by_category]
    assert "미지정" in cats


def test_education_by_month_counts(db_session, dept_a, course_법정):
    emp = _make_emp(db_session, emp_no="E1", dept_id=dept_a.id)
    _make_record(db_session, emp_id=emp.id, course_id=course_법정.id, year=2025, month=3)
    _make_record(db_session, emp_id=emp.id, course_id=course_법정.id, year=2025, month=3)
    _make_record(db_session, emp_id=emp.id, course_id=course_법정.id, year=2025, month=7)
    res = svc.get_education(db_session, year=2025)
    by_month = {row.month: row.count for row in res.by_month}
    assert by_month[3] == 2
    assert by_month[7] == 1
    assert by_month[1] == 0


def test_education_by_dept_avg_hours(db_session, dept_a, course_법정):
    emp1 = _make_emp(db_session, emp_no="E1", dept_id=dept_a.id)
    emp2 = _make_emp(db_session, emp_no="E2", dept_id=dept_a.id)
    _make_record(db_session, emp_id=emp1.id, course_id=course_법정.id, hours="8.0")
    _make_record(db_session, emp_id=emp2.id, course_id=course_법정.id, hours="4.0")
    res = svc.get_education(db_session, year=2025)
    rows = {row.dept_name: row for row in res.by_dept}
    assert rows["개발팀"].record_count == 2
    assert rows["개발팀"].emp_count == 2
    assert rows["개발팀"].total_hours == 12.0
    assert rows["개발팀"].avg_hours_per_emp == 6.0


def test_education_incomplete_lists_active_without_수료(db_session, dept_a, course_법정):
    emp_done = _make_emp(db_session, emp_no="E1", dept_id=dept_a.id)
    emp_miss = _make_emp(db_session, emp_no="E2", dept_id=dept_a.id)
    _make_emp(
        db_session, emp_no="E3", dept_id=dept_a.id,
        status="퇴직", resign=date(2025, 1, 1),
    )
    _make_record(db_session, emp_id=emp_done.id, course_id=course_법정.id, result="수료")
    res = svc.get_education(db_session, year=2025)
    emp_nos = {row.emp_no for row in res.incomplete_employees}
    assert "E2" in emp_nos
    assert "E1" not in emp_nos
    assert "E3" not in emp_nos


def test_education_incomplete_capped_at_100(db_session, dept_a):
    for i in range(110):
        _make_emp(db_session, emp_no=f"E{i:03d}", dept_id=dept_a.id)
    res = svc.get_education(db_session, year=2025)
    assert len(res.incomplete_employees) == 100
