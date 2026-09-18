from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, require_roles
from app.db.models import User
from app.db.session import get_db
from app.schemas.eval_schedule import EvalScheduleBulkCreate, EvalScheduleResponse
from app.services.eval_round import bulk_upsert_schedules, list_schedules

router = APIRouter(prefix="/eval/schedules", tags=["eval-schedules"])


@router.get("", response_model=list[EvalScheduleResponse])
def list_eval_schedules(
    round_id: int = Query(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return list_schedules(db, round_id)


@router.post("", response_model=list[EvalScheduleResponse], status_code=status.HTTP_201_CREATED)
def bulk_upsert_eval_schedules(
    body: EvalScheduleBulkCreate,
    current_user: User = Depends(require_roles("SYSTEM_ADMIN", "HR_ADMIN")),
    db: Session = Depends(get_db),
):
    try:
        return bulk_upsert_schedules(db, body)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
