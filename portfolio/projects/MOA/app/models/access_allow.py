"""화면 접근 허용 명단 (a10_access_allow).

이 표에 활성(active='Y') 행이 하나라도 있으면 **allowlist 모드**가 켜진다:
명단에 없는 사용자는 사용자 컨텍스트 조회가 거부되어 화면 자체가 열리지 않는다.
표가 비어 있으면(기본) 아무도 차단하지 않는다 — 코드 배포와 명단 설정을 분리하기 위한 안전장치.
"""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, String, Unicode, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AccessAllow(Base):
    __tablename__ = "a10_access_allow"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    usr_seq: Mapped[int] = mapped_column(Integer, nullable=False, unique=True, index=True)
    emp_name: Mapped[str | None] = mapped_column(Unicode(30))
    active: Mapped[str] = mapped_column(String(1), nullable=False, server_default="Y")
    memo: Mapped[str | None] = mapped_column(Unicode(200))
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
