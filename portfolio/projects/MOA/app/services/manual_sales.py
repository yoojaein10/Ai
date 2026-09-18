"""감정서번호가 없는 탁상·가격자문 매출의 Amaranth 전표 생성."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.amaranth.client import AmaranthClient
from app.models.voucher_cache import VoucherCache
from app.models.voucher_sync import VoucherSync
from app.services.bank_division import bank_division
from app.services.default_vouchers import DefaultVoucherService


REVENUE_ACCOUNTS = {
    "4010001": "감정수수료",
    "4010002": "기타수수료",
    "4010003": "공시지가등수익",
    "4010004": "용역수수료",
    "4010005": "임대수수료",
    "9090000": "주차장수익",   # 마티즈주차장(0000037910) 등 — 2026-09-08 사용자 요청
}


class ManualSaleError(ValueError):
    pass


class ManualSaleDuplicateError(ManualSaleError):
    pass


class ManualSaleService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.client = AmaranthClient(db)

    def exists(self, reference: str) -> bool:
        row = self.db.scalar(
            select(VoucherSync).where(
                VoucherSync.src_voucher_no == f"MANUAL-SALE-{reference}"
            )
        )
        return row is not None and row.status != "F"

    def create(
        self,
        *,
        reference: str,
        office_code: str,
        partner_code: str,
        partner_name: str,
        voucher_date: date,
        supply_cost: int,
        tax: int,
        revenue_account: str,
        sales_division: str,
        memo: str,
        tax_invoice_confirm: str | None,
    ) -> dict[str, Any]:
        if not partner_code.strip():
            raise ManualSaleError("Amaranth 거래처를 먼저 선택해 주세요.")
        if supply_cost <= 0 or tax < 0:
            raise ManualSaleError("공급가액과 부가세를 확인해 주세요.")
        if revenue_account not in REVENUE_ACCOUNTS:
            raise ManualSaleError("지원하지 않는 매출 계정과목입니다.")

        src_no = f"MANUAL-SALE-{reference}"
        previous = self.db.scalar(
            select(VoucherSync).where(VoucherSync.src_voucher_no == src_no)
        )
        if previous and previous.status == "F":
            self.db.delete(previous)
            self.db.commit()
            previous = None
        if previous:
            raise ManualSaleDuplicateError("이미 전표가 생성된 수기 매출입니다.")

        total = supply_cost + tax
        company_code, division_code = DefaultVoucherService(self.db)._organization(office_code)
        sync = VoucherSync(
            src_voucher_no=src_no,
            # 내부 재시도·중복검사용 키다. Amaranth 관리번호에는 보내지 않는다.
            management_no=reference,
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
            raise ManualSaleDuplicateError("이미 전표 생성 요청이 처리되었습니다.") from exc

        menu_sq = 10000 + (int(sync.id) % 90000)
        lines = manual_voucher_lines(
            reference=reference,
            company_code=company_code,
            division_code=division_code,
            voucher_date=voucher_date,
            menu_sq=menu_sq,
            partner_code=partner_code.strip(),
            partner_name=partner_name.strip(),
            supply_cost=supply_cost,
            tax=tax,
            revenue_account=revenue_account,
            sales_division=sales_division,
            memo=memo.strip(),
            tax_invoice_confirm=tax_invoice_confirm,
            dept_cd="1010" if office_code == "10" else "",
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
            account_names = {
                "1080000": "외상매출금",
                "2550000": "부가세예수금",
                **REVENUE_ACCOUNTS,
            }
            for line in lines:
                self.db.add(VoucherCache(
                    voucher_date=voucher_date,
                    voucher_no=voucher_no,
                    line_no=str(line["menuLnSq"]),
                    division_code=division_code,
                    management_no=None,
                    debit_credit=line["drcrFg"],
                    account_code=line["acctCd"],
                    account_name=account_names.get(line["acctCd"]),
                    partner_code=line.get("trCd"),
                    partner_name=partner_name,
                    amount=Decimal(str(line["acctAm"])),
                    remark=line.get("rmkDc"),
                    document_status="0",
                    raw_json=json.dumps(line, ensure_ascii=False, default=str),
                ))
            self.db.commit()
        except Exception as exc:
            sync.status = "F"
            sync.error_msg = str(exc)
            self.db.commit()
            raise ManualSaleError(f"Amaranth 전표 등록에 실패했습니다: {exc}") from exc

        return {
            "reference": reference,
            "voucher_date": voucher_date.isoformat(),
            "voucher_no": sync.a10_voucher_no or str(menu_sq),
            "supply_cost": supply_cost,
            "tax": tax,
            "total": total,
            "partner_code": partner_code.strip(),
            "partner_name": partner_name,
        }


def manual_voucher_lines(**values: Any) -> list[dict[str, Any]]:
    """관리번호 없이 외상매출금/매출/부가세 3줄을 만든다."""
    memo = str(values.get("memo") or "탁상수수료").strip()[:100]
    common: dict[str, Any] = {
        "inDivCd": values["division_code"],
        "menuDt": values["voucher_date"].strftime("%Y%m%d"),
        "menuSq": values["menu_sq"],
        "docuTy": "3",
        "isuDoc": f"수기 매출 {memo}"[:100],
    }
    if values.get("dept_cd"):
        common["ctDept"] = values["dept_cd"]
    raw = [
        ("3", "1080000", values["supply_cost"] + values["tax"], "외상매출 발생"),
        ("4", values["revenue_account"], values["supply_cost"], memo),
        ("4", "2550000", values["tax"], memo),
    ]
    lines: list[dict[str, Any]] = []
    for drcr, account, amount, remark in raw:
        if amount <= 0:
            continue
        line: dict[str, Any] = {
            **common,
            "menuLnSq": len(lines) + 1,
            "drcrFg": drcr,
            "acctCd": account,
            "acctAm": float(amount),
            "rmkDc": remark,
            "trCd": values["partner_code"],
        }
        if account == values["revenue_account"]:
            if values.get("sales_division"):
                line["userlTy2"] = values["sales_division"]
            line["usermTy1"] = bank_division(values["partner_name"])
        if account == "2550000":
            line.update({
                "vatDivCd": values["division_code"],
                "issDt": values["voucher_date"].strftime("%Y%m%d"),
                "taxFg": "11",
                "supAm": float(values["supply_cost"]),
            })
            confirm = values.get("tax_invoice_confirm")
            if confirm is not None:
                line["jeonjaYn"] = "1"
                if confirm:
                    line["issNo"] = confirm
        # 감정서번호가 없으므로 maNb/ctNb를 의도적으로 싣지 않는다.
        lines.append(line)
    return lines
