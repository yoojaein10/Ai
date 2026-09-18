"""권한 변경 이력 — 그리고 나중에 붙을 신청·승인까지 같은 표에 담는다.

왜 있나 (2026-08-16 진단)
    권한 변경이 **아무 흔적도 안 남기고 있었다.** a10_access_log 5,499행은 전부
    EXE_LAUNCH(로그인)이고 권한 변경은 한 줄도 없다. 남는 것은 현재 상태와
    updated_by_usr_seq, 마지막 시각뿐이라 '누가 언제 무엇을 무엇으로 바꿨나'가
    어디에도 없었다. 묶음은 참조라 하나를 고치면 지사 여러 곳이 동시에 바뀌는데,
    잘못 건드려도 원래 무엇이었는지 되돌릴 근거가 없었다.

왜 신청 표를 따로 안 만드나
    이력과 신청은 컬럼이 대부분 겹친다 — 대상·행위자·요청자·사유·시각·before/after.
    따로 만들면 '왜 줬나'가 이력·신청·access_log 세 곳으로 흩어지고 이을 키가 없다.
    그래서 한 표에 담고 status 로 가른다:
      applied   … 관리자가 직접 바꿨다 (requested_by == actor, 지금 유일한 경우)
      pending   … 누군가 신청했고 아직 아무 일도 안 일어났다
      rejected  … 반려됐다
    신청 흐름을 붙이는 날, 표를 새로 만들 필요 없이 pending 행을 쓰기 시작하면 된다.

**덧붙이지 말고 쌓기만 한다(append-only).** 행을 고치면 이력이 아니다.
표 정의는 scripts/sql/20260816_create_access_change.sql 과 짝이다.
"""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    Index,
    Integer,
    String,
    Unicode,
    UnicodeText,
    func,
)
from sqlalchemy.dialects.mssql import NVARCHAR
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

# a10_access_policy.memo 가 varchar(200) 이라 운영에 저장된 단 하나의 한글 사유가
# '??? ?? ???? ???' 로 죽어 있다(2026-08-16 확인). 같은 실수를 되풀이하지 않는다.
_JSON = UnicodeText().with_variant(NVARCHAR(None), "mssql")


class AccessChange(Base):
    __tablename__ = "a10_access_change"

    # BigInteger 그대로 두면 **sqlite 에서 자동증가가 안 된다** — sqlite 는
    # INTEGER PRIMARY KEY 에만 rowid 를 붙여 주고 BIGINT 에는 안 붙인다.
    # 운영(MSSQL)은 BIGINT IDENTITY 로 나가고, 시험용 sqlite 에서만 INTEGER 가 된다.
    change_id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True, autoincrement=True,
    )

    # 무엇을 바꿨나 — 'policy'(개인 예외) | 'role'(묶음 정의) |
    #                'dept_role'(부서 부여) | 'user_role'(개인 부여) | 'grant'(전체지사)
    target_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    # 대상 식별자. 사람이면 usr_seq, 묶음이면 role_id, 부서면 office_id|부서명.
    target_key: Mapped[str] = mapped_column(Unicode(120), nullable=False)
    # 사람이 읽을 대상 이름. 나중에 원본이 바뀌어도 '그때 누구였는지'가 남는다.
    target_label: Mapped[str | None] = mapped_column(Unicode(120), nullable=True)

    action: Mapped[str] = mapped_column(String(20), nullable=False)   # create|update|delete|assign|unassign
    status: Mapped[str] = mapped_column(String(12), nullable=False, server_default="applied")

    # 되돌리려면 before 가 있어야 한다. 이게 이 표의 존재 이유다.
    before_json: Mapped[str | None] = mapped_column(_JSON, nullable=True)
    after_json: Mapped[str | None] = mapped_column(_JSON, nullable=True)

    # 실제로 바꾼 사람과, 그걸 요청한 사람. 지금은 둘이 같지만(관리자 직접 변경)
    # 신청 흐름이 붙으면 갈린다 — 그때 결재선이 여기서 읽힌다.
    actor_usr_seq: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    requested_by_usr_seq: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # 사유는 반드시 nvarchar 다. 한글이 죽으면 사유를 받는 의미가 없다.
    reason: Mapped[str | None] = mapped_column(Unicode(400), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    __table_args__ = (
        # '이 사람 권한이 언제부터 이랬나' 가 가장 잦은 질문이다.
        Index("IX_a10_access_change_target", "target_kind", "target_key", "created_at"),
        # '지난주에 누가 뭘 만졌나' — 사고 직후에 보는 축.
        Index("IX_a10_access_change_time", "created_at"),
        # 신청 흐름이 붙으면 '대기 N건' 을 이 인덱스로 센다.
        Index("IX_a10_access_change_status", "status", "created_at"),
    )
