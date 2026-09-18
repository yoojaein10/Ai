from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.db.models import User
from app.db.session import get_db
from app.schemas.comp_sar import CompSarCreate, CompSarResponse, CompSarUpdate
from app.services.comp_sar import (
    create_sar,
    delete_sar,
    get_sar,
    list_sar,
    update_sar,
)

router = APIRouter(prefix="/eval/comp/sar", tags=["eval-comp-sar"])


@router.get("", response_model=list[CompSarResponse])
def list_comp_sar(
    emp_id: int | None = Query(default=None, alias="emp_id"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return list_sar(db, target_emp_id=emp_id)


@router.post("", response_model=CompSarResponse, status_code=status.HTTP_201_CREATED)
def create_comp_sar(
    body: CompSarCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.employee_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="No employee mapping"
        )
    try:
        return create_sar(db, current_user.employee_id, body)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.put("/{sar_id}", response_model=CompSarResponse)
def update_comp_sar(
    sar_id: int,
    body: CompSarUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    record = get_sar(db, sar_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="SAR record not found"
        )
    if (
        current_user.employee_id is None
        or record.observer_id != current_user.employee_id
    ):
        roles = {ur.role.code for ur in current_user.roles}
        if not ({"SYSTEM_ADMIN", "HR_ADMIN"} & roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cannot edit other observer's record",
            )
    try:
        return update_sar(db, sar_id, body)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.delete("/{sar_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_comp_sar(
    sar_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    record = get_sar(db, sar_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="SAR record not found"
        )
    if (
        current_user.employee_id is None
        or record.observer_id != current_user.employee_id
    ):
        roles = {ur.role.code for ur in current_user.roles}
        if not ({"SYSTEM_ADMIN", "HR_ADMIN"} & roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cannot delete other observer's record",
            )
    try:
        delete_sar(db, sar_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
