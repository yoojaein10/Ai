"""업무실적 보고 감정서별 기재사항 (a10_work_report_note).

담당자가 화면에서 남기는 포함·제외 결정과 그 사유를 감정서 1건 = 1행으로 보관한다.

키는 (지사, 년, 월, 반월, 감정서번호)다. 기준(접수/전례/매출)은 키에 넣지 않는다 —
같은 반월 안에서 2개 이상 기준에 걸치는 감정서가 실측 40~51%라, 기준을 키에 넣으면
셀렉트를 한 번 바꾸는 것만으로 화면 절반의 기재사항이 빈 칸이 된다. 어느 기준으로
마지막에 저장했는지는 감사용 last_basis 로만 남긴다.

반월(half)은 키에 넣는다. 상·하반은 별개 제출 배치이고, 빼면 상반의 제외 결정이
하반 목록에 그대로 따라붙는다.

excluded 는 3상태로 읽는다:
  행 없음  = 담당자가 손대지 않음 → 화면 자동기본값(NO_FEE)을 따른다
  'Y'      = 명시적으로 제외
  'N'      = 명시적으로 포함 (자동기본값이 제외라도 포함으로 되돌린 것)
2치로 합치면 '실비만 건을 일부러 포함시킨 결정'이 자동기본값으로 되살아난다.
"""

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Unicode, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

MAX_REASON = 200
MAX_MEMO = 500


class WorkReportNote(Base):
    __tablename__ = "a10_work_report_note"

    # 복합 자연키. 서로게이트 BigInteger PK를 쓰지 않는다 — sqlite 인메모리 테스트에서
    # autoincrement PK 가 INSERT 시 NOT NULL 로 죽어 영속 테스트를 못 쓴다.
    office_code: Mapped[str] = mapped_column(String(10), primary_key=True)
    period_year: Mapped[int] = mapped_column(Integer, primary_key=True)
    period_month: Mapped[int] = mapped_column(Integer, primary_key=True)
    half: Mapped[str] = mapped_column(Unicode(4), primary_key=True)
    doc_id: Mapped[str] = mapped_column(String(30), primary_key=True)

    # 'Y'/'N' 문자 — mssql BIT 와 sqlite Boolean 의 차이를 피한다(a10_access_allow 관행).
    excluded: Mapped[str] = mapped_column(String(1), nullable=False, default="N")

    # 이 반월 작업 목록에 들어 있는가(멤버십). '작업 저장'이 화면의 전 행을 'Y'로 적고,
    # 목록에서 빠진 건은 'N'으로 되돌린다. 저장본을 다시 열 때 이 목록이 곧 화면이다
    # (2026-09-07 사용자 요청 — 수기 추가분이 다시 불러오면 사라지던 문제).
    # 체크·사유(excluded/reason)만 저장되고 '어떤 건이 목록에 있었나'가 안 남아서 생긴 구멍이다.
    in_list: Mapped[str] = mapped_column(String(1), nullable=False, default="N")
    reason: Mapped[str | None] = mapped_column(Unicode(MAX_REASON))
    memo: Mapped[str | None] = mapped_column(Unicode(MAX_MEMO))

    # 저장 시점의 감정평가액·수수료 지문. 원천이 바뀌면 화면에 표시만 하고 저장은 막지 않는다.
    amount_fingerprint: Mapped[str | None] = mapped_column(String(64))
    last_basis: Mapped[str | None] = mapped_column(Unicode(4))

    updated_by: Mapped[int | None] = mapped_column(Integer)
    updated_by_name: Mapped[str | None] = mapped_column(Unicode(30))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
