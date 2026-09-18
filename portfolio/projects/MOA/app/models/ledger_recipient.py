"""계정별원장 지사 담당자 (a10_ledger_recipient).

지사 계정(1410002~1410022) 하나에 사람이 여럿일 수 있다 — 받는사람(TO)과
참조(CC)를 kind 로 나눈다. 사람이 바뀌면 이 표만 고친다(코드·배포 없이).

담당자가 없으면 그 지사는 **안 나간다**(fail-closed). 지우는 대신 active='N' 으로
두면 누가 언제 빠졌는지 남는다 — 살아 있는 행끼리만 주소가 겹치지 않게 하는
조건부 유니크 인덱스는 scripts/sql/20260824_create_ledger_mail.sql 이 건다.
"""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, Integer, String, Unicode, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class LedgerRecipient(Base):
    __tablename__ = "a10_ledger_recipient"
    __table_args__ = (
        Index("ix_a10_ledger_recipient_account", "account_code"),
    )

    recipient_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 지사 계정 코드. a10_voucher_cache.account_code 와 같은 값이다.
    account_code: Mapped[str] = mapped_column(String(20), nullable=False)
    # 지사 코드(a10_office_map.office_id). 계정만으로 충분하지만 지사 화면과
    # 이어 붙일 때 쓰려고 남겨 둔다.
    office_id: Mapped[str | None] = mapped_column(String(10))
    name: Mapped[str | None] = mapped_column(Unicode(60))
    email: Mapped[str] = mapped_column(Unicode(200), nullable=False)
    # 'TO' 받는사람 · 'CC' 참조
    kind: Mapped[str] = mapped_column(String(2), nullable=False, server_default="TO")
    active: Mapped[str] = mapped_column(String(1), nullable=False, server_default="Y")
    memo: Mapped[str | None] = mapped_column(Unicode(200))
    updated_by_usr_seq: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )
