"""기존 Amaranth 전표를 감정서번호(ctNb)로 찾는 읽기 전용 조회."""

from __future__ import annotations

import time
from calendar import monthrange
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy.orm import Session

from app.amaranth.client import AmaranthClient

_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_organization_cache: tuple[float, tuple[str, list[str]]] | None = None
_CACHE_SECONDS = 300


class AmaranthVoucherLookup:
    def __init__(self, db: Session) -> None:
        self.client = AmaranthClient(db)

    def find(self, doc_id: str, receipt_date: date | None) -> dict[str, Any]:
        cached = _cache.get(doc_id)
        if cached and time.monotonic() - cached[0] < _CACHE_SECONDS:
            return cached[1]

        company_code, divisions = self._organization_codes()
        date_from, date_to = _search_period(doc_id, receipt_date)
        hits = self._find_candidate_lines(
            doc_id, company_code, divisions, date_from, date_to
        )
        voucher_keys = list(
            dict.fromkeys(
                (
                    str(line.get("isuDt") or ""),
                    str(line.get("isuSq") or ""),
                    str(line.get("divCd") or ""),
                )
                for line in hits
                if line.get("isuDt") and line.get("isuSq")
            )
        )
        items = [
            self._load_voucher(company_code, divisions, doc_id, *key)
            for key in voucher_keys
        ]
        result = {
            "items": [item for item in items if item is not None],
            "count": sum(item is not None for item in items),
            "source": "amaranth_api11A14",
            "matched_field": "ctNb",
            "searched_from": date_from.isoformat(),
            "searched_to": date_to.isoformat(),
        }
        _cache[doc_id] = (time.monotonic(), result)
        return result

    def _organization_codes(self) -> tuple[str, list[str]]:
        global _organization_cache
        if (
            _organization_cache
            and time.monotonic() - _organization_cache[0] < 3600
        ):
            return _organization_cache[1]
        companies = _rows(
            self.client.post("/apiproxy/api16S08", json_body={})
        )
        if not companies:
            raise RuntimeError("Amaranth 회사코드를 찾지 못했습니다.")
        company_code = str(companies[0].get("coCd") or companies[0].get("outCoCd"))
        divisions = _rows(
            self.client.post(
                "/apiproxy/api16S09", json_body={"coCd": company_code}
            )
        )
        division_codes = [
            str(row.get("divCd") or row.get("outDivCd"))
            for row in divisions
            if row.get("divCd") or row.get("outDivCd")
        ]
        if not division_codes:
            raise RuntimeError("Amaranth 회계단위 코드를 찾지 못했습니다.")
        result = company_code, list(dict.fromkeys(division_codes))
        _organization_cache = (time.monotonic(), result)
        return result

    def _find_candidate_lines(
        self,
        doc_id: str,
        company_code: str,
        divisions: list[str],
        date_from: date,
        date_to: date,
    ) -> list[dict[str, Any]]:
        current = date_to
        while current >= date_from:
            matches: list[dict[str, Any]] = []
            for page in range(1, 11):
                payload = self.client.post(
                    "/apiproxy/api11A14",
                    json_body=_query_body(
                        company_code,
                        divisions,
                        current,
                        current,
                        page=page,
                        account_filter="1080000|4010001|",
                    ),
                )
                data = payload.get("resultData") or {}
                lines = data.get("datas") or data.get("data") or []
                matches.extend(
                    line
                    for line in lines
                    if str(line.get("ctNb") or "").strip() == doc_id
                )
                total = int(
                    data.get("allCount") or data.get("totalCount") or len(lines)
                )
                if not lines or page * 100 >= total:
                    break
            if matches:
                return matches
            current -= timedelta(days=1)
        return []

    def _load_voucher(
        self,
        company_code: str,
        divisions: list[str],
        doc_id: str,
        voucher_date: str,
        voucher_no: str,
        division_code: str,
    ) -> dict[str, Any] | None:
        body = _query_body(
            company_code,
            [division_code] if division_code else divisions,
            _parse_date(voucher_date),
            _parse_date(voucher_date),
            page=1,
        )
        try:
            number = int(voucher_no)
        except ValueError:
            number = 0
        body.update({"isuSqFr": number, "isuSqTo": number, "viewCount": 500})
        payload = self.client.post("/apiproxy/api11A14", json_body=body)
        data = payload.get("resultData") or {}
        all_lines = data.get("datas") or data.get("data") or []
        lines = [
            line
            for line in all_lines
            if str(line.get("isuDt") or "") == voucher_date
            and str(line.get("isuSq") or "").lstrip("0")
            == voucher_no.lstrip("0")
        ]
        if not lines:
            return None
        debit_total = sum(
            _amount(line.get("acctAm")) for line in lines if str(line.get("drcrFg")) == "3"
        )
        credit_total = sum(
            _amount(line.get("acctAm")) for line in lines if str(line.get("drcrFg")) == "4"
        )
        return {
            "source_voucher_no": f"{voucher_date}-{voucher_no}",
            "management_no": doc_id,
            "voucher_date": _parse_date(voucher_date).isoformat(),
            "debit_total": float(debit_total),
            "credit_total": float(credit_total),
            "status": "승인" if any(str(line.get("docuSt")) == "1" for line in lines) else "미승인",
            "a10_voucher_no": voucher_no,
            "error_message": None,
            "lines": [
                {
                    "line_no": line.get("lnSq"),
                    "debit_credit": line.get("drcrFg"),
                    "account_code": line.get("acctCd"),
                    "account_name": line.get("acctNm"),
                    "partner_code": line.get("trCd"),
                    "partner_name": line.get("attrNm"),
                    "amount": float(_amount(line.get("acctAm"))),
                    "remark": line.get("rmkDc"),
                    "ctNb": line.get("ctNb"),
                }
                for line in lines
            ],
        }


def _query_body(
    company_code: str,
    divisions: list[str],
    date_from: date,
    date_to: date,
    *,
    page: int,
    account_filter: str = "",
    view_count: int = 100,
) -> dict[str, Any]:
    return {
        "coCd": company_code,
        "divCds": "|".join(divisions) + "|",
        "isuDtFr": date_from.strftime("%Y%m%d"),
        "isuDtTo": date_to.strftime("%Y%m%d"),
        "viewPage": page,
        "viewCount": view_count,
        "isAllTrCd": "1",
        "trCds": "",
        "acctStr": account_filter,
        "docuStStr": "1|0|",
        "docuTyStr": "1|2|3|4|5|6|7|8|9|",
    }


def _search_period(doc_id: str, receipt_date: date | None) -> tuple[date, date]:
    parts = doc_id.split("-")
    if len(parts) >= 2 and len(parts[1]) == 4 and parts[1].isdigit():
        year = 2000 + int(parts[1][:2])
        month = int(parts[1][2:])
        if 1 <= month <= 12:
            start = date(year, month, 1)
            end = date(year, month, monthrange(year, month)[1])
            return start, min(date.today(), end)
    target = receipt_date or date.today()
    return date(target.year, target.month, 1), min(date.today(), target)


def _parse_date(value: str) -> date:
    return date(int(value[:4]), int(value[4:6]), int(value[6:8]))


def _amount(value: Any) -> Decimal:
    try:
        return Decimal(str(value or 0))
    except InvalidOperation:
        return Decimal(0)


def _rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    data = payload.get("resultData")
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    if isinstance(data, dict):
        for key in ("data", "datas", "list"):
            value = data.get(key)
            if isinstance(value, list):
                return [row for row in value if isinstance(row, dict)]
    return []
