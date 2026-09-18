"""권한 묶음(역할)과 그 적용처.

지금까지는 부서·직군 기본값이 **코드에 박혀** 있어(access_policy.py) 권한을 바꾸려면
배포를 해야 했고, 화면에서는 사람을 하나씩만 고칠 수 있었다. 이 세 표가 그걸
'화면에서 묶음을 만들고 부서·사람에 붙이는' 방식으로 바꾼다.

해석 순서 (2026-08-13 사용자 확정) — **개인이 부서를 이긴다**
  ① 코드 기본값(과도기)  ② 부서 묶음(①을 대체)  ③ 개인 묶음(②를 대체)
  ④ 개인 예외(a10_access_policy.menu_overrides_json)가 그 위에 얹힌다

묶음은 **참조**다. 묶음을 고치면 그걸 쓰는 부서·사람이 즉시 따라간다.
표 정의는 scripts/sql/20260813_create_access_role.sql 참고.
"""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Unicode,
    UnicodeText,
    func,
    text,
)
from sqlalchemy.dialects.mssql import NVARCHAR
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

# 배포는 scripts.create_tables 의 Base.metadata.create_all() 로도 표를 만든다
# (server_redeploy.ps1). 그래서 **모델과 DDL 스크립트가 같은 것을 만들어야 한다** —
# 2026-08-13 대조에서 넷이 어긋나 있었다: 이름 유니크 인덱스 없음(같은 이름 묶음이
# 둘 생긴다) · 외래키 없음 · menu_keys_json 이 NTEXT(사용 중단 타입) · 시각이 DATETIME.
# 아래에서 넷 다 맞춘다. scripts/sql/20260813_create_access_role.sql 과 짝이다.
_JSON = UnicodeText().with_variant(NVARCHAR(None), "mssql")   # NVARCHAR(MAX)


class AccessRole(Base):
    __tablename__ = "a10_access_role"

    role_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(Unicode(60), nullable=False)
    # 소속 — 이 묶음이 속한 곳(본사 '10' 또는 지사코드). **공용 없이 각 소속이 자기
    # 묶음을 따로 가진다**(2026-08-18 사용자 결정). 권한일괄적용은 대상의 소속과 같은
    # office_id 묶음만 보여 준다. 기존 행은 마이그레이션에서 '10'(본사)으로 채운다.
    office_id: Mapped[str] = mapped_column(String(10), nullable=False, server_default="10")
    # 켜진 메뉴 키 배열. 메뉴가 늘어도 컬럼을 안 바꾸려고 JSON 으로 둔다.
    menu_keys_json: Mapped[str | None] = mapped_column(_JSON, nullable=True)
    # 'Y'/'N'/None. None 은 '이 묶음은 이 플래그를 정하지 않는다' — 아래 층이 산다.
    view_all_offices: Mapped[str | None] = mapped_column(String(1), nullable=True)
    view_other_users: Mapped[str | None] = mapped_column(String(1), nullable=True)
    active: Mapped[str] = mapped_column(String(1), nullable=False, server_default="Y")
    memo: Mapped[str | None] = mapped_column(Unicode(200), nullable=True)
    updated_by_usr_seq: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    # 살아 있는 묶음끼리만 이름이 겹치지 않게. 지운(active='N') 이름은 재사용 가능.
    # **애플리케이션 검사만으로는 부족하다** — 동시에 두 번 저장하면 뚫린다.
    # 이름 유일성은 **소속별**로 — 각 지사가 '평가사 기본' 을 따로 가질 수 있다
    # (2026-08-18 공용 없는 지사별 묶음). active='N'(지운 것) 이름은 재사용 가능.
    __table_args__ = (
        Index(
            "UX_a10_access_role_office_name", "office_id", "name", unique=True,
            mssql_where=text("active = 'Y'"), sqlite_where=text("active = 'Y'"),
        ),
    )


class AccessDeptRole(Base):
    """부서 → 묶음. 본사는 office_id='10' + 부서명, 지사는 지사코드 + 부서명.

    부서명은 access_policy.identity_from_row 가 만드는 것과 **같은 문자열**이어야
    한다(본사는 좌석코드→이름 변환, 지사는 chrg_biz 원문).
    """

    __tablename__ = "a10_access_dept_role"

    office_id: Mapped[str] = mapped_column(String(10), primary_key=True)
    department_name: Mapped[str] = mapped_column(Unicode(60), primary_key=True)
    role_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("a10_access_role.role_id"), nullable=False
    )
    active: Mapped[str] = mapped_column(String(1), nullable=False, server_default="Y")
    updated_by_usr_seq: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )


class AccessUserRole(Base):
    """개인 → 묶음. 부서 묶음을 **대체**한다(개인이 이긴다)."""

    __tablename__ = "a10_access_user_role"

    usr_seq: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    role_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("a10_access_role.role_id"), nullable=False
    )
    active: Mapped[str] = mapped_column(String(1), nullable=False, server_default="Y")
    updated_by_usr_seq: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    # '이 묶음을 쓰는 사람 수' 를 셀 때 쓴다(access_roles._usage). 사람 수가 늘면
    # 매번 전체를 훑게 되므로 붙여 둔다.
    __table_args__ = (
        Index("IX_a10_access_user_role_role", "role_id"),
    )
