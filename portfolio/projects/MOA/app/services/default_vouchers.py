"""감정서 발송 건의 기본 매출전표를 Amaranth 자동전표로 등록한다."""

from __future__ import annotations

import json
import re
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.amaranth.client import AmaranthClient
from app.config import get_settings
from app.models.voucher_cache import VoucherCache
from app.models.voucher_sync import VoucherSync
from app.services.bank_division import bank_division
from app.services.office_lookup import normalize_office_name as _normalize_office_name
from app.services.partners import PartnerService
from app.services.sales_division import sales_account, sales_division


# 작성자는 api11A10 입력 필드가 없어 지정 불가 — 아마란스에서 발행 처리한
# 담당자가 작성자로 찍힌다(재무팀 요청은 장세희 발행 처리로 충족, 2026-08-05).
_FIXED_DEPT_CD = "1010"  # 사용부서(관리항목 C1) — 본사-재무팀

# 부가세예수금 라인의 세무구분. 현금영수증으로 받은 건은 31(현금과세)다.
# 그동안 11로 고정해 보내서 재무팀이 아마란스에서 손으로 31로 고쳐 왔다
# (2026-08 MOA 생성분 6건 중 4건이 그렇게 정정돼 있었다).
TAX_FG_TAXABLE = "11"  # 과세매출 (세금계산서)
TAX_FG_CASH = "31"     # 현금과세 (현금영수증)
_CASH_RECEIPT_PARTNER_CODE = "0000028605"
_CASH_RECEIPT_PARTNER_NAME = "현금영수증(국세청)"


def has_cash_receipt(db: Session, doc_id: str) -> bool:
    """이 감정서로 현금영수증이 발행됐는지 (취소분 제외).

    발급 원장(a10_issued_taxinvoice) 하나로 본다 (2026-09-09) — MOA 직접 발급분·팝빌 동기화분·
    TAMS 이관분이 한 테이블에 있다. 현금취소는 양수 취소금액 행이라 빼서 순액이 남는지 본다.
    취소된 현금영수증을 세면 세무구분이 현금과세로 잘못 바뀐다.
    """
    if not doc_id:
        return False
    net = db.execute(
        text(
            "SELECT SUM(CASE WHEN doc_type = N'현금취소' THEN -ABS(ISNULL(total, 0)) ELSE ISNULL(total, 0) END) "
            "FROM dbo.a10_issued_taxinvoice "
            "WHERE doc_id = :doc AND is_test = 0 AND doc_type IN (N'현금영수증', N'현금취소')"
        ),
        {"doc": doc_id},
    ).scalar()
    found = net if (net or 0) > 0 else None
    return found is not None


def issued_tax_invoice_confirm(db: Session, doc_id: str) -> "str | None":
    """이 감정서로 발행된 전자세금계산서(팝빌 운영 발행분)의 국세청 승인번호.

    None = 발행 없음. 빈 문자열 = 발행됐으나 승인번호 미확정(전자 여부만 표시 가능).
    테스트 발행(is_test=1)은 무시한다 — 전표에 전자발행 표시가 붙으면 안 된다.
    세금계산서를 먼저 발급하고 전표를 나중에 만드는 경우만 자동 반영하고,
    반대 순서(전표 먼저)는 재무팀이 아마란스 화면에서 수기 처리한다(2026-08-11 결정).
    """
    if not doc_id:
        return None
    # 취소('세금취소') 행 포함 최신 행 기준 — 취소된 건은 미발행으로 본다.
    row = db.execute(
        text(
            "SELECT TOP 1 doc_type, nts_confirm FROM dbo.a10_issued_taxinvoice "
            "WHERE doc_id = :doc AND doc_type IN (N'세금계산서', N'세금취소') "
            "  AND is_test = 0 ORDER BY id DESC"
        ),
        {"doc": doc_id},
    ).first()
    if row is None or str(row[0]) == "세금취소":
        return None
    return str(row[1] or "").strip()


def issued_tax_invoice_account(db: Session, doc_id: str) -> "str | None":
    """발급 팝업에서 고른 매출 계정과목(a10_issued_taxinvoice.account_code) — 최신 운영 발행분.

    팝업에서 용역수수료를 골라도 전표는 늘 감정수수료로 나갔다(2026-08-27 사용자 발견) —
    고른 값은 원장에만 남고 전표 생성은 감정서 유형 규칙만 봤기 때문. 취소된 건·기록 없음은 None.
    """
    if not doc_id:
        return None
    row = db.execute(
        text(
            "SELECT TOP 1 doc_type, account_code FROM dbo.a10_issued_taxinvoice "
            "WHERE doc_id = :doc AND doc_type IN (N'세금계산서', N'세금취소') "
            "  AND is_test = 0 ORDER BY id DESC"
        ),
        {"doc": doc_id},
    ).first()
    if row is None or str(row[0]) == "세금취소":
        return None
    return str(row[1] or "").strip() or None


class DefaultVoucherError(ValueError):
    pass


class DefaultVoucherDuplicateError(DefaultVoucherError):
    pass


class DefaultVoucherService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.client = AmaranthClient(db)

    def exists(self, doc_id: str) -> bool:
        """이 감정서의 기본 매출전표가 이미 있는지 — create()의 중복 검사와 같은 기준.

        MOA 생성 기록(VoucherSync) 또는 전표 캐시의 외상매출금(1080000) 차변
        (재무팀 수기 청구 전표 포함). 실패 기록(status=F)은 재시도 가능이라 없음으로
        친다 — 조회일 뿐이니 create()처럼 지우지는 않는다.
        캐시는 매시간 동기화라 방금 만든 수기 전표는 못 잡을 수 있다.
        """
        previous = self.db.scalar(
            select(VoucherSync).where(
                VoucherSync.src_voucher_no == f"APPRAISAL-SEND-{doc_id}"
            )
        )
        if previous is not None and previous.status != "F":
            return True
        return self.db.scalar(
            select(VoucherCache.id).where(
                VoucherCache.management_no == doc_id,
                VoucherCache.account_code == "1080000",
                VoucherCache.debit_credit == "3",
            ).limit(1)
        ) is not None

    def partner_context(self, doc_id: str) -> dict[str, Any]:
        source_db = get_settings().mssql_source_db
        row = self.db.execute(
            text(
                f"""
                SELECT TOP 1 m.DocID, m.Office, m.CustID, m.CustName,
                       m.Production, m.SendDate,
                       c.SNO, c.Boss, c.ZipCode, c.Addr1, c.Addr2,
                       c.Uptae, c.Jongmok, c.Phone
                FROM [{source_db}].dbo.APW_Master m
                LEFT JOIN [{source_db}].dbo.APW_Customer c
                  ON c.CustID = m.CustID AND c.Office = m.Office
                WHERE m.DocID = :doc_id
                ORDER BY c.Active DESC, c.SEQ DESC
                """
            ),
            {"doc_id": doc_id},
        ).mappings().first()
        if not row:
            raise DefaultVoucherError("감정서를 찾을 수 없습니다.")
        company_code, division_code = self._organization(str(row["Office"] or ""))
        name = str(row["CustName"] or "").strip()
        production = str(row["Production"] or "").strip()
        search_name = _partner_search_name(production or name)
        matches = PartnerService(self.db, self.client).list(
            company_code, search=search_name, page=1, page_size=30
        )["items"]
        return {
            "doc_id": doc_id,
            "company_code": company_code,
            "division_code": division_code,
            # 전표 작성일을 기본값으로 사용한다. 화면의 날짜 입력란에서 사용자가 수정할 수 있다.
            "voucher_date": date.today().isoformat(),
            "partner_search_name": search_name,
            "apworks_partner": {
                "customer_id": row["CustID"],
                "name": name,
                "production": production,
                "business_no": _digits(row["SNO"]),
                "representative": row["Boss"],
                "postal_code": row["ZipCode"],
                "address1": row["Addr1"],
                "address2": row["Addr2"],
                "business_type": row["Uptae"],
                "business_item": row["Jongmok"],
                "telephone": row["Phone"],
            },
            "matches": matches,
        }

    def create(
        self,
        doc_id: str,
        *,
        partner_code: str,
        partner_name: str,
        voucher_date: date,
        requester_usr_seq: "int | None" = None,
        # 재생성(recreate) 전용 — sync 키를 바꿔 재시도 안전을 유지하고,
        # '이미 전표 있음' 검사를 건너뛴다(마이너스 전표로 상쇄한 직후라 있는 게 정상).
        sync_key: "str | None" = None,
        allow_existing: bool = False,
        # 청구액보다 적게 받고 끝난 건 — 원장 금액 대신 실제 증빙 금액으로 전표를
        # 세운다 (2026-09-07 01-2609-6-0487: 청구 55,000 · 입금·현금영수증 5,500).
        # 증빙이 청구액보다 **적을 때만** 열린다. 초과는 여전히 막는다.
        use_evidence_amount: bool = False,
    ) -> dict[str, Any]:
        if not partner_code.strip():
            raise DefaultVoucherError("Amaranth 거래처를 먼저 선택해 주세요.")
        appraisal = self.db.execute(
            text(
                f"""
                SELECT TOP 1 DocID, Office, SendDate, CustName,
                       [수수료합계] AS fee_total, [부가가치세] AS vat_amount,
                       [청구금액] AS billed_amount
                FROM [{get_settings().mssql_source_db}].dbo.apw_masterex
                WHERE DocID = :doc_id
                """
            ),
            {"doc_id": doc_id},
        ).mappings().first()
        if not appraisal:
            raise DefaultVoucherError("감정서를 찾을 수 없습니다.")
        # 발송 전에도 전표 생성 허용 (2026-08-14 사용자 지시 — 기존에는
        # SendDate 없으면 막았으나, 분할 청구 등 발송 전 청구 건이 있다)

        sync_key = sync_key or f"APPRAISAL-SEND-{doc_id}"
        previous = self.db.scalar(
            select(VoucherSync).where(VoucherSync.src_voucher_no == sync_key)
        )
        cached_billing = None if allow_existing else self.db.scalar(
            select(VoucherCache.id).where(
                VoucherCache.management_no == doc_id,
                VoucherCache.account_code == "1080000",
                VoucherCache.debit_credit == "3",
            ).limit(1)
        )
        if previous and previous.status == "F":
            self.db.delete(previous)
            self.db.commit()
            previous = None
        if previous or cached_billing:
            raise DefaultVoucherDuplicateError(
                "이미 기본 매출전표가 생성된 감정서입니다."
            )

        # 청구서 그대로 청구 — 공급가 = 수수료합계(항목 합계 − 절사금액).
        # 부가세는 재계산(×0.1)하지 않고 감정서의 부가가치세 값을 쓴다
        # (절사/반올림 방식이 혼재라 재계산하면 1원이 어긋나는 건이 있다).
        supply = _amount(appraisal["fee_total"])
        if supply <= 0:
            raise DefaultVoucherError("수수료합계 금액을 확인해 주세요.")
        vat = _amount(appraisal["vat_amount"])
        total = supply + vat
        # 청구금액이 수수료합계+부가세와 달라도 막지 않는다(2026-08-14 사용자
        # 지시) — 분할 청구 등에서 어긋나는 건이 있고, 전표는 어차피
        # 수수료합계(공급가)+부가세 기준으로 만든다.

        from app.services.popbill_tax import evidence_issue_totals

        evidence = evidence_issue_totals(self.db, doc_id)
        issued_total = int(evidence["combined"]["total"])
        if use_evidence_amount:
            # 계산서·현금영수증 금액만큼 전표를 세운다 (2026-09-08 사용자 결정 — 발급
            # 팝업의 '전표 생성'은 늘 이 경로). 원장보다 커도 증빙을 따른다: 초과 발행
            # 자체는 발급 단계(evidence_issue_error)에서 막히고, 외부(TAMS) 발행분이
            # 더 크면 원장이 틀린 것이라 전표는 실제 증빙과 맞아야 한다.
            if issued_total <= 0:
                raise DefaultVoucherError("발행된 증빙이 없습니다.")
            supply = _amount(evidence["combined"]["supply"])
            vat = _amount(evidence["combined"]["tax"])
            total = supply + vat
        elif issued_total > 0 and issued_total != int(total):
            raise DefaultVoucherError(
                "증빙 일부금액만 발행된 상태입니다. 청구액 전액 발행 후 전표를 생성하세요."
            )

        company_code, division_code = self._organization(str(appraisal["Office"] or ""))
        sync = VoucherSync(
            src_voucher_no=sync_key,
            management_no=doc_id,
            voucher_date=voucher_date,
            debit_total=total,
            credit_total=total,
            status="P",
        )
        try:
            self.db.add(sync)
            self.db.flush()
        except IntegrityError as exc:
            self.db.rollback()
            raise DefaultVoucherDuplicateError(
                "이미 기본전표 생성 요청이 처리되었습니다."
            ) from exc

        dept_cd = _FIXED_DEPT_CD
        menu_sq = 10000 + (int(sync.id) % 90000)
        # 세금계산서 승인번호는 세금계산서 몫의 부가세 라인에만 전자발행으로 싣는다.
        # 혼합 분할발행이면 아래에서 현금과세(31)와 과세매출(11)을 따로 만든다.
        tax_invoice_issno = issued_tax_invoice_confirm(self.db, doc_id)
        cash_part, tax_part = evidence["cash"], evidence["tax"]
        revenue_account = issued_tax_invoice_account(self.db, doc_id)
        if cash_part["total"] > 0 and tax_part["total"] > 0:
            # 혼합 분할발행은 증빙마다 외상·매출·부가세 줄을 나눠 세무구분과
            # 거래처를 보존한다. 합계가 원 청구액과 일치할 때만 전표를 만든다.
            cash_lines = _voucher_lines(
                doc_id=doc_id, customer_name=_CASH_RECEIPT_PARTNER_NAME,
                partner_name=_CASH_RECEIPT_PARTNER_NAME, company_code=company_code,
                division_code=division_code, voucher_date=voucher_date, menu_sq=menu_sq,
                base_fee=Decimal(str(cash_part["supply"])),
                vat=Decimal(str(cash_part["tax"])), total=Decimal(str(cash_part["total"])),
                partner_code=_CASH_RECEIPT_PARTNER_CODE, dept_cd=dept_cd,
                cash_receipt=True, tax_invoice_issno=None,
                revenue_account=revenue_account,
            )
            tax_lines = _voucher_lines(
                doc_id=doc_id, customer_name=str(appraisal["CustName"] or ""),
                partner_name=partner_name, company_code=company_code,
                division_code=division_code, voucher_date=voucher_date, menu_sq=menu_sq,
                base_fee=Decimal(str(tax_part["supply"])),
                vat=Decimal(str(tax_part["tax"])), total=Decimal(str(tax_part["total"])),
                partner_code=partner_code.strip(), dept_cd=dept_cd,
                cash_receipt=False, tax_invoice_issno=tax_invoice_issno,
                revenue_account=revenue_account,
            )
            lines = [
                {**line, "menuLnSq": index,
                 "isuDoc": f"분할매출 {doc_id} 현금영수증+세금계산서"[:100]}
                for index, line in enumerate([*cash_lines, *tax_lines], start=1)
            ]
        else:
            lines = _voucher_lines(
                doc_id=doc_id,
                customer_name=str(appraisal["CustName"] or ""),
                partner_name=partner_name,
                company_code=company_code,
                division_code=division_code,
                voucher_date=voucher_date,
                menu_sq=menu_sq,
                base_fee=supply,
                vat=vat,
                total=total,
                partner_code=partner_code.strip(),
                dept_cd=dept_cd,
                cash_receipt=(
                    tax_invoice_issno is None and has_cash_receipt(self.db, doc_id)
                ),
                tax_invoice_issno=tax_invoice_issno,
                revenue_account=revenue_account,
            )
        body = {"coCd": company_code, "data": lines}
        sync.request_body = json.dumps(body, ensure_ascii=False, default=str)
        try:
            response = self.client.post("/apiproxy/api11A10", json_body=body)
            sync.response_body = json.dumps(response, ensure_ascii=False, default=str)
            sync.status = "S"
            result_rows = response.get("resultData") or []
            if isinstance(result_rows, dict):
                result_rows = [result_rows]
            if result_rows:
                sync.a10_voucher_no = str(
                    result_rows[0].get("isuSq")
                    or result_rows[0].get("menuSq")
                    or menu_sq
                )
            voucher_no = sync.a10_voucher_no or str(menu_sq)
            for line in lines:
                account_names = {
                    "1080000": "외상매출금",
                    "4010001": "감정수수료", "4010002": "기타수수료", "4010003": "공시지가등수익",
                    "4010004": "용역수수료", "4010005": "임대수수료", "9090000": "주차장수익",
                    "8120000": "여비교통비",
                    "2550000": "부가세예수금",
                }
                self.db.add(
                    VoucherCache(
                        voucher_date=voucher_date,
                        voucher_no=voucher_no,
                        line_no=str(line["menuLnSq"]),
                        division_code=division_code,
                        management_no=line.get("maNb"),
                        debit_credit=line["drcrFg"],
                        account_code=line["acctCd"],
                        account_name=account_names.get(line["acctCd"]),
                        # 거래처를 비우면 당일 세금계산서 발급 팝업이 공급받는자를
                        # 못 찾는다 (동기화가 채우기 전까지 tr_cd 조회 불가).
                        partner_code=line.get("trCd"),
                        partner_name=(
                            _CASH_RECEIPT_PARTNER_NAME
                            if line.get("trCd") == _CASH_RECEIPT_PARTNER_CODE
                            else partner_name
                        ),
                        amount=Decimal(str(line["acctAm"])),
                        remark=line.get("rmkDc"),
                        document_status="0",
                        raw_json=json.dumps(line, ensure_ascii=False, default=str),
                    )
                )
            self.db.commit()
        except Exception as exc:
            sync.status = "F"
            sync.error_msg = str(exc)
            self.db.commit()
            raise DefaultVoucherError(f"Amaranth 전표 등록에 실패했습니다: {exc}") from exc

        return {
            "doc_id": doc_id,
            "voucher_date": voucher_date.isoformat(),
            "voucher_no": sync.a10_voucher_no or str(menu_sq),
            "fee_total": float(supply),
            "vat": float(vat),
            "total": float(total),
            "partner_code": partner_code.strip(),
            "partner_name": partner_name,
        }

    def recreate_context(self, doc_id: str) -> dict[str, Any]:
        """'전표 재생성' 가능 여부와 취소 전표 재료 (2026-09-02).

        대상: 증빙(현금영수증·세금계산서)을 취소하고 세금계산서를 다시 발행했는데
        옛 증빙 때 만든 전표가 살아 있는 건 (실측 01-2608-3-2700).
        조건 — ① 살아 있는 청구(외상 순액 > 0) ② 취소 증빙 이력(현금취소·세금취소)
        ③ 살아 있는 세금계산서(취소로 상쇄되지 않은 순액 > 0) ④ 아직 재생성 안 함.
        """
        rows = self.db.execute(
            text(
                "SELECT account_code, debit_credit, "
                "RTRIM(ISNULL(partner_code, '')) AS partner_code, "
                "RTRIM(ISNULL(partner_name, '')) AS partner_name, amount "
                "FROM dbo.a10_voucher_cache "
                "WHERE management_no = CAST(:doc AS varchar(500)) "
                "AND (account_code = '1080000' OR account_code LIKE '401%' OR account_code = '9090000') "
                "ORDER BY voucher_date, voucher_no, line_no"
            ),
            {"doc": doc_id},
        ).mappings().all()
        total = Decimal("0")
        fee_by_account: "dict[str, Decimal]" = {}
        partner_code = partner_name = ""
        for row in rows:
            amount = Decimal(str(row["amount"] or 0))
            if row["account_code"] == "1080000":
                total += amount if str(row["debit_credit"]) == "3" else -amount
                if str(row["debit_credit"]) == "3" and row["partner_code"]:
                    partner_code, partner_name = row["partner_code"], row["partner_name"]
            else:
                net = amount if str(row["debit_credit"]) == "4" else -amount
                fee_by_account[row["account_code"]] = (
                    fee_by_account.get(row["account_code"], Decimal("0")) + net
                )
        fee_by_account = {a: v for a, v in fee_by_account.items() if v}
        fee = sum(fee_by_account.values(), Decimal("0"))

        proof = self.db.execute(
            text(
                "SELECT SUM(CASE WHEN doc_type IN (N'현금취소', N'세금취소') THEN 1 ELSE 0 END) AS cancels, "
                "SUM(CASE WHEN doc_type = N'현금취소' THEN 1 ELSE 0 END) AS cash_cancels, "
                "SUM(CASE WHEN doc_type IN (N'세금계산서', N'세금취소') THEN CAST(total AS float) ELSE 0 END) AS tax_net "
                "FROM dbo.a10_issued_taxinvoice WHERE doc_id = :doc AND is_test = 0 AND is_pool = 0"
            ),
            {"doc": doc_id},
        ).mappings().one()
        resent = self.db.scalar(
            select(VoucherSync).where(
                VoucherSync.src_voucher_no == f"APPRAISAL-RESEND-{doc_id}",
                VoucherSync.status != "F",
            )
        )
        # 취소 전표가 이미 나갔으면 외상 순액이 0이 된다 — 남은 일(새 전표)만
        # 이어가면 되므로 금액 조건은 건너뛴다 (2단계 실패 후 재시도 경로).
        cancel_done = self.db.scalar(
            select(VoucherSync).where(
                VoucherSync.src_voucher_no.like(f"APPRAISAL-CANCEL-{doc_id}%"),
                VoucherSync.status == "S",
            )
        ) is not None
        reason = ""
        if resent is not None:
            reason = "이미 재생성된 감정서입니다."
        elif not int(proof["cancels"] or 0):
            reason = "취소한 증빙이 없습니다 — 일반 전표 생성을 쓰세요."
        elif float(proof["tax_net"] or 0) <= 0:
            reason = "살아 있는 세금계산서가 없습니다."
        elif not cancel_done and (total <= 0 or fee <= 0):
            reason = "상쇄할 기존 전표가 없습니다."
        return {
            "possible": not reason, "reason": reason, "cancel_done": cancel_done,
            "total": total, "vat": total - fee, "fee_by_account": fee_by_account,
            "partner_code": partner_code, "partner_name": partner_name,
            # 취소 전표 적요용 — 현금영수증을 취소한 건이면 그 문구를 쓴다
            "cancel_kind": "현금영수증" if int(proof["cash_cancels"] or 0) else "세금계산서",
        }

    def create_cash_cancel_voucher(
        self,
        doc_id: str,
        *,
        cancel_mgt_key: str,
        voucher_date: date,
    ) -> dict[str, Any]:
        """현금영수증 취소 직후 기존 매출을 상쇄하는 취소 전표를 만든다.

        본사 기존 취소 전표 형식 그대로 세 줄을 모두 대변에 기록한다:
        외상매출금 +합계 / 매출 -공급가 / 부가세예수금 -부가세.
        팝빌 취소 문서관리번호를 sync 키에 넣어 같은 취소 응답의 중복 전송을 막는다.
        """
        sync_key = f"APPRAISAL-CANCEL-{cancel_mgt_key}"
        if len(sync_key) > 50:
            raise DefaultVoucherError("취소 전표 동기화 키가 너무 깁니다.")

        previous = self.db.scalar(
            select(VoucherSync).where(VoucherSync.src_voucher_no == sync_key)
        )
        if previous is not None and previous.status == "S":
            return {
                "doc_id": doc_id,
                "voucher_date": previous.voucher_date.isoformat(),
                "voucher_no": previous.a10_voucher_no,
                "cancel_voucher_no": previous.a10_voucher_no,
                "already_created": True,
            }
        if previous is not None and previous.status == "P":
            raise DefaultVoucherDuplicateError("취소 전표를 생성 중입니다.")
        if previous is not None:
            self.db.delete(previous)
            self.db.commit()

        ctx = self.recreate_context(doc_id)
        if ctx["total"] <= 0 or not ctx["fee_by_account"]:
            raise DefaultVoucherError("상쇄할 기존 매출 전표를 찾지 못했습니다.")
        if not ctx["partner_code"]:
            raise DefaultVoucherError("기존 매출 전표의 거래처를 찾지 못했습니다.")

        source_db = get_settings().mssql_source_db
        office = self.db.execute(
            text(
                f"SELECT TOP 1 Office FROM [{source_db}].dbo.apw_masterex "
                "WHERE DocID = :doc_id"
            ),
            {"doc_id": doc_id},
        ).scalar()
        if office is None:
            raise DefaultVoucherError("감정서를 찾을 수 없습니다.")
        company_code, division_code = self._organization(str(office or ""))

        sync = VoucherSync(
            src_voucher_no=sync_key,
            management_no=doc_id,
            voucher_date=voucher_date,
            debit_total=Decimal("0"),
            credit_total=Decimal("0"),
            status="P",
        )
        try:
            self.db.add(sync)
            self.db.flush()
        except IntegrityError as exc:
            self.db.rollback()
            raise DefaultVoucherDuplicateError("이미 생성된 취소 전표입니다.") from exc

        menu_sq = 10000 + (int(sync.id) % 90000)
        lines = _cancel_voucher_lines(
            doc_id=doc_id,
            division_code=division_code,
            voucher_date=voucher_date,
            menu_sq=menu_sq,
            fee_by_account=ctx["fee_by_account"],
            vat=ctx["vat"],
            total=ctx["total"],
            partner_code=ctx["partner_code"],
            partner_name=ctx["partner_name"],
            cancel_kind="현금영수증",
            dept_cd=_FIXED_DEPT_CD,
        )
        body = {"coCd": company_code, "data": lines}
        sync.request_body = json.dumps(body, ensure_ascii=False, default=str)
        account_names = {
            "1080000": "외상매출금",
            "4010001": "감정수수료", "4010002": "기타수수료",
            "4010003": "공시지가등수익", "4010004": "용역수수료",
            "4010005": "임대수수료", "9090000": "주차장수익", "2550000": "부가세예수금",
        }
        try:
            response = self.client.post("/apiproxy/api11A10", json_body=body)
            sync.response_body = json.dumps(response, ensure_ascii=False, default=str)
            sync.status = "S"
            result_rows = response.get("resultData") or []
            if isinstance(result_rows, dict):
                result_rows = [result_rows]
            if result_rows:
                sync.a10_voucher_no = str(
                    result_rows[0].get("isuSq")
                    or result_rows[0].get("menuSq")
                    or menu_sq
                )
            voucher_no = sync.a10_voucher_no or str(menu_sq)
            for line in lines:
                self.db.add(
                    VoucherCache(
                        voucher_date=voucher_date,
                        voucher_no=voucher_no,
                        line_no=str(line["menuLnSq"]),
                        division_code=division_code,
                        management_no=line.get("maNb"),
                        debit_credit=line["drcrFg"],
                        account_code=line["acctCd"],
                        account_name=account_names.get(line["acctCd"]),
                        partner_code=line.get("trCd"),
                        partner_name=ctx["partner_name"],
                        amount=Decimal(str(line["acctAm"])),
                        remark=line.get("rmkDc"),
                        document_status="0",
                        raw_json=json.dumps(line, ensure_ascii=False, default=str),
                    )
                )
            self.db.commit()
        except Exception as exc:
            sync.status = "F"
            sync.error_msg = str(exc)
            self.db.commit()
            raise DefaultVoucherError(f"Amaranth 취소 전표 등록에 실패했습니다: {exc}") from exc

        return {
            "doc_id": doc_id,
            "voucher_date": voucher_date.isoformat(),
            "voucher_no": sync.a10_voucher_no or str(menu_sq),
            "cancel_voucher_no": sync.a10_voucher_no or str(menu_sq),
            "fee_total": float(sum(ctx["fee_by_account"].values(), Decimal("0"))),
            "vat": float(ctx["vat"]),
            "total": float(ctx["total"]),
        }

    def recreate(
        self,
        doc_id: str,
        *,
        partner_code: str,
        partner_name: str,
        voucher_date: date,
        requester_usr_seq: "int | None" = None,
    ) -> dict[str, Any]:
        """증빙 취소 후 재발행 건 — 마이너스 전표 1장 + 새 매출 전표 1장 (2026-09-02).

        1단계(취소)와 2단계(새 전표)는 sync 키가 달라 각각 재시도 안전하다:
        2단계에서 실패하면 다시 눌렀을 때 1단계는 건너뛰고 2단계만 다시 간다.
        """
        ctx = self.recreate_context(doc_id)
        if not ctx["possible"]:
            raise DefaultVoucherError(ctx["reason"] or "재생성할 수 없는 감정서입니다.")

        # 취소 전표가 아직 안 나간 신규 건 — 취소 줄과 새 매출 줄을 한 전표로
        # 올린다 (2026-09-03 재무팀 요청: 10122 취소 전표에 매출 줄을 이어 붙인다).
        # 예전처럼 취소만 따로 나간 건(cancel_done)은 새 매출 전표만 이어 만든다.
        if not ctx["cancel_done"]:
            for key in (f"APPRAISAL-CANCEL-{doc_id}", f"APPRAISAL-RESEND-{doc_id}"):
                stale = self.db.scalar(
                    select(VoucherSync).where(
                        VoucherSync.src_voucher_no == key, VoucherSync.status == "F"
                    )
                )
                if stale is not None:
                    self.db.delete(stale)
            self.db.commit()
            return self._post_combined_voucher(
                doc_id, voucher_date, ctx,
                partner_code=partner_code, partner_name=partner_name,
            )

        cancel_key = f"APPRAISAL-CANCEL-{doc_id}"
        previous = self.db.scalar(
            select(VoucherSync).where(VoucherSync.src_voucher_no == cancel_key)
        )
        cancel_no = previous.a10_voucher_no if previous is not None else None

        result = self.create(
            doc_id,
            partner_code=partner_code, partner_name=partner_name,
            voucher_date=voucher_date, requester_usr_seq=requester_usr_seq,
            sync_key=f"APPRAISAL-RESEND-{doc_id}", allow_existing=True,
        )
        return {**result, "cancel_voucher_no": cancel_no}

    def _post_combined_voucher(
        self,
        doc_id: str,
        voucher_date: date,
        ctx: "dict[str, Any]",
        *,
        partner_code: str,
        partner_name: str,
    ) -> dict[str, Any]:
        """취소 줄 + 새 매출 줄을 한 전표로 등록한다 (2026-09-03 재무팀 요청).

        현금영수증(또는 세금계산서) 취소와 세금계산서 재발행을 두 전표로 나누지
        않고, 재무팀이 쓰던 취소 전표 한 장에 새 매출 줄을 이어 붙인다. 전표품의
        (isuDoc)는 취소 전표 그대로, 적요(rmkDc)는 줄마다 원래대로 둔다. 차변=대변
        (취소 외상 대변 +합계 ↔ 새 매출 외상 차변 +합계가 상쇄)으로 스스로 맞는다.
        """
        if not partner_code.strip():
            raise DefaultVoucherError("Amaranth 거래처를 먼저 선택해 주세요.")
        source_db = get_settings().mssql_source_db
        appraisal = self.db.execute(
            text(
                f"""
                SELECT TOP 1 Office, CustName,
                       [수수료합계] AS fee_total, [부가가치세] AS vat_amount
                FROM [{source_db}].dbo.apw_masterex WHERE DocID = :doc_id
                """
            ),
            {"doc_id": doc_id},
        ).mappings().first()
        if not appraisal:
            raise DefaultVoucherError("감정서를 찾을 수 없습니다.")
        supply = _amount(appraisal["fee_total"])
        if supply <= 0:
            raise DefaultVoucherError("수수료합계 금액을 확인해 주세요.")
        vat = _amount(appraisal["vat_amount"])
        total = supply + vat

        # 재생성도 최초 생성과 같은 잣대로 증빙을 본다. 안 그러면 현금영수증 절반 +
        # 세금계산서 절반인 건이 청구액 전액 세금계산서로 나갔다 (2026-09-07,
        # 01-2609-3-2763: 현금과세 580,800 이 통째로 과세매출로 잡혔다).
        from app.services.popbill_tax import evidence_issue_totals

        evidence = evidence_issue_totals(self.db, doc_id)
        if evidence["combined"]["total"] > 0:
            # 재생성도 증빙 금액만큼 (2026-09-08) — 원장과 다르면 원장이 아니라 증빙을 따른다
            supply = _amount(evidence["combined"]["supply"])
            vat = _amount(evidence["combined"]["tax"])
            total = supply + vat

        company_code, division_code = self._organization(str(appraisal["Office"] or ""))
        sync = VoucherSync(
            src_voucher_no=f"APPRAISAL-RESEND-{doc_id}",
            management_no=doc_id,
            voucher_date=voucher_date,
            debit_total=total,
            credit_total=total,
            status="P",
        )
        try:
            self.db.add(sync)
            self.db.flush()
        except IntegrityError as exc:
            self.db.rollback()
            raise DefaultVoucherDuplicateError("이미 재생성된 감정서입니다.") from exc
        menu_sq = 10000 + (int(sync.id) % 90000)

        cancel_lines = _cancel_voucher_lines(
            doc_id=doc_id,
            division_code=division_code,
            voucher_date=voucher_date,
            menu_sq=menu_sq,
            fee_by_account=ctx["fee_by_account"],
            vat=ctx["vat"],
            total=ctx["total"],
            partner_code=ctx["partner_code"],
            partner_name=ctx["partner_name"],
            cancel_kind=ctx.get("cancel_kind"),
            dept_cd=_FIXED_DEPT_CD,
        )
        tax_invoice_issno = issued_tax_invoice_confirm(self.db, doc_id)
        revenue_account = issued_tax_invoice_account(self.db, doc_id)
        cash_part, tax_part = evidence["cash"], evidence["tax"]
        common = dict(
            doc_id=doc_id, company_code=company_code, division_code=division_code,
            voucher_date=voucher_date, menu_sq=menu_sq, dept_cd=_FIXED_DEPT_CD,
            revenue_account=revenue_account,
        )
        if cash_part["total"] > 0 and tax_part["total"] > 0:
            # 혼합 분할발행 — 새 매출 줄도 증빙마다 외상·매출·부가세를 나눠
            # 세무구분(현금과세 31 / 과세매출 11)과 거래처를 보존한다.
            sales_lines = [
                *_voucher_lines(
                    customer_name=_CASH_RECEIPT_PARTNER_NAME,
                    partner_name=_CASH_RECEIPT_PARTNER_NAME,
                    base_fee=Decimal(str(cash_part["supply"])),
                    vat=Decimal(str(cash_part["tax"])),
                    total=Decimal(str(cash_part["total"])),
                    partner_code=_CASH_RECEIPT_PARTNER_CODE,
                    cash_receipt=True, tax_invoice_issno=None, **common,
                ),
                *_voucher_lines(
                    customer_name=str(appraisal["CustName"] or ""),
                    partner_name=partner_name,
                    base_fee=Decimal(str(tax_part["supply"])),
                    vat=Decimal(str(tax_part["tax"])),
                    total=Decimal(str(tax_part["total"])),
                    partner_code=partner_code.strip(),
                    cash_receipt=False, tax_invoice_issno=tax_invoice_issno, **common,
                ),
            ]
        else:
            sales_lines = _voucher_lines(
                customer_name=str(appraisal["CustName"] or ""),
                partner_name=partner_name,
                base_fee=supply,
                vat=vat,
                total=total,
                partner_code=partner_code.strip(),
                cash_receipt=(
                    tax_invoice_issno is None and has_cash_receipt(self.db, doc_id)
                ),
                tax_invoice_issno=tax_invoice_issno,
                **common,
            )
        lines = _merge_voucher_lines(cancel_lines, sales_lines)
        body = {"coCd": company_code, "data": lines}
        sync.request_body = json.dumps(body, ensure_ascii=False, default=str)
        # 취소 줄은 원 증빙 거래처, 매출 줄은 새 세금계산서 거래처 — 줄마다 이름을 맞춘다
        name_by_code = {
            str(ctx["partner_code"]): ctx["partner_name"],
            partner_code.strip(): partner_name,
        }
        account_names = {
            "1080000": "외상매출금",
            "4010001": "감정수수료", "4010002": "기타수수료", "4010003": "공시지가등수익",
            "4010004": "용역수수료", "4010005": "임대수수료", "9090000": "주차장수익",
            "8120000": "여비교통비",
            "2550000": "부가세예수금",
        }
        try:
            response = self.client.post("/apiproxy/api11A10", json_body=body)
            sync.response_body = json.dumps(response, ensure_ascii=False, default=str)
            sync.status = "S"
            result_rows = response.get("resultData") or []
            if isinstance(result_rows, dict):
                result_rows = [result_rows]
            if result_rows:
                sync.a10_voucher_no = str(
                    result_rows[0].get("isuSq")
                    or result_rows[0].get("menuSq")
                    or menu_sq
                )
            voucher_no = sync.a10_voucher_no or str(menu_sq)
            for line in lines:
                tr = line.get("trCd")
                self.db.add(
                    VoucherCache(
                        voucher_date=voucher_date,
                        voucher_no=voucher_no,
                        line_no=str(line["menuLnSq"]),
                        division_code=division_code,
                        management_no=line.get("maNb"),
                        debit_credit=line["drcrFg"],
                        account_code=line["acctCd"],
                        account_name=account_names.get(line["acctCd"]),
                        partner_code=tr,
                        partner_name=name_by_code.get(str(tr or ""), partner_name),
                        amount=Decimal(str(line["acctAm"])),
                        remark=line.get("rmkDc"),
                        document_status="0",
                        raw_json=json.dumps(line, ensure_ascii=False, default=str),
                    )
                )
            self.db.commit()
        except Exception as exc:
            sync.status = "F"
            sync.error_msg = str(exc)
            self.db.commit()
            raise DefaultVoucherError(f"Amaranth 전표 등록에 실패했습니다: {exc}") from exc

        return {
            "doc_id": doc_id,
            "voucher_date": voucher_date.isoformat(),
            "voucher_no": sync.a10_voucher_no or str(menu_sq),
            "cancel_voucher_no": sync.a10_voucher_no or str(menu_sq),
            "fee_total": float(supply),
            "vat": float(vat),
            "total": float(total),
            "partner_code": partner_code.strip(),
            "partner_name": partner_name,
            "combined": True,
        }

    def _organization(self, office_code: str) -> tuple[str, str]:
        companies = _rows(self.client.post("/apiproxy/api16S08", json_body={}))
        if not companies:
            raise DefaultVoucherError("Amaranth 회사코드를 찾지 못했습니다.")
        company_code = str(companies[0].get("coCd") or companies[0].get("outCoCd") or "")
        divisions = _rows(
            self.client.post("/apiproxy/api16S09", json_body={"coCd": company_code})
        )
        office_name = self.db.execute(
            text(
                f"SELECT TOP 1 RTRIM(Name) FROM [{get_settings().mssql_source_db}].dbo.apw_office "
                "WHERE OfficeID = :office_code"
            ),
            {"office_code": office_code},
        ).scalar()
        normalized = _normalize_office_name(office_name)
        division = next(
            (
                item for item in divisions
                if _normalize_office_name(item.get("divNm") or item.get("outDivNm"))
                == normalized
            ),
            None,
        )
        if not division:
            raise DefaultVoucherError("해당 본·지사의 Amaranth 회계단위를 찾지 못했습니다.")
        division_code = str(division.get("divCd") or division.get("outDivCd") or "")
        return company_code, division_code


def _cancel_voucher_lines(**values: Any) -> "list[dict[str, Any]]":
    """증빙 취소 마이너스 전표 — 본사 재무팀 관행 그대로 (2026-09-02 실측).

    본사 취소 전표(8/13 00003·8/27 00001·8/28 00004·8/11 00033)는 **전부 대변**이다:
        대 외상매출금   +합계     (양수)
        대 감정수수료   −공급가
        대 부가세예수금 −부가세
    대변 합이 0으로 스스로 맞는 전표다. 지사는 차−/대− 방식도 쓰지만 이 기능은
    본사 발급 건용이라 본사 관행을 따른다. 적요는 5/27 본사 실전(00046) 문구
    '현금영수증 취소→계산서 발행 {번호}' 계열. 거래처는 원 전표 거래처, 관리번호
    (maNb)는 외상·매출 줄에만 — 부가세 줄은 원 전표와 같게 달지 않는다.
    """
    common = {
        "inDivCd": values["division_code"],
        "menuDt": values["voucher_date"].strftime("%Y%m%d"),
        "menuSq": values["menu_sq"],
        "docuTy": "3",
        "isuDoc": f"매출취소 {values['doc_id']} {values['partner_name']}".strip()[:100],
    }
    if values.get("dept_cd"):
        common["ctDept"] = values["dept_cd"]
    kind = values.get("cancel_kind") or "현금영수증"
    remark = (
        f"현금영수증 취소→계산서 발행 {values['doc_id']}" if kind == "현금영수증"
        else f"세금계산서 취소→재발행 {values['doc_id']}"
    )
    raw: "list[tuple[Decimal, str, bool]]" = [
        (values["total"], "1080000", True),                       # 대변 +합계
    ]
    raw.extend((-fee, account, True) for account, fee in values["fee_by_account"].items())
    raw.append((-values["vat"], "2550000", False))
    fee_total = sum(values["fee_by_account"].values(), Decimal("0"))
    lines = []
    for amount, account, tag_doc in raw:
        if amount == 0:
            continue
        line = {
            **common,
            "menuLnSq": len(lines) + 1,
            "drcrFg": "4",
            "acctCd": account,
            "acctAm": float(amount),
            "rmkDc": remark[:100],
            "trCd": values["partner_code"],
        }
        if tag_doc:
            line["maNb"] = values["doc_id"]
        if account not in {"1080000", "2550000"}:
            # 매출 계정 401xxxx는 Amaranth 필수 관리항목(M1/M2)이 필요하다.
            division = sales_division(values["doc_id"])
            if division:
                line["userlTy2"] = division
            line["usermTy1"] = bank_division(values.get("partner_name") or "")
        if account == "2550000":
            # 부가세 계정은 부가세사업장·신고기준일·세무구분·공급가액이 필수다
            # (api11A10 실측 거부: "부가세계정입니다.…입력하여 업로드"). 취소는
            # 원 증빙의 세무구분(현금영수증=31, 세금계산서=11)으로 음수 공급가를 싣는다
            # — 그래야 부가세 신고서에서 원 증빙 매출이 음수로 상쇄된다.
            line.update(
                {
                    "vatDivCd": values["division_code"],
                    "issDt": values["voucher_date"].strftime("%Y%m%d"),
                    "taxFg": TAX_FG_CASH if kind == "현금영수증" else TAX_FG_TAXABLE,
                    "supAm": float(-fee_total),
                }
            )
        lines.append(line)
    return lines


def _merge_voucher_lines(
    cancel_lines: "list[dict[str, Any]]", sales_lines: "list[dict[str, Any]]"
) -> "list[dict[str, Any]]":
    """취소 줄과 새 매출 줄을 한 전표로 합친다 (2026-09-03 재무팀 요청).

    재무팀은 취소 전표(10122) 한 장에 새 매출 줄을 이어 붙인다. 전표품의(isuDoc)는
    취소 전표 것으로 통일하고, 줄번호(menuLnSq)는 1..N 이어서 매긴다. 적요(rmkDc)는
    줄마다 원래대로 둔다(취소·매출 구분이 남는다). 원본은 건드리지 않는다.
    """
    source = [*cancel_lines, *sales_lines]
    header = source[0]["isuDoc"] if source else ""
    merged = []
    for index, line in enumerate(source, start=1):
        merged.append({**line, "menuLnSq": index, "isuDoc": header})
    return merged


def _voucher_lines(**values: Any) -> list[dict[str, Any]]:
    # 품의내역·은행구분의 거래처는 전표에 고른 거래처(partner_name) — 원장(APWorks)
    # 거래처와 다른 건이 있다 (2026-09-02, 01-2608-4-0298: 원장은 주택도시보증공사,
    # 전표·계산서는 씨엔에스파크). 이름이 안 넘어오면 원장 거래처로 때운다.
    partner_label = str(values.get("partner_name") or "").strip() or values["customer_name"]
    common = {
        "inDivCd": values["division_code"],
        "menuDt": values["voucher_date"].strftime("%Y%m%d"),
        "menuSq": values["menu_sq"],
        "docuTy": "3",
        # 품의내역 — 재무팀 관행 "매출 {감정서번호} {거래처명}" (2026-08-06)
        "isuDoc": f"매출 {values['doc_id']} {partner_label}".strip()[:100],
    }
    if values.get("dept_cd"):
        common["ctDept"] = values["dept_cd"]
    # 적요는 재무팀 수기 전표 관행 그대로 (2026-08-06, 7월 본사 최빈값 실측):
    # 외상매출금 "외상매출 발생" / 매출 "일반 매출" / 부가세 "감정평가수수료 {번호}"
    # 매출 계정은 발급 팝업에서 고른 것(revenue_account)이 우선, 없으면 유형별 —
    # 약식(-6-)은 기타수수료 4010002 (재무팀 지침)
    revenue_account = values.get("revenue_account") or sales_account(values["doc_id"])
    raw = [
        ("3", "1080000", values["total"], values["doc_id"], "외상매출 발생"),
        ("4", revenue_account, values["base_fee"], values["doc_id"], "일반 매출"),
        ("4", "2550000", values["vat"], "", f"감정평가수수료 {values['doc_id']}"),
    ]
    lines = []
    for drcr, account, amount, management_no, remark in raw:
        if amount <= 0:
            continue
        line = {
            **common,
            "menuLnSq": len(lines) + 1,
            "drcrFg": drcr,
            "acctCd": account,
            "acctAm": float(amount),
            "rmkDc": remark[:100],
            "trCd": values["partner_code"],
        }
        # 관리번호는 maNb(계정과목 관리항목 EA). ctNb는 부가세계정의
        # 수출신고번호/현금영수증 승인번호 필드라 관리번호로 저장되지 않는다.
        if management_no:
            line["maNb"] = management_no
        if account == revenue_account:
            # 매출 라인에만 관리항목 L2(매출구분)·M1(은행구분) 자리가 있다.
            division = sales_division(values["doc_id"])
            if division:
                line["userlTy2"] = division
            line["usermTy1"] = bank_division(partner_label)
        if account == "2550000":
            line.update(
                {
                    "vatDivCd": values["division_code"],
                    "issDt": values["voucher_date"].strftime("%Y%m%d"),
                    "taxFg": (
                        TAX_FG_CASH if values.get("cash_receipt") else TAX_FG_TAXABLE
                    ),
                    "supAm": float(values["base_fee"]),
                }
            )
            issno = values.get("tax_invoice_issno")
            if issno is not None:
                # 전자세금계산서 발행 건 — 아마란스 '전자발행여부' 화면이 발행/
                # 11일내전송 Yes로 표시된다(jeonjaYn=1이면 11일내전송 자동 Yes, 스펙 p44).
                line["jeonjaYn"] = "1"
                if issno:
                    line["issNo"] = issno  # 국세청 승인번호(24자) → 계산서번호 칸
        lines.append(line)
    return lines


def _rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    data = payload.get("resultData") or []
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        rows = data.get("datas") or data.get("data") or []
        return rows if isinstance(rows, list) else []
    return []


def _amount(value: Any) -> Decimal:
    return Decimal(str(value or 0)).quantize(Decimal("1"), ROUND_HALF_UP)


def _digits(value: Any) -> str:
    return "".join(character for character in str(value or "") if character.isdigit())


def _partner_search_name(value: str) -> str:
    return re.sub(r"\s*(?:이사장|지점장)\s*$", "", value).strip()
