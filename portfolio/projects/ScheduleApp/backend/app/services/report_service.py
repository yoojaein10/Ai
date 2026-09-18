"""
report_service.py — 출장 일간 현황

데이터 흐름:
1. seat_Userinfo WHERE Dept_Nm IN ('pg1','pg2','su')  → 평가사 목록
2. 오늘 기준 5 영업일 전 ~ 오늘 범위의 접수 감정서 수집
   APW_IW_DAYCULJANG → Apw_Master → Apw_MasterEx.ReceiptDate
3. 해당 감정서의 해당 월 출장 날짜  (APW_IW_DAYCULJANG)
4. 해당 감정서의 해당 월 공정 이력  (APW_Process)

반환 구조:
  [
    { "apwid": 4317, "name": "홍길동", "dept": "pg1",
      "docs": [
        { "docNo": "01-2604-3-1066", "address": "서울시...",
          "lStatus": "평가작성중(처리중)",
          "events": [{"date":"2026-04-02","status":"출장"}, ...] },
        ...
      ]
    },
    ...
  ]
"""
import logging
import pyodbc
from datetime import date, timedelta

logger = logging.getLogger(__name__)

DB         = "apworksdw.dbo"
DEPT_ORDER = {"pg1": 0, "pg2": 1, "su": 2}
_RANK_ORDER = {
    "대표이사": 1, "이사": 2, "본부장": 3, "지사장": 4,
    "국장": 5, "부장": 6, "실장": 7,
    "차장": 8, "자장": 8, "과장": 9,
    "대리": 10, "주임": 11, "사원": 12,
    "수습": 13, "수습평가사": 13,
}


def _trim_addr(addr: str) -> str:
    """마지막 공백 기준 끝 토큰만 반환. 예) '서울특별시 강남구 압구정동' → '압구정동'"""
    parts = addr.strip().split()
    return parts[-1] if parts else ""

def _business_days_ago(ref: date, n: int) -> date:
    """ref 기준 n 영업일(주말 제외) 이전 날짜 반환"""
    d = ref
    count = 0
    while count < n:
        d -= timedelta(days=1)
        if d.weekday() < 5:  # 0=월 ~ 4=금
            count += 1
    return d


def get_daily_list(cursor: pyodbc.Cursor, year: int, month: int) -> list[dict]:
    import calendar as cal_mod

    # ── 1. 평가사 목록 ──────────────────────────────────────────────────────────
    cursor.execute(f"""
        SELECT Apwid, Uname, Dept_Nm, Ugrade
        FROM {DB}.seat_Userinfo
        WHERE Dept_Nm IN ('pg1', 'pg2', 'su')
          AND LTRIM(RTRIM(Ugrade)) != '국장'
        ORDER BY Dept_Nm, Uname
    """)
    user_rows = cursor.fetchall()
    if not user_rows:
        return []

    user_map: dict[str, dict] = {
        row.Uname: {
            "apwid": int(row.Apwid),
            "name":  row.Uname,
            "dept":  row.Dept_Nm,
            "rank":  (row.Ugrade or "").strip(),
            "_docs": {},   # docNo → {"address","lStatus","events":[]}
        }
        for row in user_rows
    }
    names = list(user_map.keys())
    ph    = ",".join(["?"] * len(names))

    # ── 2. 접수일 기준 5 영업일 범위 ───────────────────────────────────────────
    # 기준일(ref_date): 조회 월이 과거면 그 달 말일, 현재/미래면 오늘.
    #   → 과거 월 조회 시 '해당 월 말 기준 최근 5영업일' 접수분을 문서 후보로 삼음.
    today      = date.today()
    last_day   = cal_mod.monthrange(year, month)[1]
    month_last = date(year, month, last_day)
    ref_date   = min(today, month_last)
    start_date = _business_days_ago(ref_date, 5)
    names_set  = set(names)

    # ── 3. Apw_MasterEx에서 접수일 범위 감정서 수집 (Charge → 평가사 매핑) ─────
    # Charge 필드: 단일 이름 또는 "이름1,이름2" 형태
    # ── 3a. 접수일 기준 5영업일 후보 문서 ──────────────────────────────────────
    cursor.execute(
        f"""
        SELECT am.DocID, mx.Charge, mx.LStatus, mx.Address,
               CONVERT(varchar(10), mx.ReceiptDate, 23) AS ReceiptDate,
               mx.LWorkinfo, mx.LCategory
        FROM {DB}.Apw_MasterEx mx
        JOIN {DB}.Apw_Master   am ON am.MasterID = mx.MasterID
        WHERE mx.ReceiptDate >= ? AND mx.ReceiptDate <= ?
          AND mx.Charge IS NOT NULL
        ORDER BY am.DocID
        """,
        [str(start_date), str(ref_date)],
    )

    # docId → name 역매핑 (이벤트 매핑용, 복수 담당자면 첫 번째 기준)
    docid_to_name: dict[str, str] = {}
    for row in cursor.fetchall():
        docid        = row.DocID
        charge_names = [n.strip() for n in (row.Charge or "").split(",")]
        for cname in charge_names:
            if cname not in names_set:
                continue
            user_map[cname]["_docs"].setdefault(docid, {
                "address":     (row.Address or "").strip(),
                "lStatus":     row.LStatus or "",
                "receiptDate": row.ReceiptDate or "",
                "workType":    row.LWorkinfo or "",
                "category":    row.LCategory or "",
                "events":      [],
            })
            if docid not in docid_to_name:
                docid_to_name[docid] = cname

    # ── 3b. 기준일 출장 데이터가 있는 문서 추가 (접수일 범위 밖 포함) ──────────
    cursor.execute(
        f"""
        SELECT DISTINCT d.Docid
        FROM {DB}.APW_IW_DAYCULJANG d
        WHERE CONVERT(date, d.CulDate) = CONVERT(date, ?)
        """,
        [str(ref_date)],
    )
    today_docids = [row.Docid for row in cursor.fetchall()]

    if today_docids:
        ph_t = ",".join(["?"] * len(today_docids))
        cursor.execute(
            f"""
            SELECT am.DocID, mx.Charge, mx.LStatus, mx.Address,
                   CONVERT(varchar(10), mx.ReceiptDate, 23) AS ReceiptDate,
                   mx.LWorkinfo, mx.LCategory
            FROM {DB}.Apw_MasterEx mx
            JOIN {DB}.Apw_Master   am ON am.MasterID = mx.MasterID
            WHERE am.DocID IN ({ph_t})
              AND mx.Charge IS NOT NULL
            """,
            today_docids,
        )
        for row in cursor.fetchall():
            docid        = row.DocID
            charge_names = [n.strip() for n in (row.Charge or "").split(",")]
            for cname in charge_names:
                if cname not in names_set:
                    continue
                user_map[cname]["_docs"].setdefault(docid, {
                    "address":     (row.Address or "").strip(),
                    "lStatus":     row.LStatus or "",
                    "receiptDate": row.ReceiptDate or "",
                    "workType":    row.LWorkinfo or "",
                    "category":    row.LCategory or "",
                    "events":      [],
                })
                if docid not in docid_to_name:
                    docid_to_name[docid] = cname

    if not docid_to_name:
        return _build_result(user_map)

    seen_docids = list(docid_to_name.keys())
    ph2         = ",".join(["?"] * len(seen_docids))

    # ── 4. 해당 월 출장 날짜 (APW_IW_DAYCULJANG) ───────────────────────────────
    month_start = f"{year}-{month:02d}-01"
    month_end   = f"{year}-{month:02d}-{last_day:02d}"

    cursor.execute(
        f"""
        SELECT Docid, CONVERT(varchar(10), CulDate, 23) AS CulDate
        FROM {DB}.APW_IW_DAYCULJANG
        WHERE Docid IN ({ph2})
          AND CulDate >= ? AND CulDate <= ?
        ORDER BY Docid, CulDate
        """,
        seen_docids + [month_start, month_end],
    )
    for row in cursor.fetchall():
        name = docid_to_name.get(row.Docid)
        if not name:
            continue
        user_map[name]["_docs"][row.Docid]["events"].append(
            {"date": row.CulDate, "status": "출장"}
        )

    # ── 5. 해당 월 공정 이력 (APW_Process) ─────────────────────────────────────
    # DocID → MasterID
    cursor.execute(
        f"SELECT DocID, MasterID FROM {DB}.Apw_Master WHERE DocID IN ({ph2})",
        seen_docids,
    )
    docid_to_master: dict[str, int] = {row.DocID: row.MasterID for row in cursor.fetchall()}
    master_ids = list(docid_to_master.values())

    if master_ids:
        ph3 = ",".join(["?"] * len(master_ids))
        cursor.execute(
            f"""
            SELECT DISTINCT
                a.MasterID,
                CASE a.iType
                    WHEN 1 THEN (SELECT [Name] FROM {DB}.APW_Status WHERE Code = a.Code)
                    WHEN 2 THEN (SELECT [Name] FROM {DB}.APW_Result WHERE Code = a.Code)
                END AS CodeCaption,
                CONVERT(varchar(10), a.ProcessDate, 23) AS ProcessDate
            FROM {DB}.APW_Process a
            WHERE a.MasterID IN ({ph3})
              AND a.ProcessDate >= ? AND a.ProcessDate <= ?
              AND a.ProcessDate IS NOT NULL
            """,
            master_ids + [month_start, month_end],
        )
        master_to_procs: dict[int, list[dict]] = {}
        for row in cursor.fetchall():
            if not row.CodeCaption or not row.ProcessDate:
                continue
            master_to_procs.setdefault(row.MasterID, []).append(
                {"date": row.ProcessDate, "status": row.CodeCaption}
            )

        # 공정 이벤트 → docs에 추가
        for docid, name in docid_to_name.items():
            mid = docid_to_master.get(docid)
            if mid is None:
                continue
            user_map[name]["_docs"][docid]["events"].extend(
                master_to_procs.get(mid, [])
            )

    return _build_result(user_map)


def _build_result(user_map: dict) -> list[dict]:
    sorted_users = sorted(
        user_map.values(),
        key=lambda u: (DEPT_ORDER.get(u["dept"], 99), _RANK_ORDER.get(u["rank"], 99), u["name"]),
    )
    result = []
    for user in sorted_users:
        docs = [
            {
                "docNo":       docno,
                "address":     info["address"],
                "lStatus":     info["lStatus"],
                "receiptDate": info["receiptDate"],
                "workType":    info.get("workType", ""),
                "category":    info.get("category", ""),
                "events":      info["events"],
            }
            for docno, info in user["_docs"].items()
        ]
        result.append({
            "apwid": user["apwid"],
            "name":  user["name"],
            "dept":  user["dept"],
            "docs":  docs,
        })
    return result
