"""계정별 전기이월 — 계정별원장 첫 줄 [전 기 이 월] 값.

전표 캐시가 2025-07-24 부터라 작년 말 잔액을 계산할 수 없다. 아마란스 계정별원장
화면의 [전 기 이 월] 줄을 계정·연도별로 한 번 적어 두고 읽는다 (2026-08-21).
"""

from sqlalchemy import Column, Integer, Numeric, String, UniqueConstraint

from app.database import Base


class AccountOpening(Base):
    __tablename__ = "a10_account_opening"
    __table_args__ = (
        UniqueConstraint("account_code", "fiscal_year", name="uq_a10_account_opening"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    account_code = Column(String(20), nullable=False)
    fiscal_year = Column(Integer, nullable=False)
    # 아마란스가 찍는 그대로 넣는다 — 음수일 수 있다 (호남지사 2026: 차변 -46,529,401).
    debit = Column(Numeric(19, 4), nullable=False, default=0)
    credit = Column(Numeric(19, 4), nullable=False, default=0)
