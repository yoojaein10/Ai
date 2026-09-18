"""팝빌로 발급한 전자세금계산서·현금영수증 발급 내역.

TAMS 부가세.DB 조회를 대체하는 자체 발급 원장. 발급 성공 시 1행 저장한다.
"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, Integer, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class IssuedTaxInvoice(Base):
    __tablename__ = "a10_issued_taxinvoice"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    doc_type: Mapped[str] = mapped_column(String(10), nullable=False)  # 세금계산서 / 현금영수증
    doc_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)  # 감정서번호
    mgt_key: Mapped[str] = mapped_column(String(100), nullable=False)  # 팝빌 문서관리번호
    receiver_corp_num: Mapped["str | None"] = mapped_column(String(20))
    receiver_name: Mapped["str | None"] = mapped_column(String(200))
    supply_cost: Mapped[Decimal] = mapped_column(Numeric(19, 4), nullable=False, default=0)
    tax: Mapped[Decimal] = mapped_column(Numeric(19, 4), nullable=False, default=0)
    total: Mapped[Decimal] = mapped_column(Numeric(19, 4), nullable=False, default=0)
    nts_confirm: Mapped["str | None"] = mapped_column(String(30))  # 국세청 승인번호
    issue_dt: Mapped["str | None"] = mapped_column(String(20))     # 발급일시 (팝빌 문자열)
    trade_usage: Mapped["str | None"] = mapped_column(String(20))  # 현금영수증 거래구분
    # 매출 계정과목(401xxxx) — 발급 팝업에서 선택, 기록용(세금계산서 문서에는 없음)
    account_code: Mapped["str | None"] = mapped_column(String(10))
    is_test: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    # 출처 — MOA팝빌(발급 팝업·일괄발급·수기매출) / 팝빌동기화(사이트 발행분 흡수) /
    # TAMS / 나라장터 / 나라빌 / 국세청 / 기타 (2026-09-09). 값 목록은 popbill_tax.ISSUE_SOURCES.
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="MOA팝빌", server_default="MOA팝빌")
    write_date: Mapped["date | None"] = mapped_column(Date)  # 작성일자 (발행일시와 다르다)
    # 입금 적용용 계산서 (2026-09-10): is_pool=1 은 대표 감정서번호로 끊어 둔 모계산서(어느 감정서
    # 발행금액에도 안 잡힘), pool_id 는 적용 행이 떼어 온 모계산서 id. 값 규칙은 invoice_pool.py.
    is_pool: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    pool_id: Mapped["int | None"] = mapped_column(Integer)
