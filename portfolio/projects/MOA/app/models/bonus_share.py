"""감정서 지분 (a10_bonus_share).

공동 건의 인별 지분(%). 엑셀은 거래처명 괄호 '(김5 강2.5 조2.5)', '(안9:이1)' 로
적었고 시드는 각 월 시트의 실제 적용 지분(H/(F+G))에서 만든다. 독립 백분율이라
한 감정서의 합이 100 이 아닐 수 있다(공동유치 50% 인정, 부가 2.5%) — 경고만 띄운다.
bc_pct 는 법인카드 몫이 지분과 다를 때만('안6:황4/법카 안100').
살아 있는 행끼리 (doc_id, person)이 겹치지 않게 하는 조건부 유니크 인덱스는
scripts/sql/20260826_create_bonus_master.sql 이 건다.
"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, DateTime, Index, Integer, Numeric, String, Unicode, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class BonusShare(Base):
    __tablename__ = "a10_bonus_share"
    __table_args__ = (
        Index("ix_a10_bonus_share_doc", "doc_id"),
    )

    share_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # a10_voucher_cache.management_no 와 같은 값 (RTRIM 된 감정서번호)
    doc_id: Mapped[str] = mapped_column(String(50), nullable=False)
    person: Mapped[str] = mapped_column(Unicode(30), nullable=False)
    share_pct: Mapped[Decimal] = mapped_column(Numeric(6, 3), nullable=False)
    bc_pct: Mapped[Decimal | None] = mapped_column(Numeric(6, 3))
    # 'SEED' 엑셀 시드 · 'MANUAL' 화면 입력 · 'PARSED' 괄호 파서 제안
    source: Mapped[str] = mapped_column(String(8), nullable=False, server_default="SEED")
    note: Mapped[str | None] = mapped_column(Unicode(200))
    active: Mapped[str] = mapped_column(String(1), nullable=False, server_default="Y")
    updated_by_usr_seq: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )
