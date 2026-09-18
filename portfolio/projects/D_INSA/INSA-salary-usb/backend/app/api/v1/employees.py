from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, require_roles
from app.db.models import User
from app.db.session import get_db
from app.schemas.employee import (
    EmployeeCreate,
    EmployeeListResponse,
    EmployeeResponse,
    EmployeeUpdate,
)
from app.services.employee import (
    create_employee,
    get_employee,
    get_employee_by_emp_no,
    get_employees,
    update_employee,
)

router = APIRouter(prefix="/employees", tags=["employees"])


@router.get("", response_model=EmployeeListResponse)
def list_employees(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    search: str | None = None,
    dept_id: int | None = None,
    emp_status: str | None = None,
    workplace: str | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    items, total = get_employees(
        db, page=page, page_size=page_size, search=search,
        dept_id=dept_id, emp_status=emp_status, workplace=workplace,
    )
    return EmployeeListResponse(
        items=[_to_response(emp) for emp in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{employee_id}", response_model=EmployeeResponse)
def read_employee(
    employee_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    emp = get_employee(db, employee_id)
    if emp is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found")
    return _to_response(emp)


@router.post("", response_model=EmployeeResponse, status_code=status.HTTP_201_CREATED)
def create_new_employee(
    body: EmployeeCreate,
    current_user: User = Depends(require_roles("SYSTEM_ADMIN", "HR_ADMIN")),
    db: Session = Depends(get_db),
):
    existing = get_employee_by_emp_no(db, body.emp_no)
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Employee number already exists")
    emp = create_employee(db, body)
    return _to_response(emp)


@router.patch("/{employee_id}", response_model=EmployeeResponse)
def update_existing_employee(
    employee_id: int,
    body: EmployeeUpdate,
    current_user: User = Depends(require_roles("SYSTEM_ADMIN", "HR_ADMIN")),
    db: Session = Depends(get_db),
):
    emp = update_employee(db, employee_id, body)
    if emp is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found")
    return _to_response(emp)


def _to_response(emp) -> EmployeeResponse:
    return EmployeeResponse(
        id=emp.id,
        emp_no=emp.emp_no,
        name_ko=emp.name_ko,
        name_cn=emp.name_cn,
        name_en=emp.name_en,
        gender=emp.gender,
        birth_date=emp.birth_date,
        hire_date=emp.hire_date,
        hire_type=emp.hire_type,
        workplace=emp.workplace,
        work_location=emp.work_location,
        dept_id=emp.dept_id,
        job_rank=emp.job_rank,
        job_position=emp.job_position,
        job_title=emp.job_title,
        emp_status=emp.emp_status,
        emp_type=emp.emp_type,
        resign_date=emp.resign_date,
        department_name=emp.department.name if emp.department else None,
        created_at=emp.created_at,
        updated_at=emp.updated_at,
    )
