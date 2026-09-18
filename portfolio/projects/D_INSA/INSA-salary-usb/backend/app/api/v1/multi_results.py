from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.db.models import User
from app.db.session import get_db
from app.schemas.multi_response import MultiSubmissionStatus
from app.schemas.multi_result import MultiResultResponse
from app.services.multi_result import get_result_for_emp, get_submission_status

router = APIRouter(prefix="/eval/multi", tags=["eval-multi-results"])


def _is_admin(user: User) -> bool:
    roles = {ur.role.code for ur in user.roles}
    return bool({"SYSTEM_ADMIN", "HR_ADMIN"} & roles)


@router.get("/results/{emp_id}", response_model=MultiResultResponse)
def get_my_multi_result(
    emp_id: int,
    round_id: int = Query(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not _is_admin(current_user) and current_user.employee_id != emp_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot view other employee's result",
        )
    return get_result_for_emp(db, round_id, emp_id)


@router.get("/status", response_model=MultiSubmissionStatus)
def get_multi_status(
    round_id: int = Query(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not _is_admin(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admin only"
        )
    return get_submission_status(db, round_id)
