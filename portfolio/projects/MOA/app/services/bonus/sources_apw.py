"""원천 DB([apworksdw]) 리더 — 감정서 메타·인별 배분·지분표·청구·명부 (2단계 12).

여기 SQL 은 시험 DB(sqlite)로 돌리지 않는다(리포지토리 관례). 문자열 검사와 실측
대조 스크립트(scripts/bonus_compare_excel.py)로 검증한다. 규칙:
- varchar 열에 바인드할 때는 `CAST(:p AS varchar(n))` — NVARCHAR 로 들어가면 풀스캔.
- IN 목록은 500건씩 청크 (MSSQL 2016 파라미터 2,100개 제한).
"""

from datetime import timedelta, date, datetime
from typing import Any

from sqlalchemy import text

from app.config import get_settings
from app.services.bonus.rules import manager_entries, _charge_ratio

_CHUNK = 500


def source_database() -> str:
    database = get_settings().mssql_source_db
    if not database.replace("_", "").isalnum():
        raise RuntimeError("MSSQL_SOURCE_DB 이름이 올바르지 않습니다.")
    return database


def _chunks(doc_ids: "list[str]"):
    ids = [doc for doc in dict.fromkeys(str(d or "").strip() for d in doc_ids) if doc]
    for start in range(0, len(ids), _CHUNK):
        chunk = ids[start:start + _CHUNK]
        names = [f"d{i}" for i in range(len(chunk))]
        yield ", ".join(f"CAST(:{n} AS varchar(50))" for n in names), dict(zip(names, chunk))


def _as_date(value: Any) -> "date | None":
    if value is None:
        return None
    return value.date() if isinstance(value, datetime) else value


def doc_meta(db, doc_ids: "list[str]") -> "dict[str, dict[str, Any]]":
    """apw_masterex 의 감정서 메타 — 접수일(요율 판정)·업무분류·거래처·담당자·조사자·경비 항목."""
    database = source_database()
    result: "dict[str, dict[str, Any]]" = {}
    for in_list, params in _chunks(doc_ids):
        rows = db.execute(text(f"""
SELECT RTRIM(m.DocID) AS doc_id, m.ReceiptDate AS receipt_date,
       RTRIM(m.LWorkinfo) AS work_type, RTRIM(m.CustName) AS customer_name,
       RTRIM(m.Manager) AS manager, RTRIM(m.Charge) AS investigator,
       m.[기초수수료] AS base_fee, m.[절사금액] AS cut_fee, m.[토지조사비] AS land_fee,
       m.[여비] AS travel_billed, m.[물건조사비] AS survey_fee,
       c.Names AS ratio_names, c.Ratios AS ratio_values,
       ISNULL(cj.claim_total, 0) AS travel_claimed
FROM [{database}].dbo.apw_masterex m
LEFT JOIN [{database}].dbo.APW_Charge_IDX c ON c.MasterID = m.MasterID AND c.iType = 1
LEFT JOIN (
    SELECT Docid, SUM(Cul_In + Cul_Out) AS claim_total
    FROM [{database}].dbo.APW_YJI_ManCulJang
    WHERE ApproState >= 3          -- 승인(3) 이상만 (2026-08-27 사용자 확정)
    GROUP BY Docid
) cj ON cj.Docid = m.DocID
WHERE m.DocID IN ({in_list})
"""), params).mappings().all()
        for row in rows:
            result[row["doc_id"]] = {
                "receipt_date": _as_date(row["receipt_date"]),
                "work_type": row["work_type"] or "",
                "customer_name": row["customer_name"] or "",
                "manager": row["manager"] or "",
                "investigator": row["investigator"] or "",
                "base_fee": float(row["base_fee"] or 0),
                "cut_fee": float(row["cut_fee"] or 0),
                "land_fee": float(row["land_fee"] or 0),
                "travel_billed": float(row["travel_billed"] or 0),
                "travel_claimed": float(row["travel_claimed"] or 0),
                "survey_fee": float(row["survey_fee"] or 0),
                "ratio_names": row["ratio_names"],
                "ratio_values": row["ratio_values"],
            }
    return result


def charge_ratio(meta: "dict[str, Any]", person: str) -> "float | None":
    """APW_Charge_IDX 담당자 비율(%) — 없으면 None."""
    ratio = _charge_ratio(person, meta.get("ratio_names"), meta.get("ratio_values"))
    return ratio * 100 if ratio is not None else None


def gaprice_allocations(db, doc_ids: "list[str]") -> "dict[str, dict[str, float]]":
    """매출입력 승인 배분(Apw_Mae_GaPrice.In_Price > 0) — {감정서: {사람: 배분액}} (전 기간)."""
    database = source_database()
    result: "dict[str, dict[str, float]]" = {}
    for in_list, params in _chunks(doc_ids):
        rows = db.execute(text(f"""
SELECT RTRIM(Docid) AS doc_id, RTRIM(Manager) AS person, SUM(In_Price) AS in_price
FROM [{database}].dbo.Apw_Mae_GaPrice
WHERE Docid IN ({in_list}) AND In_Price > 0
GROUP BY RTRIM(Docid), RTRIM(Manager)
"""), params).mappings().all()
        for row in rows:
            if row["person"]:
                result.setdefault(row["doc_id"], {})[row["person"]] = float(row["in_price"] or 0)
    return result


def booking_shares(db, doc_ids: "list[str]") -> "dict[str, dict[str, float]]":
    """APWorks 유치 지분표(APW_Booking.Ratio, 합으로 정규화한 %) — my_sales._SHARE_SQL 과 같은 규칙."""
    database = source_database()
    by_seq: "dict[str, dict[str, float]]" = {}
    for in_list, params in _chunks(doc_ids):
        rows = db.execute(text(f"""
SELECT RTRIM(k.DocID) AS doc_id, RTRIM(b.Manager) AS usr_seq,
       CAST(b.Ratio AS float)
         / NULLIF(SUM(CAST(b.Ratio AS float)) OVER (PARTITION BY b.MasterID), 0) AS share
FROM [{database}].dbo.APW_Booking b
JOIN [{database}].dbo.APW_MASTER k ON k.MasterID = b.MasterID
WHERE b.Ratio > 0 AND k.DocID IN ({in_list})
"""), params).mappings().all()
        for row in rows:
            if row["usr_seq"] and row["share"]:
                by_seq.setdefault(row["doc_id"], {})[row["usr_seq"]] = float(row["share"]) * 100
    seqs = sorted({seq for shares in by_seq.values() for seq in shares})
    names = _names_by_usr_seq(db, database, seqs)
    return {
        doc: {names.get(seq, seq): pct for seq, pct in shares.items()}
        for doc, shares in by_seq.items()
    }


def _names_by_usr_seq(db, database: str, seqs: "list[str]") -> "dict[str, str]":
    result: "dict[str, str]" = {}
    for start in range(0, len(seqs), _CHUNK):
        chunk = seqs[start:start + _CHUNK]
        names = [f"s{i}" for i in range(len(chunk))]
        rows = db.execute(text(f"""
SELECT CAST(USR_SEQ AS varchar(20)) AS usr_seq, RTRIM(EMP) AS emp_name
FROM [{database}].dbo.TMWCMN_USR_BAC_INFO
WHERE EMP IS NOT NULL AND CAST(USR_SEQ AS varchar(20)) IN ({", ".join(f"CAST(:{n} AS varchar(20))" for n in names)})
"""), dict(zip(names, chunk))).mappings().all()
        result.update({row["usr_seq"]: row["emp_name"] for row in rows if row["emp_name"]})
    return result


def survey_claims(db, doc_ids: "list[str]") -> "dict[str, dict[str, float]]":
    """감정서별 조사자 물건조사비 청구(APW_YJI_ManCulJang.Mul_Amt, 승인 완료만) — {감정서: {조사자: 합}}."""
    database = source_database()
    result: "dict[str, dict[str, float]]" = {}
    for in_list, params in _chunks(doc_ids):
        rows = db.execute(text(f"""
SELECT RTRIM(Docid) AS doc_id, RTRIM(Write_Name) AS who, SUM(Mul_Amt) AS amount
FROM [{database}].dbo.APW_YJI_ManCulJang
WHERE Docid IN ({in_list}) AND Mul_Amt > 0 AND ApproState >= 3
GROUP BY RTRIM(Docid), RTRIM(Write_Name)
"""), params).mappings().all()
        for row in rows:
            result.setdefault(row["doc_id"], {})[row["who"]] = float(row["amount"] or 0)
    return result


def variable_costs(db, standmon: str) -> "dict[str, float]":
    """가변비(APW_IW_MONGABUNBI) 인별 합 — 상여 시트 'NN월가변비' 자동값. standmon = 'YYYY-MM'."""
    database = source_database()
    rows = db.execute(text(
        f"SELECT RTRIM(Manager) AS person, SUM(Gabunbi) AS amount "
        f"FROM [{database}].dbo.APW_IW_MONGABUNBI "
        f"WHERE Standmon = CAST(:standmon AS varchar(10)) GROUP BY RTRIM(Manager)"
    ), {"standmon": standmon}).mappings().all()
    return {row["person"]: float(row["amount"] or 0) for row in rows if row["person"]}


def active_names(db) -> "set[str]":
    """재직자 이름 집합 (USE_YN='Y' AND RTRM_FL='0') — 동명이인은 한 명이라도 재직이면 재직."""
    database = source_database()
    rows = db.execute(text(
        f"SELECT DISTINCT RTRIM(EMP) FROM [{database}].dbo.TMWCMN_USR_BAC_INFO "
        f"WHERE USE_YN = 'Y' AND RTRM_FL = '0'"
    )).all()
    return {row[0] for row in rows if row[0]}


def dept_by_name(db) -> "dict[str, str]":
    """Seat_userinfo 부서코드 — 'so' 만 소속평가사(평·동)."""
    database = source_database()
    rows = db.execute(text(
        f"SELECT RTRIM(Uname) AS name, RTRIM(Dept_Nm) AS dept "
        f"FROM [{database}].dbo.Seat_userinfo WHERE Uname IS NOT NULL"
    )).all()
    result: "dict[str, str]" = {}
    for name, dept in rows:
        if name and name not in result:
            result[name] = dept or None
    return result


def search_docs(db, person: str, date_from, date_to, *, limit: int = 300) -> "list[dict[str, Any]]":
    """담당자(공(X) 포함)가 그 사람인 감정서를 접수일 구간으로 찾는다 — 상여 화면 '추가'(수기 포함) 목록.

    Manager 는 '윤도,공(장재원)' 같은 쉼표 목록이라 LIKE 로 넓게 잡은 뒤 파이썬에서 정확히 가른다.
    """
    database = source_database()
    name = str(person or "").strip()
    if not name:
        return []
    rows = db.execute(text(f"""
SELECT TOP {int(limit)} RTRIM(m.DocID) AS doc_id, m.ReceiptDate AS receipt_date,
       RTRIM(m.LWorkinfo) AS work_type, RTRIM(m.CustName) AS customer_name,
       RTRIM(m.Manager) AS manager, m.[기초수수료] AS base_fee, m.[절사금액] AS cut_fee
FROM [{database}].dbo.apw_masterex m
WHERE m.ReceiptDate >= :date_from AND m.ReceiptDate < :date_to_next
  AND m.Manager LIKE CAST(:pattern AS NVARCHAR(100))
  AND m.DocID LIKE '01%'
ORDER BY m.ReceiptDate DESC, m.DocID DESC
"""), {"date_from": date_from, "date_to_next": date_to + timedelta(days=1), "pattern": f"%{name}%"}).mappings().all()
    result = []
    for row in rows:
        names = {plain for plain, _ in manager_entries(row["manager"] or "")}
        if name not in names:
            continue
        common = any(is_common for plain, is_common in manager_entries(row["manager"] or "") if plain == name)
        result.append({
            "doc_id": row["doc_id"], "receipt_date": _as_date(row["receipt_date"]),
            "work_type": row["work_type"] or "", "customer_name": row["customer_name"] or "",
            "manager": row["manager"] or "", "common": common,
            "fee": float(row["base_fee"] or 0) - float(row["cut_fee"] or 0),
        })
    return result
