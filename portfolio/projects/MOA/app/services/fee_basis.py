"""보수기준 점검 단일 서비스.

업무실적 모집단, 수수료 계산, JUN/APWorks 근거, 동결 스냅숏, 의견 저장과
사전생성 CLI를 한 기능 경계에 둔다. 운영 배포에서 fee-review 모듈은 필요하지 않다.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import hmac
import json
import logging
import re
import secrets
import threading
import time
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from math import ceil, floor
from typing import Any, Iterator, Literal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    LargeBinary,
    String,
    Unicode,
    UnicodeText,
    func,
    select,
    text,
)
from sqlalchemy.dialects import mssql
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.config import get_settings
from app.database import (
    Base,
    get_engine,
    get_gamjun_parse_engine,
    get_session_factory,
    get_source_engine,
)
from app.models.office_map import OfficeMap
from app.services import fee_basis_rules as rules
from app.services.fee_basis_evidence import (
    KEYWORD_RULE_VERSION,
    SEARCH_ENGINE_VERSION,
    attach_review_evidence,
)
from app.services.work_report import (
    POPULATION_VERSION,
    Basis,
    Half,
    _create_sales_temp,
    _resolve_appcode_cursor,
    _select_doc_ids_cursor,
    build_kapa_rows,
    half_month_range,
    quarter_bungi,
    select_doc_ids_with_precedent,
)


# ======================== 업무실적 모집단과 기본 판정 ========================

logger = logging.getLogger(__name__)

Filter = Literal["전체", "불일치", "미입력", "금액이탈", "할인위험", "격차발생"]

# 격차율이 '발생'한 것으로 보는 하한 (비율). 화면은 격차율을 (gap*100).toFixed(1) 로
# 찍고 그 결과가 0.0 이면 부호를 떼어 '0.0%' 하나로 모은다 — 요율적용금액은 원 미만이
# 남고 청구액은 원 단위라 정확히 기준대로 청구해도 1원쯤 어긋나기 때문이다.
# 필터도 같은 선을 써야 화면에 '0.0%'로 보이는 행이 '격차 발생'으로 딸려오지 않는다.
GAP_OCCURRED_MIN = 0.0005  # = 0.05%

# 금액 비교를 보류하는 사유. 보수기준 검토(fee_review)와 같은 말을 쓴다 — 같은 상태를
# 두 화면이 다르게 부르면 재무팀이 두 목록을 대조할 수 없다.
FEE_CONFLICT = "수수료 원천 충돌"      # 청구행마다 금액이 달라 대표값을 못 고른다
EXPENSE_ONLY = "실비만"                # 감정수수료 계상이 없다 — 금액은 실비다
NOT_COMPARABLE_APPRAISAL = "평가액 없음"  # 보수표를 적용할 평가액이 없다
NO_AMOUNT_SOURCE = "금액 원천 없음"     # 모집단에는 있는데 협회양식 행이 없다
ZERO_FEE = "0원 청구 확인"             # 합산청구 등으로 이 건에는 0원 계상 — 이탈 아님

_DATE_RE = re.compile(r"(\d{4})[-./년\s]*(\d{1,2})[-./월\s]*(\d{1,2})")


def _masterex_table() -> str:
    database = get_settings().mssql_source_db
    if not database.replace("_", "").isalnum():
        raise RuntimeError("MSSQL_SOURCE_DB 이름이 올바르지 않습니다.")
    return f"[{database}].dbo.apw_masterex"


def build_fee_basis_report(
    db: Session,
    *,
    office_id: str,
    year: int,
    month: int,
    half: Half,
    basis: Basis,
    flt: Filter = "전체",
    page: int = 1,
    page_size: int = 50,
) -> dict[str, Any]:
    if not office_id.isalnum():
        raise ValueError("office_id 형식이 올바르지 않습니다.")
    start, end = half_month_range(year, month, half)
    bungi = quarter_bungi(year, month)

    raw = get_source_engine().raw_connection()
    try:
        cursor = raw.cursor()
        appcode = _resolve_appcode_cursor(cursor, office_id)
        if basis == "매출":
            _create_sales_temp(cursor, start, end)
        # 업무실적과 같은 모집단을 본다 — 정비사업+시군구는 발송 전이라도 선례 대상이라
        # 두 화면에 같이 떠야 한다(2026-08-06 사용자 결정). 청구가 없는 건은
        # _fee_judgement 가 fee_state=NO_AMOUNT_SOURCE 로 표시하므로 판정이 뭉개지지 않는다.
        selected, precedent_extra = select_doc_ids_with_precedent(
            cursor, appcode, bungi, month, start, end, basis
        )
        doc_ids = [*selected, *precedent_extra]
        entered = _entered_codes(cursor, doc_ids)
        code_names = _susuwhy_names(cursor)
        # 재평가 이력을 먼저 구해서 '직전 감정서'의 기준시점까지 한 번에 가져온다.
        # 현재 목록 것만 가져오면 시점 비교가 늘 None 이 돼 코드13/14가 안 갈린다.
        reappraisal = _reappraisal_history(db, doc_ids)
        prior_ids = [v[1] for v in reappraisal.values() if v and v[1]]
        price_points = _price_point_dates(cursor, [*doc_ids, *prior_ids])
    finally:
        raw.close()

    meta = _masterex_meta(db, doc_ids)
    # 파싱 DB(gamjundw)가 죽어도 조회는 계속돼야 한다 — 본문 근거만 빠지고
    # 목적·이력 판별은 그대로 동작한다. 실패 사실은 요약(jun_error)로 화면에 알린다.
    try:
        parsed = _parsed_signals(doc_ids)
    except Exception:
        logger.warning("감정서 파싱 DB 조회 실패 — 본문 근거 없이 진행", exc_info=True)
        parsed = {}
    amounts = _fee_amounts(
        db, office_id=office_id, year=year, month=month, half=half, basis=basis
    )
    # 적용 요율은 계산값이 아니라 수임 시 정하는 선택값이다(APW_BILL.SusuRate).
    rates = fetch_rates(doc_ids)

    items = []
    for doc_id in doc_ids:
        info = meta.get(doc_id, {})
        parse = parsed.get(doc_id, {})
        prior = reappraisal.get(doc_id)
        candidates = rules.detect(
            work=info.get("work"),
            purpose=info.get("purpose"),
            receipt_date=info.get("receipt_date"),
            # 파싱값 우선, 없으면 원장 기준시점(PricePointDate)으로 메운다.
            appraisal_date=parse.get("appraisal_date") or price_points.get(doc_id),
            pages=parse.get("pages"),
            reappraisal_months=prior and prior[0],
            reappraisal_doc_id=prior and prior[1],
            # 3개월 이내 재평가는 기준시점이 같으냐로 코드13/14가 갈린다.
            # 둘 중 하나라도 기준시점을 모르면 None — 그때는 예전처럼 14로 둔다.
            reappraisal_same_price_point=_same_price_point(
                price_points.get(doc_id), prior and price_points.get(prior[1])
            ),
        )
        for candidate in candidates:  # 수수료청구서에서 보던 항목명 그대로 표시
            candidate["label"] = code_names.get(candidate["code"], candidate["label"])
        entry = entered.get(doc_id, {})
        verdict = rules.verdict(entry.get("code"), candidates)
        entered_code = entry.get("code")
        rate_info = rates.get(doc_id) or {}
        # 할인 적정성(업무연락 제2026-38호) — 밴드 밑으로 깎였다면 조문상 허용
        # 구간인지. 재평가 이력·목적 후보를 이미 구해 뒀으므로 추가 조회가 없다.
        discount = rules.discount_judgement(
            rate_info.get("susu_dc"),
            conflict=bool(rate_info.get("conflict")),
            candidates=candidates,
            entered_code=entered_code,
            purpose=info.get("purpose"),
            work=info.get("work"),
        )
        items.append(
            {
                **_fee_judgement(
                    amounts.get(doc_id), info.get("receipt_date"),
                    rate_source=rates.get(doc_id),
                ),
                "discount_state": discount["state"],
                "discount_note": discount["note"],
                "doc_id": doc_id,
                "receipt_date": _iso(info.get("receipt_date")),
                "send_date": _iso(info.get("send_date")),
                "cust_name": info.get("cust_name") or "",
                "work": info.get("work") or "",
                "purpose": info.get("purpose") or "",
                "manager": info.get("manager") or "",
                "entered_code": entered_code,
                "entered_label": code_names.get(
                    entered_code or 0, rules.FEE_CODE_LABELS.get(entered_code or 0, "")
                ),
                "entered_bigo": entry.get("bigo") or "",
                "candidates": candidates,
                "verdict": verdict,
                "parsed": bool(parse),
            }
        )

    summary = {
        "total": len(items),
        "match": sum(1 for i in items if i["verdict"] == "일치"),
        "mismatch": sum(1 for i in items if i["verdict"] == "불일치"),
        "missing": sum(1 for i in items if i["verdict"] == "미입력"),
        "parsed": sum(1 for i in items if i["parsed"]),
        # 금액 이탈 — 보수기준 코드와 별개 축이다. 코드를 맞게 골랐어도 금액이 틀릴 수 있다.
        "fee_below": sum(
            1 for i in items if i["deviation_direction"] == DEVIATION_BELOW
        ),
        "fee_above": sum(
            1 for i in items if i["deviation_direction"] == DEVIATION_ABOVE
        ),
        "fee_within": sum(
            1 for i in items if i["deviation_direction"] == DEVIATION_WITHIN
        ),
        "fee_uncomparable": sum(1 for i in items if i["fee_state"]),
        # 할인 적정성 — 한도 초과·근거 없음이 조치 대상이다(업무연락 제2026-38호).
        "discount_flagged": sum(
            1 for i in items
            if i["discount_state"] in (
                rules.DISCOUNT_STATE_OVER, rules.DISCOUNT_STATE_NO_BASIS
            )
        ),
        "discount_ok": sum(
            1 for i in items if i["discount_state"] == rules.DISCOUNT_STATE_OK
        ),
    }
    if flt == "불일치":
        items = [i for i in items if i["verdict"] == "불일치"]
    elif flt == "미입력":
        items = [i for i in items if i["verdict"] == "미입력"]
    elif flt == "금액이탈":
        items = [
            i for i in items
            if i["deviation_direction"] in (
                DEVIATION_BELOW, DEVIATION_ABOVE
            )
        ]
    elif flt == "할인위험":
        items = [
            i for i in items
            if i["discount_state"] in (
                rules.DISCOUNT_STATE_OVER, rules.DISCOUNT_STATE_NO_BASIS
            )
        ]

    filtered_total = len(items)
    offset = (page - 1) * page_size
    return {
        "summary": summary,
        "total": filtered_total,
        "page": page,
        "page_size": page_size,
        "items": items[offset:offset + page_size],
    }


def _iso(value: Any) -> str | None:
    if isinstance(value, (datetime, date)):
        return value.date().isoformat() if isinstance(value, datetime) else value.isoformat()
    return None


def _fee_amounts(
    db: Session,
    *,
    office_id: str,
    year: int,
    month: int,
    half: Half,
    basis: Basis,
) -> "dict[str, dict[str, Any]]":
    """감정서별 평가액·순수수료. 협회양식과 같은 원천(build_kapa_rows)을 쓴다.

    직접 SQL을 새로 짜지 않는 이유: 평가액·순수수료는 APW_MASTER와 청구행(APW_BILL)을
    함께 봐야 나오고, 그 조합은 build_kapa_rows가 재무팀 엑셀 대조로 이미 검증됐다.
    여기서 다시 만들면 같은 감정서에 두 화면이 다른 금액을 보여줄 수 있다.

    한 감정서에 청구행이 여럿이고 금액이 다르면 대표값을 고르지 않고 충돌로 남긴다.
    """
    report = build_kapa_rows(
        db, office_id=office_id, year=year, month=month, half=half, basis=basis
    )
    grouped: "dict[str, list[dict[str, Any]]]" = {}
    for row in report.get("rows") or []:
        doc_id = str(row.get("ID_NUM") or "").strip()
        if doc_id:
            grouped.setdefault(doc_id, []).append(row)

    found: "dict[str, dict[str, Any]]" = {}
    for doc_id, rows in grouped.items():
        signatures = {
            (
                to_number(row.get("GAMGA")),
                to_number(row.get("SUSU")),
            )
            for row in rows
        }
        if len(signatures) > 1:
            found[doc_id] = {"conflict": True, "row_count": len(rows)}
            continue
        appraisal, actual = next(iter(signatures))
        found[doc_id] = {
            "conflict": False,
            "row_count": len(rows),
            "appraisal_amount": appraisal,
            "actual_fee": actual,
            # NO_FEE: 입금 신호로만 잡혔는데 감정수수료(4010001) 계상이 없는 건.
            # 금액이 있어도 그건 실비(여비및기타)라 보수표와 비교할 값이 아니다.
            "no_fee": any(bool(row.get("NO_FEE")) for row in rows),
        }
    return found


def _fee_judgement(
    amount: "dict[str, Any] | None",
    receipt_date: Any,
    *,
    rate_source: "dict[str, Any] | None" = None,
) -> "dict[str, Any]":
    """금액 이탈 판정 필드. 계산 불가 사유를 숨기지 않고 fee_state로 남긴다.

    판정 순서는 보수기준 검토(fee_review._comparability)와 같게 둔다. 두 화면이 같은
    감정서에 다른 답을 내면 재무팀이 어느 쪽을 믿을지 알 수 없다.
    """
    blank = {
        "appraisal_amount": None,
        "actual_fee": None,
        "standard_fee": None,
        "lower_fee": None,
        "upper_fee": None,
        "reference_gap_rate": None,
        "deviation_direction": None,
        "fee_state": "",
        **describe(
            rate_source, billed_fee=None, standard_fee=None,
            lower_fee=None, upper_fee=None,
        ),
    }
    if amount is None:
        # 모집단에는 있는데 협회양식 행이 없는 건. 조용히 0원으로 뭉개지 않는다.
        return {**blank, "fee_state": NO_AMOUNT_SOURCE}
    if amount.get("conflict"):
        return {**blank, "fee_state": FEE_CONFLICT}

    appraisal = amount.get("appraisal_amount")
    actual = amount.get("actual_fee")
    if amount.get("no_fee"):
        # 감정수수료 계상이 없는 건. 금액이 있어도 그건 실비라 보수표 비교 대상이 아니다.
        # 이걸 빼먹으면 실비 금액을 수수료로 오인해 '기준 내'로 잘못 판정한다(실측 3건).
        return {**blank, "actual_fee": actual, "fee_state": EXPENSE_ONLY}
    if appraisal is None or float(appraisal) <= 0:
        # 평가액이 없으면 보수표를 적용할 수 없다(컨설팅·자문 등).
        return {**blank, "actual_fee": actual, "fee_state": NOT_COMPARABLE_APPRAISAL}
    if actual is not None and float(actual) == 0:
        # 0원 청구는 하한 미만 이탈이 아니라 합산청구 등으로 이 건에 계상이 없는
        # 상태다. 보수기준 검토(fee_review)의 ZERO_FEE_REVIEW 게이트와 같은 판단이다.
        return {**blank, "appraisal_amount": float(appraisal),
                "actual_fee": 0.0, "fee_state": ZERO_FEE}

    calc = evaluate(
        appraisal_amount=appraisal, actual_fee=actual, receipt_date=receipt_date
    )
    lower = calc["lower_fee"]
    rate_info = describe(
        rate_source,
        billed_fee=calc["actual_fee"],
        standard_fee=calc["standard_fee"],
        lower_fee=lower,
        upper_fee=calc["upper_fee"],
    )
    # 격차율의 기준선은 **요율적용금액**이다 — 재무팀 엑셀(보수기준검토_YYYY-MM)의
    # Z열 정의 그대로다: `청구 순수수료(W) ÷ 적용 요율에 따른 수수료(Y) − 1`.
    # 2026-06·07 엑셀 477행 전수에서 이 식이 원 단위까지 맞는다.
    #
    # 전에는 하한(lower)으로 나눴다. 그 엑셀은 **요율이 전부 0.8**이라 요율적용금액과
    # 하한이 같은 값이어서 두 식이 구분되지 않았고, 대조해도 100% 맞아 보였다.
    # 우리 데이터는 요율이 섞여 있어(2026-07 실측: 0.8이 479건·1.0이 49건) 거기서
    # 갈린다 — 요율 1.0 건은 기준액대로 청구해도 하한 대비 +25%가 찍혀,
    # 정상 건을 이탈로 헛짚게 만들었다(실측: 음수 44건 중 32건이 허수였다).
    #
    # 요율을 모르면(rate_conflict·요율 미상) 기준선이 없으므로 격차율도 내지 않는다 —
    # 하한으로 대신 재면 그게 바로 위의 허수를 되살리는 길이다.
    applied = rate_info.get("rate_applied_fee")
    return {
        **rate_info,
        "appraisal_amount": calc["appraisal_amount"],
        "actual_fee": calc["actual_fee"],
        "standard_fee": calc["standard_fee"],
        "lower_fee": lower,
        "upper_fee": calc["upper_fee"],
        "reference_gap_rate": (
            (float(actual) / float(applied) - 1)
            if actual is not None and applied else None
        ),
        "deviation_direction": calc["deviation_direction"],
        "fee_state": "",
    }


def _susuwhy_names(cursor: Any) -> dict[int, str]:
    """보수기준 항목명(APW_IW_SusuWhy) — 수수료청구서에 보이는 명칭 그대로 쓴다."""
    cursor.execute("SELECT Code, Contents FROM dbo.APW_IW_SusuWhy")
    return {
        int(code): re.sub(r"\s+", " ", str(contents or "").strip())
        for code, contents in cursor.fetchall()
        if code is not None
    }


def _entered_codes(cursor: Any, doc_ids: list[str]) -> dict[str, dict[str, Any]]:
    """수수료청구서에서 고른 보수기준(APW_IW_SuSuList). 감정서당 사실상 1건."""
    found: dict[str, dict[str, Any]] = {}
    for chunk in _chunks(doc_ids, 500):
        placeholders = ", ".join("?" for _ in chunk)
        cursor.execute(
            "SELECT RTRIM(Docid), Code, RTRIM(ISNULL(Bigo, '')) "
            f"FROM dbo.APW_IW_SuSuList WHERE Docid IN ({placeholders})",
            chunk,
        )
        for doc, code, bigo in cursor.fetchall():
            found[str(doc).strip()] = {"code": int(code or 0) or None, "bigo": bigo}
    return found


def _same_price_point(current: Any, prior: Any) -> "bool | None":
    """두 감정서의 기준시점이 같은가. 하나라도 모르면 None(판단 보류)."""
    if current is None or prior is None:
        return None
    left = current.date() if isinstance(current, datetime) else current
    right = prior.date() if isinstance(prior, datetime) else prior
    return left == right


def _price_point_dates(cursor: Any, doc_ids: list[str]) -> dict[str, Any]:
    """기준시점(APW_DOCUMENT.PricePointDate). 감정서당 1행.

    협회양식이 CONSULTDATE 로 쓰는 바로 그 컬럼이다
    (app/services/sql/work_report_mapping.sql:27 `D.PRICEPOINTDATE AS CONSULTDATE`).

    지금까지 기준시점을 PDF 파싱값에서만 읽었는데 커버리지가 14.5% 뿐이라
    제5조 소급(코드2)·재평가 시점동일(코드13/14) 판정이 6분의 1만 돌았다.
    이 컬럼은 90.7%가 채워져 있고, 둘 다 있는 2,607건 중 84.1%가 날짜까지 같다
    (2026-08-07 실측). 파싱값이 있으면 그것을 우선하고 없을 때 이 값으로 메운다.
    """
    found: dict[str, Any] = {}
    docs = [doc for doc in doc_ids if doc]
    for start in range(0, len(docs), 500):
        chunk = docs[start:start + 500]
        placeholders = ", ".join("?" for _ in chunk)
        cursor.execute(
            "SELECT RTRIM(m.DocID), d.PricePointDate "
            "FROM APW_MASTER m JOIN APW_DOCUMENT d ON d.MasterID = m.MASTERID "
            f"WHERE m.DocID IN ({placeholders}) AND d.PricePointDate IS NOT NULL",
            chunk,
        )
        for doc, price_point in cursor.fetchall():
            if price_point is not None:
                found[str(doc).strip()] = price_point
    return found


def _masterex_meta(db: Session, doc_ids: list[str]) -> dict[str, dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    for chunk in _chunks(doc_ids, 500):
        placeholders = ", ".join(f"CAST(:d{i} AS VARCHAR(50))" for i in range(len(chunk)))
        rows = db.execute(
            text(
                "SELECT RTRIM(DocID), ReceiptDate, SendDate, CustName, "
                "LWorkinfo, LPurpose, Manager "
                f"FROM {_masterex_table()} WHERE DocID IN ({placeholders})"
            ),
            {f"d{i}": doc for i, doc in enumerate(chunk)},
        )
        for doc, receipt, send, cust, work, purpose, manager in rows:
            found[str(doc).strip()] = {
                "receipt_date": receipt,
                "send_date": send,
                "cust_name": (cust or "").strip(),
                "work": (work or "").strip(),
                "purpose": (purpose or "").strip(),
                "manager": (manager or "").strip(),
            }
    return found


def _reappraisal_history(db: Session, doc_ids: list[str]) -> dict[str, tuple[int, str]]:
    """동일 지번(동·호 포함)의 24개월 내 직전 감정 → {doc: (개월, 직전 DocID)}.

    지번이 비어 있으면 아무거나 매칭되므로 BUN1 있는 건만 본다.

    의뢰인 동일(prior.CustID = cur.CustID) 조건은 뺐다(2026-08-07). 보수기준 제6조
    제2항제1호는 '동일 법인이 동일 물건을 재평가'만 요구하고 의뢰인 동일은 요구하지
    않는다. 조건을 빼면 recall 38.5%→55.5%, precision 5.6%→4.8% 로 재현율이 크게
    오르고 정밀도는 거의 안 떨어진다(실측).
    """
    found: dict[str, tuple[int, str]] = {}
    master = _masterex_table()
    for chunk in _chunks(doc_ids, 200):
        placeholders = ", ".join(f"CAST(:d{i} AS VARCHAR(50))" for i in range(len(chunk)))
        rows = db.execute(
            text(
                f"""
                SELECT doc_id, prior_doc, months_ago FROM (
                    SELECT RTRIM(cur.DocID) AS doc_id, RTRIM(prior.DocID) AS prior_doc,
                           DATEDIFF(month, prior.SendDate, cur.ReceiptDate) AS months_ago,
                           ROW_NUMBER() OVER (
                               PARTITION BY cur.DocID ORDER BY prior.SendDate DESC
                           ) AS rn
                    FROM {master} cur
                    JOIN {master} prior
                        ON prior.REG = cur.REG AND prior.EUB = cur.EUB
                        AND ISNULL(prior.SAN, '') = ISNULL(cur.SAN, '')
                        AND prior.BUN1 = cur.BUN1
                        AND ISNULL(prior.BUN2, '') = ISNULL(cur.BUN2, '')
                        AND ISNULL(prior.Dong, '') = ISNULL(cur.Dong, '')
                        AND ISNULL(prior.Ho, '') = ISNULL(cur.Ho, '')
                        AND prior.DocID <> cur.DocID
                        AND prior.SendDate < cur.ReceiptDate
                        AND prior.SendDate >= DATEADD(month, -24, cur.ReceiptDate)
                    WHERE LTRIM(RTRIM(ISNULL(cur.BUN1, ''))) <> ''
                      AND cur.DocID IN ({placeholders})
                ) ranked WHERE rn = 1
                """
            ),
            {f"d{i}": doc for i, doc in enumerate(chunk)},
        )
        for doc, prior_doc, months_ago in rows:
            if months_ago is not None and months_ago >= 0:
                found[doc] = (int(months_ago), prior_doc)
    return found


# 산출근거 본문에서 기준시점을 되찾을 때 쓰는 패턴.
# 왜 필요한가: document_version.extracted_data_json 의 AppraisalDate 가 비는 건이 많다.
# 실측(2026-01~07 확인필요 61건) — 기준시점을 못 읽은 32건 중 19건을 본문에서 되찾았고
# 그 중 17건이 제5조 소급 할증(코드 2)으로 판별됐다. 전부 국세청·세무서 상속 감정이고
# 본문에 "기준시점은 귀 제시일을 기준한 2024년 12월 22일임.(상속개시일)" 처럼 적혀 있다.
_BASIS_DATE_ANCHOR = re.compile(r"기\s*준\s*시\s*점")
# 기준시점 문장 뒤에 실지조사 기간이 이어진다. 거기까지 넘어가면 조사일을 기준시점으로
# 잘못 읽는다(실측: OCR 이 깨진 건에서 실지조사일을 주워옴). 만나면 창을 끊는다.
_BASIS_DATE_STOP = re.compile(r"실\s*지\s*조\s*사|가격조사\s*기간|작성일")
_BASIS_DATE_PATTERNS = (
    re.compile(r"(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일"),
    re.compile(r"(\d{4})\s*[.\-/]\s*(\d{1,2})\s*[.\-/]\s*(\d{1,2})"),
)
_BASIS_DATE_WINDOW = 220
# '기준시점'은 유사 물건 평가선례·거래사례 표의 **열 제목**으로도 나온다. 그 뒤에 오는
# 날짜는 남의 감정 기준시점이다. 진짜 문장이 OCR 로 깨질수록('20266 3월 13일',
# '2226년', '2022604177') 정규식이 실패해 다음 앵커인 선례표를 주워오는 구조였다
# (실측: 본문 복구 45건 중 6~7건이 이 오탐. 01-2603-3-0800 은 실제 2026-03-13 인데
# 17쪽 선례1의 2023-07-27 을 집어 32개월 소급으로 표시됐다).
_BASIS_DATE_TABLE_CUE = re.compile(
    r"평가선례|평가사례|거래사례|비교표준지|공시기준일|표준지|선\s*례|시점수정"
    r"|전유면적|한국감정평가사협회"
)
# 반대로 이 말이 창 안에 있으면 기준시점을 '결정'하는 문장이다. 실제 문서 형태:
#   "기준시점 결정 및 그 이유 기준시점은 귀 제시일을 기준한 2024년 12월 22일임.(상속개시일)"
#   "「감정평가에 관한 규칙」제9조 제2항에 따라 가격조사를 완료한 날짜인 2026년 3월 9일"
#   "대상물건의 기준시점은 귀 측에서 제시한 2026년 01월 10일임"
_BASIS_DATE_SENTENCE_CUE = re.compile(
    r"결\s*정|제\s*시|완\s*료|기준한|기준으로|상속개시일|제\s*9\s*조|의거|따라"
)


def _basis_date_in_text(blob: str) -> "date | None":
    """'기준시점' 문장에 적힌 날짜. 못 읽으면 None(추정하지 않는다).

    표의 열 제목으로 쓰인 '기준시점'은 건너뛴다 — 그 뒤 날짜는 남의 감정 건이다.
    """
    text_blob = blob or ""
    for anchor in _BASIS_DATE_ANCHOR.finditer(text_blob):
        window = text_blob[anchor.end():anchor.end() + _BASIS_DATE_WINDOW]
        stop = _BASIS_DATE_STOP.search(window)
        if stop:
            window = window[:stop.start()]
        # 앞뒤 문맥이 표를 가리키면 이 앵커는 버린다.
        around = text_blob[max(0, anchor.start() - 120):anchor.end() + 120]
        if _BASIS_DATE_TABLE_CUE.search(around):
            continue
        # 기준시점을 정하는 문장이라는 근거가 있어야 채택한다.
        if not _BASIS_DATE_SENTENCE_CUE.search(around):
            continue
        for pattern in _BASIS_DATE_PATTERNS:
            hit = pattern.search(window)
            if not hit:
                continue
            year, month, day = (int(part) for part in hit.groups())
            if not 2000 <= year <= 2030:
                continue
            try:
                return date(year, month, day)
            except ValueError:
                continue
    return None


def _basis_dates_from_chunks(
    conn: Any, versions: "dict[str, int]"
) -> "dict[str, date]":
    """산출근거 청크에서 기준시점을 되찾는다. 못 읽은 감정서에만 쓴다.

    document_version_id 로 좁혀서만 조회한다 — jun.chunk 는 86만 행이다.
    """
    if not versions:
        return {}
    dvid_to_doc = {dvid: doc for doc, dvid in versions.items()}
    found: "dict[str, date]" = {}
    for chunk in _chunks(list(dvid_to_doc), 200):
        placeholders = ", ".join(f":v{i}" for i in range(len(chunk)))
        # content 는 nvarchar(max) 라 LOB 읽기가 비싸다. 기준시점 문장은 산출근거
        # 앞쪽 페이지의 문단 첫머리에 있으므로 앞 3,000자만 가져오고 페이지도 제한한다
        # (실측: 복구 소요 14.6초 → 이 제한으로 줄인다. 복구 건수는 유지).
        rows = conn.execute(
            text(
                "SELECT document_version_id, LEFT(content, 3000) FROM jun.chunk "
                f"WHERE document_version_id IN ({placeholders}) "
                "AND section_type IN (N'calculation_basis', N'summary', N'cover') "
                "AND page_start <= 20 "
                "AND content LIKE N'%기준시점%' "
                "ORDER BY document_version_id, page_start"
            ),
            {f"v{i}": dvid for i, dvid in enumerate(chunk)},
        )
        for dvid, content in rows:
            doc = dvid_to_doc.get(dvid)
            if doc is None or doc in found:
                continue
            parsed = _basis_date_in_text(str(content or ""))
            if parsed:
                found[doc] = parsed
    return found


def _parsed_signals(doc_ids: list[str]) -> dict[str, dict[str, Any]]:
    """파싱 DB에서 감정서별 본문 페이지와 기준시점을 가져온다 (파싱된 건만)."""
    if not doc_ids:
        return {}
    engine = get_gamjun_parse_engine()
    versions: dict[str, int] = {}
    appraisal_dates: dict[str, date] = {}
    # JUN 은 감정서번호를 소문자로 저장한 건이 있다(실측 772건 — 상속 B계열 등).
    # DB 콜레이션이 대소문자를 무시해 SELECT 는 맞는데, 돌려받은 표기를 그대로 키로 쓰면
    # 호출자가 대문자 doc_id 로 찾을 때 통째로 빗나간다. 요청한 표기로 되돌린다.
    requested = {doc.casefold(): doc for doc in doc_ids}
    with engine.connect() as conn:
        for chunk in _chunks(doc_ids, 500):
            placeholders = ", ".join(f"CAST(:d{i} AS NVARCHAR(50))" for i in range(len(chunk)))
            rows = conn.execute(
                text(
                    "SELECT appraisal_number, document_version_id, "
                    "JSON_VALUE(extracted_data_json, '$.AppraisalDate') "
                    "FROM jun.document_version "
                    "WHERE file_role = 'report' AND is_current = 1 AND status = 'done' "
                    f"AND appraisal_number IN ({placeholders})"
                ),
                {f"d{i}": doc for i, doc in enumerate(chunk)},
            )
            for appno, dvid, raw_date in rows:
                found = str(appno).strip()
                key = requested.get(found.casefold(), found)
                versions[key] = dvid
                parsed_date = _parse_korean_date(raw_date)
                if parsed_date:
                    appraisal_dates[key] = parsed_date

        pages: dict[str, list[tuple[int, str]]] = {}
        dvid_to_doc = {dvid: doc for doc, dvid in versions.items()}
        for chunk in _chunks(list(dvid_to_doc), 200):
            placeholders = ", ".join(f":v{i}" for i in range(len(chunk)))
            rows = conn.execute(
                text(
                    "SELECT document_version_id, page_no, text_content FROM jun.page "
                    f"WHERE document_version_id IN ({placeholders}) "
                    "AND text_content IS NOT NULL ORDER BY document_version_id, page_no"
                ),
                {f"v{i}": dvid for i, dvid in enumerate(chunk)},
            )
            for dvid, page_no, content in rows:
                pages.setdefault(dvid_to_doc[dvid], []).append((page_no, content or ""))

        # 기준시점을 못 읽은 건만 본문에서 되찾는다. 이게 비면 제5조 소급 할증(코드 2)이
        # 조용히 빠지고 화면 의견이 '확인필요'로 남는다.
        unresolved = {
            doc: dvid for doc, dvid in versions.items() if doc not in appraisal_dates
        }
        appraisal_dates.update(_basis_dates_from_chunks(conn, unresolved))

    return {
        doc: {"pages": pages.get(doc, []), "appraisal_date": appraisal_dates.get(doc)}
        for doc in versions
    }


def _parse_korean_date(value: Any) -> date | None:
    match = _DATE_RE.search(str(value or ""))
    if not match:
        return None
    year, month, day = (int(g) for g in match.groups())
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _chunks(values: list, size: int) -> list[list]:
    return [values[i:i + size] for i in range(0, len(values), size)]


# ======================== 영속 스냅숏 모델 ========================

class FeeReviewRunRecord(Base):
    __tablename__ = "a10_fee_review_run"
    __table_args__ = (
        CheckConstraint(
            "period_year BETWEEN 2020 AND 2100",
            name="ck_a10_fee_review_run_year",
        ),
        CheckConstraint(
            "period_month BETWEEN 1 AND 12",
            name="ck_a10_fee_review_run_month",
        ),
        CheckConstraint(
            "status IN ('ACTIVE', 'FINALIZED', 'EXPIRED')",
            name="ck_a10_fee_review_run_status",
        ),
        CheckConstraint(
            "ISJSON(decisions_json) = 1",
            name="ck_a10_fee_review_run_json",
        ).ddl_if(dialect="mssql"),
        Index(
            "ix_a10_fee_review_run_latest",
            "owner_usr_seq",
            "office_code",
            "period_year",
            "period_month",
            "half",
            "basis",
            "created_at",
        ),
    )

    run_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    owner_usr_seq: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    office_code: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    period_year: Mapped[int] = mapped_column(Integer, nullable=False)
    period_month: Mapped[int] = mapped_column(Integer, nullable=False)
    half: Mapped[str] = mapped_column(Unicode(10), nullable=False)
    basis: Mapped[str] = mapped_column(Unicode(10), nullable=False)
    profile: Mapped[str] = mapped_column(String(40), nullable=False)
    snapshot_schema_version: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="1"
    )
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    snapshot_blob: Mapped[bytes] = mapped_column(
        LargeBinary().with_variant(mssql.VARBINARY(None), "mssql"),
        nullable=False,
    )
    decisions_json: Mapped[str] = mapped_column(
        UnicodeText().with_variant(mssql.NVARCHAR(None), "mssql"),
        nullable=False,
        server_default="{}",
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="ACTIVE"
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime().with_variant(mssql.DATETIME2(), "mssql"),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime().with_variant(mssql.DATETIME2(), "mssql"),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime().with_variant(mssql.DATETIME2(), "mssql"),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


# ======================== 영속 스냅숏 저장소 ========================

MEMORY_TTL_SECONDS = 2 * 60 * 60
PERSISTED_TTL_SECONDS = 90 * 24 * 60 * 60
CACHE_TTL_SECONDS = 2 * 60 * 60
MAX_OPINION_LENGTH = 500
MAX_RUNS = 64
SNAPSHOT_SCHEMA_VERSION = 1
PREPARED_OWNER_USR_SEQ = 0
PREPARED_HALF = "월전체"
PREPARED_PROFILE = "FINANCE_FEE_CACHE_V1"


class RunNotFound(LookupError):
    pass


class RunExpired(LookupError):
    pass


class RunForbidden(PermissionError):
    pass


class RunValidationError(ValueError):
    pass


class RunStoreUnavailable(RuntimeError):
    pass


class RunSourceChanged(RunValidationError):
    """A stale run tried to save after a newer source was generated."""


@dataclass
class FeeReviewRun:
    run_id: str
    owner_usr_seq: str
    office_code: str
    created_at: datetime
    updated_at: datetime
    expires_at: datetime
    data: "dict[str, Any]"
    source_sha256: str
    persisted: bool = False
    persistence_warning: "str | None" = None
    opinions: "dict[int, str]" = field(default_factory=dict)
    skipped: "dict[int, str]" = field(default_factory=dict)
    accepted: "set[int]" = field(default_factory=set)
    source_changed: bool = False
    review_required: bool = False
    previous_source_sha256: "str | None" = None
    reused_from_run_id: "str | None" = None
    cached_at: float = field(default_factory=time.time)


_LOCK = threading.RLock()
_RUNS: "dict[str, FeeReviewRun]" = {}
_LAST_MUTATION_AT: "datetime | None" = None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _next_mutation_at(*, after: "datetime | None" = None) -> datetime:
    """Return a process-local strictly increasing mutation timestamp."""
    global _LAST_MUTATION_AT
    with _LOCK:
        candidate = _utcnow()
        floors = [
            value for value in (_LAST_MUTATION_AT, after)
            if value is not None
        ]
        if floors:
            floor = max(floors)
            if candidate <= floor:
                candidate = floor + timedelta(microseconds=1)
        _LAST_MUTATION_AT = candidate
        return candidate


def _json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _canonical_hash(data: "dict[str, Any]") -> str:
    """Hash only frozen source rows, not cache bookkeeping timestamps.

    ``prepared_at`` and ``snapshot_created_at`` change on every prewarm even
    when the source is identical.  Keeping them outside the hash prevents a
    harmless cache refresh from invalidating already reviewed opinions.
    """
    payload = _json(data.get("items") or []).encode("utf-8")
    return hashlib.sha256(payload).hexdigest().upper()


def _pack_snapshot(data: "dict[str, Any]") -> bytes:
    return gzip.compress(_json(data).encode("utf-8"), compresslevel=6)


def _unpack_snapshot(payload: bytes) -> "dict[str, Any]":
    value = json.loads(gzip.decompress(payload).decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("snapshot root is not an object")
    return value


def _decisions_payload(
    *,
    opinions: "dict[int, str]",
    skipped: "dict[int, str]",
    accepted: "set[int]",
    source_changed: "bool | None" = None,
    review_required: "bool | None" = None,
    previous_source_sha256: "str | None" = None,
    reused_from_run_id: "str | None" = None,
) -> "dict[str, Any]":
    payload: "dict[str, Any]" = {
        "opinions": {str(row): text for row, text in opinions.items()},
        "skipped": {str(row): text for row, text in skipped.items()},
        "accepted": sorted(accepted),
    }
    # Public decision_state keeps its original compact shape.  The metadata is
    # written only when the caller explicitly supplies the two boolean flags.
    # This lets the existing JSON column hold source-safety state without a
    # duplicate table or an operational DDL change.
    if source_changed is not None and review_required is not None:
        payload["_source"] = {
            "source_changed": source_changed,
            "review_required": review_required,
            "previous_source_sha256": previous_source_sha256,
            "reused_from_run_id": reused_from_run_id,
        }
    return payload


def _parse_decisions(
    raw: "str | None",
) -> "tuple[dict[int, str], dict[int, str], set[int], dict[str, Any]]":
    payload = json.loads(raw or "{}")
    if not isinstance(payload, dict):
        raise ValueError("decision root is not an object")
    raw_opinions = payload.get("opinions") or {}
    raw_skipped = payload.get("skipped") or {}
    raw_accepted = payload.get("accepted") or []
    if not isinstance(raw_opinions, dict) or not isinstance(raw_skipped, dict):
        raise ValueError("decision maps are invalid")
    if not isinstance(raw_accepted, list):
        raise ValueError("accepted rows are invalid")
    raw_source = payload.get("_source") or {}
    if not isinstance(raw_source, dict):
        raise ValueError("decision source metadata is invalid")
    source_changed = raw_source.get("source_changed", False)
    review_required = raw_source.get("review_required", False)
    previous_source_sha256 = raw_source.get("previous_source_sha256")
    reused_from_run_id = raw_source.get("reused_from_run_id")
    if not isinstance(source_changed, bool) or not isinstance(
        review_required, bool
    ):
        raise ValueError("decision source flags are invalid")
    if previous_source_sha256 is not None and not isinstance(
        previous_source_sha256, str
    ):
        raise ValueError("previous source checksum is invalid")
    if reused_from_run_id is not None and not isinstance(
        reused_from_run_id, str
    ):
        raise ValueError("reused run id is invalid")
    opinions = {
        int(row): str(text)
        for row, text in raw_opinions.items()
    }
    skipped = {
        int(row): str(text)
        for row, text in raw_skipped.items()
    }
    accepted = {int(row) for row in raw_accepted}
    return opinions, skipped, accepted, {
        "source_changed": source_changed,
        "review_required": review_required,
        "previous_source_sha256": previous_source_sha256,
        "reused_from_run_id": reused_from_run_id,
    }


def _stored_decisions(run: FeeReviewRun) -> "dict[str, Any]":
    return _decisions_payload(
        opinions=run.opinions,
        skipped=run.skipped,
        accepted=run.accepted,
        source_changed=run.source_changed,
        review_required=run.review_required,
        previous_source_sha256=run.previous_source_sha256,
        reused_from_run_id=run.reused_from_run_id,
    )


def _cleanup(now: "datetime | None" = None) -> None:
    current = _utcnow() if now is None else now
    current_cache = time.time()
    removable = [
        key for key, run in _RUNS.items()
        if run.expires_at <= current
        or (
            run.persisted
            and current_cache - run.cached_at > CACHE_TTL_SECONDS
        )
    ]
    for key in removable:
        _RUNS.pop(key, None)
    if len(_RUNS) > MAX_RUNS:
        oldest = sorted(_RUNS.values(), key=lambda run: run.cached_at)
        for run in oldest[:len(_RUNS) - MAX_RUNS]:
            _RUNS.pop(run.run_id, None)


def _cache(run: FeeReviewRun) -> FeeReviewRun:
    with _LOCK:
        _cleanup()
        run.cached_at = time.time()
        _RUNS[run.run_id] = run
    return run


def _record_to_run(record: FeeReviewRunRecord) -> FeeReviewRun:
    try:
        if record.snapshot_schema_version != SNAPSHOT_SCHEMA_VERSION:
            raise ValueError("unsupported snapshot schema")
        data = _unpack_snapshot(record.snapshot_blob)
        if not hmac.compare_digest(
            _canonical_hash(data), record.source_sha256
        ):
            raise ValueError("snapshot checksum mismatch")
        opinions, skipped, accepted, source_state = _parse_decisions(
            record.decisions_json
        )
    except (OSError, UnicodeError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise RunStoreUnavailable(
            "저장된 보수검토 스냅숏을 복원하지 못했습니다."
        ) from exc
    return FeeReviewRun(
        run_id=record.run_id,
        owner_usr_seq=str(record.owner_usr_seq),
        office_code=record.office_code,
        created_at=record.created_at,
        updated_at=record.updated_at,
        expires_at=record.expires_at,
        data=data,
        source_sha256=record.source_sha256,
        persisted=True,
        opinions=opinions,
        skipped=skipped,
        accepted=accepted,
        source_changed=source_state["source_changed"],
        review_required=source_state["review_required"],
        previous_source_sha256=source_state["previous_source_sha256"],
        reused_from_run_id=source_state["reused_from_run_id"],
    )


def _load_record(db: Session, run_id: str) -> "FeeReviewRunRecord | None":
    try:
        return db.get(FeeReviewRunRecord, run_id)
    except SQLAlchemyError as exc:
        db.rollback()
        raise RunStoreUnavailable(
            "보수검토 저장 테이블을 조회할 수 없습니다."
        ) from exc


def _latest_prior_run(
    *,
    owner_usr_seq: int,
    office_code: str,
    year: int,
    month: int,
    half: str,
    basis: str,
    profile: str,
    db: "Session | None",
) -> "FeeReviewRun | None":
    """Return the newest run in the exact user/filter scope.

    The newest source is intentionally authoritative.  When it differs from a
    newly generated source we do not search farther back for a coincidentally
    matching hash, because that would silently bypass the intervening source
    change and revive stale manual decisions.
    """
    now = _utcnow()
    store_error: "Exception | None" = None
    if db is not None:
        try:
            record = db.scalar(
                select(FeeReviewRunRecord)
                .where(
                    FeeReviewRunRecord.owner_usr_seq == owner_usr_seq,
                    FeeReviewRunRecord.office_code == office_code,
                    FeeReviewRunRecord.period_year == year,
                    FeeReviewRunRecord.period_month == month,
                    FeeReviewRunRecord.half == half,
                    FeeReviewRunRecord.basis == basis,
                    FeeReviewRunRecord.profile == profile,
                    FeeReviewRunRecord.status == "ACTIVE",
                    FeeReviewRunRecord.expires_at > now,
                )
                .order_by(
                    FeeReviewRunRecord.updated_at.desc(),
                    FeeReviewRunRecord.created_at.desc(),
                )
                .limit(1)
            )
        except (SQLAlchemyError, TypeError, ValueError) as exc:
            db.rollback()
            store_error = exc
        else:
            if record is not None:
                return _record_to_run(record)

    owner = str(owner_usr_seq)
    with _LOCK:
        _cleanup(now)
        matches = [
            run for run in _RUNS.values()
            if run.owner_usr_seq == owner
            and run.office_code == office_code
            and int(run.data.get("year") or 0) == year
            and int(run.data.get("month") or 0) == month
            and str(run.data.get("half") or "월전체") == half
            and str(run.data.get("basis") or "매출") == basis
            and str(run.data.get("profile") or "") == profile
        ]
    if matches:
        return max(
            matches, key=lambda run: (run.updated_at, run.created_at)
        )
    if store_error is not None and not get_settings().fee_review_allow_memory_fallback:
        raise RunStoreUnavailable(
            "이전 보수검토 의견을 운영 DB에서 확인할 수 없습니다."
        ) from store_error
    return None


def _create_run_locked(
    data: "dict[str, Any]",
    *,
    owner_usr_seq: Any,
    office_code: str,
    ttl_seconds: "int | None" = None,
    db: "Session | None" = None,
) -> FeeReviewRun:
    try:
        owner = int(owner_usr_seq)
    except (TypeError, ValueError) as exc:
        raise RunValidationError("보수검토 저장 사용자 정보가 없습니다.") from exc

    run_id = secrets.token_urlsafe(18)
    frozen = deepcopy(data)
    source_sha256 = _canonical_hash(frozen)
    try:
        year = int(frozen["year"])
        month = int(frozen["month"])
    except (KeyError, TypeError, ValueError) as exc:
        raise RunValidationError("보수검토 기간이 올바르지 않습니다.") from exc
    half = str(frozen.get("half") or "월전체")
    basis = str(frozen.get("basis") or "매출")
    profile = str(frozen.get("profile") or "FINANCE_FEE_CHECK_V1")

    opinions: "dict[int, str]" = {}
    skipped: "dict[int, str]" = {}
    accepted: "set[int]" = set()
    source_changed = False
    review_required = False
    previous_source_sha256: "str | None" = None
    reused_from_run_id: "str | None" = None
    prior: "FeeReviewRun | None" = None
    if owner != PREPARED_OWNER_USR_SEQ:
        prior = _latest_prior_run(
            owner_usr_seq=owner,
            office_code=str(office_code),
            year=year,
            month=month,
            half=half,
            basis=basis,
            profile=profile,
            db=db,
        )
        if prior is not None:
            if hmac.compare_digest(prior.source_sha256, source_sha256):
                opinions = deepcopy(prior.opinions)
                skipped = deepcopy(prior.skipped)
                accepted = set(prior.accepted)
                source_changed = prior.source_changed
                review_required = prior.review_required
                previous_source_sha256 = prior.previous_source_sha256
                reused_from_run_id = prior.run_id
            else:
                # A changed frozen source invalidates all row-based decisions.
                # Preserve only the audit pointer and require a fresh review.
                source_changed = True
                review_required = True
                previous_source_sha256 = prior.source_sha256
    now = _next_mutation_at(after=prior.updated_at if prior else None)
    # 호출부가 넘긴 TTL 을 무시하면 100년으로 저장하려던 의견이 메모리 폴백에서만
    # 2시간으로 깎인다. DB 경로(아래 PERSISTED_TTL 분기)와 같은 규칙을 쓴다.
    expires_at = now + timedelta(
        seconds=MEMORY_TTL_SECONDS if ttl_seconds is None else int(ttl_seconds)
    )
    persisted = False
    warning = (
        "운영 DB 저장 세션이 없어 현재 서버 메모리에만 임시 저장됩니다."
        if db is None else None
    )

    if db is not None:
        record = FeeReviewRunRecord(
            run_id=run_id,
            owner_usr_seq=owner,
            office_code=str(office_code),
            period_year=year,
            period_month=month,
            half=half,
            basis=basis,
            profile=profile,
            snapshot_schema_version=SNAPSHOT_SCHEMA_VERSION,
            source_sha256=source_sha256,
            snapshot_blob=_pack_snapshot(frozen),
            decisions_json=_json(_decisions_payload(
                opinions=opinions,
                skipped=skipped,
                accepted=accepted,
                source_changed=source_changed,
                review_required=review_required,
                previous_source_sha256=previous_source_sha256,
                reused_from_run_id=reused_from_run_id,
            )),
            status="ACTIVE",
            expires_at=now + timedelta(
                seconds=PERSISTED_TTL_SECONDS if ttl_seconds is None else int(ttl_seconds)
            ),
            created_at=now,
            updated_at=now,
        )
        try:
            db.add(record)
            db.commit()
            persisted = True
            expires_at = record.expires_at
        except SQLAlchemyError as exc:
            db.rollback()
            logger.warning(
                "fee review run persistence failed (%s); "
                "memory fallback allowed=%s",
                type(exc).__name__,
                get_settings().fee_review_allow_memory_fallback,
            )
            if not get_settings().fee_review_allow_memory_fallback:
                raise RunStoreUnavailable(
                    "보수검토를 운영 DB에 저장하지 못했습니다. "
                    "저장 테이블과 DB 연결 상태를 확인해 주세요."
                ) from exc
            warning = (
                "개발용 메모리 임시저장 모드입니다. 서버 재시작 시 "
                "현재 검토 내용이 복구되지 않습니다."
            )

    run = FeeReviewRun(
        run_id=run_id,
        owner_usr_seq=str(owner),
        office_code=str(office_code),
        created_at=now,
        updated_at=now,
        expires_at=expires_at,
        data=frozen,
        source_sha256=source_sha256,
        persisted=persisted,
        persistence_warning=warning,
        opinions=opinions,
        skipped=skipped,
        accepted=accepted,
        source_changed=source_changed,
        review_required=review_required,
        previous_source_sha256=previous_source_sha256,
        reused_from_run_id=reused_from_run_id,
    )
    return _cache(run)


def create_run(
    data: "dict[str, Any]",
    *,
    owner_usr_seq: Any,
    office_code: str,
    ttl_seconds: "int | None" = None,
    db: "Session | None" = None,
) -> FeeReviewRun:
    # Serializing create/save closes the in-process source-check/commit race.
    # Cross-process coordination still belongs to the operating DB layer.
    with _LOCK:
        return _create_run_locked(
            data,
            owner_usr_seq=owner_usr_seq,
            office_code=office_code,
            ttl_seconds=ttl_seconds,
            db=db,
        )


def _validate_access(
    run: FeeReviewRun,
    *,
    owner_usr_seq: Any,
    office_code: "str | None" = None,
) -> FeeReviewRun:
    if run.expires_at <= _utcnow():
        with _LOCK:
            _RUNS.pop(run.run_id, None)
        raise RunExpired(run.run_id)
    if run.owner_usr_seq != str(owner_usr_seq):
        raise RunForbidden(run.run_id)
    if office_code is not None and run.office_code != str(office_code):
        raise RunForbidden(run.run_id)
    return run


def get_run(
    run_id: str,
    *,
    owner_usr_seq: Any,
    office_code: "str | None" = None,
    db: "Session | None" = None,
) -> FeeReviewRun:
    with _LOCK:
        _cleanup()
        cached = _RUNS.get(run_id)
    if cached is not None and (not cached.persisted or db is None):
        return _validate_access(
            cached, owner_usr_seq=owner_usr_seq, office_code=office_code
        )
    if db is None:
        raise RunNotFound(run_id)

    record = _load_record(db, run_id)
    if record is None:
        raise RunNotFound(run_id)
    run = _record_to_run(record)
    _validate_access(run, owner_usr_seq=owner_usr_seq, office_code=office_code)
    return _cache(run)


def find_latest_run(
    *,
    owner_usr_seq: Any,
    office_code: str,
    year: int,
    month: int,
    half: str,
    basis: str,
    profile: "str | None" = None,
    lock_for_update: bool = False,
    db: "Session | None" = None,
) -> FeeReviewRun:
    try:
        owner_number = int(owner_usr_seq)
    except (TypeError, ValueError) as exc:
        raise RunValidationError("보수검토 저장 사용자 정보가 없습니다.") from exc
    # 공용 소유자(배치·화면 캐시·의견)는 같은 키에 profile 만 다른 행이 여럿이다.
    # profile 을 빼면 updated_at 이 최신인 행이 잡혀 의견 조회에 스냅숏 행이 걸리고
    # 의견이 '없는 것'으로 보인다(검증에서 재현됨). 공용 범위에서는 필수로 받는다.
    if profile is None and owner_number == PREPARED_OWNER_USR_SEQ:
        raise RunValidationError("공용 스냅숏 조회에는 profile이 필요합니다.")
    owner = str(owner_number)
    now = _utcnow()

    if db is not None:
        try:
            conditions = [
                    FeeReviewRunRecord.owner_usr_seq == owner_number,
                    FeeReviewRunRecord.office_code == str(office_code),
                    FeeReviewRunRecord.period_year == int(year),
                    FeeReviewRunRecord.period_month == int(month),
                    FeeReviewRunRecord.half == str(half),
                    FeeReviewRunRecord.basis == str(basis),
                    FeeReviewRunRecord.status == "ACTIVE",
                    FeeReviewRunRecord.expires_at > now,
            ]
            if profile is not None:
                conditions.append(FeeReviewRunRecord.profile == str(profile))
            statement = (
                select(FeeReviewRunRecord)
                .where(*conditions)
                .order_by(
                    FeeReviewRunRecord.updated_at.desc(),
                    FeeReviewRunRecord.created_at.desc(),
                )
                .limit(1)
            )
            if lock_for_update:
                # SQL Server ignores generic SELECT .. FOR UPDATE syntax, so
                # use its update/serializable lock hints as well.  The lock is
                # held until the caller commits the opinion upsert.
                statement = (
                    statement.with_for_update()
                    .with_hint(
                        FeeReviewRunRecord,
                        "WITH (UPDLOCK, HOLDLOCK)",
                        dialect_name="mssql",
                    )
                )
            record = db.scalar(statement)
        except (SQLAlchemyError, TypeError, ValueError) as exc:
            db.rollback()
            record = None
            store_error = exc
        else:
            store_error = None
        if record is not None:
            run = _record_to_run(record)
            _validate_access(
                run, owner_usr_seq=owner_usr_seq, office_code=office_code
            )
            return _cache(run)
    else:
        store_error = None

    with _LOCK:
        _cleanup(now)
        matches = [
            run for run in _RUNS.values()
            if run.owner_usr_seq == owner
            and run.office_code == str(office_code)
            and int(run.data.get("year") or 0) == int(year)
            and int(run.data.get("month") or 0) == int(month)
            and str(run.data.get("half") or "월전체") == str(half)
            and str(run.data.get("basis") or "매출") == str(basis)
            and (
                profile is None
                or str(run.data.get("profile") or "") == str(profile)
            )
        ]
    if matches:
        return max(
            matches, key=lambda run: (run.updated_at, run.created_at)
        )
    if store_error is not None:
        raise RunStoreUnavailable(
            "보수검토 저장 테이블을 조회할 수 없습니다."
        ) from store_error
    raise RunNotFound("latest")


def find_prepared_run(
    *,
    office_code: str,
    year: int,
    month: int,
    basis: str,
    half: str = PREPARED_HALF,
    profile: str = PREPARED_PROFILE,
    lock_for_update: bool = False,
    db: "Session | None" = None,
) -> FeeReviewRun:
    """배치나 조회가 만든 공용 스냅숏을 찾는다.

    half·profile 기본값은 보수기준 검토(월전체)다. 보수기준 점검처럼 반월 단위로
    조회하는 화면은 자기 반월과 자기 프로파일을 넘겨 같은 엔진을 나눠 쓴다.
    """
    return find_latest_run(
        owner_usr_seq=PREPARED_OWNER_USR_SEQ,
        office_code=office_code,
        year=year,
        month=month,
        half=half,
        basis=basis,
        profile=profile,
        lock_for_update=lock_for_update,
        db=db,
    )


def save_prepared_run(
    data: "dict[str, Any]",
    *,
    office_code: str,
    half: str = PREPARED_HALF,
    profile: str = PREPARED_PROFILE,
    ttl_seconds: "int | None" = None,
    db: "Session | None" = None,
) -> FeeReviewRun:
    """공용 스냅숏을 키별 한 행으로 갱신한다.

    운영 DB에서는 같은 지사·기간·반월·기준·프로파일의 공용 행을 제자리 갱신해
    실행마다 레코드가 늘어나지 않게 한다. 개발용 메모리 폴백도 같은 키를 치환한다.

    half·profile 기본값은 보수기준 검토(월전체)다. 다른 화면은 자기 값을 넘긴다.
    """
    frozen = deepcopy(data)
    frozen["half"] = half
    frozen["profile"] = profile
    try:
        year = int(frozen["year"])
        month = int(frozen["month"])
    except (KeyError, TypeError, ValueError) as exc:
        raise RunValidationError("보수검토 사전생성 기간이 올바르지 않습니다.") from exc
    basis = str(frozen.get("basis") or "매출")
    now = _utcnow()
    # 스냅숏은 캐시라 만료가 맞지만, 의견처럼 기록 성격인 행은 호출자가 TTL 을 넉넉히
    # 지정한다. 만료되면 조회 필터(expires_at > now)에서 걸러져 조용히 사라지고,
    # 만료 후 첫 저장이 빈 병합 기반 위에 덮어써 기존 내용을 영구 소실시킨다(검토 발견).
    if ttl_seconds is None and profile == OPINION_PROFILE:
        # 의견은 기록이지 캐시가 아니다. 호출부가 TTL 을 빠뜨리면 90일 뒤 조회 필터에서
        # 조용히 사라지고, 만료 후 첫 저장이 빈 병합 기반 위에 덮어써 영구 소실된다
        # (검증에서 실제로 재현됨). 함수 안에서 못을 박는다.
        ttl_seconds = OPINION_TTL_SECONDS
    effective_ttl = PERSISTED_TTL_SECONDS if ttl_seconds is None else int(ttl_seconds)
    source_sha256 = _canonical_hash(frozen)

    if db is not None:
        try:
            record = db.scalar(
                select(FeeReviewRunRecord)
                .where(
                    FeeReviewRunRecord.owner_usr_seq == PREPARED_OWNER_USR_SEQ,
                    FeeReviewRunRecord.office_code == str(office_code),
                    FeeReviewRunRecord.period_year == year,
                    FeeReviewRunRecord.period_month == month,
                    FeeReviewRunRecord.half == half,
                    FeeReviewRunRecord.basis == basis,
                    FeeReviewRunRecord.profile == profile,
                )
                .order_by(FeeReviewRunRecord.created_at.desc())
                .limit(1)
            )
        except (SQLAlchemyError, TypeError, ValueError) as exc:
            db.rollback()
            if not get_settings().fee_review_allow_memory_fallback:
                raise RunStoreUnavailable(
                    "보수검토 사전생성 스냅숏을 운영 DB에 저장할 수 없습니다."
                ) from exc
            record = None
            db = None

        if record is not None:
            # decisions_json 은 배치 산출물이 아니라 사람 입력(행번호 의견·보류·확정)이다.
            # 무조건 빈 값으로 덮으면 사람이 남긴 값이 경고 없이 사라진다. 스냅숏만
            # 갈아끼우고 사람 값은 살리되, 원천이 바뀐 사실은 플래그로 알려 재확인을
            # 강제한다(행번호 키라 원천이 바뀌면 엉뚱한 행에 붙을 수 있다).
            previous_sha = str(record.source_sha256 or "")
            source_changed = previous_sha != source_sha256
            try:
                prior_opinions, prior_skipped, prior_accepted, _prior_meta = (
                    _parse_decisions(record.decisions_json)
                )
            except (ValueError, TypeError, json.JSONDecodeError):
                prior_opinions, prior_skipped, prior_accepted = {}, {}, set()
            record.source_sha256 = source_sha256
            record.snapshot_schema_version = SNAPSHOT_SCHEMA_VERSION
            record.snapshot_blob = _pack_snapshot(frozen)
            record.decisions_json = _json(_decisions_payload(
                opinions=prior_opinions,
                skipped=prior_skipped,
                accepted=prior_accepted,
                source_changed=source_changed,
                review_required=source_changed,
                previous_source_sha256=previous_sha if source_changed else None,
            ))
            record.status = "ACTIVE"
            record.expires_at = now + timedelta(seconds=effective_ttl)
            record.created_at = now
            record.updated_at = now
            try:
                db.commit()
            except SQLAlchemyError as exc:
                db.rollback()
                raise RunStoreUnavailable(
                    "보수검토 사전생성 스냅숏을 운영 DB에 갱신할 수 없습니다."
                ) from exc
            return _cache(_record_to_run(record))

    with _LOCK:
        removable = [
            run_id
            for run_id, run in _RUNS.items()
            if run.owner_usr_seq == str(PREPARED_OWNER_USR_SEQ)
            and run.office_code == str(office_code)
            and int(run.data.get("year") or 0) == year
            and int(run.data.get("month") or 0) == month
            and str(run.data.get("half") or "") == half
            and str(run.data.get("basis") or "") == basis
            and str(run.data.get("profile") or "") == profile
        ]
        for run_id in removable:
            _RUNS.pop(run_id, None)

    return create_run(
        frozen,
        owner_usr_seq=PREPARED_OWNER_USR_SEQ,
        office_code=office_code,
        ttl_seconds=ttl_seconds,
        db=db,
    )


def _known_rows(run: FeeReviewRun) -> "set[int]":
    return {
        int(item["source_row_number"])
        for item in run.data.get("items") or []
    }


def _newer_different_source(
    run: FeeReviewRun, *, db: "Session | None"
) -> "tuple[str, datetime, str] | None":
    """Return the newest later run from a different source epoch, if any."""
    try:
        owner_number = int(run.owner_usr_seq)
        year = int(run.data["year"])
        month = int(run.data["month"])
    except (KeyError, TypeError, ValueError) as exc:
        raise RunValidationError("보수검토 저장 범위가 올바르지 않습니다.") from exc
    half = str(run.data.get("half") or "월전체")
    basis = str(run.data.get("basis") or "매출")
    profile = str(run.data.get("profile") or "FINANCE_FEE_CHECK_V1")
    now = _utcnow()
    store_error: "Exception | None" = None

    if db is not None:
        try:
            record = db.scalar(
                select(FeeReviewRunRecord)
                .where(
                    FeeReviewRunRecord.owner_usr_seq == owner_number,
                    FeeReviewRunRecord.office_code == run.office_code,
                    FeeReviewRunRecord.period_year == year,
                    FeeReviewRunRecord.period_month == month,
                    FeeReviewRunRecord.half == half,
                    FeeReviewRunRecord.basis == basis,
                    FeeReviewRunRecord.profile == profile,
                    FeeReviewRunRecord.created_at > run.created_at,
                    FeeReviewRunRecord.source_sha256 != run.source_sha256,
                    FeeReviewRunRecord.status == "ACTIVE",
                    FeeReviewRunRecord.expires_at > now,
                )
                .order_by(FeeReviewRunRecord.created_at.desc())
                .limit(1)
            )
        except (SQLAlchemyError, TypeError, ValueError) as exc:
            db.rollback()
            store_error = exc
        else:
            if record is not None:
                return (
                    record.source_sha256,
                    record.created_at,
                    record.run_id,
                )

    with _LOCK:
        _cleanup(now)
        matches = [
            candidate for candidate in _RUNS.values()
            if candidate.owner_usr_seq == run.owner_usr_seq
            and candidate.office_code == run.office_code
            and int(candidate.data.get("year") or 0) == year
            and int(candidate.data.get("month") or 0) == month
            and str(candidate.data.get("half") or "월전체") == half
            and str(candidate.data.get("basis") or "매출") == basis
            and str(candidate.data.get("profile") or "") == profile
            and candidate.created_at > run.created_at
            and not hmac.compare_digest(
                candidate.source_sha256, run.source_sha256
            )
        ]
    if matches:
        newest = max(matches, key=lambda candidate: candidate.created_at)
        return newest.source_sha256, newest.created_at, newest.run_id
    if store_error is not None and not get_settings().fee_review_allow_memory_fallback:
        raise RunStoreUnavailable(
            "최신 보수검토 원천을 운영 DB에서 확인할 수 없습니다."
        ) from store_error
    return None


def _ensure_current_source(
    run: FeeReviewRun, *, db: "Session | None"
) -> None:
    changed = _newer_different_source(run, db=db)
    if changed is None:
        return
    raise RunSourceChanged(
        "조회 후 원천 데이터가 변경되었습니다. 최신 결과를 다시 조회한 뒤 "
        "의견을 저장해 주세요."
    )


def _latest_same_source_run(
    run: FeeReviewRun, *, db: "Session | None"
) -> FeeReviewRun:
    try:
        owner_number = int(run.owner_usr_seq)
        year = int(run.data["year"])
        month = int(run.data["month"])
    except (KeyError, TypeError, ValueError) as exc:
        raise RunValidationError("보수검토 저장 범위가 올바르지 않습니다.") from exc
    half = str(run.data.get("half") or "월전체")
    basis = str(run.data.get("basis") or "매출")
    profile = str(run.data.get("profile") or "FINANCE_FEE_CHECK_V1")
    now = _utcnow()
    store_error: "Exception | None" = None

    if db is not None:
        try:
            record = db.scalar(
                select(FeeReviewRunRecord)
                .where(
                    FeeReviewRunRecord.owner_usr_seq == owner_number,
                    FeeReviewRunRecord.office_code == run.office_code,
                    FeeReviewRunRecord.period_year == year,
                    FeeReviewRunRecord.period_month == month,
                    FeeReviewRunRecord.half == half,
                    FeeReviewRunRecord.basis == basis,
                    FeeReviewRunRecord.profile == profile,
                    FeeReviewRunRecord.source_sha256 == run.source_sha256,
                    FeeReviewRunRecord.status == "ACTIVE",
                    FeeReviewRunRecord.expires_at > now,
                )
                .order_by(
                    FeeReviewRunRecord.updated_at.desc(),
                    FeeReviewRunRecord.created_at.desc(),
                )
                .limit(1)
            )
        except (SQLAlchemyError, TypeError, ValueError) as exc:
            db.rollback()
            store_error = exc
        else:
            if record is not None:
                return _record_to_run(record)

    with _LOCK:
        _cleanup(now)
        matches = [
            candidate for candidate in _RUNS.values()
            if candidate.owner_usr_seq == run.owner_usr_seq
            and candidate.office_code == run.office_code
            and int(candidate.data.get("year") or 0) == year
            and int(candidate.data.get("month") or 0) == month
            and str(candidate.data.get("half") or "월전체") == half
            and str(candidate.data.get("basis") or "매출") == basis
            and str(candidate.data.get("profile") or "") == profile
            and hmac.compare_digest(
                candidate.source_sha256, run.source_sha256
            )
        ]
    if matches:
        return max(
            matches,
            key=lambda candidate: (
                candidate.updated_at,
                candidate.created_at,
            ),
        )
    if store_error is not None and not get_settings().fee_review_allow_memory_fallback:
        raise RunStoreUnavailable(
            "최신 보수검토 의견을 운영 DB에서 확인할 수 없습니다."
        ) from store_error
    return run


# 근거를 못 찾은 의견 대상에 쓰는 최종 표시. 빈칸으로 두면 검토 누락으로 읽힌다.
MANUAL_REVIEW_OPINION = "담당자확인요청"


def _is_review_target(run: FeeReviewRun, row: int) -> bool:
    for item in run.data.get("items") or []:
        try:
            if int(item.get("source_row_number")) == row:
                return bool(item.get("review_target"))
        except (TypeError, ValueError):
            continue
    return False


def _update_decisions_locked(
    run: FeeReviewRun,
    *,
    opinions: "dict[str | int, Any]",
    skipped: "dict[str | int, Any]",
    accepted: "list[int]",
    db: "Session | None" = None,
) -> None:
    _ensure_current_source(run, db=db)
    carrier = _latest_same_source_run(run, db=db)
    known = _known_rows(run)

    def normalized_map(
        values: "dict[str | int, Any]", *, limit: int
    ) -> "dict[int, str]":
        result = {}
        for raw_row, raw_text in values.items():
            try:
                row = int(raw_row)
            except (TypeError, ValueError) as exc:
                raise RunValidationError("행번호가 올바르지 않습니다.") from exc
            if row not in known:
                raise RunValidationError(f"{row}행은 현재 스냅숏에 없습니다.")
            text = "" if raw_text is None else str(raw_text)
            if not text.strip():
                text = ""
            if len(text) > limit:
                raise RunValidationError(f"{row}행 의견이 {limit}자를 넘습니다.")
            result[row] = text
        return result

    incoming_opinions = normalized_map(
        opinions or {}, limit=MAX_OPINION_LENGTH
    )
    incoming_skipped = normalized_map(skipped or {}, limit=200)
    incoming_accepted = {int(row) for row in (accepted or [])}
    if not incoming_accepted.issubset(known):
        raise RunValidationError("현재 스냅숏에 없는 행을 채택할 수 없습니다.")

    # PATCH is a partial merge.  Start from the newest decision carrier for
    # this exact source so two tabs editing different AB rows cannot erase
    # each other.  An explicit opinion key—including ""—wins over legacy skip.
    merged_opinions = deepcopy(carrier.opinions)
    merged_skipped = deepcopy(carrier.skipped)
    merged_accepted = set(carrier.accepted)
    for row, text in incoming_skipped.items():
        if text:
            merged_skipped[row] = text
            merged_opinions.pop(row, None)
        else:
            merged_skipped.pop(row, None)
    for row, text in incoming_opinions.items():
        # 같은 요청에서 공란 의견 + 제외 사유가 함께 오면 '제외' 의도로 본다.
        # (화면이 AB를 지우고 사유를 적는 흐름이 한 번의 저장으로 들어온다)
        if not text.strip() and incoming_skipped.get(row, "").strip():
            continue
        merged_opinions[row] = text
        merged_skipped.pop(row, None)
    merged_accepted.update(incoming_accepted)

    # 실제 이탈·특수 확인 대상은 AB가 비어 있으면 재무팀이 "검토 누락"으로 읽는다.
    # 공란으로 두려면 제외 사유를 함께 남겨야 한다(사유가 있으면 SKIPPED로 비운다).
    for row, text in merged_opinions.items():
        if text.strip():
            continue
        if merged_skipped.get(row, "").strip():
            continue
        if _is_review_target(run, row):
            raise RunValidationError(
                f"{row}행은 의견 대상입니다. 의견을 비우려면 제외 사유를 함께 입력하세요."
            )

    # Saving is an explicit review of the current frozen source, including an
    # intentionally blank opinion.  Keep source_changed as audit history while
    # clearing only the outstanding re-review flag.
    review_required = False
    decision_updated_at = _next_mutation_at(after=carrier.updated_at)
    if run.persisted:
        if db is None:
            raise RunStoreUnavailable("보수검토 저장 세션이 없습니다.")
        record = _load_record(db, run.run_id)
        if record is None:
            raise RunNotFound(run.run_id)
        record.decisions_json = _json(_decisions_payload(
            opinions=merged_opinions,
            skipped=merged_skipped,
            accepted=merged_accepted,
            source_changed=run.source_changed,
            review_required=review_required,
            previous_source_sha256=run.previous_source_sha256,
            reused_from_run_id=run.reused_from_run_id,
        ))
        record.updated_at = decision_updated_at
        try:
            db.commit()
        except SQLAlchemyError as exc:
            db.rollback()
            raise RunStoreUnavailable(
                "보수검토 의견을 운영 DB에 저장하지 못했습니다."
            ) from exc

    with _LOCK:
        run.opinions = merged_opinions
        run.skipped = merged_skipped
        run.accepted = merged_accepted
        run.review_required = review_required
        run.updated_at = decision_updated_at
        run.cached_at = time.time()


def update_decisions(
    run: FeeReviewRun,
    *,
    opinions: "dict[str | int, Any]",
    skipped: "dict[str | int, Any]",
    accepted: "list[int]",
    db: "Session | None" = None,
) -> None:
    with _LOCK:
        _update_decisions_locked(
            run,
            opinions=opinions,
            skipped=skipped,
            accepted=accepted,
            db=db,
        )


def decision_summary(run: FeeReviewRun) -> "dict[str, int]":
    targets = [
        item for item in run.data.get("items") or [] if item.get("review_target")
    ]
    handled = 0
    for item in targets:
        row = int(item["source_row_number"])
        if (
            row in run.accepted
            or row in run.opinions
            or bool(run.skipped.get(row, "").strip())
            or bool(str(item.get("existing_opinion") or "").strip())
        ):
            handled += 1
    return {
        "target": len(targets),
        "handled": handled,
        "pending": len(targets) - handled,
    }


def public_data(run: FeeReviewRun) -> "dict[str, Any]":
    data = deepcopy(run.data)
    data["items"], _ = _effective_rows(run)
    remaining = max(
        0, int((run.expires_at - _utcnow()).total_seconds())
    )
    data.update({
        "run_id": run.run_id,
        "source_sha256": run.source_sha256,
        "snapshot_ttl_seconds": remaining,
        "snapshot_expires_at": run.expires_at.isoformat(),
        "decision_summary": decision_summary(run),
        "decision_state": _decisions_payload(
            opinions=run.opinions,
            skipped=run.skipped,
            accepted=run.accepted,
        ),
        "persisted": run.persisted,
        "persistence_warning": run.persistence_warning,
        "source_changed": run.source_changed,
        "review_required": run.review_required,
        "previous_source_sha256": run.previous_source_sha256,
        "reused_from_run_id": run.reused_from_run_id,
    })
    return data


def _effective_rows(
    run: FeeReviewRun,
) -> "tuple[list[dict[str, Any]], list[int]]":
    """Materialize the one effective AB opinion used by screen and export.

    A row key in ``opinions`` is an explicit manual decision even when its
    value is blank.  This distinction prevents a deliberately cleared opinion
    from falling back to the automatic suggestion on refresh or export.
    """
    rows = deepcopy(run.data.get("items") or [])
    pending: "list[int]" = []
    for item in rows:
        row = int(item["source_row_number"])
        existing = str(item.get("existing_opinion") or "")
        suggested = str(item.get("suggested_opinion") or "")
        has_manual = row in run.opinions
        manual = run.opinions.get(row, "")
        skip_reason = run.skipped.get(row, "")
        has_skip_reason = bool(skip_reason.strip())
        if has_manual and (
            manual.strip()
            or has_skip_reason
            or not item.get("review_target")
        ):
            opinion = manual
            origin = "MANUAL"
        elif has_manual:
            # 제외 사유 없이 비워진 의견 대상 행(옛 저장분). 공란으로 내보내지 않는다.
            opinion = suggested or existing or MANUAL_REVIEW_OPINION
            origin = "AUTO" if suggested else ("EXISTING" if existing else "AUTO")
        elif has_skip_reason:
            opinion = ""
            origin = "SKIPPED"
        elif existing:
            opinion = existing
            origin = "EXISTING"
        elif suggested:
            opinion = suggested
            origin = "AUTO"
        else:
            opinion = ""
            origin = "NONE"
        item["final_opinion"] = opinion
        item["effective_opinion"] = opinion
        item["effective_opinion_origin"] = origin
        item.setdefault("source_row_json", {})["AB"] = opinion

        if item.get("review_target") and not existing:
            handled = row in run.accepted or has_manual or has_skip_reason
            if not handled:
                pending.append(row)
    return rows, pending


def export_rows(
    run: FeeReviewRun, *, mode: str
) -> "tuple[list[dict[str, Any]], list[int]]":
    """내보낼 행 사본과 미처리 행번호.

    draft는 미채택 제안도 AB에 넣는다. final은 미처리 대상이 하나라도 있으면 호출측이
    409로 막는다. 제외 사유가 채워진 행은 AB를 비운다.
    """
    return _effective_rows(run)


# ======================== 보수표 계산 ========================

# 국토교통부 공고 제2025-334호 시행일. 이 날 이후 '최초 계약' 건에 현행표를 적용한다.
FEE_RULESET_CUTOFF = date(2025, 3, 17)

# 보수 계산 로직 버전. 요율표·경계 판정(floor/ceil)·누진상수 계산을 바꾸면 올린다.
# 사전생성 스냅숏 재사용 판정(is_fresh)이 이 값을 본다.
# /2 — 경계에 원 단위 절사 오차 1원을 허용(BOUNDARY_TOLERANCE_WON). 판정이 바뀌므로
# 올려야 낡은 캐시가 폐기된다.
FEE_RULES_VERSION = "fee-rules-ko/2"

RULESET_CURRENT = "MOLIT_2025_334"
RULESET_PREVIOUS = "PRE_2025_334"

# fee_bands()가 받는 산식 코드 (위 레지스트리 코드와 이름이 다르다)
_FORMULA_BY_RULESET = {
    RULESET_PREVIOUS: "pre-2025-334",
    RULESET_CURRENT: "2025-334",
}

DEVIATION_MISSING = "수수료 미입력"
DEVIATION_BELOW = "하한 미만"
DEVIATION_ABOVE = "상한 초과"
DEVIATION_WITHIN = "기준 내"


def fee_bands(
    appraisal_amount: float | Decimal,
    *,
    ruleset: str = "2025-334",
) -> tuple[float, float, float]:
    """보수기준 버전별 기준·80% 하한·120% 상한.

    2025-334는 2025-03-17 이후 최초 계약 건에 적용되는 기본수수료 인상표다.
    계약일이 없는 경우에는 호출자가 버전을 확정하지 말고 별도 품질 상태를 남겨야 한다.
    """
    amount = float(appraisal_amount or 0)
    if ruleset not in {"pre-2025-334", "2025-334"}:
        raise ValueError(f"지원하지 않는 보수기준 버전입니다: {ruleset}")
    base_adjustment = -50_000 if ruleset == "pre-2025-334" else 0
    tiers = (
        (50_000_000, 0, 250_000, 250_000, 250_000),
        (500_000_000, 11, 195_000, 206_000, 184_000),
        (1_000_000_000, 9, 295_000, 286_000, 304_000),
        (5_000_000_000, 8, 395_000, 366_000, 424_000),
        (10_000_000_000, 7, 895_000, 766_000, 1_024_000),
        (50_000_000_000, 6, 1_895_000, 1_566_000, 2_224_000),
        (100_000_000_000, 5, 6_895_000, 5_566_000, 8_224_000),
        (300_000_000_000, 4, 16_895_000, 13_566_000, 20_224_000),
        (600_000_000_000, 3, 46_895_000, 37_566_000, 56_224_000),
        (1_000_000_000_000, 2, 106_895_000, 85_566_000, 128_224_000),
        (float("inf"), 1, 206_895_000, 165_566_000, 248_224_000),
    )
    for limit, rate, standard_constant, lower_constant, upper_constant in tiers:
        if amount <= limit:
            if rate == 0:
                base = 250_000.0 + base_adjustment
                return base, base, base
            variable = amount * rate / 10_000
            return (
                variable + standard_constant + base_adjustment,
                variable * 0.8 + lower_constant + base_adjustment,
                variable * 1.2 + upper_constant + base_adjustment,
            )
    raise AssertionError("unreachable")


# 경계에서 이만큼까지는 '기준 내'다. APWorks 청구액이 하한 밴드보다 정확히 1원
# 적게 끊기는 건이 2026년 1~7월에 5건 있었다(전부 요율 0.8·할인 없음, 청구액이
# floor(하한)-1원). 화면에서는 요율적용금액과 순수수료가 같은 숫자로 보이는데 행만
# 이탈색으로 칠해져 재무팀이 헛짚는다. 재무팀 확정 엑셀도 이 건에 의견을 달지 않았다
# (01-2603-3-1032: 하한 791,131.8112 / 청구 791,130 / 격차율 -0.0000023, 의견란 공란).
# 실제 이탈 중 가장 작은 폭이 10,690원이라 1원을 허용해도 진짜 이탈은 섞이지 않는다.
BOUNDARY_TOLERANCE_WON = 1.0


def deviation(actual_fee: Any, lower_fee: Any, upper_fee: Any) -> str:
    """실제 순수수료의 이탈 방향. NULL은 0원으로 뭉개지 않고 '수수료 미입력'이다.

    원 단위 운영 경계라 하한은 floor, 상한은 ceil을 쓰고 경계값 자체는 '기준 내'다.
    여기에 원 단위 절사 오차 1원을 더 허용한다(BOUNDARY_TOLERANCE_WON).
    """
    if actual_fee is None:
        return DEVIATION_MISSING
    if float(actual_fee) < floor(float(lower_fee)) - BOUNDARY_TOLERANCE_WON:
        return DEVIATION_BELOW
    if float(actual_fee) > ceil(float(upper_fee)) + BOUNDARY_TOLERANCE_WON:
        return DEVIATION_ABOVE
    return DEVIATION_WITHIN


def decision_status(deviation_direction: str) -> str:
    """이탈 방향 → 검토 상태. 이탈 건은 사유 확인 전까지 '확인 필요'로 둔다."""
    if deviation_direction in (DEVIATION_WITHIN, DEVIATION_MISSING):
        return deviation_direction
    return "확인 필요"


def as_date(value: Any) -> date | None:
    """datetime/date/문자열을 date로. 파싱 실패는 예외 대신 None(버전 미확정)으로 흘린다."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if value:
        try:
            return date.fromisoformat(str(value)[:10])
        except ValueError:
            return None
    return None


def to_number(value: Any) -> int | float | None:
    """SQL Server decimal/money를 정수면 int, 아니면 float로. None은 None 그대로 둔다."""
    if value is None:
        return None
    number = Decimal(str(value))
    return int(number) if number == number.to_integral_value() else float(number)


def ruleset_for(
    *,
    receipt_date: Any = None,
    contract_date: Any = None,
    ruleset_code: str | None = None,
) -> dict[str, Any]:
    """적용할 보수표 버전과 그 근거 상태.

    우선순위: 호출자가 지정한 코드 > 계약일 > 접수일(제안값).
    계약일 근거가 없으면 접수일로 계산은 보여주되 status를 UNCONFIRMED로 남겨
    화면이 '보수표 버전 미확정'을 표시할 수 있게 한다 (접수일은 계약일이 아니다).
    """
    given = str(ruleset_code or "").strip()
    if given:
        return {
            "fee_ruleset_code": given,
            "fee_ruleset_status": "CONFIRMED",
            "contract_date": as_date(contract_date),
            "contract_date_source": "CONTRACT_RULE" if contract_date else "GIVEN",
        }

    contract = as_date(contract_date)
    if contract is not None:
        code = RULESET_PREVIOUS if contract < FEE_RULESET_CUTOFF else RULESET_CURRENT
        return {
            "fee_ruleset_code": code,
            "fee_ruleset_status": "CONFIRMED_FROM_CONTRACT_RULE",
            "contract_date": contract,
            "contract_date_source": "CONTRACT_RULE",
        }

    receipt = as_date(receipt_date)
    code = (
        RULESET_PREVIOUS
        if receipt is not None and receipt < FEE_RULESET_CUTOFF
        else RULESET_CURRENT
    )
    return {
        "fee_ruleset_code": code,
        "fee_ruleset_status": "UNCONFIRMED",
        "contract_date": None,
        "contract_date_source": "UNKNOWN",
    }


def evaluate(
    *,
    appraisal_amount: Any,
    actual_fee: Any,
    receipt_date: Any = None,
    contract_date: Any = None,
    ruleset_code: str | None = None,
) -> dict[str, Any]:
    """감정서 한 건의 보수기준 계산 결과. 호출자가 원본 행에 병합해서 쓴다.

    actual_fee가 None이면 0원으로 바꾸지 않는다 — '수수료 미입력'과 '0원 청구'는
    재무팀 대사에서 의미가 전혀 다르다.
    """
    appraisal = float(appraisal_amount or 0)
    actual = None if actual_fee is None else float(actual_fee)
    version = ruleset_for(
        receipt_date=receipt_date,
        contract_date=contract_date,
        ruleset_code=ruleset_code,
    )
    formula = _FORMULA_BY_RULESET.get(version["fee_ruleset_code"], "2025-334")
    standard, lower, upper = fee_bands(appraisal, ruleset=formula)
    direction = deviation(actual, lower, upper)
    return {
        **version,
        "appraisal_amount": appraisal,
        "actual_fee": actual,
        "standard_fee": standard,
        "lower_fee": lower,
        "upper_fee": upper,
        "actual_rate": (
            actual / standard if actual is not None and standard else None
        ),
        "deviation_direction": direction,
        "decision_status": decision_status(direction),
    }


# ======================== 적용 요율 ========================

# SusuRate → 어느 밴드로 청구했는가.
BAND_BY_RATE = {0.8: "lower_fee", 1.0: "standard_fee", 1.2: "upper_fee"}

# 예상 금액과 실제 청구액이 이 이상 벌어지면 요율로 설명되지 않는 건으로 본다.
# 원 단위 반올림이 있어 절대 2원 또는 0.1%를 허용한다.
MATCH_ABS_TOLERANCE = 2.0
MATCH_RATIO_TOLERANCE = 0.001


def fetch_rates(doc_ids: "list[str]") -> "dict[str, dict[str, Any]]":
    """감정서별 원천 요율. {감정서번호: {susu_rate, susu_dc}}

    한 감정서에 청구행이 여럿이고 값이 다르면 대표를 고르지 않고 conflict로 남긴다.
    """
    unique = list(dict.fromkeys(doc for doc in doc_ids if doc))
    if not unique:
        return {}
    found: "dict[str, dict[str, Any]]" = {}
    raw = get_source_engine().raw_connection()
    try:
        cursor = raw.cursor()
        for start in range(0, len(unique), 200):
            chunk = unique[start:start + 200]
            placeholders = ", ".join("CAST(? AS VARCHAR(30))" for _ in chunk)
            cursor.execute(
                f"""
                SELECT RTRIM(m.DocID), b.SusuRate, b.SusuDc
                FROM APW_MASTER m
                JOIN APW_BILL b ON b.MasterID = m.MasterID
                WHERE RTRIM(m.DocID) IN ({placeholders})
                """,
                chunk,
            )
            for doc, rate, discount in cursor.fetchall():
                key = str(doc or "").strip()
                if not key:
                    continue
                value = {
                    "susu_rate": None if rate is None else float(rate),
                    "susu_dc": None if discount is None else float(discount),
                }
                previous = found.get(key)
                if previous is None:
                    found[key] = value
                elif previous != value and not previous.get("conflict"):
                    # 청구행마다 요율이 다르면 어느 값이 맞는지 알 수 없다.
                    found[key] = {**previous, "conflict": True}
    finally:
        raw.close()
    return found


def describe(
    source: "dict[str, Any] | None",
    *,
    billed_fee: Any,
    standard_fee: Any,
    lower_fee: Any,
    upper_fee: Any,
) -> "dict[str, Any]":
    """원천 요율 + 실효율 + 둘이 어긋나는지.

    반환
      applied_rate      원천 SusuRate (없으면 None)
      applied_discount  원천 SusuDc
      effective_rate    청구 / 기준 — 금액에서 역산한 실효율
      rate_label        화면·엑셀에 그대로 쓰는 문구
      rate_explained    원천 요율로 청구액이 설명되는지
    """
    bands = {
        "standard_fee": _number(standard_fee),
        "lower_fee": _number(lower_fee),
        "upper_fee": _number(upper_fee),
    }
    billed = _number(billed_fee)
    standard = bands["standard_fee"]
    effective = (
        billed / standard if billed is not None and standard else None
    )

    rate = (source or {}).get("susu_rate")
    discount = (source or {}).get("susu_dc")
    conflict = bool((source or {}).get("conflict"))

    # 요율적용금액 — 적용한 요율의 **밴드 금액**이다. 할인(SusuDc)은 곱하지 않는다.
    # 재무팀 엑셀 Y열이 그 정의다(실측 2026-05 대조: 할인을 곱했더니 9건이 어긋났고,
    # 01-2602-3-0636 은 엑셀 81,939,370 인데 우리는 x0.7 한 57,357,559 였다).
    # 할인은 별도 열(SusuDc)과 요율 표시에서 본다.
    applied_fee = None
    explained = False
    if not conflict and rate is not None:
        band = bands.get(BAND_BY_RATE.get(rate, ""))
        if band:
            applied_fee = band
            if billed is not None:
                # 청구액이 설명되는지는 할인까지 감안해 판정한다 — 표시값과 판정 기준이
                # 다른 이유는 엑셀 표기(밴드)와 실제 청구 공식(밴드 x 할인)이 달라서다.
                expected = band * (1.0 if discount is None else discount)
                tolerance = max(
                    MATCH_ABS_TOLERANCE, abs(expected) * MATCH_RATIO_TOLERANCE
                )
                explained = abs(billed - expected) <= tolerance

    return {
        "applied_rate": rate,
        "applied_discount": discount,
        "rate_applied_fee": applied_fee,
        "effective_rate": effective,
        "rate_conflict": conflict,
        "rate_explained": explained,
        "rate_label": _label(
            rate=rate, discount=discount, effective=effective,
            conflict=conflict, explained=explained,
        ),
    }


def _label(
    *,
    rate: "float | None",
    discount: "float | None",
    effective: "float | None",
    conflict: bool,
    explained: bool,
) -> str:
    """요율 표시 문구. 정상이면 짧게, 어긋나면 실효율을 함께 보여준다."""
    if conflict:
        return "요율 원천 충돌"
    if rate is None:
        # 원천에 요율이 없다. 금액에서 역산한 값만 근사로 알려준다.
        return "" if effective is None else f"실효 {effective:.2f}"
    text = _trim(rate)
    if discount is not None and abs(discount - 1.0) > 1e-9:
        text += f" x{_trim(discount)}"
    if not explained and effective is not None:
        # 정액 계약·합산청구·예규 할증처럼 보수표 밖에서 정해진 건이다.
        text += f" (실효 {effective:.2f})"
    return text


def _trim(value: float) -> str:
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return text or "0"


def _number(value: Any) -> "float | None":
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# ======================== 조회 스냅숏 ========================

SNAPSHOT_PROFILE = "FEE_BASIS_CHECK_V1"

# 마감된 달은 원천이 거의 안 변하고, 당월은 전표가 계속 붙는다.
MAX_AGE_CURRENT = timedelta(hours=6)
MAX_AGE_CLOSED = timedelta(hours=30)
KST = timezone(timedelta(hours=9))

# 판별 규칙을 바꾸면 올린다. 올리지 않으면 낡은 캐시가 계속 나온다.
# 실측으로 두 번 겪었다 — 빈 결과가 캐시돼 있는데 응답이 빨라서 정상처럼 보였다.
# /2 — 기준시점을 산출근거 본문에서 되찾는다(_basis_dates_from_chunks).
# /3 — 그 복구가 평가선례 표의 '기준시점' 열에서 남의 날짜를 주워오던 것을 막고,
#      제5조 '6월 이상' 판정을 달력 월 뺄셈에서 실제 경과 기간으로 바꿨다.
#      /2 로 이미 박힌 스냅숏을 폐기해야 하므로 반드시 올린다.
BASIS_RULES_VERSION = "fee-basis-detect/3"

# 스냅숏에 담는 필드가 바뀌면 올린다. 규칙이 그대로여도 형태가 다르면 화면·저장이 깨진다.
# /2: 저장용 source_row_number 추가. /1 스냅숏에는 그 필드가 없어 KeyError가 났다.
# /3: 보수기준 검토 판정을 후보 목록에 합침(ab_keyword·evidence_grade 추가).
# /4: 기준 내 행에 붙던 `수수료차액발생 0`(54건)과 `담당자확인요청`(63건) 제거.
# /5: 적용 요율을 원천(APW_BILL.SusuRate/SusuDc)에서 읽는다. 종전에는 0.8 상수였다.
# /6: 문서없음·기타확인을 후보에서 빼고 의견을 `확인필요`로 통일. 요율적용금액 추가.
# /7: 의견을 감정서번호 키로 별도 행에 저장(배치가 지우지 않는다).
# /8: 요율적용금액에서 할인(SusuDc)을 빼 재무팀 엑셀 Y열 정의에 맞춤.
# /9: 0원 청구를 '하한 미만'이 아니라 '0원 청구 확인'으로(배포 전 검토 발견).
# /11: 격차율 기준선을 하한 → 요율적용금액으로(재무팀 엑셀 Z열 정의). 저장된 값이라
#      올리지 않으면 배포해도 화면은 옛 격차율을 계속 내준다 — 배치가 다시 만드는
#      최근 몇 달만 바뀌고 그 밖 기간은 영영 옛 값으로 남는다.
SNAPSHOT_SHAPE_VERSION = "fee-basis-snapshot/11"


# 스냅숏 행이 반드시 가져야 하는 필드. 버전을 올리는 것을 잊어도 여기서 걸린다.
#
# 왜 필요한가: 스냅숏에 필드를 추가할 때마다 SNAPSHOT_SHAPE_VERSION 을 올려야 하는데
# 오늘 세 번 잊었다. 낡은 캐시가 그대로 재사용돼 화면이 조용히 이상해졌다.
#   /2 source_row_number 누락 → 조회에서 KeyError
#   /5 primary_candidate 누락 → 화면이 대표 후보 대신 첫 후보(기본 요율체계)를 표시
#   /8 요율 필드 누락
# 사람이 기억하는 대신 코드가 검사한다. 필드를 새로 쓰기 시작하면 이 목록에 넣는다.
REQUIRED_ITEM_FIELDS = (
    "doc_id",              # 의견 저장 키
    "source_row_number",   # 행 식별
    "appraisal_amount",    # 금액 판정
    "lower_fee",
    "standard_fee",
    "upper_fee",
    "actual_fee",
    "deviation_direction",
    "fee_state",
    "rate_applied_fee",    # 요율적용금액
    "applied_rate",
    "rate_label",
    "rate_explained",
    "candidates",          # 자동판별
    "primary_candidate",
    "primary_label",
    "suggested_opinion",   # 의견 초기값
    "verdict",
    "discount_state",      # 할인 적정성 (업무연락 제2026-38호)
    "discount_note",
)


def _stable_hash(value) -> str:
    import hashlib

    return hashlib.sha256(repr(value).encode("utf-8")).hexdigest()[:16]


def _rule_versions() -> "dict[str, str]":
    return {
        "basis_rules_version": BASIS_RULES_VERSION,
        "snapshot_shape_version": SNAPSHOT_SHAPE_VERSION,
        "fee_rules_version": FEE_RULES_VERSION,
        # 코드↔조문 라벨 표가 바뀌면 화면 문구가 달라진다. 개수만 보면 항목을 하나
        # 바꾸고 하나 지운 경우를 놓치므로(검토 발견) 내용 해시로 비교한다.
        "code_label_hash": _stable_hash(sorted(rules.FEE_CODE_LABELS.items())),
        "text_signal_hash": _stable_hash(sorted(rules.TEXT_SIGNALS)),
        # 보수기준 검토 판정도 후보에 들어가므로 그 버전들도 함께 본다.
        "keyword_rule_version": KEYWORD_RULE_VERSION,
        "search_engine_version": SEARCH_ENGINE_VERSION,
        # 업무실적과 공유하는 모집단이 바뀌면 행 수가 달라진다. 여기에 없으면 캐시된
        # 스냅숏이 옛 목록을 계속 내주고, 나중에 다른 이유로 재생성될 때 조용히 바뀐다.
        "population_version": POPULATION_VERSION,
    }


def build_snapshot(
    db: Session,
    *,
    office_id: str,
    year: int,
    month: int,
    half: Half,
    basis: Basis,
) -> "dict[str, Any]":
    """필터·페이지를 적용하지 않은 전체 결과 + 재사용 판정용 메타."""
    report = build_fee_basis_report(
        db,
        office_id=office_id,
        year=year,
        month=month,
        half=half,
        basis=basis,
        flt="전체",
        page=1,
        page_size=1_000_000,
    )
    # 행 식별자. 저장 엔진이 "몇 행 의견인지"를 이 번호로 잡는다. 감정서번호를 키로
    # 쓰지 않는 이유: 접미사·자번호 표기가 원천마다 달라 같은 건이 다른 키가 될 수 있다.
    items = report.get("items") or []
    for number, item in enumerate(items, 1):
        item["source_row_number"] = number

    # 보수기준 검토 판정을 같은 코드 체계로 합친다. 실패해도 행은 그대로 남는다.
    evidence = attach_review_evidence(items)

    created_at = datetime.now(timezone.utc).isoformat()
    return {
        **report,
        "items": items,
        "evidence_summary": evidence,
        # 근거 원천이 죽어도 행 수는 그대로 나온다. 화면에 알리지 않으면 근거 0건
        # 결과를 확정본으로 쓴다.
        "jun_error": evidence.get("jun_error"),
        "apw_error": evidence.get("apw_error"),
        "prior_error": evidence.get("prior_error"),
        "office_code": office_id,
        "year": year,
        "month": month,
        "half": half,
        "basis": basis,
        "profile": SNAPSHOT_PROFILE,
        "row_count": len(report.get("items") or []),
        "snapshot_created_at": created_at,
        "prepared_at": created_at,
        "rule_versions": _rule_versions(),
    }


def is_fresh(
    snapshot: "dict[str, Any]",
    *,
    now: "datetime | None" = None,
) -> bool:
    """이 스냅숏을 그대로 보여줘도 되는지.

    시간이 남아 있어도 판별 규칙·보수표 버전이 코드와 다르면 다시 만든다.
    """
    if not isinstance(snapshot, dict):
        return False
    recorded = snapshot.get("rule_versions") or {}
    if recorded != _rule_versions():
        return False

    raw = snapshot.get("prepared_at") or snapshot.get("snapshot_created_at")
    if not raw:
        return False
    try:
        prepared_at = datetime.fromisoformat(str(raw))
    except (TypeError, ValueError):
        return False
    if prepared_at.tzinfo is None:
        prepared_at = prepared_at.replace(tzinfo=timezone.utc)

    current = now or datetime.now(timezone.utc)
    try:
        period = (int(snapshot.get("year") or 0), int(snapshot.get("month") or 0))
    except (TypeError, ValueError):
        return False
    current_kst = current.astimezone(KST)
    max_age = (
        MAX_AGE_CURRENT
        if period == (current_kst.year, current_kst.month)
        else MAX_AGE_CLOSED
    )
    if current - prepared_at > max_age:
        return False

    # 버전을 올리는 것을 잊었어도 필드가 빠졌으면 여기서 버린다. 첫 행만 봐도 충분하다 —
    # 같은 코드가 만든 스냅숏이라 행마다 필드 구성이 다를 수 없다.
    items = snapshot.get("items") or []
    if items:
        missing = [
            field for field in REQUIRED_ITEM_FIELDS if field not in items[0]
        ]
        if missing:
            return False
    return True


def _opinion_view(
    item: "dict[str, Any]", saved: "dict[str, str]"
) -> "dict[str, Any]":
    """행 하나의 의견 표시값.

    키가 있으면 저장값이 이긴다 — 빈 문자열이어도. 예전에는 `saved.get(...) or 제안`
    이라 담당자가 비운 칸에 자동 제안이 되살아났다(실측 확인).
    """
    key = str(item.get("doc_id") or "").strip()
    raw = saved.get(key)
    if raw is None:
        return {
            "saved_opinion": "",
            "opinion_cleared": False,
            "effective_opinion": str(item.get("suggested_opinion") or ""),
        }
    text = str(raw)
    return {
        "saved_opinion": text,
        "opinion_cleared": not text.strip(),
        "effective_opinion": text,
    }


def select_view(
    snapshot: "dict[str, Any]",
    *,
    flt: str = "전체",
    page: int = 1,
    page_size: int = 50,
    opinions: "dict[str, str] | None" = None,
) -> "dict[str, Any]":
    """동결된 전체 목록에서 화면 조건만 적용한다. 원천을 다시 보지 않는다.

    opinions: 저장된 담당자 의견. 자동 제안이 이 값을 덮지 않는다 — 재무팀 확정 의견을
    자동값으로 지우는 사고를 막는 규칙이다.
    """
    # 의견은 감정서번호로 맞춘다. 행 번호는 순번이라 원천에 행이 추가·삭제되면
    # 5행이 다른 감정서가 되고 옛 의견이 엉뚱한 행에 붙는다.
    saved = opinions or {}
    items = [
        {
            **item,
            **_opinion_view(item, saved),
        }
        for item in (snapshot.get("items") or [])
    ]
    if flt == "불일치":
        items = [i for i in items if i.get("verdict") == "불일치"]
    elif flt == "미입력":
        items = [i for i in items if i.get("verdict") == "미입력"]
    elif flt == "금액이탈":
        items = [
            i for i in items
            if i.get("deviation_direction") in (
                DEVIATION_BELOW, DEVIATION_ABOVE
            )
        ]
    elif flt == "할인위험":
        items = [
            i for i in items
            if i.get("discount_state") in (
                rules.DISCOUNT_STATE_OVER, rules.DISCOUNT_STATE_NO_BASIS
            )
        ]
    elif flt == "격차발생":
        # 요율을 몰라 격차율을 못 낸 행(None)은 '발생'이 아니다 — 기준선이 없을 뿐이라
        # 여기에 섞으면 정작 어긋난 건이 묻힌다. 그런 행은 '불일치'·'금액이탈'로 본다.
        items = [
            i for i in items
            if i.get("reference_gap_rate") is not None
            and abs(float(i["reference_gap_rate"])) >= GAP_OCCURRED_MIN
        ]
    offset = max(page - 1, 0) * page_size
    return {
        "summary": {
            **(snapshot.get("summary") or {}),
            "jun_error": snapshot.get("jun_error"),
            "apw_error": snapshot.get("apw_error"),
            "prior_error": snapshot.get("prior_error"),
        },
        "total": len(items),
        "page": page,
        "page_size": page_size,
        "items": items[offset:offset + page_size],
    }


# ======================== 담당자 의견 ========================

OPINION_PROFILE = "FEE_BASIS_OPINION_V1"

# 의견은 캐시가 아니라 기록이다. 기본 90일 TTL 이 지나면 조회 필터에서 걸러져 조용히
# 사라지고, 만료 후 첫 저장이 빈 병합 기반 위에 덮어써 기존 의견을 영구 소실시킨다
# (배포 전 검토에서 확정된 결함). 사실상 만료 없음으로 저장한다.
OPINION_TTL_SECONDS = 100 * 365 * 24 * 60 * 60

# load→merge→save 가 원자적이지 않아 동시 저장이 서로를 지울 수 있다(lost update).
# 서버가 단일 프로세스라 in-process 잠금으로 직렬화한다. 다중 worker 로 늘리면
# sp_getapplock 으로 바꿔야 한다.
_SAVE_LOCK = threading.Lock()


class OpinionValidationError(ValueError):
    pass


class OpinionSourceChanged(OpinionValidationError):
    """The browser is editing a snapshot that is no longer current."""


def load_with_source(
    db: Session,
    *,
    office_code: str,
    year: int,
    month: int,
    half: str,
    basis: str,
) -> "tuple[dict[str, str], str]":
    """({감정서번호: 의견}, 저장 당시 원천 해시).

    해시를 함께 돌려주는 이유: 감정서번호로 맞추므로 옛 의견이 엉뚱한 행에 붙지는
    않지만, 저장 당시와 금액이 달라졌을 수 있다(`수수료차액발생 170,344`처럼 금액을
    적은 의견은 값이 낡는다). 화면이 재확인을 안내할 수 있게 남긴다.
    """
    try:
        run = find_prepared_run(
            office_code=office_code, year=year, month=month,
            basis=basis, half=half, profile=OPINION_PROFILE, db=db,
        )
    except (RunNotFound, RunExpired):
        return {}, ""
    return _opinions_from_run(run)


def _opinions_from_run(run: Any) -> "tuple[dict[str, str], str]":
    """저장된 행에서 ({감정서번호: 의견}, 저장 당시 원천 해시)."""
    data = getattr(run, "data", None) or {}
    stored = data.get("opinions")
    if not isinstance(stored, dict):
        return {}, ""
    return (
        # 빈 값을 버리지 않는다 — '일부러 비운 기록'과 '저장한 적 없음'은 다르다.
        # 키는 select_view 의 조회 키와 맞추려고 strip 한다.
        {
            str(doc).strip(): str(text)
            for doc, text in stored.items()
            if str(doc).strip()
        },
        str(data.get("snapshot_source_sha256") or ""),
    )


def load(
    db: Session,
    *,
    office_code: str,
    year: int,
    month: int,
    half: str,
    basis: str,
) -> "dict[str, str]":
    opinions, _source = load_with_source(
        db, office_code=office_code, year=year, month=month,
        half=half, basis=basis,
    )
    return opinions


def save(
    db: Session,
    *,
    office_code: str,
    year: int,
    month: int,
    half: str,
    basis: str,
    opinions: "dict[str, str]",
    snapshot_run_id: str,
    snapshot_source_sha256: str,
    snapshot_profile: str,
) -> "dict[str, str]":
    """변경분만 병합 저장한다. 빈 값은 삭제로 본다.

    저장 직전에 조회 스냅숏을 행 잠금으로 다시 확인한다. 배치가 새 스냅숏으로
    바꿨거나 목록에 없는 감정서번호면 저장하지 않는다.
    """
    with _SAVE_LOCK:
        try:
            snapshot = find_prepared_run(
                office_code=office_code,
                year=year,
                month=month,
                half=half,
                basis=basis,
                profile=snapshot_profile,
                lock_for_update=True,
                db=db,
            )
        except (RunNotFound, RunExpired) as exc:
            raise OpinionSourceChanged(
                "조회한 원천이 만료되었습니다. 다시 조회한 뒤 저장해 주세요."
            ) from exc
        if (
            snapshot.run_id != snapshot_run_id
            or not hmac.compare_digest(
                str(snapshot.source_sha256 or ""),
                str(snapshot_source_sha256 or ""),
            )
        ):
            raise OpinionSourceChanged(
                "조회 후 원천 데이터가 변경되었습니다. 다시 조회한 뒤 저장해 주세요."
            )
        known_doc_ids = {
            str(item.get("doc_id") or "").strip()
            for item in (snapshot.data.get("items") or [])
            if str(item.get("doc_id") or "").strip()
        }
        return _save_locked(
            db, office_code=office_code, year=year, month=month, half=half,
            basis=basis, opinions=opinions, known_doc_ids=known_doc_ids,
            snapshot_source_sha256=snapshot_source_sha256,
        )


def _save_locked(
    db: Session,
    *,
    office_code: str,
    year: int,
    month: int,
    half: str,
    basis: str,
    opinions: "dict[str, str]",
    known_doc_ids: "set[str]",
    snapshot_source_sha256: str,
) -> "dict[str, str]":
    merged = load(
        db, office_code=office_code, year=year, month=month,
        half=half, basis=basis,
    )
    for raw_doc, raw_text in (opinions or {}).items():
        doc = str(raw_doc or "").strip()
        if not doc:
            raise OpinionValidationError("감정서번호가 비어 있습니다.")
        if doc not in known_doc_ids:
            raise OpinionValidationError(f"{doc}는 현재 목록에 없습니다.")
        if raw_text is None:
            # null 은 '자동 제안으로 복귀'다. 기록을 지우는 유일한 방법이며 화면에는
            # 아직 경로가 없다(API 로만 가능).
            merged.pop(doc, None)
            continue
        text = str(raw_text)
        if len(text) > MAX_OPINION_LENGTH:
            raise OpinionValidationError(
                f"{doc} 의견이 {MAX_OPINION_LENGTH}자를 넘습니다."
            )
        # 빈 문자열은 삭제가 아니라 '담당자가 일부러 비웠다'는 기록이다. 지우면 자동
        # 제안이 되살아나는데, 그 제안 문구는 배치가 규칙을 고칠 때마다 바뀌고
        # (실측 2026-04 하반 179행 중 10건) 엑셀 '의견' 열로도 나간다. 검토를 끝낸
        # 행이 '확인필요'로 되돌아가는 셈이라 담당자 입력을 뒤집는다.
        merged[doc] = text

    save_prepared_run(
        {
            "office_code": office_code,
            "year": year,
            "month": month,
            "half": half,
            "basis": basis,
            "profile": OPINION_PROFILE,
            "opinions": merged,
            # 저장 당시 원천 해시. 이후 금액이 달라지면 화면이 재확인을 안내한다.
            "snapshot_source_sha256": snapshot_source_sha256,
            # 스냅숏 형식 검증을 타지 않도록 items 는 두지 않는다.
            "row_count": len(merged),
        },
        office_code=office_code, half=half, profile=OPINION_PROFILE,
        ttl_seconds=OPINION_TTL_SECONDS, db=db,
    )
    return merged


def apply_to_items(
    items: "list[dict[str, Any]]",
    opinions: "dict[str, str]",
) -> None:
    """저장 의견을 행에 붙인다(제자리). 자동 제안을 덮지 않는다.

    감정서번호로 맞추므로 행 순서가 바뀌어도 옛 의견이 엉뚱한 행에 붙지 않는다.
    """
    for item in items:
        item.update(_opinion_view(item, opinions or {}))


# ======================== 사전생성 배치와 CLI ========================

# 보수기준 검토 배치와 다른 자원명을 쓴다. 같은 이름이면 둘 중 하나가 건너뛰어진다.
LOCK_RESOURCE = "A10Bridge_FeeBasisPrepare"

HALVES = ("상반", "하반")
DEFAULT_OFFICE = "10"


class FeeBasisPrepareAlreadyRunning(RuntimeError):
    pass


@contextmanager
def prepare_lock() -> Iterator[None]:
    """여러 회차가 겹치지 않도록 SQL Server 세션 잠금을 잡는다."""
    connection = get_engine().connect()
    acquired = False
    try:
        result = connection.execute(
            text(
                """
                DECLARE @result int;
                EXEC @result = sys.sp_getapplock
                    @Resource = :resource,
                    @LockMode = 'Exclusive',
                    @LockOwner = 'Session',
                    @LockTimeout = 0;
                SELECT @result;
                """
            ),
            {"resource": LOCK_RESOURCE},
        ).scalar_one()
        acquired = int(result) >= 0
        if not acquired:
            raise FeeBasisPrepareAlreadyRunning(
                "다른 보수기준 점검 사전생성 작업이 실행 중입니다."
            )
        yield
    finally:
        if acquired:
            try:
                connection.execute(
                    text(
                        """
                        EXEC sys.sp_releaseapplock
                            @Resource = :resource,
                            @LockOwner = 'Session';
                        """
                    ),
                    {"resource": LOCK_RESOURCE},
                )
            finally:
                connection.close()
        else:
            connection.close()


def month_targets(today: date, months_back: int) -> "list[tuple[int, int]]":
    if months_back < 0 or months_back > 24:
        raise ValueError("--months-back은 0~24 사이여야 합니다.")
    targets: list[tuple[int, int]] = []
    year, month = today.year, today.month
    for _ in range(months_back + 1):
        targets.append((year, month))
        if month == 1:
            year, month = year - 1, 12
        else:
            month -= 1
    return targets


def prepare(
    *,
    periods: "list[tuple[int, int]]",
    office_codes: "list[str] | None" = None,
    basis: str = "매출",
    halves: "tuple[str, ...]" = HALVES,
) -> "dict[str, int]":
    result = {"completed": 0, "failed": 0}
    wanted = office_codes or [DEFAULT_OFFICE]
    with prepare_lock():
        with get_session_factory()() as db:
            offices = list(
                db.scalars(
                    select(OfficeMap)
                    .where(OfficeMap.active == "Y", OfficeMap.office_id.in_(wanted))
                    .order_by(OfficeMap.sort_order, OfficeMap.office_id)
                ).all()
            )
            missing = sorted(set(wanted) - {office.office_id for office in offices})
            if missing:
                raise ValueError(f"활성 지사 매핑이 없습니다: {', '.join(missing)}")

            for year, month in periods:
                for office in offices:
                    for half in halves:
                        label = (
                            f"{year}-{month:02d} {half} {basis} "
                            f"{office.office_id} {office.office_name}"
                        )
                        try:
                            print(f"보수기준 점검 사전생성 시작: {label}")
                            snapshot = build_snapshot(
                                db,
                                office_id=office.office_id,
                                year=year,
                                month=month,
                                half=half,
                                basis=basis,
                            )
                            save_prepared_run(
                                snapshot,
                                office_code=office.office_id,
                                half=half,
                                profile=SNAPSHOT_PROFILE,
                                db=db,
                            )
                        except Exception as exc:
                            db.rollback()
                            result["failed"] += 1
                            print(
                                f"보수기준 점검 사전생성 실패: {label} "
                                f"({type(exc).__name__}: {exc})"
                            )
                            continue
                        result["completed"] += 1
                        summary = snapshot.get("summary") or {}
                        print(
                            f"보수기준 점검 사전생성 완료: {label}, "
                            f"{snapshot['row_count']:,}건, "
                            f"코드 불일치 {summary.get('mismatch', 0):,}건, "
                            f"금액 이탈 "
                            f"{summary.get('fee_below', 0) + summary.get('fee_above', 0):,}건"
                        )
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int)
    parser.add_argument("--month", type=int)
    parser.add_argument("--months-back", type=int, default=0)
    parser.add_argument(
        "--office", action="append", dest="office_codes",
        help=f"지사 코드(반복 지정). 생략하면 본사({DEFAULT_OFFICE})만.",
    )
    parser.add_argument(
        "--basis", choices=("매출", "접수", "전례"), default="매출",
    )
    parser.add_argument(
        "--half", choices=HALVES, action="append", dest="halves",
        help="반월(반복 지정). 생략하면 상반·하반 모두.",
    )
    args = parser.parse_args()

    if (args.year is None) != (args.month is None):
        parser.error("--year와 --month는 함께 입력하세요.")
    if args.month is not None and not 1 <= args.month <= 12:
        parser.error("--month는 1~12 사이여야 합니다.")
    if args.year is not None:
        periods = [(args.year, args.month)]
    else:
        try:
            periods = month_targets(date.today(), args.months_back)
        except ValueError as exc:
            parser.error(str(exc))

    try:
        result = prepare(
            periods=periods,
            office_codes=args.office_codes,
            basis=args.basis,
            halves=tuple(args.halves) if args.halves else HALVES,
        )
    except FeeBasisPrepareAlreadyRunning as exc:
        print(f"보수기준 점검 사전생성 건너뜀: {exc}")
        return
    print(
        f"보수기준 점검 사전생성 종료: 성공 {result['completed']:,}건, "
        f"실패 {result['failed']:,}건"
    )
    if result["failed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
