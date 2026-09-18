"""업무용승용차 (a10_card_vehicle) — 카드전표 차량유지비 라인에 붙는 아마란스 차량코드.

아마란스 전표의 관리항목 '업무용승용차'(읽기 c3Type/c3Value, 쓰기 carCd)는 차량마다 코드가 있다
(예: 0000002166 = 313도5539 신상우). 카드 사용자(사원)로 차량을 찾아 8220000 차량유지비 라인에
carCd 를 싣는다. 사람이 차가 둘이면(김형수·정승훈·윤도) 현재 보험에 든 차만 active='Y'.
"""

from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, Unicode, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class CardVehicle(Base):
    __tablename__ = "a10_card_vehicle"
    __table_args__ = (Index("ix_a10_card_vehicle_person", "person"),)

    vehicle_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    plate: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)   # 차량번호 313도5539
    car_cd: Mapped[str] = mapped_column(String(10), nullable=False)               # 아마란스 차량코드 0000002166
    person: Mapped[str] = mapped_column(Unicode(30), nullable=False)              # 관리사원 (카드 사용자명과 같은 표기, 여럿이면 '/'로)
    model: Mapped[str | None] = mapped_column(Unicode(50))                        # 차종 (표시용)
    division_code: Mapped[str] = mapped_column(String(4), nullable=False, server_default="1000")
    active: Mapped[str] = mapped_column(String(1), nullable=False, server_default="Y")
    memo: Mapped[str | None] = mapped_column(Unicode(200))
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())
