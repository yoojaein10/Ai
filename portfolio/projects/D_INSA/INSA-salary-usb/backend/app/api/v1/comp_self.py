from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.db.models import User
from app.db.session import get_db
from app.schemas.comp_self import CompEvalSelfBulkCreate, CompEvalSelfResponse
from app.services.comp_self import list_self, upsert_self_bulk

router = APIRouter(prefix="/eval/comp", tags=["eval-comp-self"])


@router.get("/my-eval", response_model=list[CompEvalSelfResponse])
def get_my_self_eval(
    round_id: int = Query(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.employee_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="No employee mapping"
        )
    return list_self(db, current_user.employee_id, round_id)


@router.post(
    "/self",
    response_model=list[CompEvalSelfResponse],
    status_code=status.HTTP_201_CREATED,
)
def submit_self_eval(
    body: CompEvalSelfBulkCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.employee_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="No employee mapping"
        )
    try:
        return upsert_self_bulk(db, current_user.employee_id, body)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
