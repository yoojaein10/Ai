from calendar import monthrange
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.models import Department, Employee
from app.schemas.attendance import (
    AttendanceDailyResponse,
    AttendanceDailyRow,
    AttendanceDetailDay,
    AttendanceDetailResponse,
    AttendanceSummaryResponse,
    AttendanceSummaryRow,
)

_KO_WEEKDAYS = ["월", "화", "수", "목", "금", "토", "일"]


def _hhmmss(value: Optional[str]) -> Optional[str]:
    if not value or len(value) < 6:
        return None
    return f"{value[0:2]}:{value[2:4]}:{value[4:6]}"


def _work_minutes(first: Optional[str], last: Optional[str]) -> Optional[int]:
    if not first or not last or first == last:
        return None
    try:
        t1 = datetime.strptime(first, "%H%M%S")
        t2 = datetime.strptime(last, "%H%M%S")
    except ValueError:
        return None
    delta = (t2 - t1).total_seconds() // 60
    return int(delta) if delta >= 0 else None


def get_daily_attendance(
    att_db: Session, insa_db: Session, work_date: date
) -> AttendanceDailyResponse:
    date_str = work_date.strftime("%Y%m%d")

    # tenter에서 e_mode=3(출입)만 있는 직원도 포함해야 하므로 전체 태그 기준으로 집계.
    # 일자의 첫 태그=출근, 마지막 태그=퇴근 규칙. e_id=-1(미인식)/빈 사번 제외.
    raw = att_db.execute(
        text(
            """
            SELECT
                e_idno,
                MAX(e_name) AS e_name,
                MIN(e_time) AS first_time,
                MAX(e_time) AS last_time,
                COUNT(*)    AS tag_count
            FROM tenter
            WHERE e_date = :d
              AND e_id <> -1
              AND e_idno IS NOT NULL
              AND e_idno <> ''
            GROUP BY e_idno
            ORDER BY e_idno
            """
        ),
        {"d": date_str},
    ).mappings().all()

    if not raw:
        return AttendanceDailyResponse(
            work_date=work_date, total=0, matched_count=0, rows=[]
        )

    emp_nos = [r["e_idno"] for r in raw]
    emp_map: dict[str, tuple[str, Optional[str]]] = {}
    matched_rows = (
        insa_db.query(Employee.emp_no, Employee.name_ko, Department.name)
        .outerjoin(Department, Employee.dept_id == Department.id)
        .filter(Employee.emp_no.in_(emp_nos))
        .all()
    )
    for emp_no, name_ko, dept_name in matched_rows:
        emp_map[emp_no] = (name_ko, dept_name)

    rows: list[AttendanceDailyRow] = []
    for r in raw:
        emp_no = r["e_idno"]
        matched = emp_no in emp_map
        name = emp_map[emp_no][0] if matched else (r["e_name"] or "")
        dept_name = emp_map[emp_no][1] if matched else None

        first = r["first_time"]
        last = r["last_time"]
        rows.append(
            AttendanceDailyRow(
                emp_no=emp_no,
                name=name,
                dept_name=dept_name,
                matched=matched,
                check_in=_hhmmss(first),
                check_out=_hhmmss(last) if last != first else None,
                work_minutes=_work_minutes(first, last),
                tag_count=int(r["tag_count"]),
            )
        )

    return AttendanceDailyResponse(
        work_date=work_date,
        total=len(rows),
        matched_count=sum(1 for x in rows if x.matched),
        rows=rows,
    )


def _half_day_multiplier(bigo: Optional[str]) -> float:
    if not bigo:
        return 1.0
    return 0.5 if "반차" in bigo.replace(" ", "") else 1.0


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


def get_monthly_summary(
    att_db: Session,
    apw_db: Session,
    insa_db: Session,
    year: int,
    month: int,
) -> AttendanceSummaryResponse:
    last_day = monthrange(year, month)[1]
    start_date = date(year, month, 1)
    end_date = date(year, month, last_day)
    next_month = start_date + timedelta(days=last_day)
    start_str = start_date.strftime("%Y%m%d")
    end_str = end_date.strftime("%Y%m%d")

    per: dict[str, dict] = defaultdict(
        lambda: {
            "emp_no": None,
            "work_day_set": set(),
            "work_minutes": 0,
            "leave_days": 0.0,
            "gong_days": 0.0,
            "trip_day_set": set(),
        }
    )

    # 1. tenter — 일자×직원 단위 집계
    tenter_rows = att_db.execute(
        text(
            """
            SELECT e_idno,
                   MAX(e_name) AS e_name,
                   e_date,
                   MIN(e_time) AS first_t,
                   MAX(e_time) AS last_t
            FROM tenter
            WHERE e_date BETWEEN :s AND :e
              AND e_id <> -1
              AND e_idno IS NOT NULL
              AND e_idno <> ''
            GROUP BY e_idno, e_date
            """
        ),
        {"s": start_str, "e": end_str},
    ).mappings().all()

    for r in tenter_rows:
        name = (r["e_name"] or "").strip()
        if not name:
            continue
        entry = per[name]
        if entry["emp_no"] is None:
            entry["emp_no"] = r["e_idno"]
        entry["work_day_set"].add(r["e_date"])
        entry["work_minutes"] += _minutes_between(r["first_t"], r["last_t"])

    # 2. APW_IW_SCHEDULE — 휴가/공가 (반차는 0.5일)
    sched_rows = apw_db.execute(
        text(
            """
            SELECT name, [date], gubun, Bigo
            FROM APW_IW_SCHEDULE
            WHERE [date] >= :s AND [date] < :ne
            """
        ),
        {"s": start_date, "ne": next_month},
    ).mappings().all()

    for r in sched_rows:
        name = (r["name"] or "").strip()
        if not name:
            continue
        gubun = (r["gubun"] or "").strip()
        mult = _half_day_multiplier(r["Bigo"])
        entry = per[name]
        if gubun == "휴가":
            entry["leave_days"] += mult
        elif gubun == "공가":
            entry["gong_days"] += mult

    # 3. APW_IW_DAYCULJANG — 출장 (하루 여러 건이어도 1일)
    trip_rows = apw_db.execute(
        text(
            """
            SELECT DISTINCT Name AS name, CAST(CulDate AS date) AS d
            FROM APW_IW_DAYCULJANG
            WHERE CulDate >= :s AND CulDate < :ne
            """
        ),
        {"s": start_date, "ne": next_month},
    ).mappings().all()

    for r in trip_rows:
        name = (r["name"] or "").strip()
        if not name:
            continue
        per[name]["trip_day_set"].add(r["d"])

    # 4. INSA 직원 매칭 (부서명 enrich)
    names = list(per.keys())
    dept_map: dict[str, tuple[Optional[str], Optional[str]]] = {}
    if names:
        matched = (
            insa_db.query(Employee.emp_no, Employee.name_ko, Department.name)
            .outerjoin(Department, Employee.dept_id == Department.id)
            .filter(Employee.name_ko.in_(names))
            .all()
        )
        for emp_no, name_ko, dept_name in matched:
            dept_map[name_ko] = (emp_no, dept_name)

    # 5. 응답 조립
    rows: list[AttendanceSummaryRow] = []
    for name in sorted(per.keys()):
        e = per[name]
        insa_emp_no, dept_name = dept_map.get(name, (None, None))
        emp_no = e["emp_no"] or insa_emp_no or ""
        rows.append(
            AttendanceSummaryRow(
                emp_no=emp_no,
                name=name,
                dept_name=dept_name,
                matched=name in dept_map,
                work_days=len(e["work_day_set"]),
                work_hours=round(e["work_minutes"] / 60.0, 1),
                leave_days=round(e["leave_days"], 1),
                gong_days=round(e["gong_days"], 1),
                trip_days=len(e["trip_day_set"]),
            )
        )

    return AttendanceSummaryResponse(
        year=year,
        month=month,
        total=len(rows),
        matched_count=sum(1 for x in rows if x.matched),
        rows=rows,
    )


def get_personal_detail(
    att_db: Session,
    apw_db: Session,
    insa_db: Session,
    emp_no: str,
    year: int,
    month: int,
) -> AttendanceDetailResponse:
    last_day = monthrange(year, month)[1]
    start_date = date(year, month, 1)
    end_date = date(year, month, last_day)
    next_month = start_date + timedelta(days=last_day)
    start_str = start_date.strftime("%Y%m%d")
    end_str = end_date.strftime("%Y%m%d")

    # 1. tenter — 해당 사번의 일자별 첫/마지막 태그
    tenter_rows = att_db.execute(
        text(
            """
            SELECT e_idno,
                   MAX(e_name) AS e_name,
                   e_date,
                   MIN(e_time) AS first_t,
                   MAX(e_time) AS last_t,
                   COUNT(*) AS tag_count
            FROM tenter
            WHERE e_idno = :emp_no
              AND e_date BETWEEN :s AND :e
              AND e_id <> -1
            GROUP BY e_idno, e_date
            """
        ),
        {"emp_no": emp_no, "s": start_str, "e": end_str},
    ).mappings().all()

    tenter_by_date: dict[str, dict] = {r["e_date"]: r for r in tenter_rows}
    name_from_tenter = next(
        (r["e_name"].strip() for r in tenter_rows if r["e_name"]), None
    )

    # 2. INSA enrichment (부서/이름)
    insa_match = (
        insa_db.query(Employee.name_ko, Department.name)
        .outerjoin(Department, Employee.dept_id == Department.id)
        .filter(Employee.emp_no == emp_no)
        .first()
    )
    if insa_match:
        name = insa_match[0]
        dept_name = insa_match[1]
    else:
        name = name_from_tenter or emp_no
        dept_name = None

    # 3. APW_IW_SCHEDULE — 이름 기반 조회
    sched_by_date: dict[date, dict] = {}
    if name:
        sched_rows = apw_db.execute(
            text(
                """
                SELECT name, [date], gubun, Bigo
                FROM APW_IW_SCHEDULE
                WHERE name = :n
                  AND [date] >= :s AND [date] < :ne
                """
            ),
            {"n": name, "s": start_date, "ne": next_month},
        ).mappings().all()
        for r in sched_rows:
            d_val = r["date"]
            d_key = d_val.date() if isinstance(d_val, datetime) else d_val
            sched_by_date[d_key] = dict(r)

    # 4. APW_IW_DAYCULJANG — 이름 기반 조회 (하루에 여러 건 가능)
    trip_by_date: dict[date, list[str]] = defaultdict(list)
    if name:
        trip_rows = apw_db.execute(
            text(
                """
                SELECT Name, CAST(CulDate AS date) AS d, Address
                FROM APW_IW_DAYCULJANG
                WHERE Name = :n
                  AND CulDate >= :s AND CulDate < :ne
                ORDER BY CulDate
                """
            ),
            {"n": name, "s": start_date, "ne": next_month},
        ).mappings().all()
        for r in trip_rows:
            addr = (r["Address"] or "").strip()
            if addr:
                trip_by_date[r["d"]].append(addr)
            else:
                trip_by_date[r["d"]].append("")

    # 5. 월 전체 일자 행 생성
    days: list[AttendanceDetailDay] = []
    total_work_minutes = 0
    work_day_count = 0
    leave_sum = 0.0
    gong_sum = 0.0
    trip_day_count = 0

    for d_offset in range(last_day):
        cur = start_date + timedelta(days=d_offset)
        weekday_idx = cur.weekday()
        date_str = cur.strftime("%Y%m%d")

        check_in: Optional[str] = None
        check_out: Optional[str] = None
        work_minutes: Optional[int] = None
        tag_count = 0

        t = tenter_by_date.get(date_str)
        if t:
            first = t["first_t"]
            last = t["last_t"]
            check_in = _hhmmss(first)
            check_out = _hhmmss(last) if last != first else None
            minutes = _minutes_between(first, last)
            work_minutes = minutes if minutes > 0 else None
            tag_count = int(t["tag_count"])
            if tag_count > 0:
                work_day_count += 1
            total_work_minutes += minutes

        leave_type: Optional[str] = None
        leave_half = False
        leave_remark: Optional[str] = None
        s = sched_by_date.get(cur)
        if s:
            gubun = (s["gubun"] or "").strip()
            mult = _half_day_multiplier(s["Bigo"])
            leave_half = mult < 1.0
            leave_type = gubun or None
            leave_remark = (s["Bigo"] or "").strip() or None
            if gubun == "휴가":
                leave_sum += mult
            elif gubun == "공가":
                gong_sum += mult

        trip_places_raw = trip_by_date.get(cur, [])
        trip_flag = len(trip_places_raw) > 0
        trip_places = [p for p in trip_places_raw if p]
        if trip_flag:
            trip_day_count += 1

        days.append(
            AttendanceDetailDay(
                work_date=cur,
                weekday=_KO_WEEKDAYS[weekday_idx],
                is_weekend=weekday_idx >= 5,
                check_in=check_in,
                check_out=check_out,
                work_minutes=work_minutes,
                tag_count=tag_count,
                leave_type=leave_type,
                leave_half=leave_half,
                leave_remark=leave_remark,
                trip=trip_flag,
                trip_places=trip_places,
            )
        )

    return AttendanceDetailResponse(
        emp_no=emp_no,
        name=name or "",
        dept_name=dept_name,
        year=year,
        month=month,
        work_days=work_day_count,
        work_hours=round(total_work_minutes / 60.0, 1),
        leave_days=round(leave_sum, 1),
        gong_days=round(gong_sum, 1),
        trip_days=trip_day_count,
        days=days,
    )
