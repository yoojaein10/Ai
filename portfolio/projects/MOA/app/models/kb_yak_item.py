"""국민 약식(400) 전표 구성건 — 묶음 전표의 건별 원장.

약식 입금은 CB2에 400번호별 개별 입금으로 들어오지만, 재무팀 관행은
하루치를 모아 전표 1장(차변 보통예금 합계 + 건별 기타수수료·부가세 쌍)으로
딴다. 같은 400번호에도 일부 입금과 잔금이 따로 들어올 수 있으므로 구성건은
CB2 개별 거래(outbox_id UNIQUE) 단위로 기록한다.
"""

from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, Index, Numeric, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class KbYakItem(Base):
    __tablename__ = "a10_kb_yak_item"
    __table_args__ = (
        UniqueConstraint("outbox_id", name="uq_a10_kb_yak_item_outbox_id"),
        Index("ix_a10_kb_yak_item_yak_no", "yak_no"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    yak_no: Mapped[str] = mapped_column(String(20), nullable=False)
    # 이 400번호가 담긴 개별 입금(a10_deposit_outbox.id)
    outbox_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    tx_day: Mapped[date] = mapped_column(Date, nullable=False)
    supply: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    vat: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    branch_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    partner_code: Mapped[str | None] = mapped_column(String(10), nullable=True)
    # 묶음 전표의 menuSq — 같은 값이면 같은 전표에 담긴 구성건
    menu_sq: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="S")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
