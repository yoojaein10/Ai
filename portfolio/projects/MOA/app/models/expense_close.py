"""실비 종결 표시 — 입금현황 우클릭 '실비 처리'가 만드는 행.

실비만 받고 끝나는 건(취하·반려 등)은 상태 처리도 안 된 경우가 많아 재무팀만
안다. 그래서 자동 감지 대신 사람이 누른다 (2026-09-01 사용자 결정).

판정만 바꾸는 꼬리표다: 활성 행(released_at IS NULL)이 있으면 그 감정서의
기준액(매출총액)이 closed_amount(처리 시점 수금액)로 고정돼 완납이 되고,
미수금현황에서 빠지며, 배분 초안도 안 만든다. APWorks의 여비·기타실비
필드와는 무관하다. 해제는 삭제가 아니라 released_* 를 채운다 — 잘못 눌렀을 때
누가 언제 처리·해제했는지 남긴다.
"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, DateTime, Integer, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ExpenseClose(Base):
    __tablename__ = "a10_expense_close"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    doc_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    # 처리 시점 수금액 = 이 감정서의 최종 매출(기준액). 이후 돈이 더 들어오면
    # 과입금으로 떠서 재무팀이 알아차린다 — 동적으로 따라가면 이 신호가 사라진다.
    closed_amount: Mapped[Decimal] = mapped_column(Numeric(19, 4), nullable=False)
    closed_by: Mapped[int | None] = mapped_column(Integer)
    closed_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    released_by: Mapped[int | None] = mapped_column(Integer)
    released_at: Mapped[datetime | None] = mapped_column(DateTime)
