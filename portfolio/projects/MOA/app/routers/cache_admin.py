"""전표 캐시 수동 동기화 (권한부여 화면의 관리 기능, 본사 전용 화면에서 사용).

최근 일수 또는 시작일·종료일을 입력받아 해당 기간 전표를 Amaranth에서 다시
받아온다. 관리번호 정정 등 자동 동기화 범위 밖의 과거 전표 수정을 반영한다.

동기화는 수 분이 걸릴 수 있어 백그라운드 스레드로 실행하고 화면은 상태를 폴링한다.
예약 작업을 포함한 모든 전표 동기화는 SQL Server 공통 잠금으로 동시에 하나만
실행한다.
"""

import threading
from datetime import date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, model_validator

from app.schemas.common import ApiResponse
from fastapi.responses import JSONResponse

from app.dependencies import AccessContext, require_menu
from app.routers.permissions import _head_office_only
from app.services.voucher_sync_runner import (
    VoucherSyncAlreadyRunning,
    execute_voucher_sync,
)

router = APIRouter(prefix="/api/cache-sync", tags=["cache-sync"])

# 전체 이력(2010~)은 재수집 가능 여부가 확인되지 않아(수집 출처 불명) 대량
# 삭제-재삽입을 막는다. 1년 넘게 거슬러야 하면 별도 검토 후 CLI로 실행할 것.
MAX_DAYS = 365

_lock = threading.Lock()
_state: "dict[str, Any]" = {
    "running": False, "mode": None, "days": None,
    "date_from": None, "date_to": None, "progress": None,
    "started_at": None, "finished_at": None, "result": None, "error": None,
}


class SyncRequest(BaseModel):
    days: int | None = Field(
        default=None, ge=1, le=MAX_DAYS, description="오늘부터 거슬러 갈 일수"
    )
    date_from: date | None = None
    date_to: date | None = None

    @model_validator(mode="after")
    def validate_period(self) -> "SyncRequest":
        has_days = self.days is not None
        has_range = self.date_from is not None or self.date_to is not None
        if has_days == has_range:
            raise ValueError("최근 일수 또는 시작일·종료일 중 하나만 입력하세요.")
        if has_range:
            if self.date_from is None or self.date_to is None:
                raise ValueError("시작일과 종료일을 함께 입력하세요.")
            if self.date_from > self.date_to:
                raise ValueError("시작일은 종료일보다 늦을 수 없습니다.")
            if self.date_to > date.today():
                raise ValueError("종료일은 오늘보다 늦을 수 없습니다.")
            if (self.date_to - self.date_from).days + 1 > MAX_DAYS:
                raise ValueError(f"한 번에 동기화할 수 있는 기간은 최대 {MAX_DAYS}일입니다.")
        return self

    def resolve_period(self) -> tuple[date, date, str]:
        if self.days is not None:
            date_to = date.today()
            return date_to - timedelta(days=self.days - 1), date_to, "days"
        assert self.date_from is not None and self.date_to is not None
        return self.date_from, self.date_to, "range"


def _status() -> "dict[str, Any]":
    return dict(_state)


def _run(date_from: date, date_to: date) -> None:
    global _state

    def report(message: str) -> None:
        global _state
        _state = {**_state, "progress": message}

    try:
        total_days = (date_to - date_from).days + 1
        result = execute_voucher_sync(
            date_from,
            date_to,
            monthly_chunks=total_days > 31,
            progress=report,
        )
        _state = {**_state, "result": result, "error": None}
    except VoucherSyncAlreadyRunning as exc:
        _state = {**_state, "result": None, "error": str(exc)}
    except Exception as exc:  # 백그라운드 스레드라 상태로만 전달한다
        _state = {**_state, "result": None, "error": str(exc)}
    finally:
        _state = {
            **_state, "running": False,
            "finished_at": datetime.now().isoformat(timespec="seconds"),
        }


@router.post("/run", response_model=ApiResponse)
def run_sync(
    request: SyncRequest,
    _access: AccessContext = Depends(require_menu("permissionManage")),
    # permissionManage 는 지사에게도 열린다(available_menu_keys). 그런데 이
    # 배치는 **전 지사 전표**를 최대 365일치 지우고 다시 넣는다 — 지사 관리자
    # 한 사람이 전사 자료를 갈아엎을 수 있었다(2026-08-17 전수조사). 화면은
    # 본사로 막혀 있었지만 API 는 안 막혀 있어, 주소를 아는 사람에게 그대로
    # 열려 있던 셈이다. 묶음 정의 편집과 같은 잣대로 본사만 허용한다.
) -> "ApiResponse | JSONResponse":
    denied = _head_office_only(_access)
    if denied is not None:
        return denied
    global _state
    date_from, date_to, mode = request.resolve_period()
    total_days = (date_to - date_from).days + 1
    with _lock:
        if _state["running"]:
            return ApiResponse(
                success=False, code="SYNC_RUNNING",
                message="이미 동기화가 실행 중입니다. 끝난 뒤 다시 시도하세요.",
                data=_status(),
            )
        _state = {
            "running": True, "mode": mode, "days": total_days,
            "date_from": date_from.isoformat(), "date_to": date_to.isoformat(),
            "progress": "시작 중...",
            "started_at": datetime.now().isoformat(timespec="seconds"),
            "finished_at": None, "result": None, "error": None,
        }
    threading.Thread(
        target=_run,
        args=(date_from, date_to),
        daemon=True,
        name="manual-cache-sync",
    ).start()
    return ApiResponse(
        success=True, code="0000",
        message=(
            f"{date_from.isoformat()}~{date_to.isoformat()} "
            f"전표 동기화를 시작했습니다."
        ),
        data=_status(),
    )


@router.get("/status", response_model=ApiResponse)
def sync_status(
    _access: AccessContext = Depends(require_menu("permissionManage")),
    # permissionManage 는 지사에게도 열린다(available_menu_keys). 그런데 이
    # 배치는 **전 지사 전표**를 최대 365일치 지우고 다시 넣는다 — 지사 관리자
    # 한 사람이 전사 자료를 갈아엎을 수 있었다(2026-08-17 전수조사). 화면은
    # 본사로 막혀 있었지만 API 는 안 막혀 있어, 주소를 아는 사람에게 그대로
    # 열려 있던 셈이다. 묶음 정의 편집과 같은 잣대로 본사만 허용한다.
) -> "ApiResponse | JSONResponse":
    denied = _head_office_only(_access)
    if denied is not None:
        return denied
    return ApiResponse(success=True, code="0000", message="조회 완료", data=_status())
