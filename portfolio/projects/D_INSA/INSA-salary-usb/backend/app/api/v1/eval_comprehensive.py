from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, require_roles
from app.db.models import User
from app.db.session import get_db
from app.schemas.eval_comprehensive import (
    CalculateRequest,
    CalculateResponse,
    ComprehensiveResponse,
    GradeAdjustRequest,
)
from app.services.eval_comprehensive import (
    calculate_comprehensive,
    list_comprehensive,
    manual_adjust_grade,
)

router = APIRouter(prefix="/eval/comprehensive", tags=["eval-comprehensive"])


def _is_admin(user: User) -> bool:
    roles = {ur.role.code for ur in user.roles}
    return bool({"SYSTEM_ADMIN", "HR_ADMIN"} & roles)


@router.get("", response_model=list[ComprehensiveResponse])
def list_route(
    round_id: int = Query(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if _is_admin(current_user):
        return list_comprehensive(db, round_id)
    if current_user.employee_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No employee mapping")
    return list_comprehensive(db, round_id, emp_id=current_user.employee_id)


@router.post(
    "/calculate",
    response_model=CalculateResponse,
    dependencies=[Depends(require_roles("SYSTEM_ADMIN", "HR_ADMIN"))],
)
def calculate_route(
    payload: CalculateRequest,
    db: Session = Depends(get_db),
):
    upserted = calculate_comprehensive(db, payload.round_id)
    return CalculateResponse(round_id=payload.round_id, upserted=upserted)


@router.put(
    "/{comp_id}/grade",
    response_model=ComprehensiveResponse,
)
def adjust_grade_route(
    comp_id: int,
    payload: GradeAdjustRequest,
    current_user: User = Depends(require_roles("SYSTEM_ADMIN", "HR_ADMIN")),
    db: Session = Depends(get_db),
):
    return manual_adjust_grade(
        db,
        comp_id=comp_id,
        new_grade=payload.new_grade,
        adjusted_reason=payload.adjusted_reason,
        adjusted_by=current_user.id,
    )
