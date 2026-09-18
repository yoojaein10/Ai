import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.api.v1.salary_audit import client_ip, log_access
from app.core.deps import require_roles
from app.db.models import SalaryVaultPolicy, User
from app.db.session import get_apw_db, get_db
from app.schemas.salary_policy import PolicyCheckResponse, PolicyRow, PolicyUpsert
from app.services import salary_seat

router = APIRouter(prefix="/salary", tags=["salary"])
logger = logging.getLogger(__name__)


def _active_policy(db: Session) -> Optional[SalaryVaultPolicy]:
    return (
        db.query(SalaryVaultPolicy)
        .filter(SalaryVaultPolicy.is_active == True)  # noqa: E712
        .first()
    )


@router.get("/policy/check", response_model=PolicyCheckResponse)
def check_policy(
    request: Request,
    db: Session = Depends(get_db),
    apw_db: Optional[Session] = Depends(get_apw_db),
    current_user: User = Depends(require_roles("SYSTEM_ADMIN", "HR_ADMIN")),
) -> PolicyCheckResponse:
    """접속 IP가 이 사용자에게 허용된 자리인지 판정한다.

    허용 경로는 둘 중 하나면 된다.
      1. 좌석 규칙: APW SEAT_USERINFO에서 APWID = login_id 인 행의 UID로
         기대 IP(SALARY_SEAT_IP_PREFIX + UID)를 만들어 접속 IP와 비교
      2. 수동 허용: 관리자가 등록한 활성 정책(owner = 이 사용자, allowed_ip = 접속 IP)
    둘 다 아니면 거부한다. 좌석 매핑이 없거나 APW 조회가 실패해도 거부한다(fail-closed).
    """
    ip = client_ip(request)
    login_id = current_user.login_id

    # 1) 좌석 규칙
    seat_expected_ip: Optional[str] = None
    try:
        uid = salary_seat.lookup_seat_uid(apw_db, login_id)
        if uid is not None:
            seat_expected_ip = salary_seat.expected_ip_for_uid(uid)
    except Exception as exc:  # noqa: BLE001 — 외부 DB 장애는 거부로 처리
        logger.warning("SEAT_USERINFO 조회 실패(login_id=%s): %s", login_id, exc)
    seat_ok = seat_expected_ip is not None and ip == seat_expected_ip

    # 2) 수동 허용 (이 사용자 소유의 활성 정책만)
    policy = (
        db.query(SalaryVaultPolicy)
        .filter(
            SalaryVaultPolicy.owner_user_id == current_user.id,
            SalaryVaultPolicy.is_active == True,  # noqa: E712
        )
        .first()
    )
    manual_ok = policy is not None and policy.allowed_ip == ip

    if seat_ok or manual_ok:
        return PolicyCheckResponse(
            allowed=True,
            current_ip=ip,
            login_id=login_id,
            configured=policy is not None,
            seat_expected_ip=seat_expected_ip,
            via="seat" if seat_ok else "manual",
        )

    log_access(db, user_id=current_user.id, action="IP_DENIED", request=request)
    db.commit()
    return PolicyCheckResponse(
        allowed=False,
        current_ip=ip,
        login_id=login_id,
        configured=policy is not None,
        seat_expected_ip=seat_expected_ip,
        via=None,
        reason=f"IP {ip or '확인 불가'} 및 접근 ID {login_id}에 연봉 접근 권한이 없습니다.",
    )


@router.get("/policy", response_model=Optional[PolicyRow])
def get_policy(
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("SYSTEM_ADMIN")),
) -> Optional[PolicyRow]:
    policy = _active_policy(db)
    return PolicyRow.model_validate(policy) if policy else None


@router.put("/policy", response_model=PolicyRow)
def upsert_policy(
    data: PolicyUpsert,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("SYSTEM_ADMIN")),
) -> PolicyRow:
    owner = db.query(User).filter(User.id == data.owner_user_id).first()
    if owner is None:
        raise HTTPException(status_code=400, detail="담당자를 찾을 수 없습니다")

    # 활성 정책은 항상 최대 1개다. 스키마는 owner_user_id UNIQUE만 강제하므로
    # (Task 5 리뷰 지적) 다른 소유자의 활성 행을 여기서 먼저 비활성화한다.
    other_active = (
        db.query(SalaryVaultPolicy)
        .filter(
            SalaryVaultPolicy.owner_user_id != data.owner_user_id,
            SalaryVaultPolicy.is_active == True,  # noqa: E712
        )
        .all()
    )
    for other in other_active:
        other.is_active = False

    policy = (
        db.query(SalaryVaultPolicy)
        .filter(SalaryVaultPolicy.owner_user_id == data.owner_user_id)
        .first()
    )
    if policy is None:
        policy = SalaryVaultPolicy(
            owner_user_id=data.owner_user_id,
            allowed_ip=data.allowed_ip,
            is_active=True,
            updated_by=current_user.id,
            updated_at=datetime.now(),
        )
        db.add(policy)
    else:
        policy.allowed_ip = data.allowed_ip
        policy.is_active = True
        policy.updated_by = current_user.id
        policy.updated_at = datetime.now()

    db.flush()

    # 정책 변경과 그 감사 기록은 한 트랜잭션이어야 한다 — 아래 commit 하나로 함께
    # 커밋되고, 감사 기록이 실패하면 정책 변경도 함께 롤백된다 (log_access는
    # flush만 하고 커밋하지 않는다).
    log_access(
        db,
        user_id=current_user.id,
        action="POLICY_CHANGE",
        request=request,
        target_user_id=data.owner_user_id,
    )

    db.commit()
    db.refresh(policy)
    return PolicyRow.model_validate(policy)
