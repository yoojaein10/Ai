"""엑셀 업로드 대사 — 올린 엑셀의 감정서번호·금액을 우리 매출(전표 401계열)과 맞춰본다.

오늘(2026-07-24) TAMS 엑셀을 손으로 대조하던 걸 범용 기능으로. 특정 포맷에 안 묶이고
어떤 엑셀이든 '감정서번호 열 + 금액 열'만 지정하면 대사한다.

대사 대상 = a10_voucher_cache의 401계열 순액(대변-차변)을 감정서(관리번호)별 합산 (본사).
"""

import re
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.services.office_lookup import get_office

DOC_RE = re.compile(r"\d{2}-\d{4}-[A-Za-z0-9]-\d{4}")


def _norm(doc: str) -> str:
    """감정서번호 표준형 추출. 없으면 원문(공백/점 정리)."""
    m = DOC_RE.search(str(doc or ""))
    return m.group(0) if m else str(doc or "").strip().rstrip(".")


def cache_sales_by_doc(
    db: Session, office_code: str = "10",
    date_from: "Any" = None, date_to: "Any" = None,
) -> "dict[str, float]":
    """감정서별 우리 매출(401계열 순액) 합계. 대사 기준값.

    date_from/date_to를 주면 전표일자로 기간을 한정한다(엑셀과 같은 기간 대사).
    """
    office = get_office(db, office_code)
    division = office.division_code if office else "1000"
    where = ["division_code = CAST(:div AS varchar(10))", "account_code LIKE '401%'"]
    params: "dict[str, Any]" = {"div": division}
    if date_from and date_to:
        where.append("voucher_date BETWEEN :f AND :t")
        params["f"] = date_from
        params["t"] = date_to
    rows = db.execute(
        text(
            "SELECT LTRIM(RTRIM(management_no)) AS mgmt, "
            "SUM(CASE WHEN debit_credit='4' THEN amount "
            "         WHEN debit_credit='3' THEN -amount ELSE 0 END) AS net "
            "FROM dbo.a10_voucher_cache "
            f"WHERE {' AND '.join(where)} "
            "GROUP BY LTRIM(RTRIM(management_no))"
        ),
        params,
    ).mappings().all()
    out: "dict[str, float]" = {}
    for r in rows:
        key = _norm(r["mgmt"])
        if key:
            out[key] = out.get(key, 0.0) + float(r["net"] or 0)
    return out


def reconcile(
    db: Session, excel_pairs: "list[tuple[str, float]]", office_code: str = "10",
    date_from: "Any" = None, date_to: "Any" = None,
) -> "dict[str, Any]":
    """excel_pairs = [(감정서번호, 금액)]. 우리 매출과 대사한 결과.

    date_from/date_to를 주면 우리 매출을 그 전표일자 기간으로 한정(엑셀 기간과 맞춤).
    """
    excel: "dict[str, float]" = {}
    for doc, amt in excel_pairs:
        key = _norm(doc)
        if key:
            excel[key] = excel.get(key, 0.0) + float(amt or 0)
    cache = cache_sales_by_doc(db, office_code, date_from, date_to)

    # 어긋남 짝 후보: (우리 net - 그 감정서 엑셀금액)이 빠진 금액과 일치하는 감정서
    surplus: "dict[int, list[str]]" = {}
    for k, net in cache.items():
        diff = net - excel.get(k, 0.0)
        if abs(diff) > 0.5:
            surplus.setdefault(round(diff), []).append(k)

    matched, amount_diff, excel_only, cache_only = [], [], [], []
    for doc, amt in sorted(excel.items(), key=lambda x: -abs(x[1])):
        if doc in cache:
            if abs(cache[doc] - amt) < 1:
                matched.append({"doc": doc, "amount": amt})
            else:
                amount_diff.append({"doc": doc, "excel": amt, "ours": cache[doc],
                                    "diff": cache[doc] - amt})
        else:
            partners = [p for p in surplus.get(round(amt), []) if p not in excel]
            excel_only.append({"doc": doc, "amount": amt,
                               "partner": ", ".join(partners[:3])})
    excel_keys = set(excel)
    for doc, net in sorted(cache.items(), key=lambda x: -abs(x[1])):
        if doc not in excel_keys and abs(net) >= 1:
            cache_only.append({"doc": doc, "amount": net})

    ex_total = sum(excel.values())
    our_total = sum(cache.values())
    return {
        "excel_total": ex_total,
        "our_total": our_total,
        "diff": our_total - ex_total,
        "excel_docs": len(excel),
        "our_docs": len(cache),
        "groups": [
            {"key": "matched", "title": "일치", "count": len(matched),
             "amount": sum(x["amount"] for x in matched), "items": matched[:1000]},
            {"key": "amount_diff", "title": "금액 다름", "count": len(amount_diff),
             "amount": sum(x["diff"] for x in amount_diff), "items": amount_diff[:1000]},
            {"key": "excel_only", "title": "엑셀에만 있음", "count": len(excel_only),
             "amount": sum(x["amount"] for x in excel_only), "items": excel_only[:1000]},
            {"key": "cache_only", "title": "우리에만 있음", "count": len(cache_only),
             "amount": sum(x["amount"] for x in cache_only), "items": cache_only[:1000]},
        ],
    }
