"""MOA 사용자별 권한 예외.

조직/직군 기본값은 코드에서 계산하고 이 테이블에는 기본값과 다른 예외만 저장한다.
메뉴 예외는 JSON 객체로 보관해 메뉴가 늘어나도 컬럼 추가가 필요하지 않다.
"""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, String, UnicodeText, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AccessPolicy(Base):
    __tablename__ = "a10_access_policy"

    # APWorks TMWCMN_USR_BAC_INFO.USR_SEQ와 1:1
    usr_seq: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    usr_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    view_all_offices_override: Mapped[str | None] = mapped_column(String(1), nullable=True)
    view_other_users_override: Mapped[str | None] = mapped_column(String(1), nullable=True)
    menu_overrides_json: Mapped[str | None] = mapped_column(UnicodeText, nullable=True)
    active: Mapped[str] = mapped_column(String(1), nullable=False, server_default="Y")
    updated_by_usr_seq: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    memo: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )
