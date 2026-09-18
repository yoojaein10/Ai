from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, require_roles
from app.db.models import User
from app.db.session import get_db
from app.schemas.department import DepartmentCreate, DepartmentResponse, DepartmentUpdate
from app.services.department import (
    build_department_tree,
    create_department,
    delete_department,
    get_department,
    get_departments,
    update_department,
)

router = APIRouter(prefix="/departments", tags=["departments"])


@router.get("", response_model=list[DepartmentResponse])
def list_departments(
    include_inactive: bool = False,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return get_departments(db, include_inactive=include_inactive)


@router.get("/tree")
def department_tree(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    departments = get_departments(db, include_inactive=False)
    return build_department_tree(departments)


@router.get("/{dept_id}", response_model=DepartmentResponse)
def read_department(
    dept_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    dept = get_department(db, dept_id)
    if dept is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Department not found")
    return dept


@router.post("", response_model=DepartmentResponse, status_code=status.HTTP_201_CREATED)
def create_new_department(
    body: DepartmentCreate,
    current_user: User = Depends(require_roles("SYSTEM_ADMIN", "HR_ADMIN")),
    db: Session = Depends(get_db),
):
    dept = create_department(db, body, created_by=current_user.id)
    return dept


@router.patch("/{dept_id}", response_model=DepartmentResponse)
def update_existing_department(
    dept_id: int,
    body: DepartmentUpdate,
    current_user: User = Depends(require_roles("SYSTEM_ADMIN", "HR_ADMIN")),
    db: Session = Depends(get_db),
):
    dept = update_department(db, dept_id, body, changed_by=current_user.id)
    if dept is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Department not found")
    return dept


@router.delete("/{dept_id}", status_code=status.HTTP_200_OK)
def delete_existing_department(
    dept_id: int,
    current_user: User = Depends(require_roles("SYSTEM_ADMIN", "HR_ADMIN")),
    db: Session = Depends(get_db),
):
    ok, msg = delete_department(db, dept_id)
    if not ok:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)
    return {"message": msg}
