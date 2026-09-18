"""보수기준 점검 API (본사 관리 화면).

업무실적과 같은 모집단(지사·반월·기준)에서 감정서별로
수수료청구서 입력값(APW_IW_SuSuList) vs 자동판별 보수기준을 비교한다.
"""

import hmac
import logging
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.common import ApiResponse
from app.services import fee_basis
from app.services.excel_export import XLSX_MEDIA_TYPE, build_xlsx, xlsx_headers
from app.services.fee_basis import (
    Filter,
    OpinionSourceChanged,
    OpinionValidationError,
    RunExpired,
    RunNotFound,
    RunStoreUnavailable,
    find_prepared_run,
    save_prepared_run,
)
from app.services.users import UserContextError, UserContextService
from app.services.work_report import Basis, Half

router = APIRouter(prefix="/api/fee-basis", tags=["fee-basis"])

# 권한 정책의 메뉴 키(access_policy.MENU_KEYS). 문자열로 두는 이유: 새 권한 모듈이 없는
# 서버에도 이 파일만 배포할 수 있어야 해서 access_policy 를 임포트하지 않는다.
FEE_BASIS_MENU_KEY = "feeBasis"

logger = logging.getLogger(__name__)


def _require_hq_user(
    db: Session = Depends(get_db),
    header_usr_seq: "str | None" = Header(None, alias="X-MOA-USR-SEQ"),
    query_usr_seq: "str | None" = Query(None, alias="usr_seq"),
    query_usr: "str | None" = Query(None, alias="usr"),
) -> dict[str, Any]:
    """운영본의 기존 사용자 검증만 재사용해 본사 사용자로 제한한다.

    새 권한 모듈을 함께 배포하지 않아도 되며, 화면 숨김이 아니라 API에서 차단한다.
    """
    raw = header_usr_seq or query_usr_seq or query_usr
    if not raw or not str(raw).isdigit():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="사용자 확인이 필요합니다.",
        )
    try:
        access = UserContextService(db)._resolve(str(raw))
    except (UserContextError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="사용자 권한을 확인할 수 없습니다.",
        ) from exc
    # 2026-08-07: 소속으로 막던 것을 걷었다. 지사 재무도 자기 지사 건을 본다.
    # 대신 아래 메뉴 권한(feeBasis)이 유일한 문지기이고, 조회 범위는
    # _scoped_office 가 로그인 지사로 강제한다 — 남의 지사는 여전히 못 본다.
    # 지사는 사전생성 배치가 돌지 않아 첫 조회가 30~70초 걸린다(그 뒤 캐시).
    # 소속만 보면 본사 전 직원이 열 수 있다(실측: 메뉴 0개인 평가1부 직원도 실데이터를
    # 받았다). 메뉴 권한까지 본다.
    #
    # 새 권한 모듈(access_policy)을 함께 배포하지 않은 서버에서는 menu_permissions 자체가
    # 없다. 그때는 종전대로 본사 검사만으로 통과시킨다 — 이 파일을 단독 배포해도
    # 깨지지 않아야 한다(docs/FEE_BASIS_DEPLOY_CHECKLIST.md 의 5파일 배포).
    menus = access.get("menu_permissions")
    if isinstance(menus, dict) and menus and not menus.get(FEE_BASIS_MENU_KEY, False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="이 메뉴를 사용할 권한이 없습니다.",
        )
    return access


def _scoped_office(access: "dict[str, Any]", requested: str) -> str:
    """조회 지사를 로그인 사용자의 허용 범위로 강제한다.

    본사 전용 화면이지만 본사 안에서도 전체지사 조회 권한이 없는 사용자가 있다.
    새 권한 모듈 없이도 돌아가도록 access dict 만 본다(dependencies 를 임포트하지 않는다).
    """
    if access.get("view_all_offices"):
        return requested
    own = str(access.get("office_id") or "")
    if str(requested) != own:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="다른 지사 자료를 조회할 수 없습니다.",
        )
    return requested


def _cached_snapshot(
    db: Session,
    *,
    office_code: str,
    year: int,
    month: int,
    half: Half,
    basis: Basis,
    refresh: bool = False,
) -> "tuple[Any, dict, bool]":
    """동결 스냅숏을 재사용하거나 새로 만든다. (run, 스냅숏, 캐시 적중 여부)

    원천 조회가 반월당 30~70초라서 같은 조건을 다시 볼 때마다 다시 계산하지 않는다.
    규칙 버전이 바뀌거나 유효기간이 지나면 is_fresh가 걸러낸다.

    run이 None이면 스냅숏을 저장하지 못한 것이다 — 조회는 되지만 의견 저장은 안 된다.
    """
    if not refresh:
        try:
            cached = find_prepared_run(
                office_code=office_code, year=year, month=month,
                basis=basis, half=half, profile=fee_basis.SNAPSHOT_PROFILE, db=db,
            )
            if fee_basis.is_fresh(cached.data):
                return cached, cached.data, True
        except (RunNotFound, RunExpired):
            pass

    snapshot = fee_basis.build_snapshot(
        db, office_id=office_code, year=year, month=month, half=half, basis=basis
    )
    try:
        run = save_prepared_run(
            snapshot, office_code=office_code, half=half,
            profile=fee_basis.SNAPSHOT_PROFILE, db=db,
        )
    except (RunStoreUnavailable, ValueError):
        logger.warning("보수기준 점검 스냅숏 저장 실패", exc_info=True)
        raise RunStoreUnavailable(
            "보수기준 점검 스냅숏을 운영 DB에 저장할 수 없습니다."
        )
    return run, run.data, False


class SnapshotSourceChanged(RuntimeError):
    pass


def _bound_snapshot(
    db: Session,
    *,
    run_id: str,
    source_sha256: str,
    office_code: str,
    year: int,
    month: int,
    half: Half,
    basis: Basis,
) -> Any:
    """Return only the exact snapshot that the browser actually displayed."""
    try:
        run = find_prepared_run(
            office_code=office_code,
            year=year,
            month=month,
            half=half,
            basis=basis,
            profile=fee_basis.SNAPSHOT_PROFILE,
            db=db,
        )
    except (RunNotFound, RunExpired) as exc:
        raise SnapshotSourceChanged(
            "조회한 원천이 만료되었습니다. 다시 조회해 주세요."
        ) from exc
    if (
        run.run_id != run_id
        or not hmac.compare_digest(
            str(run.source_sha256 or ""), str(source_sha256 or "")
        )
    ):
        raise SnapshotSourceChanged(
            "조회 후 원천 데이터가 변경되었습니다. 다시 조회해 주세요."
        )
    return run


@router.get("", response_model=ApiResponse)
def get_report(
    year: int = Query(ge=2020, le=2100),
    month: int = Query(ge=1, le=12),
    half: Half = Query(),
    basis: Basis = "매출",
    office_code: str = Query("10", pattern=r"^[0-9A-Za-z]{1,10}$"),
    flt: Filter = "전체",
    page: int = Query(1, ge=1, le=1000),
    page_size: int = Query(50, ge=1, le=100000),
    _access: dict[str, Any] = Depends(_require_hq_user),
    db: Session = Depends(get_db),
) -> ApiResponse:
    # refresh 파라미터는 뺐다 — 외부에서 반복 호출하면 80초 원천 재생성을 무한히
    # 시킬 수 있다(검토 발견). 강제 재생성은 배치(fee_basis_prepare)가 담당한다.
    office_code = _scoped_office(_access, office_code)
    try:
        run, snapshot, cache_hit = _cached_snapshot(
            db, office_code=office_code, year=year, month=month,
            half=half, basis=basis,
        )
    except RunStoreUnavailable:
        logger.exception("보수기준 점검 저장소 조회 실패")
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "success": False,
                "code": "RUN_STORE_UNAVAILABLE",
                "message": "보수기준 점검 저장소를 사용할 수 없습니다.",
                "data": None,
            },
        )
    except Exception:
        # 예외 원문을 화면에 돌려주면 접속 정보·테이블 구조가 새어나간다. 로그에만 남긴다.
        logger.exception("보수기준 점검 조회 실패")
        return ApiResponse(
            success=False, code="ERROR",
            message="보수기준 점검을 조회할 수 없습니다. 관리자에게 문의해 주세요.",
            data=None,
        )
    try:
        opinions, opinion_source = fee_basis.load_with_source(
            db, office_code=office_code, year=year, month=month,
            half=half, basis=basis,
        )
    except RunStoreUnavailable:
        logger.exception("보수기준 점검 의견 저장소 조회 실패")
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "success": False,
                "code": "OPINION_STORE_UNAVAILABLE",
                "message": "저장 의견을 확인할 수 없어 조회를 중단했습니다.",
                "data": None,
            },
        )
    view = fee_basis.select_view(
        snapshot, flt=flt, page=page, page_size=page_size, opinions=opinions,
    )
    # 감정서번호로 맞추므로 의견이 엉뚱한 행에 붙지는 않는다. 다만 저장 당시와 금액이
    # 달라졌으면 금액을 적은 의견(`수수료차액발생 170,344`)이 낡았을 수 있다.
    current_source = str((run.source_sha256 if run else "") or "")
    view["opinions_stale"] = bool(
        opinions and opinion_source and current_source
        and opinion_source != current_source
    )
    view["cache_hit"] = cache_hit
    view["prepared_at"] = snapshot.get("prepared_at")
    # 의견을 저장하려면 어느 스냅숏에 대한 것인지 알아야 한다. run_id가 없으면
    # 스냅숏 저장이 실패한 것이므로 화면은 저장 버튼을 비활성해야 한다.
    view["run_id"] = run.run_id if run else None
    view["source_sha256"] = run.source_sha256 if run else None
    return ApiResponse(success=True, code="0000", message="조회 완료", data=view)


class FeeBasisOpinionUpdate(BaseModel):
    """변경한 감정서만 보낸다. 보내지 않은 감정서의 저장 의견은 그대로 남는다.

    키가 행 번호가 아니라 감정서번호인 이유: 행 번호는 순번이라 원천에 행이 추가·삭제
    되면 5행이 다른 감정서가 되고 옛 의견이 엉뚱한 행에 붙는다.
    """

    run_id: str = Field(min_length=1, max_length=40)
    source_sha256: str = Field(pattern=r"^[0-9A-Fa-f]{64}$")
    # 빈 문자열은 '담당자가 일부러 비웠다'는 기록으로 저장한다. 자동 제안으로 되돌리려면
    # null 을 보낸다 — 그때만 기록을 지운다.
    opinions: "dict[str, str | None]" = Field(default_factory=dict)


@router.patch("/opinions", response_model=ApiResponse)
def save_opinions(
    request: FeeBasisOpinionUpdate,
    year: int = Query(ge=2020, le=2100),
    month: int = Query(ge=1, le=12),
    half: Half = Query(),
    basis: Basis = "매출",
    office_code: str = Query("10", pattern=r"^[0-9A-Za-z]{1,10}$"),
    _access: dict[str, Any] = Depends(_require_hq_user),
    db: Session = Depends(get_db),
) -> "ApiResponse | JSONResponse":
    """담당자 의견을 스냅숏과 분리된 행에 저장한다.

    스냅숏은 배치가 갈아엎지만 이 행은 건드리지 않는다. 실측: 종전 구조에서는
    의견을 저장한 뒤 배치를 돌리면 의견이 사라졌다.
    """
    office_code = _scoped_office(_access, office_code)
    try:
        merged = fee_basis.save(
            db, office_code=office_code, year=year, month=month,
            half=half, basis=basis, opinions=request.opinions,
            snapshot_run_id=request.run_id,
            snapshot_source_sha256=request.source_sha256,
            snapshot_profile=fee_basis.SNAPSHOT_PROFILE,
        )
    except OpinionSourceChanged as exc:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "success": False, "code": "SOURCE_CHANGED",
                "message": str(exc), "data": None,
            },
        )
    except OpinionValidationError as exc:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "success": False, "code": "INVALID_OPINION",
                "message": str(exc), "data": None,
            },
        )
    except RunStoreUnavailable as exc:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "success": False, "code": "RUN_STORE_UNAVAILABLE",
                "message": str(exc), "data": None,
            },
        )
    except Exception:
        logger.exception("보수기준 점검 의견 저장 실패")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "success": False, "code": "ERROR",
                "message": "의견을 저장할 수 없습니다. 관리자에게 문의해 주세요.",
                "data": None,
            },
        )
    return ApiResponse(
        success=True, code="0000", message="의견을 저장했습니다.",
        data={"saved_count": len(merged)},
    )


@router.get("/export.xlsx", response_model=None)
def export(
    year: int = Query(ge=2020, le=2100),
    month: int = Query(ge=1, le=12),
    half: Half = Query(),
    basis: Basis = "매출",
    office_code: str = Query("10", pattern=r"^[0-9A-Za-z]{1,10}$"),
    flt: Filter = "전체",
    run_id: str = Query(min_length=1, max_length=40),
    source_sha256: str = Query(pattern=r"^[0-9A-Fa-f]{64}$"),
    _access: dict[str, Any] = Depends(_require_hq_user),
    db: Session = Depends(get_db),
) -> Response:
    # 화면과 같은 동결 스냅숏을 쓴다. 여기서 원천을 다시 조회하면 화면과 엑셀의
    # 행·금액이 어긋날 수 있다(원천 전표가 조회 사이에 계상되면 실제로 달라진다).
    office_code = _scoped_office(_access, office_code)
    try:
        run = _bound_snapshot(
            db,
            run_id=run_id,
            source_sha256=source_sha256,
            office_code=office_code,
            year=year,
            month=month,
            half=half,
            basis=basis,
        )
        snapshot = run.data
        opinions = fee_basis.load(
            db, office_code=office_code, year=year, month=month,
            half=half, basis=basis,
        )
    except SnapshotSourceChanged as exc:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "success": False, "code": "SOURCE_CHANGED",
                "message": str(exc), "data": None,
            },
        )
    except RunStoreUnavailable:
        logger.exception("보수기준 점검 엑셀 저장소 조회 실패")
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "success": False, "code": "RUN_STORE_UNAVAILABLE",
                "message": "저장소를 확인할 수 없어 엑셀 생성을 중단했습니다.",
                "data": None,
            },
        )
    except Exception:
        # 예외 원문을 내보내면 접속 정보가 샌다. 파일 대신 짧은 오류를 돌려준다.
        logger.exception("보수기준 점검 엑셀 생성 실패")
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "success": False, "code": "ERROR",
                "message": "엑셀을 생성할 수 없습니다. 잠시 후 다시 시도해 주세요.",
                "data": None,
            },
        )
    data = fee_basis.select_view(
        snapshot, flt=flt, page=1, page_size=1_000_000,
        opinions=opinions,
    )
    # 엑셀은 화면과 같은 열·같은 순서다. 끝에 의견 하나만 더 붙인다.
    # 화면을 보고 엑셀을 읽을 때 열이 다르면 옮겨 적는 일이 생긴다.
    rows = [
        {
            **item,
            # 화면은 업무와 세부목적을 한 칸에 보여준다. 엑셀도 같게 둔다.
            "work_purpose": " / ".join(
                part for part in (item.get("work"), item.get("purpose")) if part
            ),
            # 화면은 격차율을 %로 보여준다. 엑셀도 같은 숫자를 넣어야 옮겨 적지 않는다.
            # `+ 0.0` 은 -0.0 을 지우는 것이다 — 원 단위 반올림으로 1원 어긋난 행이
            # 엑셀에서 '-0.0' 으로 찍혀 깎인 것처럼 보이던 것을 막는다(화면도 같다).
            "gap_rate_pct": (
                round(item["reference_gap_rate"] * 100, 1) + 0.0
                if item.get("reference_gap_rate") is not None else None
            ),
        }
        for item in data["items"]
    ]
    columns = [
        ("doc_id", "감정서번호"), ("receipt_date", "접수일"),
        ("cust_name", "거래처"), ("work_purpose", "업무 / 세부목적"),
        ("manager", "유치자"), ("appraisal_amount", "감정평가액"),
        ("rate_applied_fee", "요율적용금액"), ("actual_fee", "순수수료"),
        ("gap_rate_pct", "격차율(%)"),
        # 할인 적정성(업무연락 제2026-38호) — 화면 배지와 같은 값.
        ("discount_state", "할인 점검"), ("discount_note", "할인 점검 비고"),
        ("primary_label", "자동판별"), ("effective_opinion", "의견"),
    ]
    name = f"보수기준점검_{year}.{month:02d}_{half}_{basis}_{office_code}"
    return Response(
        content=build_xlsx("보수기준점검", columns, rows),
        media_type=XLSX_MEDIA_TYPE,
        headers=xlsx_headers(name),
    )
