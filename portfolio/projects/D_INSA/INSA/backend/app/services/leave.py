from calendar import monthrange
from datetime import date, datetime, timedelta
from typing import Optional

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from app.db.models import Department, Employee
from app.schemas.leave import LeaveListResponse, LeaveRow, LeaveSummary

_KO_WEEKDAYS = ["월", "화", "수", "목", "금", "토", "일"]

# 휴가성으로 취급할 gubun 목록 (탁상/출장/파견/기타 등 제외)
_LEAVE_GUBUNS = {
    "휴가",
    "공가",
    "특가",
    "NPL휴가",
    "기타휴가",
    "가족돌봄",
    "병가",
    "예비군",
}


def _is_half(bigo: Optional[str]) -> bool:
    if not bigo:
        return False
    return "반차" in bigo.replace(" ", "")


def _classify(gubun: str, bigo: Optional[str]) -> str:
    g = (gubun or "").strip()
    b = (bigo or "").replace(" ", "")
    if g == "휴가":
        return "반차" if "반차" in b else "연차"
    if g == "공가":
        return "공가"
    if g in ("특가", "NPL휴가"):
        return "경조휴가" if "경조" in b else "특가"
    if g == "가족돌봄":
        return "가족돌봄"
    if g == "병가":
        return "병가"
    if g == "기타휴가":
        return "기타휴가"
    if g == "예비군":
        return "예비군"
    return g or "기타"


def get_leaves(
    apw_db: Session,
    insa_db: Session,
    year: int,
    month: int,
    leave_type: Optional[str] = None,
    keyword: Optional[str] = None,
) -> LeaveListResponse:
    last_day = monthrange(year, month)[1]
    start_date = date(year, month, 1)
    next_month = start_date + timedelta(days=last_day)

    stmt = text(
        """
        SELECT name, [date], gubun, Bigo
        FROM APW_IW_SCHEDULE
        WHERE [date] >= :s AND [date] < :ne
          AND gubun IN :gubuns
        ORDER BY [date], name
        """
    ).bindparams(bindparam("gubuns", expanding=True))
    sched_rows = apw_db.execute(
        stmt,
        {"s": start_date, "ne": next_month, "gubuns": list(_LEAVE_GUBUNS)},
    ).mappings().all()

    # INSA enrichment
    names = sorted({(r["name"] or "").strip() for r in sched_rows if r["name"]})
    info_map: dict[str, tuple[Optional[str], Optional[str]]] = {}
    if names:
        matched = (
            insa_db.query(Employee.emp_no, Employee.name_ko, Department.name)
            .outerjoin(Department, Employee.dept_id == Department.id)
            .filter(Employee.name_ko.in_(names))
            .all()
        )
        for emp_no, name_ko, dept_name in matched:
            info_map[name_ko] = (emp_no, dept_name)

    rows: list[LeaveRow] = []
    summary = {
        "annual": 0.0,
        "half": 0,
        "gong": 0.0,
        "special": 0.0,
        "bereavement": 0.0,
        "family_care": 0.0,
        "etc": 0.0,
    }

    type_filter = (leave_type or "").strip()
    kw = (keyword or "").strip().lower()

    for r in sched_rows:
        name = (r["name"] or "").strip()
        if not name:
            continue
        d_val = r["date"]
        d_key = d_val.date() if isinstance(d_val, datetime) else d_val
        gubun = (r["gubun"] or "").strip()
        bigo = (r["Bigo"] or "").strip() or None

        cat = _classify(gubun, bigo)
        half = _is_half(bigo)
        mult = 0.5 if half else 1.0

        if cat == "연차":
            summary["annual"] += mult
        elif cat == "반차":
            summary["half"] += 1
        elif cat == "공가":
            summary["gong"] += mult
        elif cat == "특가":
            summary["special"] += mult
        elif cat == "경조휴가":
            summary["bereavement"] += mult
        elif cat == "가족돌봄":
            summary["family_care"] += mult
        else:
            summary["etc"] += mult

        emp_no, dept_name = info_map.get(name, (None, None))
        matched = name in info_map

        # 표시용 카테고리명: 연차/반차 합쳐서 `연차`로 보이게, 하위의 half로 구분
        display_type = "연차" if cat in ("연차", "반차") else cat

        if type_filter and type_filter not in (cat, display_type):
            continue
        if kw and kw not in name.lower() and kw not in (dept_name or "").lower():
            continue

        rows.append(
            LeaveRow(
                emp_no=emp_no,
                name=name,
                dept_name=dept_name,
                matched=matched,
                leave_date=d_key,
                weekday=_KO_WEEKDAYS[d_key.weekday()],
                leave_type=display_type,
                half=half,
                remark=bigo,
            )
        )

    return LeaveListResponse(
        year=year,
        month=month,
        total=len(rows),
        summary=LeaveSummary(
            annual=round(summary["annual"], 1),
            half=summary["half"],
            gong=round(summary["gong"], 1),
            special=round(summary["special"], 1),
            bereavement=round(summary["bereavement"], 1),
            family_care=round(summary["family_care"], 1),
            etc=round(summary["etc"], 1),
        ),
        rows=rows,
    )
