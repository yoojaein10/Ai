from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, require_roles
from app.db.models import User
from app.db.session import get_db
from app.schemas.comp_indicator import CompIndicatorCreate, CompIndicatorResponse
from app.services.comp_indicator import create_indicator, list_indicators

router = APIRouter(prefix="/eval/comp/indicators", tags=["eval-comp-indicators"])


@router.get("", response_model=list[CompIndicatorResponse])
def list_comp_indicators(
    year: int | None = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return list_indicators(db, year=year)


@router.post("", response_model=CompIndicatorResponse, status_code=status.HTTP_201_CREATED)
def create_comp_indicator(
    body: CompIndicatorCreate,
    current_user: User = Depends(require_roles("SYSTEM_ADMIN", "HR_ADMIN")),
    db: Session = Depends(get_db),
):
    try:
        return create_indicator(db, body)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
