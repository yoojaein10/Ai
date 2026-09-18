from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.db.models import User
from app.db.session import get_apw_db, get_db
from app.schemas.leave import LeaveListResponse
from app.services.leave import get_leaves

router = APIRouter(prefix="/leaves", tags=["leaves"])


@router.get("", response_model=LeaveListResponse)
def list_leaves(
    year: int = Query(..., ge=2000, le=2100),
    month: int = Query(..., ge=1, le=12),
    leave_type: Optional[str] = Query(None),
    keyword: Optional[str] = Query(None),
    apw_db: Session = Depends(get_apw_db),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> LeaveListResponse:
    return get_leaves(apw_db, db, year, month, leave_type, keyword)
