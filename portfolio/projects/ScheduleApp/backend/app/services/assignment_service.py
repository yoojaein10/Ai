"""
assignment_service.py — 업무 배정 현황: 직원 목록 + 배정 데이터
"""
import pyodbc
from datetime import date as Date, timedelta
from app.exceptions import NotFoundException, ForbiddenException, ValidationException

DB = "apworksdw.dbo"

_MAX_GUBUN_LEN = 20

_TEAM_ORDER = {"pg1": 1, "pg2": 2, "su": 3}
_RANK_ORDER = {
    "대표이사": 1,
    "이사":    2,
    "본부장":  3,
    "지사장":  4,
    "국장":    5,
    "부장":    6,
    "실장":    7,
    "차장":    8,
    "자장":    8,
    "과장":    9,
    "대리":    10,
    "주임":    11,
    "사원":    12,
    "수습":    13,
    "수습평가사": 13,
}


def _emp_sort_key(emp: dict) -> tuple:
    return (
        _TEAM_ORDER.get(emp["team"], 99),
        _RANK_ORDER.get(emp["rank"].strip(), 99),
        emp["name"],
    )


def _assign_type(l_status: str) -> str:
    if not l_status:
        return "assign"
    s = l_status
    if "보류" in s or "취소" in s or "반려" in s:
        return "hold"
    return "assign"


def _clean(s) -> str:
    if not s:
        return ""
    if isinstance(s, bytes):
        try:
            return s.decode("cp949").strip()
        except Exception:
            return s.decode("utf-8", errors="replace").strip()
    # pyodbc가 일부 한글을 surrogate escape로 반환하는 경우 복원
    try:
        raw = s.encode("utf-8", errors="surrogateescape")
        return raw.decode("utf-8").strip()
    except Exception:
        pass
    try:
        raw = s.encode("utf-8", errors="surrogateescape")
        return raw.decode("cp949").strip()
    except Exception:
        pass
    return str(s).strip()


def get_assignment_employees(cursor: pyodbc.Cursor) -> list[dict]:
    """
    평가사(pg1/pg2/su) 목록 + 입사일 반환.
    seat_Userinfo.APWID = TMWCMN_EMPT_DTL.EMP_NM 으로 조인.
    """
    cursor.execute(f"""
        SELECT
            u.APWID,
            u.Uname,
            u.Ugrade,
            u.Dept_Nm,
            u.seq,
            e.REG_DAY
        FROM {DB}.seat_Userinfo u
        LEFT JOIN {DB}.TMWCMN_EMPT_DTL e
            ON CAST(u.APWID AS VARCHAR) = e.EMP_NM
        WHERE u.Dept_Nm IN ('pg1', 'pg2', 'su')
          AND LTRIM(RTRIM(u.Ugrade)) != '국장'
        ORDER BY u.Dept_Nm, u.Uname
    """)
    rows = cursor.fetchall()

    result = []
    for r in rows:
        apwid, name, grade, dept, seq, reg_day = r
        hire_date = None
        if reg_day:
            s = str(reg_day).strip()
            if len(s) == 8:
                hire_date = f"{s[:4]}-{s[4:6]}-{s[6:]}"
        result.append({
            "apwid":    int(apwid),
            "name":     _clean(name),
            "rank":     _clean(grade),
            "team":     dept,
            "seq":      seq or 999,
            "hireDate": hire_date,
        })

    result.sort(key=_emp_sort_key)
    return result


def get_assignment_data(cursor: pyodbc.Cursor, year: int, month: int) -> list[dict]:
    """
    해당 월 배정 데이터 반환.
    APW_Allocation.Charge → TMWCMN_USR_BAC_INFO.USR_SEQ → USR_ID = APWID
    """
    cursor.execute(f"""
        SELECT
            u.USR_ID        AS apwid,
            DAY(al.AllocationDate) AS day,
            mx.DocID,
            mx.Address,
            mx.LCategory,
            mx.LStatus
        FROM {DB}.APW_Allocation al
        JOIN {DB}.TMWCMN_USR_BAC_INFO u ON al.Charge = u.USR_SEQ
        JOIN {DB}.Apw_MasterEx mx ON al.MasterID = mx.MasterID
        WHERE YEAR(al.AllocationDate) = ?
          AND MONTH(al.AllocationDate) = ?
          AND u.USR_ID IN (
              SELECT CAST(APWID AS VARCHAR)
              FROM {DB}.seat_Userinfo
              WHERE Dept_Nm IN ('pg1', 'pg2', 'su')
          )
        ORDER BY al.AllocationDate, u.USR_ID
    """, year, month)

    rows = cursor.fetchall()
    result = []
    for r in rows:
        apwid, day, doc_id, address, l_category, l_status = r
        result.append({
            "apwid":    int(apwid),
            "day":      day,
            "docId":    _clean(doc_id),
            "address":  _clean(address),
            "category": _clean(l_category),
            "status":   _clean(l_status),
            "type":     _assign_type(_clean(l_status)),
        })

    # APW_IW_SCHEDULE — 해당 월 전체 gubun (필터 없음)
    _GUBUN_TYPE = {"NPL": "npl", "탁상": "taksan", "공가": "gongga", "휴가": "vacation"}

    cursor.execute(f"""
        SELECT
            u.APWID,
            DAY(s.date) AS day,
            s.gubun
        FROM {DB}.APW_IW_SCHEDULE s
        JOIN {DB}.seat_Userinfo u
            ON LTRIM(RTRIM(s.name)) = LTRIM(RTRIM(u.Uname))
        WHERE YEAR(s.date) = ?
          AND MONTH(s.date) = ?
          AND u.Dept_Nm IN ('pg1', 'pg2', 'su')
        ORDER BY s.date, u.APWID
    """, year, month)

    for r in cursor.fetchall():
        apwid, day, gubun = r
        g = _clean(gubun)
        result.append({
            "apwid":    int(apwid),
            "day":      day,
            "docId":    "",
            "address":  "",
            "category": "",
            "status":   g,
            "type":     _GUBUN_TYPE.get(g, "schedule"),
        })

    return result


def save_assignment_schedule(
    cursor: pyodbc.Cursor, apwid: int, start_date: str, end_date: str, gubun: str
) -> dict:
    """APW_IW_SCHEDULE UPSERT — start_date~end_date 기간 날짜별 INSERT/UPDATE."""
    gubun = gubun.strip()
    if not gubun:
        raise ValidationException("메모는 비워 둘 수 없습니다.")
    if len(gubun) > _MAX_GUBUN_LEN:
        raise ValidationException(f"메모는 최대 {_MAX_GUBUN_LEN}자까지 입력 가능합니다.")

    try:
        d_start = Date.fromisoformat(start_date)
        d_end   = Date.fromisoformat(end_date)
    except ValueError:
        raise ValidationException("날짜 형식이 올바르지 않습니다 (YYYY-MM-DD).")

    if d_end < d_start:
        raise ValidationException("종료일은 시작일보다 이전일 수 없습니다.")

    if (d_end - d_start).days + 1 > 62:
        raise ValidationException("기간은 최대 62일까지 허용됩니다.")

    cursor.execute(
        f"SELECT Uname, Dept_Nm FROM {DB}.seat_Userinfo WHERE APWID = ?",
        apwid,
    )
    row = cursor.fetchone()
    if not row:
        raise NotFoundException(f"직원을 찾을 수 없습니다: apwid={apwid}")

    uname, dept_nm = row
    if dept_nm not in {"pg1", "pg2", "su"}:
        raise ForbiddenException("배정현황 대상 부서가 아닙니다.")

    name = _clean(uname)
    saved = 0
    current = d_start
    while current <= d_end:
        ds = current.isoformat()
        cursor.execute(
            f"SELECT COUNT(1) FROM {DB}.APW_IW_SCHEDULE"
            f" WHERE LTRIM(RTRIM(name)) = ? AND date = ?",
            name, ds,
        )
        if cursor.fetchone()[0] > 0:
            cursor.execute(
                f"UPDATE {DB}.APW_IW_SCHEDULE SET gubun = ?, Bigo = ''"
                f" WHERE LTRIM(RTRIM(name)) = ? AND date = ?",
                gubun, name, ds,
            )
        else:
            cursor.execute(
                f"INSERT INTO {DB}.APW_IW_SCHEDULE (name, date, gubun, Bigo)"
                f" VALUES (?, ?, ?, '')",
                name, ds, gubun,
            )
        saved += 1
        current += timedelta(days=1)

    return {
        "apwid":       apwid,
        "name":        name,
        "start_date":  start_date,
        "end_date":    end_date,
        "gubun":       gubun,
        "saved_count": saved,
    }


def delete_assignment_schedule(
    cursor: pyodbc.Cursor, apwid: int, date: str
) -> dict:
    """APW_IW_SCHEDULE 단일 행 삭제 — name + date 기준."""
    try:
        Date.fromisoformat(date)
    except ValueError:
        raise ValidationException("날짜 형식이 올바르지 않습니다 (YYYY-MM-DD).")

    cursor.execute(
        f"SELECT Uname, Dept_Nm FROM {DB}.seat_Userinfo WHERE APWID = ?",
        apwid,
    )
    row = cursor.fetchone()
    if not row:
        raise NotFoundException(f"직원을 찾을 수 없습니다: apwid={apwid}")

    uname, dept_nm = row
    if dept_nm not in {"pg1", "pg2", "su"}:
        raise ForbiddenException("배정현황 대상 부서가 아닙니다.")

    name = _clean(uname)
    cursor.execute(
        f"DELETE FROM {DB}.APW_IW_SCHEDULE"
        f" WHERE LTRIM(RTRIM(name)) = ? AND date = ?",
        name, date,
    )
    deleted = cursor.rowcount

    return {
        "apwid":         apwid,
        "name":          name,
        "date":          date,
        "deleted_count": deleted,
    }
