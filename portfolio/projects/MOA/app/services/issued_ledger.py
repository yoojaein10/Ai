"""발급 원장 조회 (2026-09-11) — 계산서 등록 화면 목록. 감정서 LIST·입금현황처럼 조건으로 거르고 쪽으로 넘긴다.

원장(a10_issued_taxinvoice)의 실제 문서만 보인다: 테스트 발행(is_test=1)과 입금 적용용 계산서의
감정서별 적용 행(pool_id 있음 — 모계산서 한 장을 나눠 붙인 가상 행)은 뺀다.

작성일자는 write_date, 비었으면 발행일시(issue_dt) 앞 8자리 — MOA 팝빌 행은 write_date 가 비어 있다.
부호: 세금취소는 원장에 음수로, 현금취소는 양수로 들어 있다(읽는 쪽이 -ABS). 목록·합계는 둘 다 음수로 보인다.
번호(숫자·하이픈)로 찾으면 기간을 무시하고 전 기간에서 찾는다 — 감정서 LIST 와 같은 관례.

재무팀 요청(2026-09-11): 헤더 정렬, '감정서번호 없는 것만' 필터, 엑셀 추출, 감정서번호 수정.
번호 수정은 엑셀로 등록한 출처(나라장터·나라빌·국세청·기타)만 — MOA 팝빌·TAMS 로 들어온 건은 원본 시스템이 기준이다.
"""

import re
from datetime import date
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.external_issue import DOC_TYPES, SOURCES, _appraisals_of, is_kb_simple
from app.services.popbill_tax import ISSUE_SOURCES
from app.services.receivables import management_no_filter

DAY = "COALESCE(t.write_date, TRY_CONVERT(date, LEFT(t.issue_dt, 8), 112))"
MAX_PAGE_SIZE = 500
EXPORT_MAX = 50_000
EDITABLE_SOURCES = SOURCES   # 엑셀로 등록한 출처만 번호를 고친다
_NUMBER = re.compile(r"[0-9A-Za-z-]+")


class LedgerQueryError(ValueError):
    pass


def signed(column: str) -> str:
    """목록·합계용 부호 — 현금취소는 원장에 양수라 뒤집는다(세금취소는 이미 음수)."""
    return f"(CASE WHEN t.doc_type = '현금취소' THEN -ABS(t.{column}) ELSE t.{column} END)"


SORTS = {
    "write_date": DAY, "doc_type": "t.doc_type", "doc_id": "t.doc_id", "receiver_name": "t.receiver_name",
    "receiver_corp_num": "t.receiver_corp_num", "supply_cost": signed("supply_cost"), "tax": signed("tax"),
    "total": signed("total"), "nts_confirm": "t.nts_confirm", "source": "t.source", "issue_dt": "t.issue_dt",
    "created_at": "t.created_at",
}
EXPORT_COLUMNS = [
    ("write_date", "작성일자"), ("doc_type", "종류"), ("doc_id", "감정서번호"), ("receiver_name", "공급받는자 상호"),
    ("receiver_corp_num", "사업자번호"), ("supply_cost", "공급가액"), ("tax", "세액"), ("total", "합계"),
    ("nts_confirm", "승인번호"), ("source", "출처"), ("issue_dt", "발행일시"), ("created_at", "등록일시"),
]


def is_number_keyword(keyword: str) -> bool:
    kw = keyword.strip()
    return bool(kw) and bool(_NUMBER.fullmatch(kw)) and any(ch.isdigit() for ch in kw)


def order_sql(sort_by: str = "", sort_order: str = "desc") -> str:
    """정렬 — 허용한 열만(SQL 에 그대로 들어가므로 이름을 받지 않고 표에서 고른다). 같은 값은 id 순."""
    if sort_by and sort_by not in SORTS:
        raise LedgerQueryError("정렬할 수 없는 열입니다.")
    direction = "ASC" if sort_order == "asc" else "DESC"
    return f"{SORTS.get(sort_by) or DAY} {direction}, t.id {direction}"


def build_where(
    *, prefixes: "list[str] | None", include_kb: bool, date_from: "date | None", date_to: "date | None",
    doc_type: str = "", source: str = "", keyword: str = "", missing_doc: bool = False,
) -> "tuple[str, dict[str, Any]]":
    """조회 조건 → WHERE 절과 바인드 값. prefixes=None 은 전 지사(지사 조건 없음)."""
    clauses = ["t.is_test = 0", "t.pool_id IS NULL"]
    params: "dict[str, Any]" = {}
    kw = keyword.strip()
    number = is_number_keyword(kw)
    if not number:
        if not (date_from and date_to):
            raise LedgerQueryError("작성일자 기간을 고르세요.")
        if date_from > date_to:
            raise LedgerQueryError("시작일이 종료일보다 늦습니다.")
        clauses.append(f"{DAY} >= :df AND {DAY} < DATEADD(day, 1, :dt)")
        params.update(df=date_from, dt=date_to)
    if prefixes is not None:
        office_sql, office_params = management_no_filter(prefixes, "t.doc_id")
        if include_kb:   # 국민약식 번호(400581444)는 지사 접두사가 없다 — 본사 몫으로 같이 본다
            office_sql = f"({office_sql} OR t.doc_id LIKE '4________')"
        clauses.append(office_sql)
        params.update(office_params)
    if doc_type:
        if doc_type not in DOC_TYPES:
            raise LedgerQueryError("종류는 " + "·".join(DOC_TYPES) + " 중 하나")
        clauses.append("t.doc_type = :doc_type")
        params["doc_type"] = doc_type
    if source:
        if source not in ISSUE_SOURCES:
            raise LedgerQueryError("출처는 " + "·".join(ISSUE_SOURCES) + " 중 하나")
        clauses.append("t.source = :source")
        params["source"] = source
    if missing_doc:   # 감정서번호를 채워야 할 건 (TAMS 현금영수증 등)
        clauses.append("LTRIM(RTRIM(ISNULL(t.doc_id, ''))) = ''")
    if kw:
        if number:
            digits = re.sub(r"\D", "", kw)
            clauses.append("(t.doc_id LIKE CAST(:kw AS varchar(100)) OR t.nts_confirm LIKE CAST(:kwc AS varchar(30))"
                           " OR t.receiver_corp_num LIKE CAST(:kwd AS varchar(20)))")
            params.update(kw=f"%{kw}%", kwc=f"%{kw.replace('-', '')}%", kwd=f"%{digits}%")
        else:
            clauses.append("t.receiver_name LIKE :kwn")
            params["kwn"] = f"%{kw}%"
    return " AND ".join(clauses), params


def _issue_text(value: Any) -> str:
    """'20260909110321' → '2026-09-09 11:03'. 모양이 다르면 그대로."""
    raw = str(value or "").strip()
    if len(raw) >= 12 and raw[:12].isdigit():
        return f"{raw[:4]}-{raw[4:6]}-{raw[6:8]} {raw[8:10]}:{raw[10:12]}"
    if len(raw) == 8 and raw.isdigit():
        return f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"
    return raw


def _num(value: Any) -> int:
    return int(round(float(value or 0)))


_SELECT = f"""
    SELECT t.id, CONVERT(varchar(10), {DAY}, 23) AS write_date, t.doc_type, t.doc_id, t.receiver_name,
           t.receiver_corp_num, {signed('supply_cost')} AS supply_cost, {signed('tax')} AS tax,
           {signed('total')} AS total, t.nts_confirm, t.source, t.issue_dt,
           CONVERT(varchar(16), t.created_at, 120) AS created_at
"""


def _item(r: Any) -> "dict[str, Any]":
    source = r["source"] or ""
    return {
        "id": int(r["id"]), "write_date": r["write_date"] or "", "doc_type": r["doc_type"] or "",
        "doc_id": (r["doc_id"] or "").strip(), "receiver_name": (r["receiver_name"] or "").strip(),
        "receiver_corp_num": (r["receiver_corp_num"] or "").strip(),
        "supply_cost": _num(r["supply_cost"]), "tax": _num(r["tax"]), "total": _num(r["total"]),
        "nts_confirm": (r["nts_confirm"] or "").strip(), "source": source,
        "issue_dt": _issue_text(r["issue_dt"]), "created_at": r["created_at"] or "",
        "editable": source in EDITABLE_SOURCES,
    }


def list_ledger(
    db: Session, where: str, params: "dict[str, Any]", page: int, page_size: int, order: str = "",
) -> "dict[str, Any]":
    """한 쪽 목록 + 조건 전체 건수·합계(공급가액·세액·합계, 취소는 빼서)."""
    page_size = max(1, min(int(page_size), MAX_PAGE_SIZE))
    page = max(1, int(page))
    base = f"FROM dbo.a10_issued_taxinvoice t WHERE {where}"
    sums = db.execute(
        text(f"SELECT COUNT(*) AS n, SUM({signed('supply_cost')}) AS supply, SUM({signed('tax')}) AS tax, "
             f"SUM({signed('total')}) AS total {base}"),
        params,
    ).mappings().one()
    rows = db.execute(
        text(f"{_SELECT} {base} ORDER BY {order or order_sql()} OFFSET :offset ROWS FETCH NEXT :size ROWS ONLY"),
        {**params, "offset": (page - 1) * page_size, "size": page_size},
    ).mappings().all()
    return {
        "items": [_item(r) for r in rows], "page": page, "page_size": page_size, "total": int(sums["n"] or 0),
        "sums": {"supply_cost": _num(sums["supply"]), "tax": _num(sums["tax"]), "total": _num(sums["total"])},
    }


def export_rows(db: Session, where: str, params: "dict[str, Any]", order: str = "") -> "list[dict[str, Any]]":
    """엑셀 추출 — 조건 전체(화면 정렬 그대로). 너무 크면 기간을 줄이라고 막는다."""
    count = int(db.execute(text(f"SELECT COUNT(*) FROM dbo.a10_issued_taxinvoice t WHERE {where}"), params).scalar() or 0)
    if count > EXPORT_MAX:
        raise LedgerQueryError(f"{count:,}건입니다 — 엑셀은 {EXPORT_MAX:,}건까지. 기간이나 조건을 줄이세요.")
    rows = db.execute(
        text(f"{_SELECT} FROM dbo.a10_issued_taxinvoice t WHERE {where} ORDER BY {order or order_sql()}"), params,
    ).mappings().all()
    return [_item(r) for r in rows]


def update_doc(db: Session, row_id: int, doc_id: str) -> "dict[str, Any]":
    """감정서번호 고치기 — 엑셀로 등록한 출처만, 감정서(또는 국민약식 번호)가 있어야 한다."""
    new = str(doc_id or "").strip()
    if not new:
        raise LedgerQueryError("감정서번호를 적으세요.")
    row = db.execute(
        text("SELECT id, source, doc_id, is_test, pool_id FROM dbo.a10_issued_taxinvoice WHERE id = :i"), {"i": int(row_id)},
    ).mappings().first()
    if row is None or row["is_test"] or row["pool_id"] is not None:
        raise LedgerQueryError("고칠 계산서가 없습니다.")
    if row["source"] not in EDITABLE_SOURCES:
        # 출처는 들어온 경로다(TAMS 행도 발급은 위하고일 수 있다) — '발급분'이라 부르지 않는다
        raise LedgerQueryError(f"{row['source']}로 들어온 건은 원본 시스템에서 고칩니다 — 엑셀로 등록한 건만 여기서 고칩니다.")
    if not is_kb_simple(new) and new not in _appraisals_of(db, [new]):
        raise LedgerQueryError(f"감정서 없음: {new}")
    db.execute(text("UPDATE dbo.a10_issued_taxinvoice SET doc_id = :d WHERE id = :i"), {"d": new[:100], "i": int(row_id)})
    db.commit()
    return {"id": int(row_id), "doc_id": new, "before": (row["doc_id"] or "").strip()}
