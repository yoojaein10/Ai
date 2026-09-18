"""사람이 작성한 건 보호 — 큐 Status '진행'(발송 담당자가 집은 건)까지 자동 처리하면서도
사람이 이미 BANK24 에 작성한 폼은 절대 건드리지 않기 위한 공통 가드(러너 4종 공용).

두 가지를 본다.
  1) 작성 폼을 열어 **작성 때만 채워지는 칸**(평가사명·감정평가액·수수료·기준시점 …)에 값이 있으면
     "사람 작성"으로 보고 저장·PDF·현장조사서 전부 건너뛴다(폼은 닫기만).
     접수 단계에서 미리 채워지는 칸(기업 헤더 물건종류, 국민 수수료할증적용 '미적용', 국민 수수료 '0' 등)은
     지표에서 뺀다 — 실측(2780 기업, 2742 국민, 2717 신한 새 폼)으로 고른 목록이다.
  2) 작성 탭 목록에 없으면 **발송완료 탭**을 조회해 본다. 거기 있으면 사람이 이미 보낸 건 → 제외.

러너는 `Excluded` 를 잡아 exit 3(EXIT_EXCLUDED) 으로 끝내고, 큐 워커는 3 을 '제외'로 기록한다(재시도 없음).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from bankon.ui import navigate          # noqa: E402

EXIT_EXCLUDED = 3
NOT_IN_LIST = "행을 목록에서 찾지 못했습니다"


class Excluded(RuntimeError):
    """자동 작성 대상이 아님(사람 작성·이미 발송완료). 실패가 아니라 '제외'."""


# 은행별 '작성 때만 채워지는' 지표 칸. 하나라도 값이 있으면 사람이 작성한 폼으로 본다.
INDICATORS: dict[str, tuple[str, ...]] = {
    "신한": ("감정평가액", "감정평가료", "기준시점", "순수수료", "평가단가"),
    "국민": ("평가사명1", "감정평가액", "現 기준시점", "감정평가(순)수수료", "감정평가(순)수수료 총액"),
    "기업": ("평가사명", "감정수수료", "순수수료", "기준시점", "총감정평가액"),
    "농협": ("평가사명", "평가사명1", "기준시점", "감정평가(순)수수료", "감정수수료", "평가금액", "감정평가액"),
    # 아래 4개는 인계본 실폼 필드표(recon/fields_TBNK*24DAMB.md)에서 고른 것(2026-09-10 이식). 빈 폼 실측은 아직 없다 —
    # 접수 단계에 미리 채워지는 칸이 있으면 첫 실전 건에서 여기서 뺄 것(수협 '특별용역비 0'·새마을 '감정구분' 은 이미 제외).
    "수협": ("평가사명", "순수수료", "감정수수료", "감정평가액", "평가단가"),
    "하나": ("평가사명", "기준시점", "총감정평가액", "순수수료", "감정평가액"),
    "우리": ("평가사명", "기준시점", "감정수수료", "순수수료", "감정평가액"),
    "새마을": ("평가사성명", "가격평가일자", "감정수수료", "순수수료", "총감정평가액", "감정가액"),
}

_ZERO = re.compile(r"^0*(?:\.0+)?$")


def is_blank(value) -> bool:
    """비어 있거나 0 이면 '안 채운 칸'. 국민 새 폼은 수수료 칸이 '0' 으로 온다(실측 2742)."""
    text = str(value or "").replace(",", "").replace(" ", "").strip()
    return not text or bool(_ZERO.match(text))


def written_fields(values: dict, bank: str) -> list[tuple[str, str]]:
    """화면값(라벨→값)에서 지표 칸 중 값이 있는 것들. 비어 있으면 새 폼."""
    hits = []
    for label in INDICATORS.get(bank, ()):
        value = values.get(label)
        if value is not None and not is_blank(value):
            hits.append((label, str(value)))
    return hits


def assert_not_written(form, bank: str, summary: dict | None = None, *, force: bool = False) -> None:
    """작성 폼을 읽어 사람이 작성한 흔적이 있으면 Excluded.

    force=True(러너 `--force`) 면 흔적이 있어도 진행한다 — **사람이 쓴 폼에 덮어쓸 수 있다.**
    시연·재작성처럼 사람이 그 건을 콕 집어 지시했을 때만 쓰는 탈출구다(사용자 요청 2026-09-17).
    """
    import verify_form as vf                # noqa: E402  (러너와 같은 tools 경로)
    values = vf.screen_values(form)
    hits = written_fields(values, bank)
    checked = ", ".join(INDICATORS.get(bank, ()))
    if hits and force:
        shown = ", ".join(f"{k}={v[:14]}" for k, v in hits[:4])
        print(f"[guard] ★사람 작성 감지({shown}) — 그러나 --force 라 그대로 진행한다(사람이 쓴 값에 덮어쓸 수 있음)")
        if summary is not None:
            summary["guard_forced"] = f"사람 작성 무시({shown})"
        return
    if hits:
        shown = ", ".join(f"{k}={v[:14]}" for k, v in hits[:4])
        print(f"[guard] ★사람 작성 감지 — 지표 칸에 값 있음: {shown} → 저장·PDF·현장조사서 건너뜀")
        if summary is not None:
            summary["excluded"] = f"사람 작성({shown})"
        raise Excluded(f"사람이 이미 작성한 폼(값 있음: {shown})")
    print(f"[guard] 새 폼 확인 — 지표 칸({checked}) 모두 비어 있음")


def ensure_row_or_sent(session, doc: str, *, requery, date_from: str, date_to: str) -> str:
    """navigate.ensure_row 와 같되, 작성 탭에 없으면 발송완료 탭을 확인해 '이미 발송완료' 를 가려낸다."""
    try:
        return navigate.ensure_row(session, doc, requery=requery)
    except navigate.NavigationError as error:
        if NOT_IN_LIST not in str(error):
            raise
        print("[guard] 작성 탭에 없음 → 발송완료 탭 확인")
        try:
            sent = in_sent_tab(session, doc, date_from, date_to)
        finally:
            navigate.select_tab(session, "작성")
        if sent:
            print("[guard] ★발송완료 탭에 있음 — 사람이 이미 작성·발송한 건 → 제외")
            raise Excluded("이미 발송완료(발송완료 탭에 있음)") from error
        raise


def in_sent_tab(session, doc: str, date_from: str, date_to: str) -> bool:
    """발송완료 탭에 있는가 — 사람이 이미 작성·발송한 건인지.

    ① 준 기간으로 조회해 행을 훑고, ② 못 찾으면 **감정서번호 '찾 기'(전 기간)** 로 한 번 더 본다.
    발송완료 탭 기간 조회는 **의뢰일자** 기준이라 발송이 한참 뒤인 건은 좁은 창에서 빠진다
    (실측 2787: 의뢰 09-04 · 사람이 09-10 14:34 발송 → 09-01~09-05 조회에 안 걸려 '실패'로 남았다, 2026-09-10).
    탭 클릭이 안 먹으면 작성 탭을 다시 훑게 되므로, 실패를 그대로 알린다(오판보다 낫다).
    """
    if not navigate.select_tab(session, "발송완료"):
        print("[guard] 발송완료 탭 선택 실패 — 발송완료 여부를 확인하지 못했습니다")
        return False
    navigate.query_documents(session, start=date_from, end=date_to, work_type="담보")
    if navigate.find_row_by_doc(session, doc):
        return True
    print("[guard] 발송완료 기간 조회엔 없음 → 감정서번호 '찾 기'(전 기간)로 재확인")
    navigate.find_document(session, doc, settle=6.0)
    return navigate.find_row_by_doc(session, doc, max_rows=30)
