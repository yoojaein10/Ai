from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, require_roles
from app.db.models import User
from app.db.session import get_db
from app.schemas.multi_indicator import (
    MultiIndicatorCreate,
    MultiIndicatorResponse,
)
from app.services.multi_indicator import create_indicator, list_indicators

router = APIRouter(prefix="/eval/multi/indicators", tags=["eval-multi-indicators"])


@router.get("", response_model=list[MultiIndicatorResponse])
def list_multi_indicators(
    round_id: int = Query(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return list_indicators(db, round_id)


@router.post(
    "", response_model=MultiIndicatorResponse, status_code=status.HTTP_201_CREATED
)
def create_multi_indicator(
    body: MultiIndicatorCreate,
    current_user: User = Depends(require_roles("SYSTEM_ADMIN", "HR_ADMIN")),
    db: Session = Depends(get_db),
):
    try:
        return create_indicator(db, body)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
