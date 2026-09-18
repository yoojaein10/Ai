from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, require_roles
from app.db.models import User
from app.db.session import get_db
from app.schemas.eval_approver import (
    EvalApproverBulkCreate,
    EvalApproverResponse,
)
from app.services.eval_approver import (
    bulk_upsert_approvers,
    delete_approver,
    list_approvers,
)

router = APIRouter(prefix="/eval/approvers", tags=["eval-approvers"])


@router.get("", response_model=list[EvalApproverResponse])
def list_eval_approvers(
    round_id: int = Query(...),
    eval_type: str | None = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return list_approvers(db, round_id, eval_type=eval_type)


@router.post("", response_model=list[EvalApproverResponse], status_code=status.HTTP_201_CREATED)
def bulk_create_eval_approvers(
    body: EvalApproverBulkCreate,
    current_user: User = Depends(require_roles("SYSTEM_ADMIN", "HR_ADMIN")),
    db: Session = Depends(get_db),
):
    try:
        return bulk_upsert_approvers(db, body)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.delete("/{approver_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_eval_approver(
    approver_id: int,
    current_user: User = Depends(require_roles("SYSTEM_ADMIN", "HR_ADMIN")),
    db: Session = Depends(get_db),
):
    try:
        delete_approver(db, approver_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
