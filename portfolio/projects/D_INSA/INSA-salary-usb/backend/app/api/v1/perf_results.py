from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.db.models import EvalApprover, User
from app.db.session import get_db
from app.schemas.perf_result import PerfResultCreate, PerfResultResponse
from app.services.perf_result import create_result, list_results

router = APIRouter(prefix="/eval/perf/results", tags=["eval-perf-results"])


def _user_role_codes(user: User) -> set[str]:
    return {ur.role.code for ur in user.roles}


def _is_admin(user: User) -> bool:
    return bool({"SYSTEM_ADMIN", "HR_ADMIN"} & _user_role_codes(user))


@router.get("", response_model=list[PerfResultResponse])
def list_perf_results(
    round_id: int | None = Query(default=None),
    dept_id: int | None = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    results = list_results(db, round_id=round_id, dept_id=dept_id)
    if _is_admin(current_user):
        return results
    if current_user.employee_id is None:
        return []
    mapped = (
        db.query(EvalApprover.evaluatee_id)
        .filter(
            EvalApprover.evaluator_id == current_user.employee_id,
            EvalApprover.eval_type == "PERF",
        )
        .all()
    )
    allowed = {row[0] for row in mapped} | {current_user.employee_id}
    return [r for r in results if r.emp_id in allowed]


@router.post("", response_model=PerfResultResponse, status_code=status.HTTP_201_CREATED)
def create_perf_result(
    body: PerfResultCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.employee_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No employee mapping")
    if not _is_admin(current_user):
        mapped = (
            db.query(EvalApprover)
            .filter(
                EvalApprover.round_id == body.round_id,
                EvalApprover.evaluatee_id == body.emp_id,
                EvalApprover.evaluator_id == current_user.employee_id,
                EvalApprover.eval_type == "PERF",
            )
            .first()
        )
        if mapped is None:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not mapped as evaluator")
    try:
        return create_result(db, body, current_user.employee_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
