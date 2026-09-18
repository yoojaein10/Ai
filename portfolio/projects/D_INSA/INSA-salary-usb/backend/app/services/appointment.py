from datetime import date

from sqlalchemy.orm import Session, aliased

from app.db.models import Appointment, Department, Employee
from app.schemas.appointment import AppointmentCreate


def create_appointment(db: Session, data: AppointmentCreate, created_by: int) -> Appointment:
    """Create appointment and update employee master in a single transaction."""
    employee = db.query(Employee).filter(Employee.id == data.employee_id).first()
    if employee is None:
        raise ValueError(f"Employee {data.employee_id} not found")

    appointment = Appointment(
        employee_id=data.employee_id,
        appt_type=data.appt_type,
        appt_date=data.appt_date,
        old_dept_id=employee.dept_id,
        new_dept_id=data.new_dept_id,
        old_rank=employee.job_rank,
        new_rank=data.new_rank,
        old_position=employee.job_position,
        new_position=data.new_position,
        old_title=employee.job_title,
        new_title=data.new_title,
        description=data.description,
        created_by=created_by,
    )
    db.add(appointment)

    if data.new_dept_id is not None:
        employee.dept_id = data.new_dept_id
    if data.new_rank is not None:
        employee.job_rank = data.new_rank
    if data.new_position is not None:
        employee.job_position = data.new_position
    if data.new_title is not None:
        employee.job_title = data.new_title
    if data.appt_type == "퇴직":
        employee.emp_status = "퇴직"
        employee.resign_date = data.appt_date

    db.commit()
    db.refresh(appointment)
    return appointment


def get_appointments_by_employee(db: Session, employee_id: int) -> list[Appointment]:
    return (
        db.query(Appointment)
        .filter(Appointment.employee_id == employee_id)
        .order_by(Appointment.appt_date.desc())
        .all()
    )


def get_all_appointments(
    db: Session,
    appt_type: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    search: str | None = None,
) -> list[dict]:
    OldDept = aliased(Department)
    NewDept = aliased(Department)

    query = (
        db.query(
            Appointment,
            Employee.emp_no,
            Employee.name_ko,
            OldDept.name.label("old_dept_name"),
            NewDept.name.label("new_dept_name"),
        )
        .join(Employee, Appointment.employee_id == Employee.id)
        .outerjoin(OldDept, Appointment.old_dept_id == OldDept.id)
        .outerjoin(NewDept, Appointment.new_dept_id == NewDept.id)
    )

    if appt_type:
        query = query.filter(Appointment.appt_type == appt_type)
    if date_from:
        query = query.filter(Appointment.appt_date >= date_from)
    if date_to:
        query = query.filter(Appointment.appt_date <= date_to)
    if search:
        like = f"%{search}%"
        query = query.filter((Employee.emp_no.like(like)) | (Employee.name_ko.like(like)))

    rows = query.order_by(Appointment.appt_date.desc(), Appointment.id.desc()).all()

    return [
        {
            "id": appt.id,
            "employee_id": appt.employee_id,
            "emp_no": emp_no,
            "emp_name": name_ko,
            "appt_type": appt.appt_type,
            "appt_date": appt.appt_date,
            "old_dept_name": old_dept_name,
            "new_dept_name": new_dept_name,
            "old_rank": appt.old_rank,
            "new_rank": appt.new_rank,
            "old_position": appt.old_position,
            "new_position": appt.new_position,
            "description": appt.description,
            "created_at": appt.created_at,
        }
        for appt, emp_no, name_ko, old_dept_name, new_dept_name in rows
    ]
