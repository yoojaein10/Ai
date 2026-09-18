from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.db.models import User
from app.db.session import get_db
from app.schemas.benefit import BenefitOverviewResponse
from app.services import benefit_overview as svc

router = APIRouter(prefix="/benefits/overview", tags=["benefits"])


@router.get("", response_model=BenefitOverviewResponse)
def get_overview(
    year: int = Query(..., ge=2000, le=2100),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> BenefitOverviewResponse:
    return svc.get_overview(db, year)
