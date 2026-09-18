"""주주 상여율 스케줄 (a10_bonus_rate).

사람마다 감정서 **접수일 구간**별로 요율이 다르다 — 엑셀 합계행 라벨
('2019년분/2021년 3월~' 40%, '2025년 7월 7일 접수분~' 40% …)이 곧 이 표다.
from_date NULL 은 처음부터, to_date NULL 은 계속. 같은 사람의 살아 있는 구간은
겹치면 안 되는데 그 검사는 SQL 로 못 하므로 schedule.save_rates 가 한다.
"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Date, DateTime, Index, Integer, Numeric, String, Unicode, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class BonusRate(Base):
    __tablename__ = "a10_bonus_rate"
    __table_args__ = (
        Index("ix_a10_bonus_rate_person", "person", "from_date"),
    )

    rate_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    person: Mapped[str] = mapped_column(Unicode(30), nullable=False)
    from_date: Mapped[date | None] = mapped_column(Date)
    to_date: Mapped[date | None] = mapped_column(Date)
    # 40 / 45 / 35 / 30 (퍼센트)
    rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    # 엑셀 합계행 라벨 원문 — 시드 근거
    label: Mapped[str | None] = mapped_column(Unicode(100))
    # 'SEED' 엑셀 시드 · 'MANUAL' 화면 입력
    source: Mapped[str] = mapped_column(String(8), nullable=False, server_default="SEED")
    active: Mapped[str] = mapped_column(String(1), nullable=False, server_default="Y")
    updated_by_usr_seq: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )
