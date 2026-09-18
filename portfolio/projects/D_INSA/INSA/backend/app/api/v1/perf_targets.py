from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.db.models import User
from app.db.session import get_db
from app.schemas.perf_target import (
    PerfTargetCreate,
    PerfTargetResponse,
    PerfTargetUpdate,
)
from app.services.perf_target import (
    approve_target,
    create_target,
    get_target,
    is_authorized_to_view,
    list_targets,
    reject_target,
    submit_target,
    update_target,
)

router = APIRouter(prefix="/eval/perf/targets", tags=["eval-perf-targets"])


def _user_role_codes(user: User) -> set[str]:
    return {ur.role.code for ur in user.roles}


def _is_admin(user: User) -> bool:
    return bool({"SYSTEM_ADMIN", "HR_ADMIN"} & _user_role_codes(user))


@router.get("", response_model=list[PerfTargetResponse])
def list_perf_targets(
    emp_id: int | None = Query(default=None),
    round_id: int | None = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    targets = list_targets(db, emp_id=emp_id, round_id=round_id)
    if _is_admin(current_user):
        return targets
    role_codes = _user_role_codes(current_user)
    return [
        t for t in targets
        if is_authorized_to_view(db, t, current_user.employee_id, role_codes)
    ]


@router.post("", response_model=PerfTargetResponse, status_code=status.HTTP_201_CREATED)
def create_perf_target(
    body: PerfTargetCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not _is_admin(current_user) and current_user.employee_id != body.emp_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot create target for other employee")
    try:
        return create_target(db, body)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.put("/{target_id}", response_model=PerfTargetResponse)
def update_perf_target(
    target_id: int,
    body: PerfTargetUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    target = get_target(db, target_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Target not found")
    if not _is_admin(current_user) and current_user.employee_id != target.emp_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot update other's target")
    try:
        return update_target(db, target_id, body)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.put("/{target_id}/submit", response_model=PerfTargetResponse)
def submit_perf_target(
    target_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    target = get_target(db, target_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Target not found")
    if not _is_admin(current_user) and current_user.employee_id != target.emp_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot submit other's target")
    try:
        return submit_target(db, target_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.put("/{target_id}/approve", response_model=PerfTargetResponse)
def approve_perf_target(
    target_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.employee_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No employee mapping")
    try:
        return approve_target(db, target_id, current_user.employee_id)
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.put("/{target_id}/reject", response_model=PerfTargetResponse)
def reject_perf_target(
    target_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.employee_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No employee mapping")
    try:
        return reject_target(db, target_id, current_user.employee_id)
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
