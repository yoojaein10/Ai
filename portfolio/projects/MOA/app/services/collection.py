"""배분/수금 진행 — 감정 산정액(apw_masterex 청구금액) 대비 실제 입금 진행률.

공동감정 배분건처럼 '입금분만 전표 계상'하는 경우, 전표 기반 미수는 완납으로 보이지만
산정액 대비로는 아직 덜 받은 상태다. 이 화면이 산정액-입금 차이를 드러낸다.
받기 시작했으나(입금>0) 산정액에 못 미치는(부분수금) 건을 본다.
"""

from datetime import date
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import get_settings


def _source_db() -> str:
    name = get_settings().mssql_source_db
    if not name.replace("_", "").isalnum():
        raise RuntimeError("MSSQL_SOURCE_DB 이름이 올바르지 않습니다.")
    return name


def collection_progress(
    db: Session,
    date_from: date,
    date_to: date,
    office_code: str = "10",
    doc_id: "str | None" = None,
    manager: "str | None" = None,
    scope_person: "str | None" = None,
) -> "dict[str, Any]":
    """발송일 기준 기간의 감정서 중, 입금은 시작됐으나 산정액에 못 미치는 부분수금 건.

    감정서번호로 찾을 때는 발송일 조건을 빼고 전체 기간을 본다 — 번호를 아는 사람은
    발송일을 모르는 경우가 많아, 기간에 걸려 안 나오면 "그런 건 없다"고 오해한다.
    유치자는 기간을 좁혀 보는 조건이므로 발송일 조건을 그대로 둔다.
    """
    src = _source_db()
    params: "dict[str, Any]" = {"office": office_code, "f": date_from, "t": date_to}
    if doc_id:
        period_sql = "AND m.DocID LIKE CAST(:doc AS VARCHAR(50))"
        params["doc"] = f"%{doc_id}%"
    else:
        period_sql = "AND m.SendDate BETWEEN :f AND :t"
    # 공동유치는 유치자가 '공(홍길동)'이라 이름만 넣어도 함께 걸리도록 부분검색한다.
    manager_sql = ""
    if manager:
        manager_sql = "AND m.Manager LIKE CAST(:manager AS VARCHAR(50))"
        params["manager"] = f"%{manager}%"
    # 데이터 조회 범위: 다른 직원 조회 권한이 없으면(view_other_users=OFF) 본인 유치/조사 건으로 고정한다.
    # 클라이언트 manager 검색과 별개로 무조건 AND 결합해, 남의 감정서별 산정액·입금이 새지 않게 한다.
    scope_sql = ""
    if scope_person:
        scope_sql = "AND (m.Manager LIKE :scope_person OR m.Charge LIKE :scope_person)"
        params["scope_person"] = f"%{scope_person}%"
    rows = db.execute(
        text(
            f"""
            SELECT m.DocID AS doc, RTRIM(m.CustName) AS cust, RTRIM(m.LWorkinfo) AS work,
                   m.SendDate AS send_date, m.[청구금액] AS assessed,
                   ISNULL(b.received_amount, 0) AS received
            FROM [{src}].dbo.apw_masterex m
            LEFT JOIN dbo.a10_receivable_summary b ON b.doc_id = m.DocID
            WHERE m.Office = CAST(:office AS varchar(10))
              {period_sql}
              {manager_sql}
              {scope_sql}
              AND m.[청구금액] > 0
              AND ISNULL(b.received_amount, 0) > 0
              AND m.[청구금액] - ISNULL(b.received_amount, 0) > 1000
            ORDER BY m.[청구금액] - ISNULL(b.received_amount, 0) DESC
            """
        ),
        params,
    ).mappings().all()
    items = []
    for r in rows:
        assessed = float(r["assessed"] or 0)
        received = float(r["received"] or 0)
        unpaid = assessed - received
        items.append({
            "doc": (r["doc"] or "").strip(),
            "cust": (r["cust"] or "").strip(),
            "work": (r["work"] or "").strip(),
            "send_date": r["send_date"].date().isoformat() if r["send_date"] else None,
            "assessed": assessed,
            "received": received,
            "unpaid": unpaid,
            "rate": round(received / assessed * 100, 1) if assessed else 0,
        })
    return {
        "period": {"from": date_from.isoformat(), "to": date_to.isoformat()},
        "count": len(items),
        "assessed_total": sum(i["assessed"] for i in items),
        "received_total": sum(i["received"] for i in items),
        "unpaid_total": sum(i["unpaid"] for i in items),
        "items": items,
    }
