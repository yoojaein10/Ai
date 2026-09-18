"""성과상여 원장 — 공제 · 오버라이드 · 마감 · 결과 스냅샷 (2026-08-25 상여 재작성 2단계).

a10_bonus_deduction  공제 대장 — 사람별 공제 항목(화환·패널티·기타공제·처리수당(+)·선지급·감정서경비 …)을
                     대기(PENDING)로 두었다가 지급월에 적용(APPLIED). amount 는 항상 양수, 부호는 kind 가 정한다.
a10_bonus_override   월별 (감정서, 사람) 포함/제외·수수료·요율·지분 덮어쓰기.
a10_bonus_close      지급월 마감 상태. CLOSED 면 결과는 스냅샷에서 읽는다. source='EXCEL' 은
                     도입 전 엑셀로 지급한 달을 이력으로 넣은 것.
a10_bonus_result     마감 스냅샷 — 행(감정서×사람)과 사람 합계 행(doc_id NULL). 기지급 차감과
                     다음 달 미납비이월의 원천.
"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger, Date, DateTime, Index, Integer, Numeric, String, Unicode, UnicodeText, UniqueConstraint, func, text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

# sqlite 는 INTEGER PRIMARY KEY 만 자동증가한다 — 시험에서는 Integer, 운영(MSSQL)은 BIGINT.
_ID = BigInteger().with_variant(Integer, "sqlite")


class BonusDeduction(Base):
    """공제 대장 한 줄 — 발생(PENDING) → 지급월에 적용(APPLIED, applied_period) → 그 달 마감이면 잠금.

    2026-08-27 재정의: 달별 입력 표(period)에서 상태 있는 대장으로. 삭제 대신 VOID + 사유.
    source_key 는 엑셀·전표에서 만든 항목의 중복 방지 키(운영 DB 는 필터드 유니크 인덱스).
    """

    __tablename__ = "a10_bonus_deduction"
    __table_args__ = (
        Index("ix_a10_bonus_deduction_applied", "applied_period", "person"),
        Index("ix_a10_bonus_deduction_status", "status", "person"),
    )

    deduction_id: Mapped[int] = mapped_column(_ID, primary_key=True, autoincrement=True)
    person: Mapped[str] = mapped_column(Unicode(30), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    doc_id: Mapped[str | None] = mapped_column(String(50))
    amount: Mapped[Decimal] = mapped_column(Numeric(19, 4), nullable=False)
    occurred_on: Mapped[date | None] = mapped_column(Date)
    memo: Mapped[str | None] = mapped_column(Unicode(200))
    source: Mapped[str] = mapped_column(String(10), nullable=False, default="MANUAL", server_default="MANUAL")
    source_key: Mapped[str | None] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(8), nullable=False, default="PENDING", server_default="PENDING")
    applied_period: Mapped[str | None] = mapped_column(String(6))                 # 적용 지급월 YYYYMM
    applied_by_usr_seq: Mapped[int | None] = mapped_column(BigInteger)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime)
    void_reason: Mapped[str | None] = mapped_column(Unicode(200))
    voided_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_by_usr_seq: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime)


class BonusOverride(Base):
    __tablename__ = "a10_bonus_override"
    __table_args__ = (UniqueConstraint("period", "doc_id", "person", "action", name="ux_a10_bonus_override"),)

    override_id: Mapped[int] = mapped_column(_ID, primary_key=True, autoincrement=True)
    period: Mapped[str] = mapped_column(String(6), nullable=False)
    doc_id: Mapped[str] = mapped_column(String(50), nullable=False)
    person: Mapped[str] = mapped_column(Unicode(30), nullable=False)
    action: Mapped[str] = mapped_column(String(8), nullable=False)          # INCLUDE|EXCLUDE|FEE|RATE|SHARE
    value: Mapped[Decimal | None] = mapped_column(Numeric(19, 4))
    memo: Mapped[str | None] = mapped_column(Unicode(200))
    created_by_usr_seq: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())


class BonusClose(Base):
    __tablename__ = "a10_bonus_close"

    period: Mapped[str] = mapped_column(String(6), primary_key=True)
    status: Mapped[str] = mapped_column(String(8), nullable=False, server_default="OPEN")   # OPEN|CLOSED
    source: Mapped[str] = mapped_column(String(8), nullable=False, server_default="MOA")    # MOA|EXCEL
    closed_by_usr_seq: Mapped[int | None] = mapped_column(BigInteger)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime)
    reopened_by_usr_seq: Mapped[int | None] = mapped_column(BigInteger)
    reopened_at: Mapped[datetime | None] = mapped_column(DateTime)
    memo: Mapped[str | None] = mapped_column(Unicode(200))


class BonusResult(Base):
    __tablename__ = "a10_bonus_result"
    __table_args__ = (
        Index("ix_a10_bonus_result_period", "period", "person"),
        Index("ix_a10_bonus_result_doc", "doc_id", "person"),
    )

    result_id: Mapped[int] = mapped_column(_ID, primary_key=True, autoincrement=True)
    period: Mapped[str] = mapped_column(String(6), nullable=False)
    person: Mapped[str] = mapped_column(Unicode(30), nullable=False)
    kind: Mapped[str] = mapped_column(String(12), nullable=False)           # SHAREHOLDER|ASSOCIATE|COMMON
    doc_id: Mapped[str | None] = mapped_column(String(50))                  # NULL = 사람 합계 행
    block_from: Mapped[date | None] = mapped_column(Date)
    rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    share_pct: Mapped[Decimal | None] = mapped_column(Numeric(6, 3))
    fee: Mapped[Decimal] = mapped_column(Numeric(19, 4), nullable=False, server_default=text("0"))
    assessed: Mapped[Decimal] = mapped_column(Numeric(19, 4), nullable=False, server_default=text("0"))
    indemnity: Mapped[Decimal] = mapped_column(Numeric(19, 4), nullable=False, server_default=text("0"))
    association_fee: Mapped[Decimal] = mapped_column(Numeric(19, 4), nullable=False, server_default=text("0"))
    payout_base: Mapped[Decimal | None] = mapped_column(Numeric(19, 4))
    bonus: Mapped[Decimal | None] = mapped_column(Numeric(19, 4))
    pretax: Mapped[Decimal | None] = mapped_column(Numeric(19, 4))
    income_tax: Mapped[Decimal | None] = mapped_column(Numeric(19, 4))
    resident_tax: Mapped[Decimal | None] = mapped_column(Numeric(19, 4))
    other_deduct: Mapped[Decimal | None] = mapped_column(Numeric(19, 4))
    payment: Mapped[Decimal | None] = mapped_column(Numeric(19, 4))
    unpaid_carry_out: Mapped[Decimal | None] = mapped_column(Numeric(19, 4))
    card_limit: Mapped[Decimal | None] = mapped_column(Numeric(19, 4))
    retired: Mapped[str] = mapped_column(String(1), nullable=False, server_default="N")
    source: Mapped[str] = mapped_column(String(8), nullable=False, server_default="MOA")  # SALES|PAID|MANUAL|EXCEL|MOA
    detail_json: Mapped[str | None] = mapped_column(UnicodeText)
