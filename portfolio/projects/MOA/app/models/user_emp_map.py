"""MOA 사용자 → 아마란스 사원 매핑 (a10_user_emp_map).

카드전표 등 아마란스 전표 전송 시 작성자(empCd)·작성부서(ctDept)로 찍을 값.
전송자(usr_seq)가 이 표에 있으면 그 사원코드로, 없으면 빈 값(기존 동작)으로 나간다.
emp_cd는 아마란스 사원코드(예: 2025102801), dept_cd는 아마란스 부서코드(예: 1010 본사-재무팀).
"""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, String, Unicode, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class UserEmpMap(Base):
    __tablename__ = "a10_user_emp_map"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    usr_seq: Mapped[int] = mapped_column(Integer, nullable=False, unique=True, index=True)
    emp_cd: Mapped[str] = mapped_column(String(20), nullable=False)
    dept_cd: Mapped[str] = mapped_column(String(10), nullable=False)
    emp_name: Mapped[str | None] = mapped_column(Unicode(30))  # 표시·관리용 이름
    active: Mapped[str] = mapped_column(String(1), nullable=False, default="Y")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
