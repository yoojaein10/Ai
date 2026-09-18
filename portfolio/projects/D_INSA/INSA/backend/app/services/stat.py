from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Optional

from sqlalchemy import and_, extract, func, or_, text
from sqlalchemy.orm import Session

from app.db.models import (
    Department,
    EduCourse,
    EduRecord,
    Employee,
)
from app.schemas.stat import (
    AttendanceStatDeptRow,
    AttendanceStatMonthRow,
    AttendanceStatResponse,
    AttendanceStatTopRow,
    EducationStatCategoryRow,
    EducationStatDeptRow,
    EducationStatIncompleteRow,
    EducationStatMonthRow,
    EducationStatResponse,
    WorkforceAgeGroupRow,
    WorkforceDeptRow,
    WorkforceRankRow,
    WorkforceStatResponse,
    WorkforceTenureRow,
    WorkforceTrendRow,
)


# ── Workforce ─────────────────────────────────────────────


def _age(birth: Optional[date]) -> Optional[int]:
    if birth is None:
        return None
    today = date.today()
    return (
        today.year - birth.year - ((today.month, today.day) < (birth.month, birth.day))
    )


def _age_group(age: Optional[int]) -> str:
    if age is None:
        return "미상"
    if age < 30:
        return "20대 이하"
    if age < 40:
        return "30대"
    if age < 50:
        return "40대"
    if age < 60:
        return "50대"
    return "60대+"


def _tenure_group(hire: date) -> str:
    days = (date.today() - hire).days
    years = days / 365.25
    if years < 1:
        return "1년 미만"
    if years < 3:
        return "1-3년"
    if years < 5:
        return "3-5년"
    if years < 10:
        return "5-10년"
    return "10년+"


_RANK_ORDER = ["사원", "대리", "과장", "차장", "부장", "이사", "상무", "전무"]
_AGE_ORDER = ["20대 이하", "30대", "40대", "50대", "60대+", "미상"]
_TENURE_ORDER = ["1년 미만", "1-3년", "3-5년", "5-10년", "10년+"]


def get_workforce(db: Session) -> WorkforceStatResponse:
    rows = (
        db.query(Employee, Department)
        .outerjoin(Department, Employee.dept_id == Department.id)
        .filter(Employee.emp_status != "퇴직")
        .all()
    )

    total = len(rows)
    male = female = unknown = 0
    dept_map: dict[tuple, dict] = {}
    rank_map: dict[str, int] = defaultdict(int)
    age_map: dict[str, int] = defaultdict(int)
    tenure_map: dict[str, int] = defaultdict(int)

    for emp, dept in rows:
        key = (dept.id if dept else None, dept.name if dept else "미지정")
        entry = dept_map.setdefault(key, {"count": 0, "male": 0, "female": 0})
        entry["count"] += 1
        if emp.gender == "M":
            entry["male"] += 1
            male += 1
        elif emp.gender == "F":
            entry["female"] += 1
            female += 1
        else:
            unknown += 1

        rank_map[emp.job_rank or "미지정"] += 1
        age_map[_age_group(_age(emp.birth_date))] += 1
        tenure_map[_tenure_group(emp.hire_date)] += 1

    by_dept = [
        WorkforceDeptRow(
            dept_id=k[0],
            dept_name=k[1],
            count=v["count"],
            male=v["male"],
            female=v["female"],
        )
        for k, v in sorted(dept_map.items(), key=lambda x: -x[1]["count"])
    ]

    def _rank_key(r: str) -> int:
        return _RANK_ORDER.index(r) if r in _RANK_ORDER else 99

    by_rank = [
        WorkforceRankRow(rank=r, count=c)
        for r, c in sorted(rank_map.items(), key=lambda x: _rank_key(x[0]))
    ]

    by_age_group = [
        WorkforceAgeGroupRow(group=g, count=age_map[g])
        for g in _AGE_ORDER
        if age_map.get(g, 0) > 0
    ]

    by_tenure = [
        WorkforceTenureRow(group=g, count=tenure_map[g])
        for g in _TENURE_ORDER
        if tenure_map.get(g, 0) > 0
    ]

    # Trend: 최근 12개월 입·퇴사
    today = date.today()
    first_of_month = date(today.year, today.month, 1)
    # start = 11 months before current
    year = first_of_month.year
    month = first_of_month.month
    for _ in range(11):
        month -= 1
        if month == 0:
            month = 12
            year -= 1
    trend_start = date(year, month, 1)

    hire_rows = (
        db.query(Employee.hire_date)
        .filter(Employee.hire_date >= trend_start)
        .all()
    )
    resign_rows = (
        db.query(Employee.resign_date)
        .filter(Employee.resign_date.isnot(None), Employee.resign_date >= trend_start)
        .all()
    )

    trend_map: dict[tuple[int, int], dict] = {}
    y, m = trend_start.year, trend_start.month
    for _ in range(12):
        trend_map[(y, m)] = {"hired": 0, "resigned": 0}
        m += 1
        if m == 13:
            m = 1
            y += 1

    for (d,) in hire_rows:
        if d is None:
            continue
        k = (d.year, d.month)
        if k in trend_map:
            trend_map[k]["hired"] += 1
    for (d,) in resign_rows:
        if d is None:
            continue
        k = (d.year, d.month)
        if k in trend_map:
            trend_map[k]["resigned"] += 1

    trend_12m = [
        WorkforceTrendRow(year=k[0], month=k[1], hired=v["hired"], resigned=v["resigned"])
        for k, v in sorted(trend_map.items())
    ]

    return WorkforceStatResponse(
        total=total,
        male=male,
        female=female,
        unknown_gender=unknown,
        by_dept=by_dept,
        by_rank=by_rank,
        by_age_group=by_age_group,
        by_tenure=by_tenure,
        trend_12m=trend_12m,
    )


# ── Attendance ────────────────────────────────────────────


def _minutes_between(first: Optional[str], last: Optional[str]) -> int:
    if not first or not last or first == last:
        return 0
    try:
        t1 = datetime.strptime(first, "%H%M%S")
        t2 = datetime.strptime(last, "%H%M%S")
    except ValueError:
        return 0
    delta = int((t2 - t1).total_seconds() // 60)
    return max(delta, 0)


def _is_half(bigo: Optional[str]) -> bool:
    if not bigo:
        return False
    return "반차" in bigo.replace(" ", "")


_LEAVE_GUBUNS = (
    "휴가",
    "공가",
    "특가",
    "NPL휴가",
    "병가",
    "가족돌봄",
    "기타휴가",
)


def get_attendance(
    att_db: Session, apw_db: Session, insa_db: Session, year: int
) -> AttendanceStatResponse:
    start = date(year, 1, 1)
    end = date(year, 12, 31)
    next_year = date(year + 1, 1, 1)
    start_str = start.strftime("%Y%m%d")
    end_str = end.strftime("%Y%m%d")

    # 1. tenter — 일자×직원 집계
    tenter_rows = att_db.execute(
        text(
            """
            SELECT e_idno,
                   e_date,
                   MIN(e_time) AS first_t,
                   MAX(e_time) AS last_t
            FROM tenter
            WHERE e_date BETWEEN :s AND :e
              AND e_id <> -1
              AND e_idno IS NOT NULL AND e_idno <> ''
            GROUP BY e_idno, e_date
            """
        ),
        {"s": start_str, "e": end_str},
    ).mappings().all()

    month_data: dict[int, dict] = defaultdict(
        lambda: {"work_days": 0, "work_minutes": 0, "emps": set()}
    )
    emp_work_minutes: dict[str, int] = defaultdict(int)

    for r in tenter_rows:
        m = int(r["e_date"][4:6])
        minutes = _minutes_between(r["first_t"], r["last_t"])
        entry = month_data[m]
        entry["work_days"] += 1
        entry["work_minutes"] += minutes
        entry["emps"].add(r["e_idno"])
        emp_work_minutes[r["e_idno"]] += minutes

    # 2. APW_IW_SCHEDULE — 휴가
    from sqlalchemy import bindparam

    sched_stmt = text(
        """
        SELECT [date] AS d, name, gubun, Bigo
        FROM APW_IW_SCHEDULE
        WHERE [date] >= :s AND [date] < :ne
          AND gubun IN :gubuns
        """
    ).bindparams(bindparam("gubuns", expanding=True))
    sched_rows = apw_db.execute(
        sched_stmt,
        {"s": start, "ne": next_year, "gubuns": list(_LEAVE_GUBUNS)},
    ).mappings().all()

    leave_month: dict[int, float] = defaultdict(float)
    leave_by_name: dict[str, float] = defaultdict(float)
    for r in sched_rows:
        d_val = r["d"]
        d = d_val.date() if isinstance(d_val, datetime) else d_val
        mult = 0.5 if _is_half(r["Bigo"]) else 1.0
        leave_month[d.month] += mult
        name = (r["name"] or "").strip()
        if name:
            leave_by_name[name] += mult

    by_month: list[AttendanceStatMonthRow] = []
    for m in range(1, 13):
        e = month_data.get(m)
        emp_count = len(e["emps"]) if e else 0
        work_minutes = e["work_minutes"] if e else 0
        avg_hours = (
            round(work_minutes / 60.0 / emp_count, 1) if emp_count else 0.0
        )
        by_month.append(
            AttendanceStatMonthRow(
                month=m,
                total_work_days=e["work_days"] if e else 0,
                avg_work_hours=avg_hours,
                total_leave_days=round(leave_month.get(m, 0), 1),
                emp_count=emp_count,
            )
        )

    # 3. by_dept — INSA 부서별 연차 총합
    names = list(leave_by_name.keys())
    name_to_dept: dict[str, str] = {}
    if names:
        matched = (
            insa_db.query(Employee.name_ko, Department.name)
            .outerjoin(Department, Employee.dept_id == Department.id)
            .filter(Employee.name_ko.in_(names))
            .all()
        )
        for n, d in matched:
            name_to_dept[n] = d or "미지정"

    dept_agg: dict[str, dict] = defaultdict(
        lambda: {"emp_count": 0, "leave_days": 0.0}
    )
    for name, days in leave_by_name.items():
        dept = name_to_dept.get(name, "미매칭")
        dept_agg[dept]["leave_days"] += days

    dept_count_rows = (
        insa_db.query(Department.name, func.count(Employee.id))
        .outerjoin(
            Employee,
            and_(Employee.dept_id == Department.id, Employee.emp_status != "퇴직"),
        )
        .group_by(Department.name)
        .all()
    )
    for dname, cnt in dept_count_rows:
        key = dname or "미지정"
        dept_agg[key]["emp_count"] = cnt or 0

    by_dept = [
        AttendanceStatDeptRow(
            dept_name=k,
            emp_count=v["emp_count"],
            total_leave_days=round(v["leave_days"], 1),
            avg_leave_per_emp=(
                round(v["leave_days"] / v["emp_count"], 1)
                if v["emp_count"]
                else 0.0
            ),
        )
        for k, v in sorted(
            dept_agg.items(), key=lambda x: -x[1]["leave_days"]
        )
    ]

    # 4. Top work hours
    emp_nos = list(emp_work_minutes.keys())
    emp_info: dict[str, tuple[str, Optional[str]]] = {}
    if emp_nos:
        erows = (
            insa_db.query(Employee.emp_no, Employee.name_ko, Department.name)
            .outerjoin(Department, Employee.dept_id == Department.id)
            .filter(Employee.emp_no.in_(emp_nos))
            .all()
        )
        for emp_no, nm, dn in erows:
            emp_info[emp_no] = (nm, dn)

    top_work = sorted(emp_work_minutes.items(), key=lambda x: -x[1])[:10]
    top_work_hours = [
        AttendanceStatTopRow(
            emp_no=emp_no,
            name=emp_info.get(emp_no, (emp_no, None))[0] or emp_no,
            dept_name=emp_info.get(emp_no, (None, None))[1],
            value=round(minutes / 60.0, 1),
        )
        for emp_no, minutes in top_work
    ]

    # 5. Top leave users
    name_to_empno: dict[str, str] = {}
    if names:
        nrows = (
            insa_db.query(Employee.name_ko, Employee.emp_no)
            .filter(Employee.name_ko.in_(names))
            .all()
        )
        for n, en in nrows:
            name_to_empno[n] = en

    top_leave = sorted(leave_by_name.items(), key=lambda x: -x[1])[:10]
    top_leave_users = [
        AttendanceStatTopRow(
            emp_no=name_to_empno.get(name),
            name=name,
            dept_name=name_to_dept.get(name),
            value=round(days, 1),
        )
        for name, days in top_leave
    ]

    return AttendanceStatResponse(
        year=year,
        by_month=by_month,
        by_dept=by_dept,
        top_work_hours=top_work_hours,
        top_leave_users=top_leave_users,
    )


# ── Education ─────────────────────────────────────────────


def get_education(db: Session, year: int) -> EducationStatResponse:
    year_col = func.coalesce(EduRecord.end_date, EduRecord.start_date)

    rows = (
        db.query(EduRecord, EduCourse, Employee, Department)
        .outerjoin(EduCourse, EduRecord.course_id == EduCourse.id)
        .outerjoin(Employee, EduRecord.employee_id == Employee.id)
        .outerjoin(Department, Employee.dept_id == Department.id)
        .filter(extract("year", year_col) == year)
        .all()
    )

    total_records = len(rows)
    total_hours = 0.0
    completed = 0
    noncompleted = 0

    cat_map: dict[str, dict] = defaultdict(
        lambda: {"count": 0, "hours": 0.0, "completed": 0}
    )
    dept_map: dict[str, dict] = defaultdict(
        lambda: {"emp_set": set(), "records": 0, "hours": 0.0}
    )
    month_map: dict[int, int] = defaultdict(int)

    for rec, course, emp, dept in rows:
        hours = float(rec.hours or 0)
        total_hours += hours

        result = (rec.result or "").strip()
        if result == "수료":
            completed += 1
        elif result == "미수료":
            noncompleted += 1

        category = (course.category if course else None) or "미지정"
        cm = cat_map[category]
        cm["count"] += 1
        cm["hours"] += hours
        if result == "수료":
            cm["completed"] += 1

        dname = dept.name if dept else "미지정"
        dm = dept_map[dname]
        if emp:
            dm["emp_set"].add(emp.id)
        dm["records"] += 1
        dm["hours"] += hours

        ref_date = rec.end_date or rec.start_date
        if ref_date:
            month_map[ref_date.month] += 1

    # 재직자 기준 부서별 인원수
    dept_emp_rows = (
        db.query(Department.name, func.count(Employee.id))
        .outerjoin(
            Employee,
            and_(Employee.dept_id == Department.id, Employee.emp_status != "퇴직"),
        )
        .group_by(Department.name)
        .all()
    )
    dept_active_count: dict[str, int] = {
        (n or "미지정"): (c or 0) for n, c in dept_emp_rows
    }

    by_category = [
        EducationStatCategoryRow(
            category=k,
            count=v["count"],
            total_hours=round(v["hours"], 1),
            completed=v["completed"],
        )
        for k, v in sorted(cat_map.items(), key=lambda x: -x[1]["count"])
    ]

    by_dept = []
    for dname, dv in sorted(dept_map.items(), key=lambda x: -x[1]["records"]):
        emp_count = dept_active_count.get(dname, len(dv["emp_set"]))
        by_dept.append(
            EducationStatDeptRow(
                dept_name=dname,
                emp_count=emp_count,
                record_count=dv["records"],
                total_hours=round(dv["hours"], 1),
                avg_hours_per_emp=(
                    round(dv["hours"] / emp_count, 1) if emp_count else 0.0
                ),
            )
        )

    by_month = [
        EducationStatMonthRow(month=m, count=month_map.get(m, 0)) for m in range(1, 13)
    ]

    # 미이수자 — 재직자 중 해당 연도 이수 기록이 없는 사람
    completed_emp_ids = {
        rec.employee_id
        for rec, _c, _e, _d in rows
        if (rec.result or "") == "수료"
    }
    active_emps = (
        db.query(Employee, Department)
        .outerjoin(Department, Employee.dept_id == Department.id)
        .filter(Employee.emp_status != "퇴직")
        .all()
    )
    incomplete: list[EducationStatIncompleteRow] = []
    for emp, dept in active_emps:
        if emp.id in completed_emp_ids:
            continue
        incomplete.append(
            EducationStatIncompleteRow(
                emp_no=emp.emp_no,
                name=emp.name_ko,
                dept_name=dept.name if dept else None,
                total_hours=0.0,
            )
        )

    completion_rate = (
        round(completed / (completed + noncompleted) * 100, 1)
        if (completed + noncompleted) > 0
        else 0.0
    )

    return EducationStatResponse(
        year=year,
        total_records=total_records,
        total_hours=round(total_hours, 1),
        completed=completed,
        completion_rate=completion_rate,
        by_category=by_category,
        by_dept=by_dept,
        by_month=by_month,
        incomplete_employees=incomplete[:100],
    )
