"""약식(400*) 입금전표 회차 수동 실행 (권한 관리 화면의 관리 기능, 본사 전용).

약식 묶음전표는 하루 1장을 유지하려고 17시 예약 회차(A10Bridge_DepositVoucherYak)
에서만 나간다. 재무팀이 그 전에 전표가 필요하면 지금까지는 서버에 접속해
`schtasks /run /tn A10Bridge_DepositVoucherYak` 을 손으로 쳤다 — 그 한 줄을
버튼으로 옮긴 것이다.

배치 로직을 여기서 다시 돌리지 않고 **예약 작업 자체를** 즉시 실행한다:
작업 스케줄러가 같은 작업의 중복 실행을 막아 주고(17시 회차·연타와 겹쳐도
안전), 로그도 기존 logs\\deposit_voucher_yak.log 한 곳에 쌓인다. 결과는 그
로그 꼬리를 폴링해 보여준다 — schtasks /run 은 시작만 하고 바로 돌아온다.
"""

import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.dependencies import AccessContext, require_menu
from app.routers.permissions import _head_office_only
from app.schemas.common import ApiResponse

router = APIRouter(prefix="/api/deposit-yak", tags=["deposit-yak"])

# server_redeploy.ps1 이 등록하는 이름 그대로 — 바꾸면 배포 스크립트도 같이.
TASK_NAME = "A10Bridge_DepositVoucherYak"
LOG_PATH = Path(__file__).resolve().parents[2] / "logs" / "deposit_voucher_yak.log"


def _console_text(raw: bytes) -> str:
    # schtasks 콘솔 출력과 배치 로그는 한국어 Windows 기본 코드페이지(cp949)다.
    return raw.decode("cp949", errors="replace").strip()


def _log_tail(path: Path = LOG_PATH, size: int = 4096) -> "dict[str, Any]":
    """배치 로그의 마지막 몇 줄 — 회차가 끝나면 '전표 전송: …' 줄이 새로 붙는다."""
    if not path.exists():
        return {"exists": False, "updated_ts": None, "updated_at": None, "lines": []}
    stat = path.stat()
    with path.open("rb") as fh:
        fh.seek(max(0, stat.st_size - size))
        data = fh.read()
    lines = [line.strip() for line in _console_text(data).splitlines() if line.strip()]
    return {
        "exists": True,
        "updated_ts": stat.st_mtime,
        "updated_at": datetime.fromtimestamp(stat.st_mtime).isoformat(
            timespec="seconds"
        ),
        "lines": lines[-6:],
    }


@router.post("/run", response_model=ApiResponse)
def run_yak(
    _access: AccessContext = Depends(require_menu("permissionManage")),
    # permissionManage 는 지사에게도 열린다 — 이 버튼은 실제 아마란스 전표를
    # 만드는 배치라 캐시 동기화와 같은 잣대로 본사만 허용한다(cache_admin 참조).
) -> "ApiResponse | JSONResponse":
    denied = _head_office_only(_access)
    if denied is not None:
        return denied
    try:
        proc = subprocess.run(
            ["schtasks", "/run", "/tn", TASK_NAME],
            capture_output=True,
            timeout=20,
        )
    except FileNotFoundError:
        return ApiResponse(
            success=False, code="YAK_NO_SCHTASKS",
            message="schtasks 를 찾지 못했습니다 — Windows 서버에서만 실행할 수 있습니다.",
        )
    except subprocess.TimeoutExpired:
        return ApiResponse(
            success=False, code="YAK_TIMEOUT",
            message="예약 작업 실행 요청이 시간 안에 끝나지 않았습니다.",
        )
    if proc.returncode != 0:
        detail = _console_text(proc.stderr) or _console_text(proc.stdout)
        return ApiResponse(
            success=False, code="YAK_RUN_FAILED",
            message=f"예약 작업({TASK_NAME})을 실행하지 못했습니다: {detail}",
        )
    return ApiResponse(
        success=True, code="0000",
        message="약식 회차를 시작했습니다. 끝나면 결과가 아래에 표시됩니다.",
        data={"triggered_ts": time.time()},
    )


@router.get("/status", response_model=ApiResponse)
def yak_status(
    _access: AccessContext = Depends(require_menu("permissionManage")),
) -> "ApiResponse | JSONResponse":
    denied = _head_office_only(_access)
    if denied is not None:
        return denied
    return ApiResponse(success=True, code="0000", message="조회 완료", data=_log_tail())
