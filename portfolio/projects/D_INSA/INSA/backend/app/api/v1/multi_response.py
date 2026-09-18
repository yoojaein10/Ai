from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.db.models import User
from app.db.session import get_db
from app.schemas.multi_response import MultiResponseSubmit, MyEvalTarget
from app.services.multi_response import list_my_targets, submit_multi_response

router = APIRouter(prefix="/eval/multi", tags=["eval-multi-response"])


@router.get("/my-targets", response_model=list[MyEvalTarget])
def get_my_targets(
    round_id: int = Query(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.employee_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="No employee mapping"
        )
    return list_my_targets(db, current_user.employee_id, round_id)


@router.post("/response", status_code=status.HTTP_201_CREATED)
def submit_response(
    body: MultiResponseSubmit,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.employee_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="No employee mapping"
        )
    try:
        inserted = submit_multi_response(db, current_user.employee_id, body)
        return {"inserted": inserted}
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
