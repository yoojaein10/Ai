from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, require_roles
from app.db.models import User
from app.db.session import get_db
from app.schemas.eval_objection import (
    ObjectionCreate,
    ObjectionResponse,
    ObjectionReviewCreate,
    ObjectionReviewResponse,
)
from app.services.eval_objection import (
    create_objection,
    list_objections,
    review_objection,
)

router = APIRouter(prefix="/eval/objections", tags=["eval-objections"])


def _is_admin(user: User) -> bool:
    roles = {ur.role.code for ur in user.roles}
    return bool({"SYSTEM_ADMIN", "HR_ADMIN"} & roles)


@router.post("", response_model=ObjectionResponse)
def create_route(
    payload: ObjectionCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.employee_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No employee mapping")
    return create_objection(
        db,
        emp_id=current_user.employee_id,
        round_id=payload.round_id,
        reason=payload.reason,
    )


@router.get("", response_model=list[ObjectionResponse])
def list_route(
    round_id: int = Query(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if _is_admin(current_user):
        return list_objections(db, round_id)
    if current_user.employee_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No employee mapping")
    return list_objections(db, round_id, emp_id=current_user.employee_id)


@router.put(
    "/{objection_id}/review",
    response_model=ObjectionReviewResponse,
)
def review_route(
    objection_id: int,
    payload: ObjectionReviewCreate,
    current_user: User = Depends(require_roles("SYSTEM_ADMIN", "HR_ADMIN")),
    db: Session = Depends(get_db),
):
    return review_objection(
        db,
        objection_id=objection_id,
        decision=payload.decision,
        comment=payload.comment,
        reviewer_id=current_user.id,
    )
