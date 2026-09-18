"""Amaranth 전표출력조회 데이터를 GamJunDW 캐시에 동기화한다."""

import json
import unicodedata
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Callable

from sqlalchemy import delete, distinct, select
from sqlalchemy.orm import Session

from app.amaranth.client import AmaranthClient
from app.models.voucher_cache import VoucherCache
from scripts.find_management_numbers import _company_code, _division_codes


class VoucherCacheSynchronizer:
    def __init__(self, db: Session, *, progress: Callable[[str], None] = print) -> None:
        self.db = db
        self.client = AmaranthClient(db)
        self.progress = progress

    def _affected_docs(
        self, date_from: date, date_to: date, rows: "list[dict[str, Any]]"
    ) -> "set[str]":
        """이번 동기화로 요약이 달라질 수 있는 감정서.

        새로 들어올 전표뿐 아니라 '지워질 전표'의 관리번호도 포함해야 한다.
        Amaranth에서 전표를 삭제하면 새 목록에는 없으므로, 기존 캐시를 먼저 훑지
        않으면 그 감정서의 요약이 옛 금액인 채로 영영 남는다.
        """
        existing = self.db.execute(
            select(distinct(VoucherCache.management_no)).where(
                VoucherCache.voucher_date >= date_from,
                VoucherCache.voucher_date <= date_to,
                VoucherCache.management_no.isnot(None),
            )
        ).scalars()
        docs = {str(doc).strip() for doc in existing if str(doc or "").strip()}
        docs.update(
            str(row["management_no"]).strip()
            for row in rows
            if str(row.get("management_no") or "").strip()
        )
        return docs

    def sync(
        self,
        date_from: date,
        date_to: date,
        *,
        rebuild_summary: bool = True,
        partial_summary: bool = False,
    ) -> dict[str, Any]:
        company_code = _company_code(self.db, self.client)
        divisions = _division_codes(self.client, company_code)
        division_filter = "|".join(divisions) + "|"
        rows: list[dict[str, Any]] = []
        page = 1
        total = 0
        while True:
            payload = self.client.post(
                "/apiproxy/api11A14",
                json_body={
                    "coCd": company_code,
                    "divCds": division_filter,
                    "isuDtFr": date_from.strftime("%Y%m%d"),
                    "isuDtTo": date_to.strftime("%Y%m%d"),
                    "viewPage": page,
                    "viewCount": 1000,
                    "isAllTrCd": "1",
                    "trCds": "",
                    "docuStStr": "1|0|",
                    "docuTyStr": "1|2|3|4|5|6|7|8|9|",
                },
            )
            data = payload.get("resultData") or {}
            page_rows = data.get("datas") or data.get("data") or []
            total = int(data.get("allCount") or data.get("totalCount") or len(page_rows))
            rows.extend(_cache_mapping(row) for row in page_rows)
            self.progress(f"전표 캐시 수집 {len(rows):,}/{total:,}건")
            if not page_rows or page * 1000 >= total:
                break
            page += 1

        # 삭제 전에 훑어야 '사라질 전표'의 감정서까지 부분 갱신 대상에 들어간다.
        affected = self._affected_docs(date_from, date_to, rows) if partial_summary else set()

        self.db.execute(
            delete(VoucherCache).where(
                VoucherCache.voucher_date >= date_from,
                VoucherCache.voucher_date <= date_to,
            )
        )
        if rows:
            self.db.bulk_insert_mappings(VoucherCache, rows)
        self.db.commit()

        summary_rows = 0
        if rebuild_summary:
            # 입금·미수금 화면이 쓰는 감정서별 집계 캐시를 최신 전표 기준으로 갈아끼운다.
            from app.services.receivable_summary import (
                rebuild_receivable_summary,
                rebuild_receivable_summary_for,
            )

            if partial_summary:
                summary_rows = rebuild_receivable_summary_for(self.db, affected)
                self.progress(
                    f"입금·미수 요약 부분 재집계 {summary_rows:,}건 "
                    f"(대상 감정서 {len(affected):,}건)"
                )
            else:
                summary_rows = rebuild_receivable_summary(self.db)
                self.progress(f"입금·미수 요약 재집계 {summary_rows:,}건")
        return {
            "fetched": len(rows), "stored": len(rows), "pages": page,
            "summary_rows": summary_rows,
            # 부분 동기화 대상 감정서 — 입금 결과(payment_status) 부분 갱신에도 쓴다
            "affected_docs": sorted(affected),
        }


def _clean_text(value: Any) -> str:
    """cp949(varchar) 캐시가 표현 못 하는 문자를 호환 문자로 바꾼다.

    계정별원장 적요에 '?'가 찍힌 원인 (2026-09-02): 워드·웹에서 복사해 붙여넣은
    NBSP(U+00A0)가 varchar 컬럼에 저장되는 순간 '?'(0x3F)로 바뀐다. 호환
    정규화(NFKC)를 거치면 NBSP→공백처럼 보통 문자로 살아남는다. 그래도 안 되는
    문자(이모지 등)는 그대로 둔다 — 어차피 지금과 같은 '?' 저장이고,
    파이썬 단계에서 미리 지워버리면 원인 추적이 더 어려워진다.
    """
    text = str(value or "")
    try:
        text.encode("cp949")
        return text  # 거의 전부 여기서 끝난다 — 글자별 검사 비용을 아낀다
    except UnicodeEncodeError:
        pass
    cleaned = []
    for ch in text:
        try:
            ch.encode("cp949")
        except UnicodeEncodeError:
            normalized = unicodedata.normalize("NFKC", ch)
            try:
                normalized.encode("cp949")
                ch = normalized
            except UnicodeEncodeError:
                pass
        cleaned.append(ch)
    return "".join(cleaned)


def _cache_mapping(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "voucher_date": _parse_date(str(row.get("isuDt") or "")),
        "voucher_no": str(row.get("isuSq") or ""),
        "line_no": str(row.get("lnSq") or row.get("dispSq") or ""),
        "division_code": str(row.get("divCd") or ""),
        "management_no": _clean_text(row.get("ctNb")).strip() or None,
        "debit_credit": str(row.get("drcrFg") or "") or None,
        "account_code": str(row.get("acctCd") or "") or None,
        "account_name": _clean_text(row.get("acctNm")) or None,
        "partner_code": str(row.get("trCd") or "") or None,
        "partner_name": _clean_text(row.get("attrNm")) or None,
        "amount": _amount(row.get("acctAm")),
        "remark": _clean_text(row.get("rmkDc")) or None,
        "document_status": str(row.get("docuSt") or "") or None,
        "raw_json": json.dumps(row, ensure_ascii=False, default=str),
    }


def _parse_date(value: str) -> date:
    if len(value) < 8:
        raise ValueError(f"올바르지 않은 전표일자: {value!r}")
    return date(int(value[:4]), int(value[4:6]), int(value[6:8]))


def _amount(value: Any) -> Decimal:
    try:
        return Decimal(str(value or 0))
    except InvalidOperation:
        return Decimal(0)
