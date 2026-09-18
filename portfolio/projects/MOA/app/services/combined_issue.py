"""합산 발행 (2026-09-10 사용자 확정) — 거래처가 같은 감정서 여러 건을 세금계산서 한 장으로.

여러 건 정산을 한 장으로 끊을 때 단건 팝업은 그 감정서 청구액을 넘는다고 막았다(초과 발행
안전장치). 그래서 감정서를 여러 건(팝빌 품목 줄 상한 99) 묶어 상한을 '각 건 남은 청구액의 합'으로 보고,
팝빌에는 한 장(품목 줄은 감정서마다), 발급 원장에는 감정서마다 한 줄(승인번호·관리번호는
같은 것)을 적는다 — 입금현황·감정서 LIST·전표 생성이 건별로 그대로 돈다.

거래처 같은 건만: 각 감정서 매출 전표(401 계열)의 거래처 사업자번호가 팝업의 공급받는자와
같아야 한다. 매출 전표가 없는 건은 발행 원장의 마지막 공급받는자로 대신 본다.
"""

from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services import popbill_tax

# 건수 제한은 풀었다(2026-09-10 사용자) — 팝빌 세금계산서 품목 줄 상한(99)만 남는다
MAX_DOCS = 99


class CombinedIssueError(ValueError):
    pass


def _digits(value: Any) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def normalize_doc_ids(primary: str, extras: "list[str]") -> "list[str]":
    """대표 감정서 + 추가 감정서 → 중복·공백 제거한 순서 있는 목록. 상한 검사."""
    result = [primary.strip()]
    for raw in extras:
        doc = str(raw or "").strip()
        if doc and doc not in result:
            result.append(doc)
    if len(result) < 2:
        raise CombinedIssueError("합산 발행은 감정서를 두 건 이상 묶어야 합니다.")
    if len(result) > MAX_DOCS:
        raise CombinedIssueError(f"합산 발행은 한 장에 {MAX_DOCS}건까지입니다.")
    return result


def allocate(total: int, remainings: "list[int]") -> "list[tuple[int, int]]":
    """요청 합계를 감정서 순서대로 남은 청구액만큼 채운다 → 건별 (공급가, 세액).

    세액은 건별 합계의 1/11 반올림, 마지막 건이 끝수를 흡수해 합이 요청과 같다.
    """
    cap = sum(max(0, r) for r in remainings)
    if total <= 0:
        raise CombinedIssueError("공급가액과 세액을 확인하세요.")
    if total > cap:
        raise CombinedIssueError(f"발행 합계({total:,}원)가 묶은 감정서의 남은 청구액 합({cap:,}원)을 초과합니다.")
    left = total
    totals = []
    for remaining in remainings:
        take = min(max(0, remaining), left)
        totals.append(take)
        left -= take
    result = []
    for amount in totals:
        supply = int(round(amount / 1.1))
        result.append((supply, amount - supply))
    return result


def _doc_corp_num(db: Session, doc_id: str) -> "tuple[str, str]":
    """감정서의 거래처 사업자번호(숫자만)와 상호 — 매출 전표 거래처 → 거래처 캐시, 없으면 발행 원장."""
    row = db.execute(
        text(
            "SELECT TOP 1 RTRIM(v.partner_code) AS tr_cd, v.partner_name, pc.reg_no "
            "FROM dbo.a10_voucher_cache v "
            "LEFT JOIN dbo.a10_partner_cache pc ON pc.partner_code = RTRIM(v.partner_code) "
            "WHERE (v.account_code LIKE '401%' OR v.account_code = '9090000') AND v.debit_credit = '4' "
            "  AND LTRIM(RTRIM(v.management_no)) = CAST(:doc AS varchar(100)) "
            "  AND v.partner_code IS NOT NULL AND RTRIM(v.partner_code) <> '' AND v.partner_code <> '0000028605' "
            "ORDER BY CASE WHEN v.account_code = '4010001' THEN 0 ELSE 1 END, v.voucher_date DESC"
        ),
        {"doc": doc_id},
    ).mappings().first()
    if row and _digits(row["reg_no"]):
        return _digits(row["reg_no"]), str(row["partner_name"] or "").strip()
    issued = db.execute(
        text(
            "SELECT TOP 1 receiver_corp_num, receiver_name FROM dbo.a10_issued_taxinvoice "
            "WHERE doc_id = CAST(:doc AS varchar(100)) AND is_test = 0 AND receiver_corp_num IS NOT NULL "
            "ORDER BY id DESC"
        ),
        {"doc": doc_id},
    ).mappings().first()
    if issued:
        return _digits(issued["receiver_corp_num"]), str(issued["receiver_name"] or "").strip()
    return "", str(row["partner_name"] or "").strip() if row else ""


def preview(db: Session, doc_ids: "list[str]", receiver_corp_num: str) -> "dict[str, Any]":
    """묶을 감정서마다 남은 청구액·거래처 일치 여부. 하나라도 어긋나면 ok=False 와 사유."""
    corp = _digits(receiver_corp_num)
    if len(corp) != 10:
        raise CombinedIssueError("공급받는자 사업자번호 10자리를 먼저 확인하세요.")
    docs = []
    for doc_id in doc_ids:
        totals = popbill_tax.evidence_issue_totals(db, doc_id)
        billed = int(totals["billed_total"] or 0)
        remaining = int(totals["remaining_total"] or 0)
        doc_corp, partner_name = _doc_corp_num(db, doc_id)
        problems = []
        if billed <= 0:
            problems.append("청구액 없음")
        elif remaining <= 0:
            problems.append("이미 전액 발행")
        if not doc_corp:
            problems.append("거래처를 알 수 없음(매출 전표 없음)")
        elif doc_corp != corp:
            problems.append(f"거래처 다름({partner_name or doc_corp})")
        docs.append({
            "doc_id": doc_id, "billed_total": billed, "issued_total": int(totals["combined"]["total"] or 0),
            "remaining_total": remaining, "partner_name": partner_name, "problems": problems,
        })
    ok = all(not d["problems"] for d in docs)
    return {"docs": docs, "ok": ok, "cap_total": sum(d["remaining_total"] for d in docs) if ok else 0}


def issue(
    db: Session, *, doc_ids: "list[str]", write_date: str, supply_cost: int, tax: int,
    receiver: "dict[str, Any]", email: str = "", purpose: str = "영수", item_remark: str = "",
    remark1: str = "", account_code: str = "",
) -> "dict[str, Any]":
    """검증 → 팝빌 한 장 발행 → 원장 감정서별 기록. 실패면 success=False 와 메시지."""
    check = preview(db, doc_ids, receiver.get("corp_num", ""))
    if not check["ok"]:
        bad = "; ".join(f"{d['doc_id']}: {', '.join(d['problems'])}" for d in check["docs"] if d["problems"])
        return {"success": False, "message": f"합산 발행 조건에 맞지 않습니다 — {bad}"}
    parts = allocate(int(supply_cost) + int(tax), [d["remaining_total"] for d in check["docs"]])
    # 마지막 건이 끝수를 흡수해 화면에서 확인한 공급가·세액과 합이 같게 한다
    supply_diff = int(supply_cost) - sum(p[0] for p in parts)
    if parts and supply_diff:
        last_supply, last_tax = parts[-1]
        parts[-1] = (last_supply + supply_diff, last_tax - supply_diff)

    supplier = popbill_tax.supplier_info(db)
    rcv = dict(receiver)
    if email:
        rcv["email"] = email
    items = [{
        "date": write_date, "name": f"감정평가수수료 {doc['doc_id']}"[:100], "spec": "",
        "qty": "1", "unit_cost": str(supply), "supply_cost": supply, "tax": vat, "remark": item_remark[:100],
    } for doc, (supply, vat) in zip(check["docs"], parts) if supply + vat > 0]
    inv = popbill_tax.build_taxinvoice(
        write_date=write_date, supplier=supplier, receiver=rcv, items=items, purpose=purpose, memo=remark1,
    )
    primary = doc_ids[0]
    mgt_key = popbill_tax.next_issue_mgt_key(db, primary)
    result = popbill_tax.register_issue(inv, mgt_key, memo=f"감정 {primary} 외 {len(doc_ids) - 1}건 합산")
    result["mgt_key"] = mgt_key
    if not result.get("success"):
        return result
    info = popbill_tax.get_info(mgt_key)
    result["info"] = info
    saved = []
    for doc, (supply, vat) in zip(check["docs"], parts):
        if supply + vat <= 0:
            continue
        popbill_tax.save_issued(
            db, doc_type="세금계산서", doc_id=doc["doc_id"], mgt_key=mgt_key,
            receiver_corp_num=receiver.get("corp_num", ""), receiver_name=receiver.get("corp_name", ""),
            supply_cost=supply, tax=vat, info=info, account_code=account_code, commit=False,
        )
        saved.append({"doc_id": doc["doc_id"], "supply_cost": supply, "tax": vat})
    db.commit()
    result["combined"] = saved
    return result


def sibling_doc_ids(db: Session, doc_id: str, mgt_key: str) -> "list[str]":
    """같은 관리번호(한 장)로 발행된 다른 감정서 — 취소할 때 원장 취소를 같이 적는다."""
    rows = db.execute(
        text(
            "SELECT DISTINCT doc_id FROM dbo.a10_issued_taxinvoice "
            "WHERE mgt_key = :key AND doc_type = N'세금계산서' AND doc_id <> CAST(:doc AS varchar(100))"
        ),
        {"key": mgt_key, "doc": doc_id},
    ).all()
    return [str(r[0]) for r in rows]


def combined_mgt_key(db: Session, doc_id: str) -> "str | None":
    """이 감정서의 현재 세금계산서가 합산 발행 한 장이면 그 관리번호, 아니면 None."""
    state = popbill_tax.latest_taxinvoice_row(db, doc_id)
    if not state or state[0] != "세금계산서":
        return None
    return state[1] if sibling_doc_ids(db, doc_id, state[1]) else None


def record_combined_cancel(db: Session, doc_id: str, mgt_key: str, before_id: int) -> "list[str]":
    """전액 취소 뒤 원장 정리 — 대표 감정서에 적힌 취소를 제 몫으로 줄이고 형제 감정서마다 취소 줄을 적는다.

    cancel_taxinvoice 는 팝빌 문서(한 장) 전체 금액을 대표 감정서 한 줄에 음수로 적는다.
    합산 발행이면 그 줄을 대표 몫만 남기고, 나머지 감정서에 같은 취소 관리번호로 각자 몫을 적는다.
    """
    from app.models import IssuedTaxInvoice

    rows = db.execute(
        text(
            "SELECT doc_id, supply_cost, tax FROM dbo.a10_issued_taxinvoice "
            "WHERE mgt_key = :key AND doc_type = N'세금계산서'"
        ),
        {"key": mgt_key},
    ).mappings().all()
    portions = {str(r["doc_id"]): (int(r["supply_cost"] or 0), int(r["tax"] or 0)) for r in rows}
    if doc_id not in portions or len(portions) < 2:
        return []
    cancel_rows = db.query(IssuedTaxInvoice).filter(
        IssuedTaxInvoice.id > before_id, IssuedTaxInvoice.doc_id == doc_id,
        IssuedTaxInvoice.doc_type.in_(("세금취소", "세금수정")),
    ).order_by(IssuedTaxInvoice.id).all()
    if not cancel_rows:
        return []
    template = cancel_rows[-1]
    own_supply, own_tax = portions[doc_id]
    template.supply_cost, template.tax, template.total = -own_supply, -own_tax, -(own_supply + own_tax)
    written = []
    for sibling, (supply, vat) in portions.items():
        if sibling == doc_id:
            continue
        db.add(IssuedTaxInvoice(
            doc_type=template.doc_type, doc_id=sibling, mgt_key=template.mgt_key,
            receiver_corp_num=template.receiver_corp_num, receiver_name=template.receiver_name,
            supply_cost=-supply, tax=-vat, total=-(supply + vat),
            nts_confirm=template.nts_confirm, issue_dt=template.issue_dt,
            is_test=template.is_test, source=template.source, write_date=template.write_date,
        ))
        written.append(sibling)
    db.commit()
    return written
