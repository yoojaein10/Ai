from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import Department, Employee
from app.schemas.employee import EmployeeCreate, EmployeeUpdate


def get_employees(
    db: Session,
    page: int = 1,
    page_size: int = 10,
    search: str | None = None,
    dept_id: int | None = None,
    emp_status: str | None = None,
    workplace: str | None = None,
) -> tuple[list[Employee], int]:
    query = db.query(Employee)

    if search:
        query = query.filter(
            (Employee.emp_no.contains(search)) | (Employee.name_ko.contains(search))
        )
    if dept_id is not None:
        query = query.filter(Employee.dept_id == dept_id)
    if emp_status:
        query = query.filter(Employee.emp_status == emp_status)
    if workplace:
        query = query.filter(Employee.workplace == workplace)

    total = query.count()
    items = query.order_by(Employee.emp_no).offset((page - 1) * page_size).limit(page_size).all()
    return items, total


def get_employee(db: Session, employee_id: int) -> Employee | None:
    return db.query(Employee).filter(Employee.id == employee_id).first()


def get_employee_by_emp_no(db: Session, emp_no: str) -> Employee | None:
    return db.query(Employee).filter(Employee.emp_no == emp_no).first()


def create_employee(db: Session, data: EmployeeCreate) -> Employee:
    employee = Employee(**data.model_dump())
    db.add(employee)
    db.commit()
    db.refresh(employee)
    return employee


def update_employee(db: Session, employee_id: int, data: EmployeeUpdate) -> Employee | None:
    employee = db.query(Employee).filter(Employee.id == employee_id).first()
    if employee is None:
        return None

    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(employee, field, value)

    db.commit()
    db.refresh(employee)
    return employee
