from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.db.models import User
from app.db.session import get_db
from app.schemas.comp_boss import CompEvalBossBulkCreate, CompEvalBossResponse
from app.services.comp_boss import list_boss, upsert_boss_bulk

router = APIRouter(prefix="/eval/comp", tags=["eval-comp-boss"])


@router.get("/boss", response_model=list[CompEvalBossResponse])
def list_boss_eval(
    evaluatee_id: int | None = Query(default=None),
    round_id: int | None = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return list_boss(db, evaluatee_id=evaluatee_id, round_id=round_id)


@router.post(
    "/boss",
    response_model=list[CompEvalBossResponse],
    status_code=status.HTTP_201_CREATED,
)
def submit_boss_eval(
    body: CompEvalBossBulkCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.employee_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="No employee mapping"
        )
    try:
        return upsert_boss_bulk(db, current_user.employee_id, body)
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
