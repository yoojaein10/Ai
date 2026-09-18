from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, require_roles
from app.db.models import User
from app.db.session import get_db
from app.schemas.eval_round import (
    EvalRoundCreate,
    EvalRoundResponse,
    EvalRoundUpdate,
)
from app.services.eval_round import (
    close_round,
    create_round,
    get_round,
    list_rounds,
    update_round,
)

router = APIRouter(prefix="/eval/rounds", tags=["eval-rounds"])


@router.get("", response_model=list[EvalRoundResponse])
def list_eval_rounds(
    year: int | None = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return list_rounds(db, year=year)


@router.post("", response_model=EvalRoundResponse, status_code=status.HTTP_201_CREATED)
def create_eval_round(
    body: EvalRoundCreate,
    current_user: User = Depends(require_roles("SYSTEM_ADMIN", "HR_ADMIN")),
    db: Session = Depends(get_db),
):
    return create_round(db, body)


@router.put("/{round_id}", response_model=EvalRoundResponse)
def update_eval_round(
    round_id: int,
    body: EvalRoundUpdate,
    current_user: User = Depends(require_roles("SYSTEM_ADMIN", "HR_ADMIN")),
    db: Session = Depends(get_db),
):
    try:
        return update_round(db, round_id, body)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.put("/{round_id}/close", response_model=EvalRoundResponse)
def close_eval_round(
    round_id: int,
    current_user: User = Depends(require_roles("SYSTEM_ADMIN", "HR_ADMIN")),
    db: Session = Depends(get_db),
):
    try:
        return close_round(db, round_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/{round_id}", response_model=EvalRoundResponse)
def get_eval_round(
    round_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    round_ = get_round(db, round_id)
    if round_ is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Round not found")
    return round_
