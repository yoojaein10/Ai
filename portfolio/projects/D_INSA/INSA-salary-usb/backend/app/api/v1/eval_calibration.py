from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, require_roles
from app.db.models import User
from app.db.session import get_db
from app.schemas.eval_calibration import (
    EvalCalibrationGroupCreate,
    EvalCalibrationGroupDetail,
    EvalCalibrationGroupResponse,
    EvalCalibrationGroupUpdate,
    EvalCalibrationMemberAdd,
)
from app.services.eval_calibration import (
    add_members,
    create_group,
    get_group_detail,
    list_groups,
    remove_member,
    update_group,
)

router = APIRouter(prefix="/eval/calibration-groups", tags=["eval-calibration"])


@router.get("", response_model=list[EvalCalibrationGroupResponse])
def list_eval_calibration_groups(
    year: int | None = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return list_groups(db, year=year)


@router.get("/{group_id}", response_model=EvalCalibrationGroupDetail)
def get_eval_calibration_group(
    group_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    detail = get_group_detail(db, group_id)
    if detail is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found")
    return detail


@router.post("", response_model=EvalCalibrationGroupResponse, status_code=status.HTTP_201_CREATED)
def create_eval_calibration_group(
    body: EvalCalibrationGroupCreate,
    current_user: User = Depends(require_roles("SYSTEM_ADMIN", "HR_ADMIN")),
    db: Session = Depends(get_db),
):
    group = create_group(db, body, created_by=current_user.id)
    return {
        "id": group.id,
        "year": group.year,
        "name": group.name,
        "created_by": group.created_by,
        "created_at": group.created_at,
        "member_count": 0,
    }


@router.put("/{group_id}", response_model=EvalCalibrationGroupResponse)
def update_eval_calibration_group(
    group_id: int,
    body: EvalCalibrationGroupUpdate,
    current_user: User = Depends(require_roles("SYSTEM_ADMIN", "HR_ADMIN")),
    db: Session = Depends(get_db),
):
    try:
        group = update_group(db, group_id, body)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    detail = get_group_detail(db, group.id)
    return detail


@router.post("/{group_id}/members", status_code=status.HTTP_201_CREATED)
def add_eval_calibration_members(
    group_id: int,
    body: EvalCalibrationMemberAdd,
    current_user: User = Depends(require_roles("SYSTEM_ADMIN", "HR_ADMIN")),
    db: Session = Depends(get_db),
):
    try:
        added = add_members(db, group_id, body.emp_ids)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    return {"added": len(added)}


@router.delete("/{group_id}/members/{emp_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_eval_calibration_member(
    group_id: int,
    emp_id: int,
    current_user: User = Depends(require_roles("SYSTEM_ADMIN", "HR_ADMIN")),
    db: Session = Depends(get_db),
):
    try:
        remove_member(db, group_id, emp_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
