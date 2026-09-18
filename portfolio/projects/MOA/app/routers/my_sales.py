"""평가사 개인 매출 대시보드 API.

설계서의 보안 원칙: 남의 실적 금액은 어떤 경로로도 못 보게 한다.
순위는 내 등수와 익명 평균선만 내려간다 (services.my_sales._ranking).

그래서 emp_name 은 **클라이언트가 정하지 않는다.** 세션(usr_seq)이 정한다.
`view_other_users` 권한이 있는 사람만 남을 골라 볼 수 있다 — 권한관리 화면에서
켜고 끈다(2026-08-11 권한 체계 전환. 그 전에는 usr_seq 여덟 개를 코드에 박아 뒀다).
"""

import logging
from dataclasses import dataclass
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import require_menu_access
from app.routers._access import require_user
from app.schemas.common import ApiResponse
from app.services import my_sales

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/my-sales", tags=["my-sales"])


def _error(code: str, message: str, http_status: int) -> JSONResponse:
    response = ApiResponse(success=False, code=code, message=message, data=None)
    return JSONResponse(
        status_code=http_status, content=response.model_dump(mode="json")
    )


# 이 화면을 열 수 있는가 — 권한관리 화면에서 켜고 끈다.
MENU_KEY = "mySales"


def can_view_others(db: Session, user: "dict[str, Any]") -> bool:
    """남의 실적을 볼 수 있는가.

    2026-08-11 권한 체계로 갈아탔다. 그 전에는 usr_seq 여덟 개를 이 파일에
    **박아** 두었는데(main 의 _VIEW_ALL_USERS), 명단을 고치려면 배포를 해야 했고
    같은 판단이 코드와 표 두 곳에 흩어져 한쪽만 고쳐지기 마련이었다.
    이제 권한관리 화면에서 켜는 `view_other_users` 하나가 정한다 —
    본사 재무·집행부·전산정보팀과 지사 재무 담당자가 기본으로 갖는다.
    """
    return bool(user.get("view_other_users"))


@dataclass(frozen=True)
class Scope:
    """이 요청이 무엇을 볼 수 있는가. 서버만 만든다.

    is_all 은 '사람이 아니라 지사(전사) 통짜' 다 (2026-08-10 요청).
    이때 name 은 None 이다 — 센티널 이름('전체'·'__ALL__')을 쓰면 그 문자열이
    active_names 의 IN 절, 상여의 이름 비교, 프로시저의 @Manager, 화면의 select
    값 동기화까지 그대로 흘러가 '__ALL__ 평가사' 같은 화면을 만든다.
    """

    name: "str | None"
    office: "str | None"
    allowed: bool
    is_all: bool = False


def _resolve_scope(
    db: Session,
    user: dict[str, Any],
    requested_name: "str | None",
    requested_office: str,
    requested_scope: "str | None" = None,
) -> Scope:
    """(볼 사람 이름, 지사코드, 남을 볼 권한) 을 서버가 정한다.

    권한이 없으면 요청에 뭐가 실려 오든 세션 값으로 덮어쓴다.
    이름만으로 사람을 가리는 게 안전한 근거: 재직 중 계정이 이름·지사까지
    같은 경우는 없다(2026-08-07 실측 — 동명이인 18명 전원 소속 지사가 다르다).
    """
    allowed = can_view_others(db, user)
    if not allowed:
        # 거절이 아니라 **강등**이다(원래 방식 그대로) — requested_* 는 읽지도
        # 않는다. 전체 요청도 여기서 조용히 본인 모드가 된다.
        return Scope(user["emp_name"], user["office_id"], False, False)

    name = (requested_name or "").strip() or user["emp_name"]
    if requested_office == "all":
        # 전 지사 열람은 지사 권한도 같이 있어야 한다.
        office = None if user["view_all_offices"] else user["office_id"]
    elif any(o["office_code"] == requested_office for o in user["offices"]):
        office = requested_office
    else:
        office = user["office_id"]
    # 전사 통짜는 두 관문을 **모두** 통과해야 성립한다 — 남 열람(can_view_others)
    # 과 전 지사 열람(view_all_offices). 후자가 없으면 위에서 이미 자기 지사로
    # 좁혀졌으므로 여기서 따로 막지 않아도 지사 통짜까지만 열린다.
    if requested_scope == "office":
        return Scope(None, office, True, True)
    return Scope(name, office, True, False)


@router.get("/appraisers", response_model=ApiResponse)
def list_appraisers(
    office_code: Annotated[str, Query(pattern=r"^[0-9A-Za-z]+$", max_length=10)] = "10",
    scope: Annotated[str | None, Query(pattern=r"^(mine|office)$")] = None,
    date_from: date | None = None,
    date_to: date | None = None,
    db: Session = Depends(get_db),
    user: dict[str, Any] = Depends(require_user),
) -> ApiResponse | JSONResponse:
    """고를 수 있는 평가사 목록 — 금액은 주지 않는다.

    권한이 없으면 본인 이름 하나만 준다 (목록으로 사내 실적자 명단이 새지 않게).
    """
    require_menu_access(user, MENU_KEY)
    today = date.today()
    start = date_from or date(today.year, 1, 1)
    end = date_to or today
    # 목록은 전체 모드와 무관하다 — 사람 이름만 준다. scope 파라미터는 받지만
    # 여기서는 쓰지 않는다(호출부가 네 곳에 같은 인자를 실어 보내기 때문).
    got = _resolve_scope(db, user, None, office_code)
    if not got.allowed:
        return ApiResponse(
            success=True, code="0000", message="조회 완료",
            data={"names": [user["emp_name"]], "count": 1, "can_view_others": False},
        )
    try:
        names = my_sales.appraiser_names(db, got.office, start, end)
    except LookupError as exc:
        return _error("OFFICE_NOT_MAPPED", str(exc), status.HTTP_404_NOT_FOUND)
    # '전체' 를 names 안에 문자열로 끼워 넣지 않는다 — names 는 사람 이름 목록이고
    # 화면의 선택 복원도 서버의 이름 비교도 전부 그 전제를 쓴다. 별도 깃발로 준다.
    return ApiResponse(
        success=True, code="0000", message="조회 완료",
        data={"names": names, "count": len(names), "can_view_others": True,
              "supports_all": True},
    )


@router.get("/dashboard", response_model=ApiResponse)
def get_dashboard(
    emp_name: Annotated[str | None, Query(max_length=60)] = None,
    office_code: Annotated[str, Query(pattern=r"^[0-9A-Za-z]+$", max_length=10)] = "10",
    scope: Annotated[str | None, Query(pattern=r"^(mine|office)$")] = None,
    date_from: date | None = None,
    date_to: date | None = None,
    db: Session = Depends(get_db),
    user: dict[str, Any] = Depends(require_user),
) -> ApiResponse | JSONResponse:
    require_menu_access(user, MENU_KEY)
    today = date.today()
    start = date_from or date(today.year, 1, 1)
    end = date_to or today
    if end < start:
        return _error(
            "INVALID_RANGE", "종료일이 시작일보다 빠릅니다.",
            status.HTTP_400_BAD_REQUEST,
        )
    got = _resolve_scope(db, user, emp_name, office_code, scope)
    try:
        data = my_sales.dashboard(
            db, emp_name=got.name, office_code=got.office,
            date_from=start, date_to=end, whole=got.is_all,
        )
    except LookupError as exc:
        return _error("OFFICE_NOT_MAPPED", str(exc), status.HTTP_404_NOT_FOUND)
    # 방금 계산한 것을 적어 둔다 — AI 분석이 몇 초 뒤 같은 숫자를 서술할 때
    # 처음부터 다시 계산하지 않게(실측 5.3초 절약). 읽기만 하는 쪽은 analyze 다.
    my_sales.remember_dashboard(
        got.name, got.office, start, end, got.is_all, data)
    data["viewer"] = {
        "emp_name": got.name,
        "is_self": (not got.is_all) and got.name == user["emp_name"],
        "can_view_others": got.allowed,
        "is_all": got.is_all,
    }
    return ApiResponse(success=True, code="0000", message="조회 완료", data=data)


@router.get("/analyze", response_model=ApiResponse)
def get_analysis(
    emp_name: Annotated[str | None, Query(max_length=60)] = None,
    office_code: Annotated[str, Query(pattern=r"^[0-9A-Za-z]+$", max_length=10)] = "10",
    scope: Annotated[str | None, Query(pattern=r"^(mine|office)$")] = None,
    date_from: date | None = None,
    date_to: date | None = None,
    db: Session = Depends(get_db),
    user: dict[str, Any] = Depends(require_user),
) -> ApiResponse | JSONResponse:
    """AI 분석 — 버튼을 눌렀을 때만 돈다 (자동 브리핑을 뺐던 이유가 비용·소음).

    조회 대상·범위는 대시보드와 같은 _resolve_scope 가 정한다 — 클라이언트가
    보낸 숫자는 아무것도 믿지 않고 서버가 사실표를 다시 계산한다.
    """
    require_menu_access(user, MENU_KEY)
    today = date.today()
    start = date_from or date(today.year, 1, 1)
    end = date_to or today
    if end < start:
        return _error("INVALID_RANGE", "종료일이 시작일보다 빠릅니다.",
                      status.HTTP_400_BAD_REQUEST)
    got = _resolve_scope(db, user, emp_name, office_code, scope)
    # AI 사실표·프롬프트가 전부 '평가사 한 명' 을 전제로 쓰여 있다. 전체를 그대로
    # 태우면 '평가사: None' 짜리 사실표가 나가거나, 더 나쁘게는 강등된 본인 실적을
    # 분석해 준다. 문안을 다시 쓸 때까지는 정직하게 막는다.
    if got.is_all:
        return _error("SCOPE_NOT_SUPPORTED",
                      "AI 분석은 평가사 개인 단위만 지원합니다.",
                      status.HTTP_400_BAD_REQUEST)
    name = got.name
    try:
        result = my_sales.analyze_dashboard(
            db, emp_name=name, office_code=got.office, date_from=start, date_to=end
        )
    except LookupError as exc:
        return _error("OFFICE_NOT_MAPPED", str(exc), status.HTTP_404_NOT_FOUND)
    if not result.get("ok"):
        return _error("ANALYZE_UNAVAILABLE",
                      result.get("message") or "AI 분석을 사용할 수 없습니다.",
                      status.HTTP_503_SERVICE_UNAVAILABLE)
    return ApiResponse(success=True, code="0000", message="분석 완료",
                       data={"emp_name": name, "text": result["text"]})


@router.get("/yearly", response_model=ApiResponse)
def get_yearly(
    emp_name: Annotated[str | None, Query(max_length=60)] = None,
    office_code: Annotated[str, Query(pattern=r"^[0-9A-Za-z]+$", max_length=10)] = "10",
    scope: Annotated[str | None, Query(pattern=r"^(mine|office)$")] = None,
    end_year: Annotated[int | None, Query(ge=2010, le=2100)] = None,
    db: Session = Depends(get_db),
    user: dict[str, Any] = Depends(require_user),
) -> ApiResponse | JSONResponse:
    """연도별 추이. 대시보드와 따로 부른다 — 첫 화면이 이걸 기다리지 않게."""
    require_menu_access(user, MENU_KEY)
    got = _resolve_scope(db, user, emp_name, office_code, scope)
    try:
        years = my_sales.yearly_trend(
            db, emp_name=got.name, office_code=got.office,
            end_year=end_year or date.today().year, whole=got.is_all,
        )
    except LookupError as exc:
        return _error("OFFICE_NOT_MAPPED", str(exc), status.HTTP_404_NOT_FOUND)
    my_sales.remember_years(
        got.name, got.office, end_year or date.today().year, got.is_all, years)
    return ApiResponse(
        success=True, code="0000", message="조회 완료",
        data={"emp_name": got.name, "is_all": got.is_all, "years": years},
    )


# ── 상여·가변비 (2026-08-10) ─────────────────────────────────────────────
# 대시보드에 얹지 않고 탭을 누를 때만 부른다. 상여는 bonus_report 를 달마다
# 돌아 **월당 3.7초**(실측)라, 첫 화면이 이걸 기다리면 안 된다.
# 조회 대상·범위는 다른 탭과 같은 _resolve_scope 가 정한다 — 클라이언트가
# 보낸 이름·지사를 믿지 않는다.


def _period(date_from: "date | None", date_to: "date | None") -> "tuple[date, date]":
    today = date.today()
    return (date_from or date(today.year, 1, 1)), (date_to or today)


@router.get("/variable-cost", response_model=ApiResponse)
def get_variable_cost(
    emp_name: Annotated[str | None, Query(max_length=60)] = None,
    office_code: Annotated[str, Query(pattern=r"^[0-9A-Za-z]+$", max_length=10)] = "10",
    scope: Annotated[str | None, Query(pattern=r"^(mine|office)$")] = None,
    date_from: date | None = None,
    date_to: date | None = None,
    db: Session = Depends(get_db),
    user: dict[str, Any] = Depends(require_user),
) -> ApiResponse | JSONResponse:
    """월별 가변비. 상여 시트 '5.가변비' 와 같은 원천(APW_IW_MONGABUNBI)이다."""
    require_menu_access(user, MENU_KEY)
    start, end = _period(date_from, date_to)
    got = _resolve_scope(db, user, emp_name, office_code, scope)
    # 전체는 막는다. 이름 목록으로 루프를 돌리면 안 된다 — 가변비는 사람·달마다
    # 프로시저 한 번(3.5~5초)이라 8개월×82명이면 워커 4로도 10분이 넘고, 워커를
    # 늘리면 연결 풀(기본 5+10)에 막혀 다른 화면까지 같이 죽는다. 상여는 값은
    # 싸지만 본사 전용 규칙(01-% · 1000)이라 지사 전체에서 숫자가 거짓말을 한다.
    if got.is_all:
        return _error("SCOPE_NOT_SUPPORTED",
                      "가변비는 평가사 개인 단위만 지원합니다.",
                      status.HTTP_400_BAD_REQUEST)
    name = got.name
    data = my_sales.variable_costs(db, emp_name=name, date_from=start, date_to=end)
    return ApiResponse(
        success=True, code="0000", message="조회 완료",
        data={"emp_name": name, **data},
    )


@router.get("/bonus", response_model=ApiResponse)
def get_bonus_months(
    emp_name: Annotated[str | None, Query(max_length=60)] = None,
    office_code: Annotated[str, Query(pattern=r"^[0-9A-Za-z]+$", max_length=10)] = "10",
    scope: Annotated[str | None, Query(pattern=r"^(mine|office)$")] = None,
    date_from: date | None = None,
    date_to: date | None = None,
    db: Session = Depends(get_db),
    user: dict[str, Any] = Depends(require_user),
) -> ApiResponse | JSONResponse:
    """월별 상여. 기간이 길면 그만큼 걸린다 — 화면이 미리 알려 주고 부른다."""
    require_menu_access(user, MENU_KEY)
    start, end = _period(date_from, date_to)
    got = _resolve_scope(db, user, emp_name, office_code, scope)
    # 전체는 막는다. 이름 목록으로 루프를 돌리면 안 된다 — 가변비는 사람·달마다
    # 프로시저 한 번(3.5~5초)이라 8개월×82명이면 워커 4로도 10분이 넘고, 워커를
    # 늘리면 연결 풀(기본 5+10)에 막혀 다른 화면까지 같이 죽는다. 상여는 값은
    # 싸지만 본사 전용 규칙(01-% · 1000)이라 지사 전체에서 숫자가 거짓말을 한다.
    if got.is_all:
        return _error("SCOPE_NOT_SUPPORTED",
                      "상여는 평가사 개인 단위만 지원합니다.",
                      status.HTTP_400_BAD_REQUEST)
    name = got.name
    data = my_sales.bonus_months(db, emp_name=name, date_from=start, date_to=end)
    return ApiResponse(
        success=True, code="0000", message="조회 완료",
        data={"emp_name": name, **data},
    )
