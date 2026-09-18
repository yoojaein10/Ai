"""CB2 입금 → 아마란스 전표 처리 기록 (방식 B — CB2는 읽기만, 기록은 여기에).

CB2_ACCT_HIS의 UNIQUE_FIELD를 유니크 키로 잡아 같은 입금을 두 번
처리하지 않는다. 재무팀 Memo의 감정서번호가 매칭 근거다.
"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Date, DateTime, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class DepositOutbox(Base):
    __tablename__ = "a10_deposit_outbox"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # CB2_ACCT_HIS.UNIQUE_FIELD — 은행+계좌+거래일+순번
    unique_field: Mapped[str] = mapped_column(
        String(30), nullable=False, unique=True, index=True
    )
    bank_cd: Mapped[str] = mapped_column(String(8), nullable=False)
    acct_no: Mapped[str] = mapped_column(String(20), nullable=False)
    tx_day: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    tx_amount: Mapped[Decimal] = mapped_column(Numeric(19, 4), nullable=False)
    jeokyo: Mapped[str | None] = mapped_column(String(100), nullable=True)
    memo: Mapped[str | None] = mapped_column(String(500), nullable=True)
    doc_id: Mapped[str | None] = mapped_column(String(30), nullable=True, index=True)
    # BANJE(외상매출금 반제) | GENERAL(일반 입금전표) | ADVANCE(선수금)
    # | MISC_INCOME(잡이익 입금) | SALARY(지사 급여입금)
    # | YAK(국민 약식 400) | BRANCH(지사 입금 — 본지점 전표)
    # YAK·BRANCH·SALARY·GENERAL·BANJE·ADVANCE·MISC_INCOME — 2026-08-25 MISC_INCOME(11자)이 VARCHAR(10)에 잘려 스캔이 서던 것을 16으로
    voucher_kind: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # PENDING(전송 대상/보류) | EXCLUDED(지사·별표·기타) | LEGACY(도입 전 기존처리)
    # | S(전송 성공) | F(전송 실패)
    status: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    menu_sq: Mapped[int | None] = mapped_column(Integer, nullable=True)
    a10_voucher_no: Mapped[str | None] = mapped_column(String(30), nullable=True)
    request_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    response_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_msg: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), index=True
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
