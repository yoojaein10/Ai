"""입금 적용용 계산서 (2026-09-10 재무팀 요청) — 대표 감정서번호로 한 장 크게 끊어 두고,
같은 거래처 감정서에 입금이 잡힐 때마다 그 계산서 금액을 감정서별로 떼어 붙인다.

원장 구조: 모계산서는 is_pool=1 인 세금계산서 행(대표 감정서번호, 전액) — 어느 감정서 발행금액에도
안 잡히고 잔액 계산에만 쓴다. 적용은 대상 감정서에 세금계산서 행을 하나 더 넣는 것(pool_id=모계산서
id, 관리번호·승인번호·출처는 모계산서 것, 금액은 떼어 붙인 몫). 원장 하나만 읽는 화면·전표 생성이
그대로 "발행"으로 본다. 읽는 쪽은 is_pool=0 조건 하나만 더한다.

규칙(사용자 확정 2026-09-10, 미확인 항목은 기본값):
  - 같은 거래처 = 매출 전표(401 계열) 거래처 코드가 모계산서 공급받는자 사업자번호에 매핑되는 것
  - 상한 = 그 거래처 감정서들의 미발행 청구액 합 (초과 발행 안전장치를 거래처 단위로 넓힘)
  - 적용 순서 = 입금일 순, 이미 입금된 미발행 건도 적용, 부분입금은 들어온 만큼만
  - 적용 금액 = min(남은 청구액, 입금액 − 기발행 증빙, 모계산서 잔액)
  - 모계산서는 전액 취소만, 취소하면 적용 행 전부에 취소를 같이 적는다
"""

from datetime import date, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services import popbill_tax

PARTNER_DOC_MONTHS = 18          # 거래처 감정서를 찾는 매출 전표 기간
_DOC_PATTERN = "[0-9][0-9]-[0-9][0-9][0-9][0-9]-%"


class InvoicePoolError(ValueError):
    pass


def _digits(value: Any) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def split_vat(total: int) -> "tuple[int, int]":
    supply = int(round(int(total) / 1.1))
    return supply, int(total) - supply


# ── 순수 규칙 ──────────────────────────────────────────────────────────────


def apply_amount(remaining: int, received: int, issued: int, balance: int) -> int:
    """한 감정서에 붙일 금액 — 남은 청구액, 입금액에서 기발행 증빙을 뺀 것, 모계산서 잔액 중 최소."""
    return max(0, min(int(remaining), int(received) - int(issued), int(balance)))


def plan_applications(balance: int, docs: "list[dict[str, Any]]") -> "list[dict[str, Any]]":
    """입금일 순으로 잔액을 나눠 붙일 계획. docs: doc_id·remaining_total·received·issued_total·last_received_date."""
    ordered = sorted(docs, key=lambda d: (str(d.get("last_received_date") or "9999"), str(d["doc_id"])))
    plan = []
    left = int(balance)
    for doc in ordered:
        if left <= 0:
            break
        amount = apply_amount(doc["remaining_total"], doc["received"], doc["issued_total"], left)
        if amount <= 0:
            continue
        supply, vat = split_vat(amount)
        plan.append({"doc_id": doc["doc_id"], "total": amount, "supply_cost": supply, "tax": vat})
        left -= amount
    return plan


# ── 거래처 감정서 ───────────────────────────────────────────────────────────


def partner_codes(db: Session, corp_num: str) -> "list[str]":
    """사업자번호 → 아마란스 거래처 코드들 (거래처 캐시, 같은 번호로 여러 코드가 있을 수 있다)."""
    corp = _digits(corp_num)
    if len(corp) != 10:
        return []
    rows = db.execute(
        text(
            "SELECT partner_code FROM dbo.a10_partner_cache "
            "WHERE REPLACE(REPLACE(ISNULL(reg_no, ''), '-', ''), ' ', '') = :corp"
        ),
        {"corp": corp},
    ).all()
    return sorted({str(r[0]).strip() for r in rows if r[0]})


def partner_docs(db: Session, codes: "list[str]", today: "date | None" = None) -> "list[dict[str, Any]]":
    """그 거래처 앞 매출 전표가 있는 감정서(최근 PARTNER_DOC_MONTHS 개월) + 요약 캐시의 청구·입금."""
    if not codes:
        return []
    since = (today or date.today()) - timedelta(days=PARTNER_DOC_MONTHS * 30)
    placeholders = ", ".join(f"CAST(:c{i} AS VARCHAR(20))" for i in range(len(codes)))
    params: "dict[str, Any]" = {f"c{i}": v for i, v in enumerate(codes)}
    params.update({"since": since, "pattern": _DOC_PATTERN})
    rows = db.execute(
        text(f"""
            SELECT v.management_no AS doc_id, MAX(v.voucher_date) AS last_sale_date,
                   MAX(ISNULL(b.received_amount, 0)) AS received, MAX(ISNULL(b.billed_amount, 0)) AS billed,
                   MAX(b.last_received_date) AS last_received_date
            FROM dbo.a10_voucher_cache v
            LEFT JOIN dbo.a10_receivable_summary b ON b.doc_id = v.management_no
            WHERE v.account_code LIKE '401%' AND v.debit_credit = '4'
              AND RTRIM(v.partner_code) IN ({placeholders}) AND v.voucher_date >= :since
              AND v.management_no LIKE :pattern
            GROUP BY v.management_no
        """),
        params,
    ).mappings().all()
    return [{
        "doc_id": str(r["doc_id"]).strip(), "received": int(float(r["received"] or 0)),
        "billed": int(float(r["billed"] or 0)),
        "last_received_date": r["last_received_date"].isoformat() if r["last_received_date"] else None,
    } for r in rows]


def doc_slots(db: Session, docs: "list[dict[str, Any]]") -> "list[dict[str, Any]]":
    """감정서마다 남은 청구액·기발행 증빙(원장, 모계산서 제외)을 붙인다."""
    result = []
    for doc in docs:
        totals = popbill_tax.evidence_issue_totals(db, doc["doc_id"])
        result.append({
            **doc,
            "billed_total": int(totals["billed_total"] or 0),
            "issued_total": int(totals["combined"]["total"] or 0),
            "remaining_total": int(totals["remaining_total"] or 0),
        })
    return result


def pool_cap(db: Session, corp_num: str, primary_doc_id: str = "") -> "dict[str, Any]":
    """발행 상한 — 그 거래처 감정서들의 미발행 청구액 합. 대표 감정서는 거래처 전표가 없어도 넣는다."""
    codes = partner_codes(db, corp_num)
    docs = partner_docs(db, codes)
    if primary_doc_id and all(d["doc_id"] != primary_doc_id for d in docs):
        docs.append({"doc_id": primary_doc_id, "received": 0, "billed": 0, "last_received_date": None})
    slots = [s for s in doc_slots(db, docs) if s["remaining_total"] > 0]
    return {
        "cap_total": sum(s["remaining_total"] for s in slots), "doc_count": len(slots),
        "partner_codes": codes,
        "docs": sorted(slots, key=lambda s: (str(s["last_received_date"] or "9999"), s["doc_id"])),
    }


# ── 모계산서 ────────────────────────────────────────────────────────────────


def _pool_row(db: Session, pool_id: int) -> "dict[str, Any] | None":
    row = db.execute(
        text(
            "SELECT id, doc_id, mgt_key, receiver_corp_num, receiver_name, total, nts_confirm, issue_dt, "
            "       write_date, source, account_code, is_test FROM dbo.a10_issued_taxinvoice "
            "WHERE id = :id AND is_pool = 1 AND doc_type = N'세금계산서'"
        ),
        {"id": pool_id},
    ).mappings().first()
    return dict(row) if row else None


def pool_balance(db: Session, pool_id: int) -> int:
    """모계산서 전액 − 적용 행 합(취소는 적용 행과 같은 pool_id 의 음수 행이라 함께 더해진다)."""
    row = db.execute(
        text(
            "SELECT (SELECT CAST(ISNULL(total, 0) AS float) FROM dbo.a10_issued_taxinvoice WHERE id = :id) "
            "     - ISNULL((SELECT SUM(CAST(ISNULL(total, 0) AS float)) FROM dbo.a10_issued_taxinvoice "
            "               WHERE pool_id = :id AND doc_type IN (N'세금계산서', N'세금취소')), 0)"
        ),
        {"id": pool_id},
    ).scalar()
    return int(round(float(row or 0)))


def _pool_cancelled(db: Session, pool: "dict[str, Any]") -> bool:
    return bool(db.execute(
        text(
            "SELECT 1 FROM dbo.a10_issued_taxinvoice WHERE mgt_key = :key AND is_pool = 1 "
            "AND doc_type = N'세금취소' AND id > :id"
        ),
        {"key": pool["mgt_key"], "id": pool["id"]},
    ).first())


def applications(db: Session, pool_id: int) -> "list[dict[str, Any]]":
    rows = db.execute(
        text(
            "SELECT id, doc_id, doc_type, supply_cost, tax, total, created_at FROM dbo.a10_issued_taxinvoice "
            "WHERE pool_id = :id ORDER BY id"
        ),
        {"id": pool_id},
    ).mappings().all()
    return [{
        "id": int(r["id"]), "doc_id": str(r["doc_id"]).strip(), "doc_type": str(r["doc_type"]),
        "supply_cost": int(float(r["supply_cost"] or 0)), "tax": int(float(r["tax"] or 0)),
        "total": int(float(r["total"] or 0)),
        "created_at": r["created_at"].isoformat(timespec="minutes") if r["created_at"] else None,
    } for r in rows]


def list_pools(db: Session, include_done: bool = False) -> "list[dict[str, Any]]":
    """모계산서 목록 — 취소된 것은 빼고, 잔액 0 은 include_done 일 때만."""
    rows = db.execute(
        text(
            "SELECT id, doc_id, mgt_key, receiver_corp_num, receiver_name, total, nts_confirm, write_date, created_at "
            "FROM dbo.a10_issued_taxinvoice WHERE is_pool = 1 AND doc_type = N'세금계산서' AND is_test = 0 ORDER BY id DESC"
        )
    ).mappings().all()
    result = []
    for r in rows:
        pool = dict(r)
        if _pool_cancelled(db, pool):
            continue
        balance = pool_balance(db, int(pool["id"]))
        if balance <= 0 and not include_done:
            continue
        result.append({
            "id": int(pool["id"]), "doc_id": str(pool["doc_id"]).strip(), "mgt_key": pool["mgt_key"],
            "receiver_corp_num": pool["receiver_corp_num"], "receiver_name": pool["receiver_name"],
            "total": int(float(pool["total"] or 0)), "nts_confirm": pool["nts_confirm"],
            "write_date": pool["write_date"].isoformat() if pool["write_date"] else None,
            "created_at": pool["created_at"].isoformat(timespec="minutes") if pool["created_at"] else None,
            "balance": balance,
            "applications": [a for a in applications(db, int(pool["id"]))],
        })
    return result


def _insert_application(db: Session, pool: "dict[str, Any]", doc_id: str, supply: int, vat: int, note: str = "") -> int:
    from app.models import IssuedTaxInvoice

    row = IssuedTaxInvoice(
        doc_type="세금계산서", doc_id=doc_id, mgt_key=pool["mgt_key"],
        receiver_corp_num=pool["receiver_corp_num"], receiver_name=pool["receiver_name"],
        supply_cost=supply, tax=vat, total=supply + vat,
        nts_confirm=pool["nts_confirm"], issue_dt=pool["issue_dt"], account_code=pool["account_code"],
        is_test=bool(pool["is_test"]), source=pool["source"], write_date=pool["write_date"],
        is_pool=False, pool_id=int(pool["id"]),
    )
    db.add(row)
    db.flush()
    return int(row.id)


def apply_pool(db: Session, pool_id: int, dry_run: bool = False) -> "dict[str, Any]":
    """모계산서 하나를 같은 거래처 입금 건에 나눠 붙인다. 잔액이 없으면 아무것도 안 한다."""
    pool = _pool_row(db, pool_id)
    if pool is None:
        raise InvoicePoolError("모계산서를 찾을 수 없습니다.")
    if _pool_cancelled(db, pool):
        return {"pool_id": pool_id, "balance": 0, "applied": [], "cancelled": True}
    balance = pool_balance(db, pool_id)
    if balance <= 0:
        return {"pool_id": pool_id, "balance": balance, "applied": []}
    codes = partner_codes(db, pool["receiver_corp_num"])
    docs = partner_docs(db, codes)
    if all(d["doc_id"] != str(pool["doc_id"]).strip() for d in docs):
        docs.append({"doc_id": str(pool["doc_id"]).strip(), "received": 0, "billed": 0, "last_received_date": None})
    slots = doc_slots(db, docs)
    plan = plan_applications(balance, slots)
    if not dry_run:
        for item in plan:
            item["row_id"] = _insert_application(db, pool, item["doc_id"], item["supply_cost"], item["tax"])
        db.commit()
    return {"pool_id": pool_id, "balance": balance - sum(p["total"] for p in plan), "applied": plan}


def apply_all(db: Session, dry_run: bool = False) -> "dict[str, Any]":
    """잔액이 남은 모계산서 전부 — 전표 캐시 동기화(10분) 끝에 돌린다."""
    pools = list_pools(db)
    results = [apply_pool(db, p["id"], dry_run=dry_run) for p in pools]
    applied = [a for r in results for a in r["applied"]]
    return {"pools": len(pools), "applied": len(applied), "amount": sum(a["total"] for a in applied), "details": results}


def apply_manual(db: Session, pool_id: int, doc_id: str, amount: int) -> "dict[str, Any]":
    """수동 적용 — 거래처가 같은지는 묻지 않는다(재무팀 판단), 잔액·남은 청구액만 지킨다."""
    pool = _pool_row(db, pool_id)
    if pool is None:
        raise InvoicePoolError("모계산서를 찾을 수 없습니다.")
    doc_id = doc_id.strip()
    amount = int(amount)
    if amount <= 0:
        raise InvoicePoolError("적용 금액은 0보다 커야 합니다.")
    balance = pool_balance(db, pool_id)
    if amount > balance:
        raise InvoicePoolError(f"모계산서 잔액({balance:,}원)을 초과합니다.")
    totals = popbill_tax.evidence_issue_totals(db, doc_id)
    remaining = int(totals["remaining_total"] or 0)
    if int(totals["billed_total"] or 0) <= 0:
        raise InvoicePoolError(f"{doc_id}: 청구액이 없습니다.")
    if amount > remaining:
        raise InvoicePoolError(f"{doc_id}: 남은 청구액({remaining:,}원)을 초과합니다.")
    supply, vat = split_vat(amount)
    row_id = _insert_application(db, pool, doc_id, supply, vat)
    db.commit()
    return {"row_id": row_id, "doc_id": doc_id, "total": amount, "balance": balance - amount}


def unapply(db: Session, row_id: int) -> "dict[str, Any]":
    """적용 해제 — 적용 행을 지운다(내부 배분 기록이라 국세청 문서와 무관)."""
    from app.models import IssuedTaxInvoice

    row = db.get(IssuedTaxInvoice, int(row_id))
    if row is None or not row.pool_id or row.doc_type != "세금계산서":
        raise InvoicePoolError("적용 행이 아닙니다.")
    pool_id, doc_id, total = int(row.pool_id), row.doc_id, int(float(row.total or 0))
    db.delete(row)
    db.commit()
    return {"pool_id": pool_id, "doc_id": doc_id, "total": total, "balance": pool_balance(db, pool_id)}


# ── 발행·취소 ───────────────────────────────────────────────────────────────


def issue_pool(
    db: Session, *, doc_id: str, write_date: str, supply_cost: int, tax: int, receiver: "dict[str, Any]",
    email: str = "", purpose: str = "영수", item_name: "str | None" = None, item_remark: str = "",
    remark1: str = "", account_code: str = "",
) -> "dict[str, Any]":
    """대표 감정서번호로 모계산서 한 장 발행 → 원장 is_pool=1 → 바로 한 번 적용."""
    total = int(supply_cost) + int(tax)
    cap = pool_cap(db, receiver.get("corp_num", ""), doc_id)
    if total <= 0:
        return {"success": False, "message": "공급가액과 세액을 확인하세요."}
    if total > cap["cap_total"]:
        return {"success": False, "message": (
            f"발행 합계({total:,}원)가 이 거래처 감정서 {cap['doc_count']}건의 미발행 청구액 합"
            f"({cap['cap_total']:,}원)을 초과합니다."
        )}
    result = popbill_tax.issue_for_appraisal(
        db, doc_id=doc_id, write_date=write_date, supply_cost=supply_cost, tax=tax, receiver=receiver,
        email=email, purpose=purpose,
        item_name=item_name if item_name is not None else f"감정평가수수료 {doc_id} 외",
        item_remark=item_remark, remark1=remark1,
    )
    if not result.get("success"):
        return result
    mgt_key = result.get("mgt_key") or doc_id
    info = popbill_tax.get_info(mgt_key)
    result["info"] = info
    popbill_tax.save_issued(
        db, doc_type="세금계산서", doc_id=doc_id, mgt_key=mgt_key,
        receiver_corp_num=receiver.get("corp_num", ""), receiver_name=receiver.get("corp_name", ""),
        supply_cost=supply_cost, tax=tax, info=info, account_code=account_code, is_pool=True,
    )
    pool_id = int(db.execute(
        text("SELECT MAX(id) FROM dbo.a10_issued_taxinvoice WHERE mgt_key = :key AND is_pool = 1"),
        {"key": mgt_key},
    ).scalar() or 0)
    result["pool_id"] = pool_id
    result["pool"] = apply_pool(db, pool_id)
    return result


def pool_state_of(db: Session, doc_id: str) -> "dict[str, Any]":
    """취소 라우터용 — 이 감정서의 최신 세금계산서가 모계산서인지, 적용 행(자식)인지."""
    row = db.execute(
        text(
            "SELECT TOP 1 id, is_pool, pool_id, mgt_key FROM dbo.a10_issued_taxinvoice "
            "WHERE doc_id = CAST(:doc AS varchar(100)) AND doc_type IN (N'세금계산서', N'세금취소') ORDER BY id DESC"
        ),
        {"doc": doc_id},
    ).mappings().first()
    if not row:
        return {"pool": False, "child": False}
    return {"pool": bool(row["is_pool"]), "child": bool(row["pool_id"]), "pool_id": row["pool_id"] or (row["id"] if row["is_pool"] else None), "mgt_key": row["mgt_key"]}


def record_pool_cancel(db: Session, doc_id: str, pool_id: int, before_id: int) -> "list[str]":
    """전액 취소 뒤 원장 정리 — 대표 감정서에 적힌 취소 줄은 모계산서 취소(is_pool=1)로 돌리고,
    적용 행마다 같은 취소 관리번호로 음수 줄을 적는다."""
    from app.models import IssuedTaxInvoice

    cancel_rows = db.query(IssuedTaxInvoice).filter(
        IssuedTaxInvoice.id > before_id, IssuedTaxInvoice.doc_id == doc_id,
        IssuedTaxInvoice.doc_type.in_(("세금취소", "세금수정")),
    ).order_by(IssuedTaxInvoice.id).all()
    if not cancel_rows:
        return []
    for row in cancel_rows:
        row.is_pool = True
    template = cancel_rows[-1]
    written = []
    for app_row in applications(db, pool_id):
        if app_row["doc_type"] != "세금계산서":
            continue
        db.add(IssuedTaxInvoice(
            doc_type="세금취소", doc_id=app_row["doc_id"], mgt_key=template.mgt_key,
            receiver_corp_num=template.receiver_corp_num, receiver_name=template.receiver_name,
            supply_cost=-app_row["supply_cost"], tax=-app_row["tax"], total=-app_row["total"],
            nts_confirm=template.nts_confirm, issue_dt=template.issue_dt, is_test=template.is_test,
            source=template.source, write_date=template.write_date, is_pool=False, pool_id=pool_id,
        ))
        written.append(app_row["doc_id"])
    db.commit()
    return written
