"""신한은행 발송기한 관리 — apworksdw 기존 프로시저 호출 (2026-09-02).

접수 후 4영업일(주말·APW_HOLIDAY 제외)이 발송기한이다. 계산은 전부 원본
프로시저가 한다 — 여기서 재현하지 않는다(달라지면 TAMS 쪽과 어긋난다).

  SP_S_KW_SHINHAN_DAYCOUNT         지사별 집계 (D-2·D-1·당일·+1·+2·초과)
  SP_S_KW_SHINHAN_DAYCOUNT_DETAIL  건별 상세 (@DayGubun 으로 구간 선택)
  SP_U_KW_SHINHAN_DAYCOUNT_EDITYN  조정 여부·사유 저장 (APW_KW_SHINHAN_DAYCOUNT_EDITYN)
"""

from datetime import date
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

CHECK_GUBUNS = ("전체", "조정", "비조정")
# 상세 프로시저 @DayGubun 값 (빈값 = 관리 대상 전부)
DAY_GUBUNS = ("", "-2", "-1", "발송일", "Poday", "Ptday", "ovday")


class ShinhanDelayError(ValueError):
    pass


def _check(check_gubun: str) -> str:
    if check_gubun not in CHECK_GUBUNS:
        raise ShinhanDelayError(f"구분은 {'/'.join(CHECK_GUBUNS)} 중 하나여야 합니다.")
    return check_gubun


def summary(
    db: Session, *, date_from: date, date_to: date, check_gubun: str = "전체",
) -> "list[dict[str, Any]]":
    """지사별 집계 + 총계 행. 열 이름은 프로시저 그대로 내려보낸다."""
    rows = db.execute(
        text(
            "EXEC [apworksdw].dbo.SP_S_KW_SHINHAN_DAYCOUNT "
            "@SDate = :sdate, @EDate = :edate, @Office = N'', @CheckGubun = :gubun"
        ),
        {"sdate": date_from, "edate": date_to, "gubun": _check(check_gubun)},
    ).mappings().all()
    return [dict(row) for row in rows]


def detail(
    db: Session, *, date_from: date, date_to: date,
    office: str = "", day_gubun: str = "", check_gubun: str = "전체",
) -> "list[dict[str, Any]]":
    """건별 상세 — office 는 지사 이름('총계'·'전체'는 프로시저가 빈값으로 해석)."""
    if day_gubun not in DAY_GUBUNS:
        raise ShinhanDelayError(f"구간은 {'/'.join(g or '(전부)' for g in DAY_GUBUNS)} 중 하나여야 합니다.")
    rows = db.execute(
        text(
            "EXEC [apworksdw].dbo.SP_S_KW_SHINHAN_DAYCOUNT_DETAIL "
            "@SDate = :sdate, @EDate = :edate, @Office = :office, "
            "@DayGubun = :day_gubun, @CheckGubun = :gubun"
        ),
        {
            "sdate": date_from, "edate": date_to, "office": office or "",
            "day_gubun": day_gubun, "gubun": _check(check_gubun),
        },
    ).mappings().all()
    return [dict(row) for row in rows]


def save_memo(db: Session, *, doc_id: str, edit_yn: bool, memo: str) -> None:
    """조정 여부·사유 저장 — 기존 업서트 프로시저 그대로 (체크 해제+빈 메모 = 비움)."""
    doc = doc_id.strip()
    if not doc:
        raise ShinhanDelayError("감정서번호가 없습니다.")
    db.execute(
        text(
            "EXEC [apworksdw].dbo.SP_U_KW_SHINHAN_DAYCOUNT_EDITYN "
            "@DocID = :doc, @EditYN = :yn, @EditMemo = :memo"
        ),
        {"doc": doc, "yn": "Y" if edit_yn else "N", "memo": memo.strip()[:1000]},
    )
    db.commit()
