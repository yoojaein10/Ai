"""성과상여 수기 보정 (a10_bonus_adjust).

엑셀에서 수기로 하던 조정을 저장한다 — 자동 계산(GaPrice) 위에 얹는 보정.
adjust_type:
- ROW: 수기 행 추가 (amount: 주주=산정금액, 평·동=순수수료)
- FEE: 기존 행의 인별 순수수료 보정 (평·동 전용 — 주주는 ASSESSED 사용)
- ASSESSED: 기존 행의 산정금액 직접 보정 (주주 — 순수수료·손배·협회비는 자동값 유지)
- DEDUCT: 인별 추가 공제 (label 자유 입력 — 상여기준액 계산에 포함)
- RATE: 주주 상여 적용률 선택 (40/45/35/30). doc_id가 있으면 감정서 행별 적용률,
  없으면 과거(사람 단위) 저장분 — 조회 시 행별 미선택 기본값으로만 쓰인다.
- FIELD: 주주 정산 고정 항목, 감정서 행 단위 (doc_id 필수,
  label = 가변비/미납비이월/감정서경비/화환공제/기타공제).
  감정서경비는 행 자동값(공부발급비+기타실비 안분) 덮어쓰기 — 없으면 자동값 사용.
저장은 (실적월, 사람) 단위 전체 교체(replace-all) 방식.
"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, DateTime, Integer, Numeric, String, Unicode, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class BonusAdjust(Base):
    __tablename__ = "a10_bonus_adjust"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    period_year: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    period_month: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    person: Mapped[str] = mapped_column(Unicode(30), nullable=False, index=True)
    adjust_type: Mapped[str] = mapped_column(String(10), nullable=False)
    doc_id: Mapped[str | None] = mapped_column(String(50))
    work_type: Mapped[str | None] = mapped_column(Unicode(20))
    customer_name: Mapped[str | None] = mapped_column(Unicode(100))
    label: Mapped[str | None] = mapped_column(Unicode(30))
    amount: Mapped[Decimal | None] = mapped_column(Numeric(19, 4))
    memo: Mapped[str | None] = mapped_column(Unicode(200))
    created_by: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
