"""기존 감정서 뷰와 Amaranth 전표 이력을 연결하는 조회 서비스."""

import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, or_, select, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_engine
from app.models.voucher_cache import VoucherCache
from app.models.voucher_sync import VoucherSync
from app.services.office_lookup import docid_prefixes, match_offices_to_divisions
from app.services.receivables import (
    _ROUND_NOISE,
    _expense_closes,
    attach_payment_amounts,
    attach_proof_issued,
)


class AppraisalNotFoundError(LookupError):
    pass


def _appraisal_payment_label(row: dict[str, Any]) -> str:
    """감정서 목록용 표시값을 정식 입금 판정과 일치시킨다.

    a10_receivable_summary의 outstanding_amount는 전표상 청구액만 기준으로 하므로,
    원장 청구액이 더 큰 부분입금 건도 0이 될 수 있다. 입금완료 여부는 원장
    청구액까지 검증해 만든 a10_payment_status.pay_result를 우선 사용한다.
    """
    billed = Decimal(row.get("billed_amount") or 0)
    received = Decimal(row.get("received_amount") or 0)
    advance = Decimal(row.get("advance_amount") or 0)
    overpaid = Decimal(row.get("overpaid_amount") or 0)
    pay_result = str(row.get("pay_result") or "").strip()

    if advance > 0 and billed == 0:
        return "선수금"
    if overpaid > 0:
        return "과입금"
    if pay_result == "입금완료":
        return "입금완료"
    if pay_result == "분할입금" or received > 0:
        return "일부입금"
    if billed > 0:
        return "미수"
    return "미확인"


def _effective_appraisal_payment_label(
    row: dict[str, Any], fallback: str
) -> str:
    """최종 매출액과 수금액으로 목록 상태를 재검증한다.

    전표 요약은 입금 후 선수금 상계·증빙 발행처럼 서로 다른 날짜의 전표가 이어지는
    동안 청구액 0/과입금으로 남을 수 있다. 목록 금액에 사용하는 것과 같은 최종 기준을
    적용해 실제 초과 수금일 때만 과입금으로 표시한다.
    """
    gross = Decimal(str(row.get("gross_total") or 0))
    paid = Decimal(str(row.get("received_total") or 0))
    noise = Decimal(str(_ROUND_NOISE))
    if gross <= 0:
        return fallback
    if paid - gross > noise:
        return "과입금"
    if gross - paid <= noise:
        return "입금완료"
    if paid > 0:
        return "일부입금"
    return "미수"


# 목록 건수를 페이지 조회와 동시에 계산하기 위한 전용 워커.
_COUNT_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="appraisal-count")


def _count_rows(sql: str, params: dict[str, Any]) -> int:
    """세션은 스레드 안전하지 않으므로 별도 커넥션으로 건수만 센다."""
    with get_engine().connect() as connection:
        return int(connection.execute(text(sql), params).scalar_one())


def _apply_expense_close(item: "dict[str, Any]", closed_amount: float) -> None:
    """실비 종결 건의 감정서 LIST 표시 (2026-09-02 사용자 확정) — 수금액이 최종 매출.

    감정가액은 그대로 두고, 순수수료 0 · 여비및기타 = 실비 입금액 ·
    수수료합계 = 같은 값 · 부가세 0 · 매출총액 = 실비 입금액 · 미수금 0.
    실제 입금액·입금일 칸은 건드리지 않는다 — 들어온 돈 그 자체다.
    """
    item.update(
        payment_status="실비완납",
        base_fee=0.0,
        appraisal_cost=closed_amount,
        sales_amount=closed_amount,
        vat_amount=0.0,
        gross_total=closed_amount,
        outstanding_amount=0.0,
        expense_closed=True,
    )


# 목록 한 줄의 fat 컬럼 — 뷰 경로·빠른 경로 상세 조회가 같은 SELECT 를 쓰도록 한 곳에 둔다.
# 순수수료·여비및기타는 입금현황·미수금현황과 같은 정의 (2026-09-01 열 개편).
_PAGE_COLUMNS = """
                a.DocID AS doc_id,
                a.CustDocid AS cust_doc_id,
                a.ReceiptDate AS receipt_date,
                a.Address AS address,
                a.CustName AS customer_name,
                a.Debtor AS debtor,
                a.OwnerName AS owner_name,
                a.Title AS title,
                a.Manager AS manager,
                a.Charge AS author,
                a.LWorkinfo AS purpose,
                a.LPurpose AS eval_purpose,
                a.LStatus AS progress_status,
                a.SendDate AS send_date,
                a.price AS appraisal_amount,
                a.[기초수수료] AS base_fee,   -- 청구서 순수수료합계(절사 전), 2026-09-11
                a.[여비] AS travel_expense,
                a.[물건조사비] AS survey_fee,
                a.[공부발급비] AS document_fee,
                a.[토지조사비] AS land_survey_fee,
                a.[기타실비] AS other_expense,
                a.[특별용역비] AS special_service_fee,
                a.[수수료합계] - a.[기초수수료] + ISNULL(a.[절사금액], 0) AS appraisal_cost,
                a.[수수료합계] AS sales_amount,
                a.[부가가치세] AS vat_amount,
                a.[매출총액] AS gross_total,
                a.[여비] AS travel_expense,
                a.[특별용역비] AS special_service_fee
""".strip()

# 빠른 경로(APW_Master 2단계 조회)는 화면 조회에만 쓴다. 엑셀 내보내기는 수만 건을 한
# 번에 받으므로(page_size=100000) 뷰 상세의 IN 절 파라미터 한도를 넘어 기존 경로로 보낸다.
_FAST_PAGE_LIMIT = 200


class AppraisalService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list(
        self,
        *,
        doc_id: str | None = None,
        cust_doc_id: str | None = None,
        address: str | None = None,
        customer_name: str | None = None,
        manager: str | None = None,
        charge: str | None = None,
        office_code: str | None = "10",
        sort_by: str | None = None,
        sort_order: str = "asc",
        status: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        bill_from: float | None = None,
        bill_to: float | None = None,
        price_from: float | None = None,
        price_to: float | None = None,
        purpose: str | None = None,
        scope_person: str | None = None,
        keyword: str | None = None,
        page: int = 1,
        page_size: int = 30,
    ) -> dict[str, Any]:
        where, params = _where_clause(
            doc_id, address, customer_name, manager, charge,
            status, date_from, date_to, office_code, bill_from, bill_to,
            price_from, price_to, purpose, scope_person, cust_doc_id, keyword,
        )
        params.update(offset=(page - 1) * page_size, page_size=page_size)

        source_view = _source_view()
        # 빠른 경로: 필터·정렬이 전부 구동 테이블(APW_Master) 컬럼이면 15개 테이블을
        # 조인하는 뷰를 통째로 세고 정렬하는 대신, 가벼운 APW_Master 에서 건수와 페이지
        # 키를 먼저 뽑고 뷰는 그 페이지분만 상세 조회한다. 결과·순서는 뷰 단일 조회와
        # 완전히 동일함을 실측 확인(2026-09-07: COUNT 1.85s→0.17s, 페이지 1.53s→0.99s).
        # 화면 조회에만 쓰고, 엑셀 내보내기(수만 건)·복잡 필터(주소·상태·목적·담당자·
        # 청구액·통합검색)는 기존 뷰 경로로 간다.
        plan = _base_fast_plan(
            doc_id=doc_id, cust_doc_id=cust_doc_id, address=address,
            customer_name=customer_name, manager=manager, charge=charge,
            status=status, purpose=purpose, scope_person=scope_person,
            keyword=keyword, bill_from=bill_from, bill_to=bill_to,
            price_from=price_from, price_to=price_to,
            date_from=date_from, date_to=date_to, office_code=office_code,
            sort_by=sort_by, sort_order=sort_order,
        )
        if plan is not None and page_size <= _FAST_PAGE_LIMIT:
            items, total = self._page_via_base(plan, page, page_size, source_view)
        else:
            items, total = self._page_via_view(
                where, params, sort_by, sort_order, source_view
            )
        for item, status in zip(items, self._payment_statuses([i["doc_id"] for i in items])):
            item["payment_status"] = status
        # 세금계산서/현금영수증 발행 여부 — 입금현황과 같은 규칙·같은 칸 (2026-08-27 사용자 요청)
        attach_proof_issued(self.db, items)
        # 입금액·입금일·미수금 — 입금현황과 같은 판정식 (2026-09-01 열 개편)
        attach_payment_amounts(self.db, items)
        # 요약 청구액이 0으로 남은 선수금 상계·후발행 건도 최종 매출/수금액으로
        # 재검증한다. 실제 초과 수금이 아닌 건을 과입금으로 재무팀에 표시하지 않는다.
        for item in items:
            item["payment_status"] = _effective_appraisal_payment_label(
                item, str(item.get("payment_status") or "미확인")
            )
        # 실비 종결 건 — 수금액이 최종 매출 (2026-09-02). 입금현황 판정(_GROSS 의 ec)과
        # 같은 활성 행을 읽어 상태·금액 칸을 실비 기준으로 덮는다.
        closes = _expense_closes(self.db, items)
        for item in items:
            close = closes.get(str(item["doc_id"]))
            if close:
                _apply_expense_close(item, float(close["closed_amount"] or 0))
        return {
            "items": items,
            "page": page,
            "page_size": page_size,
            "total": total,
        }

    def _page_via_view(
        self, where: str, params: dict[str, Any],
        sort_by: str | None, sort_order: str, source_view: str,
    ) -> "tuple[list[dict[str, Any]], int]":
        """기존 경로: 뷰에서 건수(병렬)와 한 페이지 fat 컬럼을 한 번에 뽑는다.

        복잡 필터·엑셀 내보내기·뷰 전용 정렬 열에 쓴다. 건수와 페이지 조회는 서로
        독립이고 각각 뷰(15개 테이블 조인)를 훑기 때문에 순차로 돌리면 시간이 두 배가
        된다. 건수는 별도 커넥션에서 동시에 계산한다.
        """
        count_future = _COUNT_POOL.submit(
            _count_rows, f"SELECT COUNT_BIG(1) FROM {source_view} {where}", dict(params)
        )
        order_sql = _view_order_sql(sort_by, sort_order)
        # 먼저 원본 뷰에서 한 페이지만 추린다. 입금상태 CTE를 여기서 조인하면 페이징 전에
        # 전체 결과와 조인되어(전체기간 조회 시 5만건+) 매우 느려진다.
        rows = self.db.execute(
            text(
                f"SELECT {_PAGE_COLUMNS} FROM {source_view} a {where} "
                f"ORDER BY {order_sql} "
                "OFFSET :offset ROWS FETCH NEXT :page_size ROWS ONLY"
            ),
            params,
        ).mappings().all()
        return [_serialize_mapping(row) for row in rows], count_future.result()

    def _page_via_base(
        self, plan: "tuple[str, dict[str, Any], str]",
        page: int, page_size: int, source_view: str,
    ) -> "tuple[list[dict[str, Any]], int]":
        """빠른 경로: APW_Master 에서 건수(병렬)와 페이지 DocID 를 먼저 뽑고, 뷰는 그
        DocID 들만 상세 조회한다."""
        base_where, base_params, base_order = plan
        source_table = _source_table()
        count_future = _COUNT_POOL.submit(
            _count_rows,
            f"SELECT COUNT_BIG(1) FROM {source_table} {base_where}",
            dict(base_params),
        )
        page_params = dict(base_params, offset=(page - 1) * page_size, page_size=page_size)
        doc_ids = list(
            self.db.execute(
                text(
                    f"SELECT DocID FROM {source_table} {base_where} "
                    f"ORDER BY {base_order} "
                    "OFFSET :offset ROWS FETCH NEXT :page_size ROWS ONLY"
                ),
                page_params,
            ).scalars().all()
        )
        return self._detail_by_docids(doc_ids, source_view), count_future.result()

    def _detail_by_docids(
        self, doc_ids: "list[str]", source_view: str
    ) -> "list[dict[str, Any]]":
        """페이지에 뽑힌 DocID 들의 fat 컬럼을 뷰에서 한 번에 읽어 base 정렬 순서대로
        되돌린다. IN 절은 순서를 보장하지 않으므로 doc_ids 순서로 재배열한다."""
        if not doc_ids:
            return []
        binds = [f"pk_{index}" for index in range(len(doc_ids))]
        params = {name: doc_ids[index] for index, name in enumerate(binds)}
        placeholders = ", ".join(f":{name}" for name in binds)
        rows = self.db.execute(
            text(
                f"SELECT {_PAGE_COLUMNS} FROM {source_view} a "
                f"WHERE a.DocID IN ({placeholders})"
            ),
            params,
        ).mappings().all()
        by_doc = {str(row["doc_id"]): _serialize_mapping(row) for row in rows}
        return [by_doc[str(doc_id)] for doc_id in doc_ids if str(doc_id) in by_doc]

    # 이 클래스에는 list() 메서드가 있어 내장 list가 가려지므로 문자열 주석을 쓴다.
    def _payment_statuses(self, doc_ids: "list[str]") -> "list[str]":
        """해당 감정서들의 입금상태를 요약·정식 판정 캐시에서 읽는다.

        엑셀 내보내기처럼 건수가 많을 수 있어 SQL Server 파라미터 한도(2100개)를
        넘지 않도록 1,000건씩 나눠 조회한다.
        """
        if not doc_ids:
            return []
        status_by_doc: dict[str, str] = {}
        for start in range(0, len(doc_ids), 1000):
            chunk = doc_ids[start:start + 1000]
            names = [f"pay_doc_{index}" for index in range(len(chunk))]
            params = {name: chunk[index] for index, name in enumerate(names)}
            rows = self.db.execute(
                text(
                    f"""
                    SELECT s.doc_id, s.billed_amount, s.received_amount,
                        s.advance_amount, s.overpaid_amount, p.pay_result
                    FROM dbo.a10_receivable_summary s
                    LEFT JOIN dbo.a10_payment_status p ON p.doc_id = s.doc_id
                    WHERE s.doc_id IN ({', '.join(':' + name for name in names)})
                    """
                ),
                params,
            ).mappings().all()
            status_by_doc.update(
                {row["doc_id"]: _appraisal_payment_label(dict(row)) for row in rows}
            )
        return [status_by_doc.get(doc_id, "미확인") for doc_id in doc_ids]

    def offices(self) -> dict[str, Any]:
        matched = match_offices_to_divisions(self.db)
        items = [
            {
                "office_code": item["office_code"],
                "office_name": item["office_name"],
                "division_code": item["division_code"],
                "division_name": item["division_name"],
            }
            for item in matched["items"]
        ]
        return {"items": items, "count": len(items), "source": matched["source"]}

    def voucher_detail(self, doc_id: str) -> dict[str, Any]:
        appraisal = self.db.execute(
            text(
                f"""
                SELECT TOP 1 DocID, ReceiptDate, CustName, price,
                    [기초수수료], [여비], [물건조사비], [토지조사비], [공부발급비],
                    [기타실비], [특별용역비], [절사금액], [수수료합계], [부가가치세], [청구금액]
                FROM {_source_view()} WHERE DocID = :doc_id
                """
            ),
            {"doc_id": doc_id},
        ).mappings().first()
        if appraisal is None:
            raise AppraisalNotFoundError("감정서를 찾을 수 없습니다.")
        fee_summary = _fee_summary(appraisal)
        tax_invoices = self._tax_invoices(doc_id)

        matched_lines = self.db.scalars(
            select(VoucherCache)
            .where(VoucherCache.management_no == doc_id)
            .order_by(
                VoucherCache.voucher_date.desc(),
                VoucherCache.voucher_no.desc(),
                VoucherCache.line_no,
            )
        ).all()
        # 경비(협회비 등) 줄은 재무팀이 관리항목에 감정서번호를 못 넣고 적요에만 적는다
        # (2026-09-10, 01-2607-4-0253 심사운영비 233,257). 관리번호가 빈 줄 중 적요가 이 번호로
        # 시작하는 것을 따로 내린다(expense_items) — 전표내용이 아니라 '감정서별 비용 지급내역'
        # 몫이다(사용자 정정). 접수일 두 달 전부터만 훑어 큰 표 스캔을 줄인다.
        expense_items = _cached_vouchers(
            self._remark_only_lines(doc_id, appraisal["ReceiptDate"]), doc_id,
        )
        if matched_lines:
            voucher_keys = list(
                dict.fromkeys(
                    (
                        line.voucher_date,
                        line.voucher_no,
                        line.division_code,
                    )
                    for line in matched_lines
                )
            )
            all_voucher_lines = self.db.scalars(
                select(VoucherCache)
                .where(
                    or_(
                        *(
                            and_(
                                VoucherCache.voucher_date == voucher_date,
                                VoucherCache.voucher_no == voucher_no,
                                VoucherCache.division_code == division_code,
                            )
                            for voucher_date, voucher_no, division_code in voucher_keys
                        )
                    )
                )
                .order_by(
                    VoucherCache.voucher_date.desc(),
                    VoucherCache.voucher_no.desc(),
                    VoucherCache.line_no,
                )
            ).all()
            cached_items = _cached_vouchers(all_voucher_lines, doc_id)
            _mark_offset_lines(cached_items)
            return {
                "doc_id": doc_id,
                "matched_by": "apworksdw.DocID = GamJunDW.a10_voucher_cache.ctNb",
                "fee_summary": fee_summary,
                "tax_invoices": tax_invoices,
                "items": cached_items,
                "expense_items": expense_items,
                "count": len(cached_items),
                "source": "gamjundw_voucher_cache",
            }

        vouchers = self.db.scalars(
            select(VoucherSync)
            .where(VoucherSync.management_no == doc_id)
            .order_by(VoucherSync.created_at.desc())
        ).all()
        local_items = [_voucher_to_dict(voucher) for voucher in vouchers]
        if local_items:
            return {
                "doc_id": doc_id,
                "matched_by": "apw_masterex.DocID = a10_voucher_sync.management_no",
                "fee_summary": fee_summary,
                "tax_invoices": tax_invoices,
                "items": local_items,
                "expense_items": expense_items,
                "count": len(local_items),
                "source": "local_sync_history",
            }

        return {
            "doc_id": doc_id,
            "matched_by": "apworksdw.DocID = GamJunDW.a10_voucher_cache.ctNb",
            "fee_summary": fee_summary,
            "tax_invoices": tax_invoices,
            "items": [],
            "expense_items": expense_items,
            "count": 0,
            "source": "gamjundw_voucher_cache",
            "cache_miss": True,
        }

    def _remark_only_lines(self, doc_id: str, receipt_date: Any) -> "list[VoucherCache]":
        since = None
        if isinstance(receipt_date, datetime):
            receipt_date = receipt_date.date()
        if isinstance(receipt_date, date):
            since = receipt_date - timedelta(days=60)
        return list(self.db.scalars(remark_only_lines_query(doc_id, since)).all())

    def _tax_invoices(self, doc_id: str) -> "list[dict[str, Any]]":
        """이 감정서번호의 세금계산서·현금영수증 내역.

        MOA가 팝빌로 발급한 것(a10_issued_taxinvoice) + 과거 TAMS 캐시분을 합친다.
        원천은 발급 원장 하나다 (2026-09-09) — 출처(source)가 MOA팝빌·팝빌동기화·TAMS 를 가른다.
        """
        # 1) MOA 자체 발급분 (팝빌) — 최신 우선
        # 발급 원장 하나로 본다 (2026-09-09): MOA 팝빌·팝빌 동기화·TAMS 이관분이 한 테이블에
        # 있고 중복은 이관·동기화 때 걸렀다. 출처(source)를 같이 내려 화면이 구분한다.
        rows = self.db.execute(
            text(
                """
                SELECT doc_type, receiver_name, supply_cost, tax, total,
                       nts_confirm, issue_dt, write_date, created_at, source, is_pool, pool_id
                FROM dbo.a10_issued_taxinvoice
                WHERE doc_id = :doc_id AND is_test = 0
                ORDER BY id DESC
                """
            ),
            {"doc_id": doc_id},
        ).mappings().all()
        result: "list[dict[str, Any]]" = []
        for row in rows:
            kind = str(row["doc_type"])
            cancel = kind in ("세금취소", "현금취소")
            tax_date = (
                row["write_date"].isoformat() if row["write_date"]
                else (str(row["issue_dt"])[:8] if row["issue_dt"]
                      else (row["created_at"].date().isoformat() if row["created_at"] else None))
            )
            result.append({
                "tax_date": tax_date,
                "company_name": row["receiver_name"],
                # 모계산서(입금 적용용)는 이 감정서 발행금액이 아니다 — 표시만 하고 상태로 구분 (2026-09-10)
                "status": ("취소" if cancel else "발급") + (" (입금적용용)" if row["is_pool"] else (" (적용)" if row["pool_id"] else "")),
                "is_pool": bool(row["is_pool"]),
                "issue_type": "현금영수증" if kind.startswith("현금") else "세금계산서",
                "approval_no": row["nts_confirm"],
                "supply_amount": float(row["supply_cost"] or 0),
                "vat_amount": float(row["tax"] or 0),
                "total_amount": float(row["total"] or 0),
                "source": row["source"],
            })
        result.sort(key=lambda item: str(item.get("tax_date") or ""), reverse=True)
        return result


def _where_clause(
    doc_id: str | None,
    address: str | None,
    customer_name: str | None,
    manager: str | None,
    charge: str | None,
    status: str | None,
    date_from: date | None,
    date_to: date | None,
    office_code: str | None,
    bill_from: float | None = None,
    bill_to: float | None = None,
    price_from: float | None = None,
    price_to: float | None = None,
    purpose: str | None = None,
    scope_person: str | None = None,
    cust_doc_id: str | None = None,
    keyword: str | None = None,
) -> tuple[str, dict[str, Any]]:
    conditions: list[str] = []
    params: dict[str, Any] = {}
    if office_code:
        conditions.append("Office = :office_code")
        params["office_code"] = office_code
    # 통합검색 — 사이버브랜치 적요를 붙여 넣으면 소재지·채무자·거래처·번호를 한꺼번에
    # 찾는다 (2026-09-03). 붙여 넣은 게 어느 칸인지 몰라도 되도록 내용 열을 OR 로 묶는다.
    if keyword:
        # 번호형은 번호 두 열만(전 기간), 글자형은 내용 6열(기간 안) — 이유는 keyword_is_number.
        if keyword_is_number(keyword):
            conditions.append(_NUMBER_KEYWORD_SQL)
            params["keyword_exact"] = keyword.strip()
        else:
            conditions.append(
                "(" + " OR ".join(f"{column} LIKE :keyword" for column in _KEYWORD_TEXT_COLUMNS) + ")"
            )
        params["keyword"] = f"%{keyword.strip()}%"
    # 감정서번호는 정확일치 — 번호는 통째로 붙여 넣으므로 LIKE 가 필요 없다
    # (2026-09-07 사용자 결정). 바인드는 varchar 로 캐스팅해야 인덱스를 탄다.
    if doc_id:
        conditions.append("DocID = CAST(:doc_id AS varchar(50))")
        params["doc_id"] = doc_id.strip()
    filters = (
        ("CustDocid", "cust_doc_id", cust_doc_id),
        ("Address", "address", address),
        ("CustName", "customer_name", customer_name),
        ("Manager", "manager", manager),
        ("Charge", "charge", charge),
    )
    for column, key, value in filters:
        if value:
            conditions.append(f"{column} LIKE :{key}")
            params[key] = f"%{value}%"
    if status:
        conditions.append("LStatus = :status")
        params["status"] = status
    # 금액 범위(원 단위). NULL인 감정서는 범위 조건이 걸리면 제외된다.
    if bill_from is not None:
        conditions.append("[청구금액] >= :bill_from")
        params["bill_from"] = bill_from
    if bill_to is not None:
        conditions.append("[청구금액] <= :bill_to")
        params["bill_to"] = bill_to
    if price_from is not None:
        conditions.append("price >= :price_from")
        params["price_from"] = price_from
    if price_to is not None:
        conditions.append("price <= :price_to")
        params["price_to"] = price_to
    if purpose:
        conditions.append("LWorkinfo LIKE :purpose")
        params["purpose"] = f"%{purpose}%"
    if scope_person:
        conditions.append("(Manager LIKE :scope_person OR Charge LIKE :scope_person)")
        params["scope_person"] = f"%{scope_person}%"
    # 감정서번호·의뢰문서번호·통합검색으로 찾을 때는 오래된 건도 검색되도록 접수일 조건을
    # 제외한다. (번호나 적요를 아는 사람은 접수일을 모르는 경우가 많아 기간에 걸려 안 나오면 오해가 생긴다)
    # 글자형 통합검색은 기간을 살린다 — 전 기간을 뒤지면 17초가 걸렸다(2026-09-07).
    pinpoint = bool(doc_id or cust_doc_id or (keyword and keyword_is_number(keyword)))
    if date_from and not pinpoint:
        conditions.append("ReceiptDate >= :date_from")
        params["date_from"] = date_from
    if date_to and not pinpoint:
        conditions.append("ReceiptDate < DATEADD(day, 1, :date_to)")
        params["date_to"] = date_to
    return ("WHERE " + " AND ".join(conditions) if conditions else ""), params


# 뷰 경로의 정렬 열 — 계산·조인 컬럼까지 포함해 모든 정렬을 뷰에서 처리한다.
_VIEW_SORT_COLUMNS = {
    "doc_id": "DocID", "cust_doc_id": "CustDocid",
    "receipt_date": "ReceiptDate",
    "address": "Address", "customer_name": "CustName", "title": "Title",   # 건명 (2026-09-11)
    "debtor": "Debtor", "owner_name": "OwnerName",
    "manager": "Manager", "author": "Charge",
    # LWorkinfo=업무구분, LPurpose=평가목적 (2026-09-03 사용자 확정)
    "purpose": "LWorkinfo", "eval_purpose": "LPurpose",
    "progress_status": "LStatus", "send_date": "SendDate",
    # 순수수료 = 청구서 순수수료합계(기초수수료, 절사 전) — 2026-09-11, 입금현황과 같은 정의
    "appraisal_amount": "price",
    "base_fee": "[기초수수료]",
    "appraisal_cost": "[수수료합계] - [기초수수료] + ISNULL([절사금액], 0)",
    "sales_amount": "[수수료합계]", "vat_amount": "[부가가치세]",
    "gross_total": "[매출총액]",
    "travel_expense": "[여비]",
    "special_service_fee": "[특별용역비]",
}


def _view_order_sql(sort_by: str | None, sort_order: str) -> str:
    direction = "DESC" if sort_order == "desc" else "ASC"
    if sort_by in _VIEW_SORT_COLUMNS:
        tie_breaker = "" if sort_by == "doc_id" else ", DocID DESC"
        return f"{_VIEW_SORT_COLUMNS[sort_by]} {direction}{tie_breaker}"
    return "ReceiptDate DESC, DocID DESC"


# 빠른 경로에서 쓸 수 있는 정렬 열 — 전부 구동 테이블(APW_Master)의 컬럼이라 뷰의
# 정렬 열과 값이 같아, 빠른 경로와 뷰 경로가 같은 순서를 낸다.
_BASE_SORT_COLUMNS = {
    "doc_id": "DocID", "cust_doc_id": "CustDocID",
    "customer_name": "CustName", "receipt_date": "ReceiptDate",
    "appraisal_amount": "price",
}


_NUMERIC_KEYWORD = re.compile(r"^[\d\-\s]+$")
_KEYWORD_TEXT_COLUMNS = ("DocID", "CustDocid", "Address", "CustName", "Debtor", "OwnerName")
_KEYWORD_NUMBER_COLUMNS = ("DocID", "CustDocid")
# 번호형 통합검색: 감정서번호는 정확일치(인덱스 탐색), 의뢰문서번호는 부분일치.
# 의뢰문서번호엔 인덱스가 없어 어차피 훑지만, 조각으로 찾는 습관은 살린다.
_NUMBER_KEYWORD_SQL = (
    "(DocID = CAST(:keyword_exact AS varchar(50)) OR CustDocid LIKE :keyword)"
)


def keyword_is_number(keyword: str | None) -> bool:
    """숫자·하이픈만이면 감정서번호·의뢰번호 조각으로 본다 ('2607', '01-2607-3-').

    번호 검색은 두 열만 보고 전 기간을 뒤진다(구동 테이블에 DocID 인덱스가 있어 빠르다).
    글자 검색은 6열 LIKE 를 유지하되 기간 조건을 살린다 — 전 기간 15-테이블 뷰를
    6열 LIKE 로 훑으면 17초(2026-09-07 실측 '2607'), 올해로 좁히면 0.8초.
    """
    return bool(keyword) and bool(_NUMERIC_KEYWORD.match(keyword.strip()))


def _base_fast_plan(
    *, doc_id, cust_doc_id, address, customer_name, manager, charge,
    status, purpose, scope_person, keyword, bill_from, bill_to,
    price_from, price_to, date_from, date_to, office_code, sort_by, sort_order,
) -> "tuple[str, dict[str, Any], str] | None":
    """필터·정렬이 전부 APW_Master 컬럼이면 (where, params, order_sql) 을, 아니면 None.

    주소(계산 컬럼)·상태·목적·담당자·조사자·범위·통합검색·청구금액은 뷰의 조인·계산
    결과라 구동 테이블만으로는 재현할 수 없어 빠른 경로를 쓰지 않는다. 여기서 만드는
    where/order 는 _where_clause·_view_order_sql 과 같은 규칙이라 결과·순서가 동일하다.
    """
    if any([address, manager, charge, status, purpose, scope_person]):
        return None
    if keyword and not keyword_is_number(keyword):
        return None  # 글자형은 Address(뷰 계산 열)를 봐야 해서 뷰 경로
    if bill_from is not None or bill_to is not None:
        return None
    if sort_by is not None and sort_by not in _BASE_SORT_COLUMNS:
        return None
    conditions: list[str] = []
    params: dict[str, Any] = {}
    if office_code:
        conditions.append("Office = :office_code")
        params["office_code"] = office_code
    if doc_id:
        conditions.append("DocID = CAST(:doc_id AS varchar(50))")
        params["doc_id"] = doc_id.strip()
    for column, key, value in (
        ("CustDocID", "cust_doc_id", cust_doc_id),
        ("CustName", "customer_name", customer_name),
    ):
        if value:
            conditions.append(f"{column} LIKE :{key}")
            params[key] = f"%{value}%"
    if price_from is not None:
        conditions.append("price >= :price_from")
        params["price_from"] = price_from
    if price_to is not None:
        conditions.append("price <= :price_to")
        params["price_to"] = price_to
    if keyword:
        # 번호형 통합검색 — 뷰 경로(_where_clause)와 같은 조건
        conditions.append(_NUMBER_KEYWORD_SQL)
        params["keyword_exact"] = keyword.strip()
        params["keyword"] = f"%{keyword.strip()}%"
    # _where_clause 와 같은 규칙: 번호로 콕 집어 찾을 땐 접수일 조건을 빼 오래된 건도 나온다.
    pinpoint = bool(doc_id or cust_doc_id or keyword)
    if date_from and not pinpoint:
        conditions.append("ReceiptDate >= :date_from")
        params["date_from"] = date_from
    if date_to and not pinpoint:
        conditions.append("ReceiptDate < DATEADD(day, 1, :date_to)")
        params["date_to"] = date_to
    where = "WHERE " + " AND ".join(conditions) if conditions else ""
    direction = "DESC" if sort_order == "desc" else "ASC"
    if sort_by in _BASE_SORT_COLUMNS:
        tie_breaker = "" if sort_by == "doc_id" else ", DocID DESC"
        order_sql = f"{_BASE_SORT_COLUMNS[sort_by]} {direction}{tie_breaker}"
    else:
        order_sql = "ReceiptDate DESC, DocID DESC"
    return where, params, order_sql


def _serialize_mapping(value: Any) -> dict[str, Any]:
    return {key: _serialize(item) for key, item in dict(value).items()}


def _serialize(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def _voucher_to_dict(voucher: VoucherSync) -> dict[str, Any]:
    request = _json_object(voucher.request_body)
    lines = request.get("data") or request.get("lines") or []
    return {
        "id": voucher.id,
        "source_voucher_no": voucher.src_voucher_no,
        "management_no": voucher.management_no,
        "voucher_date": voucher.voucher_date.isoformat(),
        "debit_total": float(voucher.debit_total),
        "credit_total": float(voucher.credit_total),
        "status": voucher.status,
        "a10_voucher_no": voucher.a10_voucher_no,
        "error_message": voucher.error_msg,
        "lines": lines if isinstance(lines, list) else [],
        "created_at": voucher.created_at.isoformat() if voucher.created_at else None,
    }


def _json_object(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    except ValueError:
        return {}


def _fee_summary(row: Any) -> dict[str, Any]:
    """청구서상 수수료 내역.

    검증된 계산식(실데이터 대조):
      수수료합계 = 항목 합계 − 절사금액,  청구금액 = 수수료합계 + 부가가치세
    """
    def amount(column: str) -> float:
        return float(row[column] or 0)

    return {
        "customer_name": row["CustName"],
        "appraisal_amount": amount("price"),
        "base_fee": amount("기초수수료"),
        "travel_expense": amount("여비"),
        "survey_fee": amount("물건조사비"),
        "land_survey_fee": amount("토지조사비"),
        "document_fee": amount("공부발급비"),
        "other_expense": amount("기타실비"),
        "special_service_fee": amount("특별용역비"),
        "rounding_off": amount("절사금액"),
        "fee_total": amount("수수료합계"),
        "vat": amount("부가가치세"),
        "billed_amount": amount("청구금액"),
    }


def _source_view() -> str:
    database = _source_database()
    return f"[{database}].dbo.apw_masterex"


def _source_table() -> str:
    """뷰 apw_masterex 의 구동 테이블. 건수·페이지 키 선별을 여기서(가볍게) 한다."""
    database = _source_database()
    return f"[{database}].dbo.APW_Master"


def _source_database() -> str:
    database = get_settings().mssql_source_db
    if not database.replace("_", "").isalnum():
        raise RuntimeError("MSSQL_SOURCE_DB 이름이 올바르지 않습니다.")
    return database


def _doc_related_lines(
    voucher_lines: list[VoucherCache], doc_id: str
) -> list[VoucherCache]:
    """일괄 정산 전표(한 전표에 여러 감정서 정산)에서는 이 감정서 라인만 남긴다.

    다른 감정서의 관리번호가 달린 라인이 하나라도 있으면 일괄 전표로 보고,
    관리번호가 이 감정서이거나 적요에 이 감정서번호가 적힌 라인(입금·부가세 등)만
    보여준다. 단일 감정서 전표는 전 라인을 그대로 둔다.
    적요로만 찾은 전표(이 감정서 관리번호가 한 줄도 없음)는 경비 지출 묶음처럼 남의 줄이
    수백 개라 적요에 이 번호가 적힌 줄만 남긴다 (2026-09-10).
    """
    has_own_doc = any((line.management_no or "").strip() == doc_id for line in voucher_lines)
    if not has_own_doc:
        return [line for line in voucher_lines if doc_id in (line.remark or "")]
    has_other_doc = any(
        (line.management_no or "").strip() not in ("", doc_id) for line in voucher_lines
    )
    if not has_other_doc:
        return voucher_lines
    return [
        line
        for line in voucher_lines
        if (line.management_no or "").strip() == doc_id or doc_id in (line.remark or "")
    ]


def _allocated_cash_lines(
    voucher_lines: list[VoucherCache], doc_id: str
) -> dict[int, tuple[Decimal, int]]:
    """일괄 정산에서 대상 감정서 몫의 보통예금/본사 라인을 계산한다.

    Amaranth는 여러 감정서를 한 번에 정산할 때 보통예금 한 줄 뒤에 감정서별
    외상매출금 줄을 둔다. 보통예금 줄에는 관리번호가 없으므로 기존 필터에서는
    사라졌다. 원전표 금액 전체를 한 감정서에 표시하면 오해가 생기므로, 같은
    정산 묶음 안의 대상 감정서 상대계정 금액만 배분해 표시한다.
    """
    has_other_doc = any(
        (line.management_no or "").strip() not in ("", doc_id) for line in voucher_lines
    )
    if not has_other_doc:
        return {}

    ordered = sorted(voucher_lines, key=lambda line: str(line.line_no or "").zfill(10))
    cash_indexes = [
        index
        for index, line in enumerate(ordered)
        if line.account_code in ("1030000", "1410001")
    ]
    allocations: dict[int, tuple[Decimal, int]] = {}
    for position, cash_index in enumerate(cash_indexes):
        cash_line = ordered[cash_index]
        next_index = cash_indexes[position + 1] if position + 1 < len(cash_indexes) else len(ordered)
        group = ordered[cash_index + 1 : next_index]
        target_lines = [
            line
            for line in group
            if (line.management_no or "").strip() == doc_id
            or doc_id in (line.remark or "")
        ]
        target_debit = sum(
            (line.amount for line in target_lines if line.debit_credit == "3"),
            Decimal(0),
        )
        target_credit = sum(
            (line.amount for line in target_lines if line.debit_credit == "4"),
            Decimal(0),
        )
        allocated = (
            target_credit - target_debit
            if cash_line.debit_credit == "3"
            else target_debit - target_credit
        )
        if allocated > 0:
            group_doc_count = len(
                {
                    (line.management_no or "").strip()
                    for line in group
                    if (line.management_no or "").strip()
                }
            )
            allocations[id(cash_line)] = (
                min(cash_line.amount, allocated),
                group_doc_count,
            )
    return allocations


# 선수금·가수금은 돈을 먼저 받아 두었다가(대변) 나중에 매출로 대체(차변)하면 잔액이 0이
# 된다. 전표만 보면 '아직 남아 있는 선수금'과 생김새가 같아 매번 두 줄을 짝지어 계산해야
# 하므로, 잔액이 0인 계정은 상계 표시를 달아 화면에서 취소선으로 죽인다.
# 일부만 반제된 건은 잔액이 남아 있으니 표시하지 않는다.
_OFFSET_ACCOUNTS = {"2590000": "선수금", "2570000": "가수금"}


def _mark_offset_lines(items: list[dict[str, Any]]) -> None:
    """감정서 전체를 통틀어 잔액이 0이 된 선수금·가수금 줄에 상계 표시를 단다."""
    for account_code, label in _OFFSET_ACCOUNTS.items():
        account_lines = [
            line
            for item in items
            for line in item["lines"]
            if line["account_code"] == account_code
        ]
        credit = sum(
            line["amount"] for line in account_lines if str(line["debit_credit"]) == "4"
        )
        debit = sum(
            line["amount"] for line in account_lines if str(line["debit_credit"]) == "3"
        )
        if credit <= 0 or debit <= 0 or round(credit - debit, 2) != 0:
            continue
        note = f"{label} {credit:,.0f}원을 받았다가 전액 반제 — 잔액 0"
        for line in account_lines:
            line["offset"] = True
            line["offset_note"] = note


def remark_only_lines_query(doc_id: str, since: "date | None"):
    """관리번호가 빈 줄 중 적요가 감정서번호로 시작하는 줄 — since 이후 전표만."""
    conditions = [
        or_(VoucherCache.management_no.is_(None), VoucherCache.management_no == ""),
        VoucherCache.remark.like(f"{doc_id}%"),
    ]
    if since is not None:
        conditions.append(VoucherCache.voucher_date >= since)
    return select(VoucherCache).where(*conditions).order_by(
        VoucherCache.voucher_date.desc(), VoucherCache.voucher_no.desc(), VoucherCache.line_no,
    )


def _cached_vouchers(lines: list[VoucherCache], doc_id: str) -> list[dict[str, Any]]:
    groups: dict[tuple[date, str, str], list[VoucherCache]] = {}
    for line in lines:
        groups.setdefault(
            (line.voucher_date, line.voucher_no, line.division_code), []
        ).append(line)
    result = []
    for (voucher_date, voucher_no, _division), voucher_lines in groups.items():
        related_lines = _doc_related_lines(voucher_lines, doc_id)
        cash_allocations = _allocated_cash_lines(voucher_lines, doc_id)
        display_lines = [
            (line, cash_allocations.get(id(line), (None, 0))[0])
            for line in voucher_lines
            if line in related_lines or id(line) in cash_allocations
        ]
        if not display_lines:
            continue
        debit = sum(
            (allocated if allocated is not None else line.amount)
            for line, allocated in display_lines
            if line.debit_credit == "3"
        )
        credit = sum(
            (allocated if allocated is not None else line.amount)
            for line, allocated in display_lines
            if line.debit_credit == "4"
        )
        batch_doc_count = max(
            (doc_count for _, doc_count in cash_allocations.values()),
            default=0,
        )
        original_cash_amount = sum(
            (line.amount for line, allocated in display_lines if allocated is not None),
            Decimal(0),
        )
        allocated_cash_amount = sum(
            (allocated for _, allocated in display_lines if allocated is not None),
            Decimal(0),
        )
        result.append(
            {
                "source_voucher_no": f"{voucher_date:%Y%m%d}-{voucher_no}",
                "management_no": doc_id,
                "voucher_date": voucher_date.isoformat(),
                "debit_total": float(debit),
                "credit_total": float(credit),
                "status": "승인" if any(line.document_status == "1" for line, _ in display_lines) else "미승인",
                "a10_voucher_no": voucher_no,
                "batch_settlement": bool(cash_allocations),
                "batch_doc_count": batch_doc_count,
                "original_cash_amount": float(original_cash_amount),
                "allocated_cash_amount": float(allocated_cash_amount),
                "batch_note": (
                    f"여러 건 묶음 · {batch_doc_count}건 · "
                    f"이 감정서 {allocated_cash_amount:,.0f}원 / "
                    f"원전표 {original_cash_amount:,.0f}원"
                    if cash_allocations
                    else None
                ),
                "error_message": None,
                "lines": [
                    {
                        "line_no": line.line_no,
                        "debit_credit": line.debit_credit,
                        "account_code": line.account_code,
                        "account_name": line.account_name,
                        "partner_code": line.partner_code,
                        "partner_name": line.partner_name,
                        "amount": float(allocated if allocated is not None else line.amount),
                        "original_amount": float(line.amount) if allocated is not None else None,
                        "allocated": allocated is not None,
                        "remark": (
                            f"{line.remark or ''} · 일괄 정산 배분"
                            f" (원전표 {line.amount:,.0f}원)"
                            if allocated is not None
                            else line.remark
                        ),
                        "ctNb": line.management_no,
                    }
                    for line, allocated in display_lines
                ],
            }
        )
    return result
