"""성과상여 사람 파라미터 (a10_bonus_person).

주주/소속 구분과 소속평가사의 지급률·소득세율을 사람별로 둔다. 엑셀에서는 이 값이
'소속 합계' 행의 수식 안에 숨어 있었다(AD ×70%, AE ×15%/30%). 시드는 엑셀에서 읽고
이후에는 상여 설정 화면에서 재무팀이 고친다. 빼는 대신 active='N'.
"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, DateTime, Numeric, String, Unicode, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class BonusPerson(Base):
    __tablename__ = "a10_bonus_person"

    # 엑셀·APWorks(apw_masterex.Manager)와 같은 표기의 이름이 키다.
    person: Mapped[str] = mapped_column(Unicode(30), primary_key=True)
    # 'SHAREHOLDER' 주주 · 'ASSOCIATE' 소속평가사(평·동)
    kind: Mapped[str] = mapped_column(String(12), nullable=False)
    # 소속 합계 AD 에 곱하는 지급률 (기본 전액, 박중호·이영은 0.7)
    pay_ratio: Mapped[Decimal] = mapped_column(
        Numeric(5, 4), nullable=False, server_default=text("1")
    )
    # 소득세율 — 주주 0.30, 소속 대부분 0.15
    tax_rate: Mapped[Decimal] = mapped_column(
        Numeric(5, 4), nullable=False, server_default=text("0.30")
    )
    # 공통건(공(X)) 요율 % — 비우면 규칙(산업은행 4·국공유/법원 15·보상 15) 아니면 3. 이영은 10, 유영조 3, 이진형·조성국 20
    common_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    active: Mapped[str] = mapped_column(String(1), nullable=False, server_default="Y")
    memo: Mapped[str | None] = mapped_column(Unicode(200))
    updated_by_usr_seq: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )
