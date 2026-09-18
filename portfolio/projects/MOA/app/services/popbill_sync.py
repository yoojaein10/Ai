"""팝빌 → MOA 발급 원장 동기화 (2026-09-09).

MOA 밖에서 — 팝빌 사이트에서 직접 — 끊거나 취소한 세금계산서·현금영수증을
a10_issued_taxinvoice 에 흡수한다. TAMS 부가세.DB 동기화가 하던 "외부 발행분 흡수"
역할을 넘겨받는다(TAMS 계산서는 팝빌을 안 거치므로 TAMS 전환 뒤에야 완전 대체).

규칙
- 작성일자 기준 최근 N일(기본 14일)을 매일 다시 훑는다 — 늦게 사이트에서 끊은 건도 잡힌다.
- 국세청 승인번호가 원장에 있으면 건너뛴다 → MOA 가 끊은 건은 두 번 안 들어간다.
- 새 발행분은 source='팝빌동기화'. 문서관리번호가 감정서번호 형식이면 doc_id 로 쓰고,
  아니면 빈값으로 두고 '미매핑'으로 보고한다(원장에서 빠지지는 않는다).
- 세금계산서 취소(팝빌 상태 6xx)는 원장에 발행 행이 있고 취소 행이 아직 없을 때만 음수 행을
  붙인다. 현금영수증 취소는 팝빌이 '취소거래' 별도 문서(고유 승인번호)로 주므로 승인번호
  기준으로 새 문서처럼 흡수한다 — 둘 다 MOA 취소 저장 규칙(세금취소·현금취소)과 같은 모양.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import IssuedTaxInvoice
from app.services import popbill_tax

SOURCE = "팝빌동기화"
CANCEL_SUFFIX = "-SYNC-C"
_DOC_ID_RE = re.compile(r"^(\d{2}-\d{4}-[0-9A-Za-z]-\d{4})")


def doc_id_from_mgt_key(mgt_key: str | None) -> str:
    """팝빌 문서관리번호 앞부분이 감정서번호 형식(01-2609-3-2761…)이면 그것을 감정서번호로."""
    match = _DOC_ID_RE.match(str(mgt_key or "").strip())
    return match.group(1) if match else ""


def _attr(item: Any, name: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


def _int(value: Any) -> int:
    try:
        return int(float(str(value or 0).replace(",", "")))
    except ValueError:
        return 0


def fetch_taxinvoices(sdate: str, edate: str) -> list[Any]:
    """작성일자 기준 매출 세금계산서 — 발행완료(3xx)·발행취소(6xx), 정발행·수정."""
    settings = get_settings()
    svc = popbill_tax._service()
    items: list[Any] = []
    page = 1
    while True:
        result = svc.search(
            settings.popbill_corp_num, "SELL", "W", sdate, edate,
            ["3**", "6**"], ["N", "M"], ["T", "N", "Z"],
            LateOnly=None, TaxRegIDYN=None, TaxRegIDType=None, TaxRegID=None,
            Page=page, PerPage=1000, Order="D",
        )
        chunk = list(getattr(result, "list", None) or [])
        items.extend(chunk)
        if len(chunk) < 1000:
            return items
        page += 1


def fetch_cashbills(sdate: str, edate: str) -> list[Any]:
    """등록일 기준 현금영수증 — 승인거래·취소거래 모두.

    실측(2026-09-09): 상태는 "1**"~"4**" 와일드카드, 거래용도는 P(소득공제)·C(지출증빙)
    코드여야 결과가 온다("100"/"11" 같은 값은 조용히 0건). 취소는 상태가 아니라
    tradeType='취소거래' 인 별도 문서로, 고유 승인번호(confirmNum)를 갖는다.
    """
    settings = get_settings()
    svc = popbill_tax._cashbill_service()
    items: list[Any] = []
    page = 1
    while True:
        result = svc.search(
            settings.popbill_corp_num, "R", sdate, edate,
            ["1**", "2**", "3**", "4**"], ["N", "C"], ["P", "C"], ["T", "N"],
            page, 1000, "D",
        )
        chunk = list(getattr(result, "list", None) or [])
        items.extend(chunk)
        if len(chunk) < 1000:
            return items
        page += 1


def _ledger_rows(db: Session) -> list[IssuedTaxInvoice]:
    settings = get_settings()
    return list(db.scalars(
        select(IssuedTaxInvoice).where(IssuedTaxInvoice.is_test == settings.popbill_is_test)
    ).all())


def sync_popbill(
    db: Session, *, days: int = 14, today: date | None = None, dry_run: bool = False,
    tax_items: list[Any] | None = None, cash_items: list[Any] | None = None,
) -> dict[str, Any]:
    """팝빌 발행·취소분을 원장에 반영한다. tax_items/cash_items 를 주면 조회를 건너뛴다(테스트용)."""
    end = today or date.today()
    start = end - timedelta(days=days)
    sdate, edate = start.strftime("%Y%m%d"), end.strftime("%Y%m%d")
    if tax_items is None:
        tax_items = fetch_taxinvoices(sdate, edate)
    if cash_items is None:
        cash_items = fetch_cashbills(sdate, edate)

    rows = _ledger_rows(db)
    known_confirms = {str(r.nts_confirm).strip() for r in rows if r.nts_confirm}
    issued_by_confirm = {
        str(r.nts_confirm).strip(): r for r in rows
        if r.nts_confirm and r.doc_type in ("세금계산서", "현금영수증")
    }
    cancelled_keys = {r.mgt_key for r in rows if r.doc_type in ("세금취소", "현금취소")}

    report: dict[str, Any] = {
        "range": f"{sdate}~{edate}", "fetched_tax": len(tax_items), "fetched_cash": len(cash_items),
        "new_tax": 0, "new_cash": 0, "cancel_tax": 0, "cancel_cash": 0, "skipped": 0,
        "unmapped": [], "dry_run": dry_run,
    }

    def add(**kw: Any) -> None:
        if not dry_run:
            popbill_tax.save_issued(db, source=SOURCE, commit=False, **kw)

    for it in tax_items:
        confirm = str(_attr(it, "ntsconfirmNum") or "").strip()
        state = str(_attr(it, "stateCode") or "")
        mgt_key = str(_attr(it, "invoicerMgtKey") or "").strip()
        supply, tax = _int(_attr(it, "supplyCostTotal")), _int(_attr(it, "taxTotal"))
        info = {"nts_confirm": confirm, "issue_dt": _attr(it, "issueDT"), "write_date": _attr(it, "writeDate")}
        receiver = (str(_attr(it, "invoiceeCorpNum") or ""), str(_attr(it, "invoiceeCorpName") or ""))
        if not confirm:
            report["skipped"] += 1
            continue
        if state.startswith("3"):
            if confirm in known_confirms:
                report["skipped"] += 1
                continue
            doc_id = doc_id_from_mgt_key(mgt_key)
            # 수정세금계산서(음수)는 취소 행으로 — MOA 수정발급 저장 규칙과 같다
            doc_type = "세금취소" if supply < 0 else "세금계산서"
            add(doc_type=doc_type, doc_id=doc_id, mgt_key=mgt_key or confirm,
                receiver_corp_num=receiver[0], receiver_name=receiver[1],
                supply_cost=supply, tax=tax, info=info)
            known_confirms.add(confirm)
            report["new_tax"] += 1
            if not doc_id:
                report["unmapped"].append({"kind": "세금계산서", "mgt_key": mgt_key, "confirm": confirm,
                                           "receiver": receiver[1], "total": supply + tax})
        elif state.startswith("6"):
            origin = issued_by_confirm.get(confirm)
            if origin is None or (origin.mgt_key + CANCEL_SUFFIX) in cancelled_keys:
                report["skipped"] += 1
                continue
            add(doc_type="세금취소", doc_id=origin.doc_id, mgt_key=origin.mgt_key + CANCEL_SUFFIX,
                receiver_corp_num=origin.receiver_corp_num or "", receiver_name="발행취소(팝빌 사이트)",
                supply_cost=-_int(origin.supply_cost), tax=-_int(origin.tax),
                info={"nts_confirm": confirm, "issue_dt": _attr(it, "issueDT")})
            cancelled_keys.add(origin.mgt_key + CANCEL_SUFFIX)
            report["cancel_tax"] += 1
        else:
            report["skipped"] += 1

    for it in cash_items:
        confirm = str(_attr(it, "confirmNum") or "").strip()
        mgt_key = str(_attr(it, "mgtKey") or "").strip()
        cancel = "취소" in str(_attr(it, "tradeType") or "")   # '취소거래' — 별도 문서, 고유 승인번호
        supply, tax = _int(_attr(it, "supplyCost")), _int(_attr(it, "tax"))
        usage = str(_attr(it, "tradeUsage") or "")
        info = {"confirm_num": confirm, "trade_dt": _attr(it, "tradeDT")}
        if not confirm or confirm in known_confirms:
            report["skipped"] += 1
            continue
        doc_id = doc_id_from_mgt_key(mgt_key)   # 취소 키 '…-C'·'…-SC-…' 도 앞부분이 감정서번호
        if cancel:
            # MOA 취소 저장 규칙과 같다 — 현금취소 행에 양수 취소금액, 승인번호는 취소분 것
            add(doc_type="현금취소", doc_id=doc_id, mgt_key=mgt_key or confirm,
                receiver_corp_num="", receiver_name="거래취소(팝빌 사이트)",
                supply_cost=supply, tax=tax, info=info, trade_usage=usage)
            report["cancel_cash"] += 1
        else:
            add(doc_type="현금영수증", doc_id=doc_id, mgt_key=mgt_key or confirm,
                receiver_corp_num=str(_attr(it, "identityNum") or ""), receiver_name=str(_attr(it, "customerName") or ""),
                supply_cost=supply, tax=tax, info=info, trade_usage=usage)
            report["new_cash"] += 1
        known_confirms.add(confirm)
        if not doc_id:
            report["unmapped"].append({"kind": "현금취소" if cancel else "현금영수증", "mgt_key": mgt_key,
                                       "confirm": confirm, "receiver": str(_attr(it, "customerName") or ""),
                                       "total": supply + tax})

    if not dry_run:
        db.commit()
    return report
