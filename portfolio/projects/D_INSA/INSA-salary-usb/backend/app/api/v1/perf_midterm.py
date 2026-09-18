from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.db.models import User
from app.db.session import get_db
from app.schemas.perf_midterm import PerfMidtermResponse, PerfMidtermUpsert
from app.services.perf_midterm import get_midterm, upsert_midterm
from app.services.perf_target import get_target, is_authorized_to_view

router = APIRouter(prefix="/eval/perf/midterm", tags=["eval-perf-midterm"])


def _user_role_codes(user: User) -> set[str]:
    return {ur.role.code for ur in user.roles}


@router.get("", response_model=PerfMidtermResponse | None)
def get_perf_midterm(
    target_id: int = Query(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    target = get_target(db, target_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Target not found")
    if not is_authorized_to_view(db, target, current_user.employee_id, _user_role_codes(current_user)):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    return get_midterm(db, target_id)


@router.post("", response_model=PerfMidtermResponse, status_code=status.HTTP_201_CREATED)
def upsert_perf_midterm(
    body: PerfMidtermUpsert,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    target = get_target(db, body.target_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Target not found")
    role_codes = _user_role_codes(current_user)
    is_admin = bool({"SYSTEM_ADMIN", "HR_ADMIN"} & role_codes)
    if not is_admin and current_user.employee_id != target.emp_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot edit other's midterm")
    try:
        return upsert_midterm(db, body)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
