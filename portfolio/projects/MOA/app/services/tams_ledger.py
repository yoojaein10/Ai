"""TAMS 캐시 → 발급 원장(a10_issued_taxinvoice, source='TAMS') 이관·증분 반영 (2026-09-09).

TAMS 부가세.DB 를 끊는 준비: 발행 이력을 한 테이블에 모은다. TAMS 동기화는 캐시를
매번 통째로 지우고 다시 넣어(id 가 바뀜) 행의 정체는 내용 기반 해시로 잡는다 —
같은 행은 몇 번 돌려도 한 번만 들어간다.

규칙 (2026-09-09 실측·사용자 결정)
- 세금계산서 캐시는 '매출'만 옮긴다. 매입(22,834행)은 감정서번호가 하나도 없고 우리 매출이 아니다.
- 취소는 gubun 이 아니라 음수 금액 행 → doc_type '세금취소'. 현금영수증은 transaction_type '1' → '현금취소'.
- TAMS 승인번호는 국세청 번호가 아니라('010000000000' 등) nts_confirm 을 비운다.
  전표 부가세 줄에 가짜 승인번호가 실리면 안 된다. 현금영수증의 K/Z 번호는 진짜라 넣는다.
- MOA(팝빌) 발행분이 TAMS 대장에도 적힌 건은 TAMS 쪽을 건너뛴다 — 화면이 쓰던
  moa_tams_dup_guard 와 같은 조건(같은 감정서 + 승인번호 일치 또는 같은 날·같은 합계).
- 감정서번호 없는 행(매출 10,613건)도 옮긴다 — doc_id 빈값. 화면 집계는 번호 기준이라 영향 없다.
- 이상 날짜(2000년 이전·2027년 이후)는 건너뛰고 보고한다.
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime
from typing import Any

from sqlalchemy import insert, select, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import IssuedTaxInvoice

SOURCE = "TAMS"
DATE_MIN, DATE_MAX = date(2000, 1, 1), date(2027, 12, 31)
CHUNK = 2000


def _digits(value: Any) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def _int(value: Any) -> int:
    try:
        return int(round(float(str(value or 0).replace(",", ""))))
    except ValueError:
        return 0


def _hash(*parts: Any) -> str:
    return hashlib.sha1("|".join(str(p or "").strip() for p in parts).encode("utf-8")).hexdigest()[:20]


def tax_key(row: dict[str, Any]) -> str:
    """세금계산서 캐시 행의 정체 — 재적재로 id 가 바뀌어도 같다."""
    return "TAMS-" + _hash(row.get("branch_code"), row.get("bill_year"), row.get("seq_no"), row.get("bal_date"),
                           _int(row.get("sup_am")), _int(row.get("vat_am")), _digits(row.get("reg_nb")),
                           row.get("appraisal_no"))


def cash_key(row: dict[str, Any]) -> str:
    """현금영수증 캐시 행의 정체 — 승인번호가 다른 날 재사용되는 일이 있어 날짜·금액을 섞는다."""
    return "TAMSC-" + _hash(row.get("approval_no"), row.get("transaction_type"), row.get("transaction_date"),
                            _int(row.get("total_amount")), row.get("appraisal_no"))


def _as_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raw = _digits(value)
    if len(raw) != 8:
        return None
    try:
        return date(int(raw[:4]), int(raw[4:6]), int(raw[6:8]))
    except ValueError:
        return None


def _moa_index(db: Session) -> tuple[set[str], dict[str, list[tuple[str, date | None, int]]]]:
    """MOA 발행분 — 승인번호 집합과 감정서별 (유형, 발행일, 합계) 목록."""
    rows = db.execute(
        select(IssuedTaxInvoice.doc_id, IssuedTaxInvoice.doc_type, IssuedTaxInvoice.nts_confirm,
               IssuedTaxInvoice.issue_dt, IssuedTaxInvoice.total)
        .where(IssuedTaxInvoice.is_test == False, IssuedTaxInvoice.source != SOURCE)  # noqa: E712
    ).all()
    confirms = {str(r.nts_confirm).strip() for r in rows if r.nts_confirm}
    by_doc: dict[str, list[tuple[str, date | None, int]]] = {}
    for r in rows:
        by_doc.setdefault(str(r.doc_id or "").strip(), []).append(
            (str(r.doc_type), _as_date(str(r.issue_dt or "")[:8]), _int(r.total)))
    return confirms, by_doc


def _is_moa_duplicate(doc_id: str, approval_no: str, bal_date: date, total: int,
                      confirms: set[str], by_doc: dict[str, list[tuple[str, date | None, int]]]) -> bool:
    if not doc_id:
        return False
    if approval_no and approval_no in confirms:
        return True
    # 세금취소도 본다 — 위하고분을 국세청 자료 엑셀로 먼저 넣으면(2026-09-11) TAMS 가 같은 취소를 또 넣어
    # 취소가 두 번 잡힌다. 합계 부호까지 같아야 맞으므로 발행분·취소분이 섞이지 않는다.
    return any(kind in ("세금계산서", "세금취소") and issued == bal_date and moa_total == total
               for kind, issued, moa_total in by_doc.get(doc_id, []))


def _tax_rows(db: Session) -> list[dict[str, Any]]:
    return [dict(r) for r in db.execute(text(
        "SELECT branch_code, bill_year, seq_no, bal_date, appraisal_no, reg_nb, company_nm, "
        "       sup_am, vat_am, total_am, approval_no "
        "FROM dbo.a10_tams_tax_cache WHERE branch_code = N'매출'"
    )).mappings().all()]


def _cash_rows(db: Session) -> list[dict[str, Any]]:
    return [dict(r) for r in db.execute(text(
        "SELECT approval_no, transaction_type, transaction_date, transaction_time, company_name, business_no, "
        "       supply_amount, vat_amount, total_amount, appraisal_no "
        "FROM dbo.a10_tams_cash_receipt_cache"
    )).mappings().all()]


def sync_tams_to_ledger(
    db: Session, *, dry_run: bool = False,
    tax_rows: list[dict[str, Any]] | None = None, cash_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """TAMS 캐시(매출 세금계산서 + 현금영수증)를 원장에 없는 것만 넣는다. 몇 번 돌려도 같다."""
    is_test = get_settings().popbill_is_test
    if tax_rows is None:
        tax_rows = _tax_rows(db)
    if cash_rows is None:
        cash_rows = _cash_rows(db)
    existing = set(db.scalars(
        select(IssuedTaxInvoice.mgt_key).where(IssuedTaxInvoice.source == SOURCE)
    ).all())
    confirms, by_doc = _moa_index(db)

    report: dict[str, Any] = {
        "tax_scanned": len(tax_rows), "cash_scanned": len(cash_rows),
        "tax_new": 0, "tax_cancel": 0, "cash_new": 0, "cash_cancel": 0,
        "skipped_existing": 0, "skipped_moa_dup": 0, "skipped_bad_date": 0, "no_doc_id": 0,
        "dry_run": dry_run,
    }
    pending: list[dict[str, Any]] = []

    for row in tax_rows:
        key = tax_key(row)
        if key in existing:
            report["skipped_existing"] += 1
            continue
        bal_date = _as_date(row.get("bal_date"))
        if bal_date is None or not (DATE_MIN <= bal_date <= DATE_MAX):
            report["skipped_bad_date"] += 1
            continue
        doc_id = str(row.get("appraisal_no") or "").strip()
        supply, tax = _int(row.get("sup_am")), _int(row.get("vat_am"))
        total = _int(row.get("total_am")) or supply + tax
        if _is_moa_duplicate(doc_id, str(row.get("approval_no") or "").strip(), bal_date, total, confirms, by_doc):
            report["skipped_moa_dup"] += 1
            continue
        cancel = total < 0 or supply < 0
        pending.append(dict(
            doc_type="세금취소" if cancel else "세금계산서", doc_id=doc_id, mgt_key=key,
            receiver_corp_num=_digits(row.get("reg_nb")) or None,
            receiver_name=str(row.get("company_nm") or "").strip()[:200] or None,
            supply_cost=supply, tax=tax, total=total,
            nts_confirm=None,                       # TAMS 승인번호는 국세청 번호가 아니다
            issue_dt=bal_date.strftime("%Y%m%d"), write_date=bal_date,
            trade_usage=None, account_code=None, is_test=is_test, source=SOURCE,
        ))
        existing.add(key)
        report["tax_cancel" if cancel else "tax_new"] += 1
        if not doc_id:
            report["no_doc_id"] += 1

    for row in cash_rows:
        key = cash_key(row)
        if key in existing:
            report["skipped_existing"] += 1
            continue
        tdate = _as_date(row.get("transaction_date"))
        if tdate is None or not (DATE_MIN <= tdate <= DATE_MAX):
            report["skipped_bad_date"] += 1
            continue
        approval = str(row.get("approval_no") or "").strip()
        if approval and approval in confirms:
            report["skipped_moa_dup"] += 1
            continue
        doc_id = str(row.get("appraisal_no") or "").strip()
        cancel = str(row.get("transaction_type") or "") == "1"
        supply, tax = abs(_int(row.get("supply_amount"))), abs(_int(row.get("vat_amount")))
        total = abs(_int(row.get("total_amount"))) or supply + tax
        time_part = _digits(row.get("transaction_time"))[:6]
        pending.append(dict(
            doc_type="현금취소" if cancel else "현금영수증", doc_id=doc_id, mgt_key=key,
            receiver_corp_num=_digits(row.get("business_no")) or None,
            receiver_name=str(row.get("company_name") or "").strip()[:200] or None,
            supply_cost=supply, tax=tax, total=total,        # 현금취소도 양수 취소금액 (MOA 규칙)
            nts_confirm=approval or None,
            issue_dt=tdate.strftime("%Y%m%d") + time_part, write_date=tdate,
            trade_usage=None, account_code=None, is_test=is_test, source=SOURCE,
        ))
        existing.add(key)
        report["cash_cancel" if cancel else "cash_new"] += 1
        if not doc_id:
            report["no_doc_id"] += 1

    report["to_insert"] = len(pending)
    if not dry_run and pending:
        for i in range(0, len(pending), CHUNK):
            db.execute(insert(IssuedTaxInvoice), pending[i:i + CHUNK])
        db.commit()
    return report
