"""팝빌(링크허브) 전자세금계산서 발행 서비스 (얇은 래퍼).

TAMS 부가세.DB 조회 의존을 끊는 관문 — MOA에서 직접 세금계산서를 발행한다.
settings.popbill_is_test=True면 팝빌 테스트 서버로만 나가고 국세청·거래처엔 전송되지 않는다.

발행 데이터(공급받는자 사업자번호·상호·대표·주소·업태·종목)는 apw_masterex에 이미 있어
감정서번호로 채울 수 있다(build_invoice_from_appraisal는 후속 단계).
"""

from datetime import date
from typing import Any

from popbill import (
    Cashbill,
    CashbillService,
    PopbillException,
    Taxinvoice,
    TaxinvoiceDetail,
    TaxinvoiceService,
)
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import get_settings

# 과세형태: 정발행(공급자가 발행). 역발행/위수탁은 후속 단계에서 확장.
_ISSUE_TYPE = "정발행"
_TAX_TYPE = "과세"


def _service() -> TaxinvoiceService:
    settings = get_settings()
    if not settings.is_popbill_configured:
        raise RuntimeError(
            "팝빌 설정이 없습니다 (.env의 POPBILL_LINK_ID·POPBILL_SECRET_KEY·POPBILL_CORP_NUM)."
        )
    svc = TaxinvoiceService(
        settings.popbill_link_id,
        settings.popbill_secret_key.get_secret_value(),
    )
    svc.IsTest = settings.popbill_is_test
    # 팝빌 SDK 기본 통신 옵션 (SDK 권장값)
    svc.IPRestrictOnOff = True
    svc.UseStaticIP = False
    svc.UseLocalTimeYN = True
    return svc


def check_balance() -> "dict[str, Any]":
    """연동 확인용 — 팝빌 잔액/포인트 조회. 발행 없이 인증·설정 검증에 쓴다."""
    settings = get_settings()
    svc = _service()
    corp = settings.popbill_corp_num
    return {
        "is_test": settings.popbill_is_test,
        "corp_num": corp,
        "balance": svc.getBalance(corp),          # 파트너 잔액
        "unit_cost": svc.getUnitCost(corp),       # 세금계산서 발행 단가
        "issued_this_month": None,
    }


def build_taxinvoice(
    *,
    write_date: str,
    supplier: "dict[str, Any]",
    receiver: "dict[str, Any]",
    items: "list[dict[str, Any]]",
    purpose: str = "영수",
    memo: str = "",
) -> Taxinvoice:
    """세금계산서 객체 생성. write_date는 'YYYYMMDD'.

    supplier/receiver: corp_num, corp_name, ceo_name, addr, biz_type, biz_class, mgt(담당) 등.
    items: [{date, name, spec, qty, unit_cost, supply_cost, tax}] — 공급가/세액.
    """
    supply_total = sum(int(it.get("supply_cost") or 0) for it in items)
    tax_total = sum(int(it.get("tax") or 0) for it in items)

    inv = Taxinvoice(
        writeDate=write_date,
        chargeDirection="정과금",        # 발행 수수료를 공급자가 부담
        issueType=_ISSUE_TYPE,
        purposeType=purpose,             # 영수 / 청구
        taxType=_TAX_TYPE,
        # 공급자
        invoicerCorpNum=supplier["corp_num"],
        invoicerCorpName=supplier["corp_name"],
        invoicerCEOName=supplier.get("ceo_name", ""),
        invoicerAddr=supplier.get("addr", ""),
        invoicerBizType=supplier.get("biz_type", ""),
        invoicerBizClass=supplier.get("biz_class", ""),
        invoicerContactName=supplier.get("contact_name", ""),
        invoicerTEL=supplier.get("tel", ""),
        invoicerEmail=supplier.get("email", ""),
        # 공급받는자
        invoiceeType="사업자",
        invoiceeCorpNum=receiver["corp_num"],
        invoiceeCorpName=receiver["corp_name"],
        invoiceeCEOName=receiver.get("ceo_name", ""),
        invoiceeAddr=receiver.get("addr", ""),
        invoiceeBizType=receiver.get("biz_type", ""),
        invoiceeBizClass=receiver.get("biz_class", ""),
        invoiceeContactName1=receiver.get("contact_name", ""),
        invoiceeEmail1=receiver.get("email", ""),
        # 합계
        supplyCostTotal=str(supply_total),
        taxTotal=str(tax_total),
        totalAmount=str(supply_total + tax_total),
        remark1=memo[:120] if memo else "",
        detailList=[
            TaxinvoiceDetail(
                serialNum=i + 1,
                purchaseDT=it.get("date", write_date),
                itemName=it.get("name", ""),
                spec=it.get("spec", ""),
                qty=str(it.get("qty", "")),
                unitCost=str(it.get("unit_cost", "")),
                supplyCost=str(int(it.get("supply_cost") or 0)),
                tax=str(int(it.get("tax") or 0)),
                remark=it.get("remark", ""),
            )
            for i, it in enumerate(items)
        ],
    )
    return inv


def register_issue(inv: Taxinvoice, mgt_key: str, memo: str = "") -> "dict[str, Any]":
    """즉시발행(registIssue). mgt_key는 우리 문서관리번호(감정서번호 등, 회사 내 유일).

    관리번호는 세금계산서 객체의 invoicerMgtKey에 실린다. 테스트 모드면 팝빌 테스트
    서버로만 발행된다(국세청·거래처 미전송). 반환에 발행 결과 코드·메시지 포함.
    """
    settings = get_settings()
    svc = _service()
    inv.invoicerMgtKey = mgt_key
    try:
        result = svc.registIssue(
            settings.popbill_corp_num, inv, memo=memo or None,
            UserID=settings.popbill_user_id or None,
        )
        return {"success": result.code == 1, "code": result.code, "message": result.message}
    except PopbillException as exc:
        return {"success": False, "code": exc.code, "message": exc.message}


def latest_taxinvoice_row(db: Session, doc_id: str) -> "tuple[str, str] | None":
    """이 감정서의 최신 세금계산서 상태 행 (doc_type, mgt_key).

    취소('세금취소') 행도 포함해 최신 1행을 본다 — 취소 후 재발행하면
    새 세금계산서 행이 더 늦게 쌓이므로 최신 행의 유형이 곧 현재 상태다.
    현재 모드(운영/테스트)의 발행분만 본다.
    """
    from sqlalchemy import text as _text

    settings = get_settings()
    row = db.execute(
        _text(
            "SELECT TOP 1 doc_type, mgt_key FROM dbo.a10_issued_taxinvoice "
            "WHERE doc_id = :doc AND doc_type IN (N'세금계산서', N'세금취소') "
            "  AND is_test = :t ORDER BY id DESC"
        ),
        {"doc": doc_id, "t": 1 if settings.popbill_is_test else 0},
    ).first()
    return (str(row[0]), str(row[1])) if row else None


def next_issue_mgt_key(db: Session, doc_id: str) -> str:
    """세금계산서 발행에 쓸 문서관리번호. 팝빌 mgtKey는 재사용이 안 되므로
    같은 감정서를 취소 후 재발행할 때는 '-R{차수}'를 붙인다."""
    from sqlalchemy import text as _text

    settings = get_settings()
    issued = db.execute(
        _text(
            "SELECT COUNT(*) FROM dbo.a10_issued_taxinvoice "
            "WHERE doc_id = :doc AND doc_type = N'세금계산서' AND is_test = :t"
        ),
        {"doc": doc_id, "t": 1 if settings.popbill_is_test else 0},
    ).scalar() or 0
    return doc_id if int(issued) == 0 else f"{doc_id}-R{int(issued) + 1}"


def latest_cashbill_row(db: Session, doc_id: str) -> "tuple[str, str] | None":
    """이 감정서의 최신 현금영수증 상태 행 (doc_type, mgt_key).

    세금계산서와 같은 규칙 — 취소('현금취소') 행도 포함해 최신 1행을 보면
    그 유형이 곧 현재 상태다. 현재 모드(운영/테스트)의 발행분만 본다.
    """
    from sqlalchemy import text as _text

    settings = get_settings()
    row = db.execute(
        _text(
            "SELECT TOP 1 doc_type, mgt_key FROM dbo.a10_issued_taxinvoice "
            "WHERE doc_id = :doc AND doc_type IN (N'현금영수증', N'현금취소') "
            "  AND is_test = :t ORDER BY id DESC"
        ),
        {"doc": doc_id, "t": 1 if settings.popbill_is_test else 0},
    ).first()
    return (str(row[0]), str(row[1])) if row else None


def _cashbill_doc_count(db: Session, doc_id: str, doc_type: str) -> int:
    from sqlalchemy import text as _text

    settings = get_settings()
    return int(db.execute(
        _text(
            "SELECT COUNT(*) FROM dbo.a10_issued_taxinvoice "
            "WHERE doc_id = :doc AND doc_type = :ty AND is_test = :t"
        ),
        {"doc": doc_id, "ty": doc_type,
         "t": 1 if settings.popbill_is_test else 0},
    ).scalar() or 0)


def next_cashbill_mgt_key(db: Session, doc_id: str) -> str:
    """현금영수증 발행 문서관리번호 — 취소 후 재발급은 '-R{차수}'로 새 키를 딴다
    (팝빌 mgtKey 재사용 불가, 2026-08-13 01-2601-2-0001 재발급 실패 실증)."""
    issued = _cashbill_doc_count(db, doc_id, "현금영수증")
    return doc_id if issued == 0 else f"{doc_id}-R{issued + 1}"


def next_cashbill_cancel_key(db: Session, doc_id: str) -> str:
    """취소 현금영수증 문서관리번호 — 두 번째 취소부터 '-C{차수}'."""
    cancelled = _cashbill_doc_count(db, doc_id, "현금취소")
    return f"{doc_id}-C" if cancelled == 0 else f"{doc_id}-C{cancelled + 1}"


def evidence_issue_totals(db: Session, doc_id: str) -> "dict[str, Any]":
    """감정서의 현재 유효 증빙 금액을 유형별로 계산한다.

    현금영수증 취소 원장은 과거부터 금액을 0으로 저장했으므로 단순 SUM으로는
    취소가 빠지지 않는다. 발행 순서대로 쌓아 두고 취소가 나오면 최신 발행분을
    하나 제거해 현재 살아 있는 현금영수증만 합산한다.
    """
    settings = get_settings()
    rows = db.execute(
        text(
            "SELECT doc_type, supply_cost, tax FROM dbo.a10_issued_taxinvoice "
            "WHERE doc_id = :doc AND is_test = :t AND is_pool = 0 "
            "  AND doc_type IN (N'현금영수증', N'현금취소', "
            "                   N'세금계산서', N'세금취소', N'세금수정') "
            "ORDER BY id"
        ),
        {"doc": doc_id, "t": 1 if settings.popbill_is_test else 0},
    ).mappings().all()
    cash_active: "list[tuple[int, int]]" = []
    tax_supply = tax_vat = 0
    for row in rows:
        kind = str(row["doc_type"])
        supply = int(row["supply_cost"] or 0)
        vat = int(row["tax"] or 0)
        if kind == "현금영수증":
            cash_active.append((supply, vat))
        elif kind == "현금취소":
            if cash_active:
                # 구형 MOA 자동 전액취소 행은 금액이 0으로 저장되어 전체 제거한다.
                # 팝빌 사이트 부분취소를 동기화한 행은 취소금액만 최신 발행분에서 뺀다.
                if supply or vat:
                    old_supply, old_vat = cash_active[-1]
                    new_supply, new_vat = old_supply - supply, old_vat - vat
                    if new_supply > 0 or new_vat > 0:
                        cash_active[-1] = (max(0, new_supply), max(0, new_vat))
                    else:
                        cash_active.pop()
                else:
                    cash_active.pop()
        else:
            tax_supply += supply
            tax_vat += vat

    cash_supply = sum(item[0] for item in cash_active)
    cash_vat = sum(item[1] for item in cash_active)
    billed = int(db.execute(
        text(
            "SELECT ISNULL(billed_amount, 0) FROM dbo.a10_receivable_summary "
            "WHERE LTRIM(RTRIM(doc_id)) = CAST(:doc AS varchar(100))"
        ),
        {"doc": doc_id},
    ).scalar() or 0)
    if not billed:
        # 요약 캐시에 없는 건(약식 -6- 등)은 청구액을 0 으로 봐서 초과 발행 검사가
        # 통째로 꺼졌다 — 잘못 발행한 뒤 취소 없이 다시 발행해도 안 막혔다
        # (2026-09-07 01-2609-6-0487). 원장 청구액으로 대신 본다.
        billed = int(db.execute(
            text(
                f"SELECT TOP 1 ISNULL([수수료합계], 0) + ISNULL([부가가치세], 0) "
                f"FROM [{get_settings().mssql_source_db}].dbo.apw_masterex "
                f"WHERE DocID = :doc"
            ),
            {"doc": doc_id},
        ).scalar() or 0)
    combined_supply = cash_supply + tax_supply
    combined_vat = cash_vat + tax_vat
    return {
        "cash": {"supply": cash_supply, "tax": cash_vat,
                 "total": cash_supply + cash_vat},
        "tax": {"supply": tax_supply, "tax": tax_vat,
                "total": tax_supply + tax_vat},
        "combined": {"supply": combined_supply, "tax": combined_vat,
                     "total": combined_supply + combined_vat},
        "billed_total": billed,
        "remaining_total": max(0, billed - combined_supply - combined_vat),
    }


def evidence_issue_error(
    db: Session, doc_id: str, supply_cost: int, tax: int
) -> "str | None":
    """부분발행 요청이 청구액을 넘는지 발행 직전에 검증한다."""
    if supply_cost <= 0 or tax < 0:
        return "공급가액과 세액을 확인하세요."
    totals = evidence_issue_totals(db, doc_id)
    billed = int(totals["billed_total"] or 0)
    after = int(totals["combined"]["total"]) + int(supply_cost) + int(tax)
    if billed > 0 and after > billed:
        return (
            f"발행 후 증빙 합계({after:,}원)가 청구액({billed:,}원)을 초과합니다. "
            f"현재 남은 금액은 {totals['remaining_total']:,}원입니다."
        )
    return None


TAXINVOICE_CANCEL_TYPES = {
    1: "기재사항 착오정정",
    2: "공급가액 변동",
    3: "환입",
    4: "계약의 해제",
    5: "내국신용장 사후개설",
    6: "착오에 의한 이중발급",
}


def taxinvoice_adjustment_totals(
    db: Session, doc_id: str, base_mgt_key: str
) -> "tuple[int, int]":
    """최신 정상 발행분 이후 공급가액 변동·환입 누계 (공급가액, 세액)."""
    settings = get_settings()
    row = db.execute(
        text(
            "SELECT ISNULL(SUM(supply_cost), 0), ISNULL(SUM(tax), 0) "
            "FROM dbo.a10_issued_taxinvoice "
            "WHERE doc_id = :doc AND doc_type = N'세금수정' AND is_test = :t "
            "  AND id > ISNULL((SELECT MAX(id) FROM dbo.a10_issued_taxinvoice "
            "                   WHERE doc_id = :doc AND mgt_key = :base AND is_test = :t), 0)"
        ),
        {"doc": doc_id, "base": base_mgt_key,
         "t": 1 if settings.popbill_is_test else 0},
    ).first()
    return (int(row[0] or 0), int(row[1] or 0)) if row else (0, 0)


def cancel_taxinvoice(
    db: Session,
    *,
    doc_id: str,
    reason_code: int = 6,
    reason_date: "date | None" = None,
    adjust_supply: "int | None" = None,
    adjust_tax: "int | None" = None,
    replacement: "dict[str, Any] | None" = None,
    memo: str = "",
) -> "dict[str, Any]":
    """세금계산서 전액 취소 — 원본의 국세청 전송 여부에 따라 경로가 갈린다.

    전송 전: 수정세금계산서가 불가하므로 발행취소(cancelIssue) 후 문서 삭제.
    전송 후: 국세청 수정사유 1~6의 작성 규칙에 맞춰 수정세금계산서를 발행한다.
    1·5는 음수/양수 2장, 2·3은 증감분 1장, 4·6은 전액 음수 1장이다.
    팝빌 화면에서 이미 발행취소(상태 600)한 건은 원장에만 취소를 반영한다.
    어느 경로든 취소 후에는 발급 팝업 잠금이 풀려 재발행할 수 있다.
    """
    from sqlalchemy import text as _text

    if reason_code not in TAXINVOICE_CANCEL_TYPES:
        return {
            "success": False,
            "message": "수정 사유는 1~6 중에서 선택하세요.",
        }

    state = latest_taxinvoice_row(db, doc_id)
    if state and state[0] == "세금취소":
        return {"success": False, "message": "이미 취소된 세금계산서입니다."}
    mgt_key = state[1] if state else doc_id
    info = get_info(mgt_key)
    if info.get("error"):
        return {"success": False,
                "message": f"팝빌에서 원본 세금계산서를 찾지 못했습니다({info['error']})."}

    settings = get_settings()
    svc = _service()

    # 팝빌 화면에서 이미 발행취소한 건 — 원장에 취소를 기록해 재발급 잠금만 푼다.
    if int(info.get("state_code") or 0) == 600:
        save_issued(
            db, doc_type="세금취소", doc_id=doc_id, mgt_key=mgt_key,
            receiver_corp_num="", receiver_name="발행취소(팝빌)",
            supply_cost=-int(info.get("supply_cost") or 0),
            tax=-int(info.get("tax") or 0), info=info,
        )
        return {"success": True, "synced": True}

    # 국세청 전송 전 — 승인번호는 발행 즉시 부여되지만 전송 전엔 수정세금계산서를
    # 못 만든다. 발행취소 후 문서 삭제(관리번호 정리)로 처리한다.
    #
    # 전송 여부는 상태코드로 본다 — 이 팝빌 계정은 getInfo의 ntsSendDT가 전송
    # 후에도 늘 비어 있어(실측 2026-09-04, 전송완료건도 None) 그걸로는 못 가린다.
    # 발행취소(cancelIssue)가 되는 건 발행완료(300, 국세청 전송 전)뿐이고,
    # 전송완료(304)에 cancelIssue를 부르면 -11002030으로 거부돼 수정발급이 실패했다.
    # 그래서 300만 전송 전으로 보고, 그 외(304 등)는 수정세금계산서 경로로 보낸다.
    state_code = int(info.get("state_code") or 0)
    before_nts = state_code == 300 and not str(info.get("nts_send_dt") or "").strip()
    if before_nts:
        try:
            svc.cancelIssue(settings.popbill_corp_num, "SELL", mgt_key,
                            memo or f"감정 {doc_id} 세금계산서 취소",
                            settings.popbill_user_id or None)
        except PopbillException as exc:
            return {"success": False, "message": f"{exc.code}: {exc.message}"}
        try:
            svc.delete(settings.popbill_corp_num, "SELL", mgt_key,
                       settings.popbill_user_id or None)
        except PopbillException:
            pass  # 삭제 실패해도 발행취소는 끝난 상태 — 원장 기록으로 잠금은 풀린다
        save_issued(
            db, doc_type="세금취소", doc_id=doc_id, mgt_key=mgt_key,
            receiver_corp_num="", receiver_name="발행취소(전송 전)",
            supply_cost=-int(info.get("supply_cost") or 0),
            tax=-int(info.get("tax") or 0), info=info,
        )
        return {"success": True, "cancelled_before_nts": True}

    nts = str(info.get("nts_confirm") or "").strip()
    if not nts:
        return {"success": False,
                "message": "국세청 승인번호가 아직 확정되지 않았습니다. 몇 분 뒤 다시 시도하세요."}

    try:
        org = svc.getDetailInfo(settings.popbill_corp_num, "SELL", mgt_key)
    except PopbillException as exc:
        return {"success": False, "message": f"{exc.code}: {exc.message}"}

    def _txt(name: str, default: str = "") -> str:
        return str(getattr(org, name, default) or default)

    def _neg(value: Any) -> str:
        try:
            return str(-int(float(value or 0)))
        except (TypeError, ValueError):
            return "0"

    original_write_date = _txt("writeDate")
    if reason_code in (2, 3, 4, 5):
        if reason_date is None:
            date_names = {2: "변동일", 3: "환입일", 4: "계약의 해제일", 5: "내국신용장 개설일"}
            return {"success": False, "message": f"{date_names[reason_code]}을 입력하세요."}
        if reason_date > date.today():
            return {"success": False, "message": "수정사유 발생일은 미래일 수 없습니다."}
        if len(original_write_date) == 8 and original_write_date.isdigit():
            try:
                original_date = date(
                    int(original_write_date[:4]),
                    int(original_write_date[4:6]),
                    int(original_write_date[6:8]),
                )
            except ValueError:
                original_date = None
            if original_date is not None and reason_date < original_date:
                return {
                    "success": False,
                    "message": "수정사유 발생일은 원 세금계산서 작성일자보다 빠를 수 없습니다.",
                }
    reason_date_text = reason_date.strftime("%Y%m%d") if reason_date else ""

    reason_name = TAXINVOICE_CANCEL_TYPES[reason_code]
    original_supply = int(info.get("supply_cost") or 0)
    original_tax = int(info.get("tax") or 0)
    prior_supply_adjustment, prior_tax_adjustment = taxinvoice_adjustment_totals(
        db, doc_id, mgt_key
    )
    current_supply = original_supply + prior_supply_adjustment
    current_tax = original_tax + prior_tax_adjustment

    if reason_code == 1:
        replacement = replacement or {}
        receiver = replacement.get("receiver") or {}
        required = (
            replacement.get("write_date"), receiver.get("corp_num"),
            receiver.get("corp_name"), replacement.get("supply_cost") is not None,
            replacement.get("tax") is not None,
        )
        if not all(required):
            return {"success": False, "message": "착오정정 후 새로 발행할 거래처·작성일자·금액을 입력하세요."}
    if reason_code == 2:
        adjust_supply = int(adjust_supply or 0)
        adjust_tax = int(adjust_tax or 0)
        if adjust_supply == 0:
            return {"success": False, "message": "공급가액 증감액을 입력하세요."}
        if (adjust_supply > 0 > adjust_tax) or (adjust_supply < 0 < adjust_tax):
            return {"success": False, "message": "공급가액과 세액의 증감 방향이 서로 다릅니다."}
    if reason_code == 3:
        adjust_supply = int(adjust_supply or 0)
        adjust_tax = int(adjust_tax or 0)
        if adjust_supply < 0 or adjust_tax < 0 or (adjust_supply == 0 and adjust_tax == 0):
            return {"success": False, "message": "환입할 공급가액·세액은 0 이상의 금액으로 입력하세요."}
        if adjust_supply > current_supply or adjust_tax > current_tax:
            return {"success": False, "message": "환입 금액은 현재 남은 세금계산서 금액을 초과할 수 없습니다."}

    def _detail(
        *, write_date: str, supply: int, tax: int, name: str,
        remark: str = "",
    ) -> TaxinvoiceDetail:
        return TaxinvoiceDetail(
            serialNum=1, purchaseDT=write_date, itemName=name[:100], spec="", qty="1",
            unitCost=str(supply), supplyCost=str(supply), tax=str(tax), remark=remark[:100],
        )

    def _modified_invoice(
        *, write_date: str, supply: int, tax: int, tax_type: str = _TAX_TYPE,
        receiver: "dict[str, Any] | None" = None,
        purpose: "str | None" = None,
        remark: str = "",
        details: "list[TaxinvoiceDetail] | None" = None,
    ) -> Taxinvoice:
        rcv = receiver or {}
        return Taxinvoice(
            writeDate=write_date, chargeDirection="정과금", issueType=_ISSUE_TYPE,
            purposeType=purpose or _txt("purposeType", "영수"), taxType=tax_type,
            modifyCode=reason_code, orgNTSConfirmNum=nts,
            invoicerCorpNum=_txt("invoicerCorpNum"), invoicerCorpName=_txt("invoicerCorpName"),
            invoicerCEOName=_txt("invoicerCEOName"), invoicerAddr=_txt("invoicerAddr"),
            invoicerBizType=_txt("invoicerBizType"), invoicerBizClass=_txt("invoicerBizClass"),
            invoicerContactName=_txt("invoicerContactName"), invoicerTEL=_txt("invoicerTEL"),
            invoicerEmail=_txt("invoicerEmail"), invoiceeType=_txt("invoiceeType", "사업자"),
            invoiceeCorpNum=str(rcv.get("corp_num") or _txt("invoiceeCorpNum")),
            invoiceeCorpName=str(rcv.get("corp_name") or _txt("invoiceeCorpName")),
            invoiceeCEOName=str(rcv.get("ceo_name") or _txt("invoiceeCEOName")),
            invoiceeAddr=str(rcv.get("addr") or _txt("invoiceeAddr")),
            invoiceeBizType=str(rcv.get("biz_type") or _txt("invoiceeBizType")),
            invoiceeBizClass=str(rcv.get("biz_class") or _txt("invoiceeBizClass")),
            invoiceeContactName1=str(rcv.get("contact_name") or _txt("invoiceeContactName1")),
            invoiceeEmail1=str(rcv.get("email") or _txt("invoiceeEmail1")),
            supplyCostTotal=str(supply), taxTotal=str(tax), totalAmount=str(supply + tax),
            remark1=(remark or memo or reason_name)[:120], detailList=details or [],
        )

    negative_detail_date = reason_date_text if reason_code == 4 else original_write_date
    if prior_supply_adjustment or prior_tax_adjustment:
        original_negative_details = [_detail(
            write_date=negative_detail_date, supply=-current_supply, tax=-current_tax,
            name=f"감정평가수수료 {doc_id}", remark=f"당초 작성일자 {original_write_date}",
        )]
    else:
        original_negative_details = [
            TaxinvoiceDetail(
                serialNum=i + 1, purchaseDT=negative_detail_date,
                itemName=str(getattr(d, "itemName", "") or ""),
                spec=str(getattr(d, "spec", "") or ""), qty=str(getattr(d, "qty", "") or ""),
                unitCost=str(getattr(d, "unitCost", "") or ""),
                supplyCost=_neg(getattr(d, "supplyCost", 0)), tax=_neg(getattr(d, "tax", 0)),
                remark=str(getattr(d, "remark", "") or ""),
            )
            for i, d in enumerate(getattr(org, "detailList", None) or [])
        ]

    documents: "list[tuple[str, Taxinvoice, str]]" = []
    if reason_code in (1, 4, 5, 6):
        negative_date = reason_date_text if reason_code == 4 else original_write_date
        negative_remark = memo or (
            reason_name if reason_code in (1, 6)
            else f"{reason_name} (당초 작성일자 {original_write_date})"
        )
        documents.append((
            "negative",
            _modified_invoice(
                write_date=negative_date, supply=-current_supply, tax=-current_tax,
                remark=negative_remark, details=original_negative_details,
            ),
            "세금취소",
        ))
    elif reason_code == 2:
        documents.append((
            "adjustment",
            _modified_invoice(
                write_date=reason_date_text, supply=int(adjust_supply), tax=int(adjust_tax),
                remark=memo or f"공급가액 변동 (당초 작성일자 {original_write_date})",
                details=[_detail(
                    write_date=reason_date_text, supply=int(adjust_supply), tax=int(adjust_tax),
                    name="공급가액 변동", remark=f"당초 작성일자 {original_write_date}",
                )],
            ),
            "세금수정",
        ))
    else:  # 3. 환입
        documents.append((
            "adjustment",
            _modified_invoice(
                write_date=reason_date_text, supply=-int(adjust_supply), tax=-int(adjust_tax),
                remark=memo or f"환입 (당초 작성일자 {original_write_date})",
                details=[_detail(
                    write_date=reason_date_text, supply=-int(adjust_supply), tax=-int(adjust_tax),
                    name="환입", remark=f"당초 작성일자 {original_write_date}",
                )],
            ),
            "세금수정",
        ))

    if reason_code == 1:
        replacement = replacement or {}
        rcv = replacement["receiver"]
        new_date = str(replacement["write_date"])
        new_supply = int(replacement["supply_cost"])
        new_tax = int(replacement["tax"])
        documents.append((
            "positive",
            _modified_invoice(
                write_date=new_date, supply=new_supply, tax=new_tax, receiver=rcv,
                purpose=str(replacement.get("purpose") or _txt("purposeType", "영수")),
                remark=str(replacement.get("remark1") or memo or reason_name),
                details=[_detail(
                    write_date=new_date, supply=new_supply, tax=new_tax,
                    name=str(replacement.get("item_name") or f"감정평가수수료 {doc_id}"),
                    remark=str(replacement.get("item_remark") or ""),
                )],
            ),
            "세금계산서",
        ))
    elif reason_code == 5:
        if prior_supply_adjustment or prior_tax_adjustment:
            positive_details = [_detail(
                write_date=original_write_date, supply=current_supply, tax=0,
                name=f"감정평가수수료 {doc_id}", remark=f"내국신용장 개설일 {reason_date_text}",
            )]
        else:
            positive_details = [
                TaxinvoiceDetail(
                    serialNum=i + 1, purchaseDT=original_write_date,
                    itemName=str(getattr(d, "itemName", "") or ""),
                    spec=str(getattr(d, "spec", "") or ""), qty=str(getattr(d, "qty", "") or ""),
                    unitCost=str(getattr(d, "unitCost", "") or ""),
                    supplyCost=str(abs(int(float(getattr(d, "supplyCost", 0) or 0)))), tax="0",
                    remark=str(getattr(d, "remark", "") or ""),
                )
                for i, d in enumerate(getattr(org, "detailList", None) or [])
            ]
        documents.append((
            "positive",
            _modified_invoice(
                write_date=original_write_date, supply=current_supply, tax=0, tax_type="영세",
                remark=memo or f"내국신용장 개설일 {reason_date_text}", details=positive_details,
            ),
            "세금계산서",
        ))

    modified_count = db.execute(
        _text(
            "SELECT COUNT(*) FROM dbo.a10_issued_taxinvoice "
            "WHERE doc_id = :doc AND doc_type IN (N'세금취소', N'세금수정') "
            "  AND is_test = :t"
        ),
        {"doc": doc_id, "t": 1 if get_settings().popbill_is_test else 0},
    ).scalar() or 0
    key_base = f"{doc_id}-M{int(modified_count) + 1}"
    issued_results = []
    for role, invoice, doc_type in documents:
        key = key_base if len(documents) == 1 else f"{key_base}-{'N' if role == 'negative' else 'P'}"
        result = register_issue(invoice, key, memo=f"감정 {doc_id} 수정세금계산서 {reason_name}")
        if not result.get("success"):
            prefix = "일부 발행 후 " if issued_results else ""
            return {
                "success": False,
                "partial": bool(issued_results),
                "issued": issued_results,
                "message": f"{prefix}{reason_name} 수정발행 실패: {result.get('message', '발행 실패')}",
            }
        issued_info = get_info(key)
        supply = int(float(getattr(invoice, "supplyCostTotal", 0) or 0))
        tax = int(float(getattr(invoice, "taxTotal", 0) or 0))
        save_issued(
            db, doc_type=doc_type, doc_id=doc_id, mgt_key=key,
            receiver_corp_num=str(getattr(invoice, "invoiceeCorpNum", "") or ""),
            receiver_name=str(getattr(invoice, "invoiceeCorpName", "") or ""),
            supply_cost=supply, tax=tax, info=issued_info,
        )
        issued_results.append({
            "role": role, "mgt_key": key, "confirm_num": issued_info.get("nts_confirm"),
        })

    cancelled = reason_code in (4, 6)
    return {
        "success": True,
        "confirm_num": issued_results[-1].get("confirm_num"),
        "issued": issued_results,
        "org_nts_confirm": nts,
        "reason_code": reason_code,
        "reason": reason_name,
        "reason_date": reason_date_text or original_write_date,
        "cancelled": cancelled,
    }


def supplier_info(db: Session) -> "dict[str, Any]":
    """공급자(대화감정평가) 정보. Amaranth 회사 API(api16S08)에서 자동으로 가져오고,
    비어있는 항목만 .env(POPBILL_SUPPLIER_*)로 보완한다."""
    from app.amaranth.client import AmaranthClient
    from scripts.find_management_numbers import _result_rows

    settings = get_settings()
    company: "dict[str, Any]" = {}
    try:
        payload = AmaranthClient(db).post("/apiproxy/api16S08", json_body={})
        rows = _result_rows(payload)
        target = next(
            (r for r in rows if str(r.get("coCd") or "") == "1000"), rows[0] if rows else {}
        )
        company = target or {}
    except Exception:
        company = {}

    def pick(api_val: str, env_val: str) -> str:
        return str(api_val or "").strip() or env_val

    addr = str(company.get("hoAddr") or company.get("hoAddr1") or "").strip()
    return {
        "corp_num": settings.popbill_corp_num or str(company.get("regNb") or "").replace("-", ""),
        "corp_name": pick(company.get("coNm"), settings.popbill_supplier_name),
        "ceo_name": pick(company.get("ceoNm"), settings.popbill_supplier_ceo),
        "addr": addr or settings.popbill_supplier_addr,
        "biz_type": pick(company.get("business"), settings.popbill_supplier_biztype),
        "biz_class": pick(company.get("jongmok"), settings.popbill_supplier_bizclass),
        "contact_name": "재무팀",
        "tel": pick(company.get("hoTel"), settings.popbill_supplier_tel),
        "email": settings.popbill_supplier_email,
    }


def lookup_customer(db: Session, tr_cd: str) -> "dict[str, Any]":
    """더존 거래처 마스터(api16S11)에서 거래처코드(trCd)로 공급받는자 정보 조회.

    감정서 매출 전표의 거래처코드로 세금계산서 공급받는자를 자동 채운다.
    """
    from app.amaranth.client import AmaranthClient
    from app.services.partners import partner_hp
    from scripts.find_management_numbers import _company_code, _result_rows

    client = AmaranthClient(db)
    company_code = _company_code(db, client)
    payload = client.post(
        "/apiproxy/api16S11",
        json_body={
            "coCd": company_code, "trCd": tr_cd,
            "usePagination": True, "pagingOffset": 0, "pagingCount": 5,
        },
    )
    for row in _result_rows(payload):
        if str(row.get("trCd") or "").strip() == tr_cd:
            addr = " ".join(str(row.get(k) or "").strip() for k in ("divAddr1", "addr2")).strip()
            return {
                "corp_num": str(row.get("regNb") or "").replace("-", ""),
                "corp_name": str(row.get("trNm") or "").strip(),
                "ceo_name": str(row.get("ceoNm") or "").strip(),
                "biz_type": str(row.get("business") or "").strip(),
                "biz_class": str(row.get("jongmok") or "").strip(),
                "addr": addr,
                # 아마란스 자체 세금계산서 화면과 같은 기준으로 담당자정보
                # (고객사담당자) 이메일만 쓴다 — 기본정보 email 등 다른 필드와
                # 섞으면 어느 메일로 나갔는지 화면과 어긋난다(2026-08-11 결정).
                # 거래처 등록 시 이 필드도 같이 채우므로(api16S14) 신규 건은 비지 않는다.
                "email": _primary_contact_email(client, company_code, tr_cd),
                "hp": partner_hp(row),  # 소득공제용 현금영수증 식별번호 후보
                "tr_cd": tr_cd,
            }
    return {}


def _primary_contact_email(client: "Any", co_cd: str, tr_cd: str) -> str:
    """고객사담당자(api16S24) 중 관리구분 정(defYn=1)인 담당자의 이메일.

    담당자가 여러 명일 수 있는데 api16S11의 조인 필드(stempgrpTrchargeEmail)는
    누구 것인지 보장이 없다 — 목록을 직접 조회해 정 담당자 것만 쓴다.
    정이 없거나 조회가 실패하면 빈 문자열(화면에서 수기 입력).
    """
    from scripts.find_management_numbers import _result_rows

    try:
        payload = client.post(
            "/apiproxy/api16S24", json_body={"coCd": co_cd, "trCd": tr_cd}
        )
        for row in _result_rows(payload):
            if str(row.get("defYn") or "").strip() == "1":
                return str(row.get("trchargeEmail") or "").strip()
    except Exception:
        pass
    return ""


def _cashbill_already(db: Session, doc_id: str) -> "dict[str, Any]":
    """발급 팝업의 현금영수증 기발행 상태 — 최신 원장 행 기준."""
    state = latest_cashbill_row(db, doc_id)
    if state and state[0] == "현금취소":
        return {"error": "취소됨", "cancelled": True}
    return get_cashbill_info(state[1]) if state else get_cashbill_info(doc_id)


def _taxinvoice_already(db: Session, doc_id: str) -> "dict[str, Any]":
    """발급 팝업의 세금계산서 기발행 상태. 최신 원장 행 기준."""
    state = latest_taxinvoice_row(db, doc_id)
    if state and state[0] == "세금취소":
        return {"error": "취소됨", "cancelled": True}
    info = get_info(state[1]) if state else get_info(doc_id)
    # 팝빌 화면에서 직접 발행취소(상태 600)한 건도 취소로 인정해 잠금을 푼다.
    if not info.get("error") and int(info.get("state_code") or 0) == 600:
        return {"error": "취소됨(팝빌 발행취소)", "cancelled": True}
    return info


def appraisal_tax_draft(db: Session, doc_id: str) -> "dict[str, Any]":
    """감정서번호로 세금계산서 발급 초안 조립: 공급받는자 + 청구액(공급가/세액).

    공급가/세액은 청구액(a10_receivable_summary.billed_amount, 부가세 포함)에서
    역산한다. 화면에서 수정 가능. 이미 발행된 건이면 발행정보도 함께 준다.
    """
    # 전표 매출 줄의 거래처를 공급받는자 기본값으로 (2026-08-28 사용자 요청으로
    # 401 계열 전체로 확대 — 4010001만 보면 기타수수료 등으로 계상된 81건이 빈칸).
    # 현금영수증(국세청) 거래처는 전표용 가짜 거래처라 공급받는자가 될 수 없다.
    row = db.execute(
        text(
            "SELECT TOP 1 partner_code, partner_name FROM dbo.a10_voucher_cache "
            "WHERE (account_code LIKE '401%' OR account_code = '9090000') AND debit_credit = '4' "
            "  AND LTRIM(RTRIM(management_no)) = CAST(:doc AS varchar(100)) "
            "  AND partner_code IS NOT NULL AND RTRIM(partner_code) <> '' "
            "  AND partner_code <> '0000028605' "
            "ORDER BY CASE WHEN account_code = '4010001' THEN 0 ELSE 1 END, "
            "         voucher_date DESC"
        ),
        {"doc": doc_id},
    ).mappings().first()
    tr_cd = str(row["partner_code"]).strip() if row else ""
    receiver = lookup_customer(db, tr_cd) if tr_cd else {}
    if row and not receiver.get("corp_name"):
        receiver["corp_name"] = str(row["partner_name"] or "").strip()
    if not tr_cd:
        # 전표가 아직 없는 감정서는 매출 줄 거래처가 없어 팝업이 빈 채로 열리고,
        # 거래처코드가 없으니 '전표 생성'도 바로 못 가고 선택 창으로 빠진다
        # (2026-09-08 01-2607-5-0112). 이미 발행한 계산서의 공급받는자 사업자번호로
        # 아마란스 거래처를 찾아 채운다 — 계산서 거래처가 곧 전표 거래처다.
        issued = db.execute(
            text(
                "SELECT TOP 1 receiver_corp_num, receiver_name FROM dbo.a10_issued_taxinvoice "
                "WHERE doc_id = :doc AND is_test = :t AND doc_type = N'세금계산서' "
                "  AND receiver_corp_num IS NOT NULL ORDER BY id DESC"
            ),
            {"doc": doc_id, "t": 1 if get_settings().popbill_is_test else 0},
        ).mappings().first()
        reg_no = "".join(ch for ch in str((issued or {}).get("receiver_corp_num") or "") if ch.isdigit())
        if reg_no:
            code = db.execute(
                text(
                    "SELECT TOP 1 partner_code FROM dbo.a10_partner_cache "
                    "WHERE REPLACE(ISNULL(reg_no, ''), '-', '') = :reg AND ISNULL(use_yn, '1') <> '0' "
                    "ORDER BY partner_code"
                ),
                {"reg": reg_no},
            ).scalar()
            tr_cd = str(code or "").strip()
            receiver = lookup_customer(db, tr_cd) if tr_cd else {}
            if not receiver.get("corp_num"):
                receiver["corp_num"] = reg_no
            if not receiver.get("corp_name"):
                receiver["corp_name"] = str(issued["receiver_name"] or "").strip()
            if tr_cd:
                receiver["tr_cd"] = tr_cd

    summary = db.execute(
        text(
            "SELECT billed_amount, last_received_date FROM dbo.a10_receivable_summary "
            "WHERE LTRIM(RTRIM(doc_id)) = CAST(:doc AS varchar(100))"
        ),
        {"doc": doc_id},
    ).mappings().first()
    billed = int((summary or {}).get("billed_amount") or 0)
    paid_date = (summary or {}).get("last_received_date")
    supply = round(billed / 1.1) if billed else 0
    tax = billed - supply
    amount_source = "요약캐시" if billed else ""
    if not billed:
        # 요약 캐시에 없는 건(약식 -6- 등)은 0 으로 열려 담당자가 금액을 손으로
        # 쳤고, 자릿수가 빠진 채 발행되는 사고가 났다 (2026-09-07 01-2609-6-0487:
        # 55,000 청구건에 5,500 현금영수증 발행 → 전표 생성이 막힘).
        # 원장의 수수료합계·부가가치세로 채운다. 화면에서 수정할 수 있다.
        source = db.execute(
            text(
                f"SELECT TOP 1 [수수료합계] AS fee, [부가가치세] AS vat "
                f"FROM [{get_settings().mssql_source_db}].dbo.apw_masterex "
                f"WHERE DocID = :doc"
            ),
            {"doc": doc_id},
        ).mappings().first()
        if source:
            supply = int(source["fee"] or 0)
            tax = int(source["vat"] or 0)
            billed = supply + tax
            amount_source = "감정서 청구액" if billed else ""

    from app.services.sales_division import sales_account

    # 기발행 합계 — 추가 발행(착수금 계산서 뒤 잔금 계산서) 확인창용.
    # 취소 행은 음수 금액으로 쌓이므로(save_issued의 세금취소) 단순 합이 곧
    # 유효 발행 합계다. 현재 모드(운영/테스트)의 발행분만 본다.
    evidence_totals = evidence_issue_totals(db, doc_id)

    return {
        "doc_id": doc_id,
        "tr_cd": tr_cd,
        "receiver": receiver,
        "supply_cost": supply,
        "tax": tax,
        "total": billed,
        # 금액을 어디서 가져왔는지 — 화면이 담당자에게 알려 준다(빈 값이면 못 채웠다는 뜻)
        "amount_source": amount_source,
        # 기존 키는 세금계산서 추가발행 화면 호환용. 아래 두 키가 혼합 분할발행용이다.
        "issued_totals": evidence_totals["tax"],
        "cash_issued_totals": evidence_totals["cash"],
        "combined_issued_totals": evidence_totals["combined"],
        "remaining_total": evidence_totals["remaining_total"],
        # 계정과목 기본값 = 전표 규칙과 같은 값(약식 -6- 은 기타수수료) — 팝업에서 고친 값이 전표에 간다
        "account_code": sales_account(doc_id),
        # 작성일자 기본값 = 최종 입금일 (화면에서 수정 가능, 없으면 오늘)
        "paid_date": paid_date.isoformat() if paid_date else None,
        # 세금계산서 기발행 정보 (없으면 error 키). 취소(수정발행)된 건은 재발급
        # 가능해야 하므로 미발행과 같은 모양으로, 재발행 건은 새 mgt_key로 조회한다.
        "already": _taxinvoice_already(db, doc_id),
        # 현금영수증 기발행 정보 (없으면 error 키). 취소분을 발행한 건은
        # 재발급 가능해야 하므로 미발행과 같은 모양(error 키)으로 돌려주되,
        # 취소 후 재발급(-R) 건은 최신 행이 현금영수증이라 발행됨으로 잡힌다.
        "already_cash": _cashbill_already(db, doc_id),
    }


def issue_for_appraisal(
    db: Session,
    *,
    doc_id: str,
    write_date: str,
    supply_cost: int,
    tax: int,
    receiver: "dict[str, Any]",
    email: str = "",
    purpose: str = "영수",
    item_name: "str | None" = None,
    item_remark: str = "",
    remark1: str = "",
) -> "dict[str, Any]":
    """감정서 건 세금계산서 발급. 공급자는 설정값, 공급받는자는 화면 확정본.

    품목(item_name)·품목 비고(item_remark)·비고1(remark1)은 화면에서 수정한
    값을 그대로 쓴다 (2026-08-03 — 품목만 기본 문구, 비고들은 기본 빈칸).
    """
    supplier = supplier_info(db)
    rcv = dict(receiver)
    if email:
        rcv["email"] = email
    items = [{
        "date": write_date,
        "name": (item_name if item_name is not None else f"감정평가수수료 {doc_id}")[:100],
        "spec": "",
        "qty": "1", "unit_cost": str(supply_cost),
        "supply_cost": supply_cost, "tax": tax, "remark": item_remark[:100],
    }]
    inv = build_taxinvoice(
        write_date=write_date, supplier=supplier, receiver=rcv,
        items=items, purpose=purpose, memo=remark1,
    )
    # 취소 후 재발행이면 팝빌 mgtKey를 새로 딴다(-R{차수}) — 키 재사용 불가.
    mgt_key = next_issue_mgt_key(db, doc_id)
    result = register_issue(inv, mgt_key, memo=f"감정 {doc_id}")
    result["mgt_key"] = mgt_key
    return result


def print_url(doc_type: str, mgt_key: str) -> str:
    """발행 건의 인쇄 팝업 URL — 유형별 양식(세금계산서/현금영수증)으로 열린다.

    팝빌이 보안 토큰이 든 URL을 주며 30초 안에 접속해야 한다 — 화면에서
    버튼 클릭 즉시 새 창으로 열고, 저장·재사용하지 않는다.
    """
    settings = get_settings()
    corp = settings.popbill_corp_num
    user = settings.popbill_user_id or None
    try:
        if doc_type == "현금영수증":
            return _cashbill_service().getPrintURL(corp, mgt_key, user)
        return _service().getPrintURL(corp, "SELL", mgt_key, user)
    except PopbillException as exc:
        raise RuntimeError(f"인쇄 URL 조회 실패: {exc.message}") from exc


def send_taxinvoice_fax(
    db: Session, *, doc_id: str, receive_num: str
) -> "dict[str, Any]":
    """발행된 세금계산서를 팩스로 전송 (팝빌 Taxinvoice sendFax, 포인트 과금).

    수신번호는 발급 팝업에서 수기 입력한다. 발신번호는 팝빌에 사전 등록된
    번호(popbill_fax_sender)만 쓸 수 있다. 재발행 건은 최신 mgt_key로 보낸다.
    """
    settings = get_settings()
    digits = "".join(ch for ch in str(receive_num or "") if ch.isdigit())
    if len(digits) < 8:
        return {"success": False, "message": "팩스 수신번호를 확인하세요."}
    mgt_key = doc_id
    state = latest_taxinvoice_row(db, doc_id)
    if state and state[0] == "세금계산서":
        mgt_key = state[1]
    try:
        # 성공 응답은 {code: 1, message: '팩스 전송 완료'} 꼴 — 접수번호는 없다
        # (테스트 환경 실측 2026-08-13). 실패는 PopbillException으로 온다.
        receipt = _service().sendFax(
            settings.popbill_corp_num, "SELL", mgt_key,
            settings.popbill_fax_sender, digits,
            settings.popbill_user_id or None,
        )
        message = getattr(receipt, "message", None) or "팩스 전송 접수"
        return {"success": True, "message": message, "receive_num": digits}
    except PopbillException as exc:
        return {"success": False, "code": exc.code, "message": exc.message}


def send_taxinvoice_email(
    db: Session, *, doc_id: str, email: str
) -> "dict[str, Any]":
    """발행된 세금계산서 안내메일을 원하는 주소로 재전송 (팝빌 sendEmail, 무료).

    발급 당시 수신자와 달라도 된다 — 담당자가 바뀌었거나 다른 부서로 다시
    보내 달라는 요청용 (2026-09-01 사용자 문의). 재발행 건은 최신 mgt_key로
    보낸다. 팝빌 운영 발급분만 가능 — TAMS 수기 대장분은 팝빌에 없다.
    """
    address = str(email or "").strip()
    if "@" not in address or "." not in address.split("@")[-1]:
        return {"success": False, "message": "이메일 주소를 확인하세요."}
    settings = get_settings()
    mgt_key = doc_id
    state = latest_taxinvoice_row(db, doc_id)
    if state and state[0] == "세금계산서":
        mgt_key = state[1]
    try:
        _service().sendEmail(
            settings.popbill_corp_num, "SELL", mgt_key, address,
            settings.popbill_user_id or None,
        )
        return {"success": True, "message": "메일 재전송 접수", "email": address}
    except PopbillException as exc:
        return {"success": False, "code": exc.code, "message": exc.message}


# 발급 원장 출처 (a10_issued_taxinvoice.source). 화면·집계는 값을 그대로 보여준다.
ISSUE_SOURCES = ("MOA팝빌", "팝빌동기화", "TAMS", "나라장터", "나라빌", "국세청", "위하고", "기타")   # 위하고: 2026-09-11


def _write_date_of(info: "dict[str, Any]") -> "date | None":
    """팝빌 조회값의 작성일자('YYYY-MM-DD' 또는 'YYYYMMDD') → date."""
    raw = str(info.get("write_date") or "").replace("-", "")
    if len(raw) != 8 or not raw.isdigit():
        return None
    try:
        return date(int(raw[:4]), int(raw[4:6]), int(raw[6:8]))
    except ValueError:
        return None


def save_issued(
    db: Session,
    *,
    doc_type: str,
    doc_id: str,
    receiver_corp_num: str,
    receiver_name: str,
    supply_cost: int,
    tax: int,
    info: "dict[str, Any]",
    trade_usage: str = "",
    mgt_key: "str | None" = None,
    account_code: str = "",
    source: str = "MOA팝빌",
    commit: bool = True,
    is_pool: bool = False,
    pool_id: "int | None" = None,
) -> None:
    """발급 성공분을 a10_issued_taxinvoice에 1행 저장 (TAMS 부가세.DB 대체 원장).

    source 는 ISSUE_SOURCES 중 하나 — MOA 가 팝빌로 직접 끊은 것은 기본값,
    팝빌 사이트 발행분을 배치가 흡수하면 '팝빌동기화' (2026-09-09).
    """
    from app.models import IssuedTaxInvoice
    if source not in ISSUE_SOURCES:
        raise ValueError(f"알 수 없는 발급 출처: {source}")
    db.add(IssuedTaxInvoice(
        doc_type=doc_type, doc_id=doc_id, mgt_key=mgt_key or doc_id,
        receiver_corp_num=receiver_corp_num or None,
        receiver_name=receiver_name or None,
        supply_cost=supply_cost, tax=tax, total=supply_cost + tax,
        nts_confirm=info.get("nts_confirm") or info.get("confirm_num"),
        issue_dt=info.get("issue_dt") or info.get("trade_dt"),
        trade_usage=trade_usage or None,
        account_code=account_code or None,
        is_test=get_settings().popbill_is_test,
        source=source,
        write_date=_write_date_of(info),
        is_pool=bool(is_pool), pool_id=pool_id,
    ))
    if commit:
        db.commit()


# ── 현금영수증 (개인·사업자 현금결제. 약식/현금 건은 세금계산서 대신 이걸로) ──

def _cashbill_service() -> CashbillService:
    settings = get_settings()
    if not settings.is_popbill_configured:
        raise RuntimeError("팝빌 설정이 없습니다.")
    svc = CashbillService(
        settings.popbill_link_id, settings.popbill_secret_key.get_secret_value()
    )
    svc.IsTest = settings.popbill_is_test
    svc.IPRestrictOnOff = True
    svc.UseStaticIP = False
    svc.UseLocalTimeYN = True
    return svc


def issue_cashbill(
    db: Session,
    *,
    doc_id: str,
    trade_usage: str,       # 소득공제용 / 지출증빙용
    identity_num: str,      # 식별번호: 소득공제=휴대폰번호, 지출증빙=사업자번호
    supply_cost: int,
    tax: int,
    customer_name: str = "",
    email: str = "",
    hp: str = "",
) -> "dict[str, Any]":
    """현금영수증 발급(승인거래·과세). mgt_key=감정서번호. 식별번호는 재무팀 수기 입력."""
    settings = get_settings()
    svc = _cashbill_service()
    supplier = supplier_info(db)
    # 취소 후 재발급이면 새 문서번호(-R{차수}) — 팝빌 키 재사용 불가
    mgt_key = next_cashbill_mgt_key(db, doc_id)
    cashbill = Cashbill(
        mgtKey=mgt_key,
        tradeType="승인거래",
        tradeUsage=trade_usage,
        taxationType="과세",
        identityNum=identity_num,
        itemName=f"감정평가수수료 {doc_id}",
        orderNumber=doc_id,
        supplyCost=str(int(supply_cost)),
        tax=str(int(tax)),
        serviceFee="0",
        totalAmount=str(int(supply_cost) + int(tax)),
        franchiseCorpNum=settings.popbill_corp_num or supplier["corp_num"],
        franchiseCorpName=supplier["corp_name"],
        franchiseCEOName=supplier["ceo_name"],
        franchiseAddr=supplier["addr"],
        franchiseTEL=supplier["tel"],
        customerName=customer_name,
        email=email,
        hp=hp,
        smssendYN=False,
    )
    try:
        result = svc.registIssue(
            settings.popbill_corp_num, cashbill, f"감정 {doc_id}",
            settings.popbill_user_id or None,
        )
        return {"success": result.code == 1, "code": result.code,
                "message": result.message, "mgt_key": mgt_key}
    except PopbillException as exc:
        return {"success": False, "code": exc.code, "message": exc.message}


def get_cashbill_info(mgt_key: str) -> "dict[str, Any]":
    settings = get_settings()
    svc = _cashbill_service()
    try:
        info = svc.getInfo(settings.popbill_corp_num, mgt_key)
        return {
            "trade_dt": getattr(info, "tradeDT", None),
            "confirm_num": getattr(info, "confirmNum", None),  # 국세청 승인번호
            "trade_usage": getattr(info, "tradeUsage", None),
            "total": getattr(info, "totalAmount", None),
        }
    except PopbillException as exc:
        return {"error": f"{exc.code}: {exc.message}"}


def cashbill_cancelled(db: Session, doc_id: str) -> bool:
    """MOA에서 취소 현금영수증을 발행한 감정서인지 (원장 doc_type='현금취소')."""
    from sqlalchemy import text as _text

    found = db.execute(
        _text(
            "SELECT 1 FROM dbo.a10_issued_taxinvoice "
            "WHERE doc_id = :doc AND doc_type = N'현금취소'"
        ),
        {"doc": doc_id},
    ).first()
    return found is not None


# 팝빌 취소 현금영수증 사유코드 — 화면 선택지와 맞춘다.
CASHBILL_CANCEL_TYPES = {1: "거래취소", 2: "오류발급취소", 3: "기타"}


def cancel_cashbill(
    db: Session, *, doc_id: str, cancel_type: int = 1, memo: str = ""
) -> "dict[str, Any]":
    """취소 현금영수증 발행(RevokeRegistIssue) — 원거래는 mgt_key=감정서번호.

    국세청 전송이 끝난 건도 취소분 발행 방식이라 취소 가능하다. 취소분은
    mgt_key '{감정서번호}-C'로 발행하고 원장에 doc_type='현금취소'로 기록한다
    (doc_type 컬럼이 VARCHAR(10)이라 '현금영수증취소'는 안 들어간다).
    MOA(팝빌)로 발행한 건만 취소할 수 있다 — 홈택스 수기 발급분은 팝빌이 모른다.
    """
    if cancel_type not in CASHBILL_CANCEL_TYPES:
        return {"success": False, "message": "취소사유는 1(거래취소)·2(오류발급취소)·3(기타) 중 하나입니다."}
    # 취소 대상 = 최신 발행분 — 재발급(-R) 건이면 그 키의 원거래를 취소한다.
    state = latest_cashbill_row(db, doc_id)
    if state and state[0] == "현금취소":
        return {"success": False, "message": "이미 취소된 현금영수증입니다."}
    org_key = state[1] if state else doc_id
    org = get_cashbill_info(org_key)
    if org.get("error"):
        return {"success": False,
                "message": f"팝빌에서 원거래를 찾지 못했습니다({org['error']}). "
                           "MOA 밖에서 발급된 건은 홈택스에서 취소하세요."}
    trade_date = str(org.get("trade_dt") or "")[:8]
    confirm = str(org.get("confirm_num") or "").strip()
    if len(trade_date) != 8 or not confirm:
        return {"success": False, "message": "원거래 승인번호/거래일자를 확인하지 못했습니다."}

    settings = get_settings()
    svc = _cashbill_service()
    cancel_key = next_cashbill_cancel_key(db, doc_id)
    try:
        svc.revokeRegistIssue(
            settings.popbill_corp_num, cancel_key, confirm, trade_date,
            False, memo or f"감정 {doc_id} 현금영수증 취소",
            settings.popbill_user_id or None, False, cancel_type,
        )
    except PopbillException as exc:
        return {"success": False, "message": f"{exc.code}: {exc.message}"}

    cancel_info = get_cashbill_info(cancel_key)
    # 취소 행에 원 금액을 양수로 싣는다 (2026-09-09) — 예전엔 0 으로 저장해 합계 방식에서
    # 취소가 안 빠졌다(0원 취소 4행은 원본 금액으로 채워 넣었다). evidence_issue_totals 는
    # 0 이면 통째 제거하던 옛 규칙도 그대로 이해한다.
    origin_amounts = None
    if getattr(db, "execute", None):
        origin_amounts = db.execute(
            text(
                "SELECT TOP 1 supply_cost, tax FROM dbo.a10_issued_taxinvoice "
                "WHERE doc_id = :doc AND doc_type = N'현금영수증' AND is_test = :t ORDER BY id DESC"
            ),
            {"doc": doc_id, "t": 1 if get_settings().popbill_is_test else 0},
        ).first()
    if origin_amounts:
        cancel_supply, cancel_tax = int(origin_amounts[0] or 0), int(origin_amounts[1] or 0)
    else:  # 원장에 원본이 없으면 팝빌 합계를 1.1 로 나눈다
        cancel_total = int(float(org.get("total") or 0))
        cancel_supply = int(round(cancel_total / 1.1))
        cancel_tax = cancel_total - cancel_supply
    save_issued(
        db, doc_type="현금취소", doc_id=doc_id, mgt_key=cancel_key,
        receiver_corp_num="", receiver_name=CASHBILL_CANCEL_TYPES[cancel_type],
        supply_cost=cancel_supply, tax=cancel_tax, info=cancel_info,
        trade_usage=str(org.get("trade_usage") or ""),
    )
    return {"success": True, "confirm_num": cancel_info.get("confirm_num"),
            "cancel_type": CASHBILL_CANCEL_TYPES[cancel_type],
            "mgt_key": cancel_key}


def get_info(mgt_key: str) -> "dict[str, Any]":
    """발행한 세금계산서 상태 조회 (국세청 승인번호·전송상태 등)."""
    settings = get_settings()
    svc = _service()
    try:
        info = svc.getInfo(settings.popbill_corp_num, "SELL", mgt_key)
        supply = int(getattr(info, "supplyCostTotal", 0) or 0)
        tax = int(getattr(info, "taxTotal", 0) or 0)
        write_date = str(getattr(info, "writeDate", "") or "")
        return {
            "issue_dt": getattr(info, "issueDT", None),
            # 작성일자(YYYY-MM-DD). 발행시각(issue_dt)과 다르다 — 9/7 작성분을 9/8 에
            # 발행하면 승인번호는 20260907… 로 나온다. 화면이 이걸 안 보여줘서
            # "9/8 로 발행됐다"는 오해가 났다 (2026-09-08 01-2609-3-2761).
            "write_date": (f"{write_date[:4]}-{write_date[4:6]}-{write_date[6:8]}"
                           if len(write_date) == 8 else None),
            "nts_confirm": getattr(info, "ntsconfirmNum", None),  # 국세청 승인번호
            "state": getattr(info, "stateMemo", None),
            "state_code": getattr(info, "stateCode", None),       # 600=발행취소
            "nts_send_dt": getattr(info, "ntsSendDT", None),      # 국세청 전송일시(전송 전엔 없음)
            "supply_cost": supply,
            "tax": tax,
            "total": supply + tax,  # getInfo엔 totalAmount 필드가 없어 합산한다
        }
    except PopbillException as exc:
        return {"error": f"{exc.code}: {exc.message}"}
