from sqlalchemy.orm import Session

from app.db.models import DeptHistory, Department, Employee
from app.schemas.department import DepartmentCreate, DepartmentUpdate


def get_departments(db: Session, include_inactive: bool = False) -> list[Department]:
    query = db.query(Department)
    if not include_inactive:
        query = query.filter(Department.is_active == True)  # noqa: E712
    return query.order_by(Department.code).all()


def get_department(db: Session, dept_id: int) -> Department | None:
    return db.query(Department).filter(Department.id == dept_id).first()


def create_department(db: Session, data: DepartmentCreate, created_by: int) -> Department:
    dept = Department(**data.model_dump())
    db.add(dept)
    db.flush()

    history = DeptHistory(
        department_id=dept.id,
        change_type="CREATE",
        new_value=dept.name,
        changed_by=created_by,
    )
    db.add(history)
    db.commit()
    db.refresh(dept)
    return dept


def update_department(
    db: Session, dept_id: int, data: DepartmentUpdate, changed_by: int
) -> Department | None:
    dept = db.query(Department).filter(Department.id == dept_id).first()
    if dept is None:
        return None

    update_data = data.model_dump(exclude_unset=True)

    if "parent_id" in update_data and update_data["parent_id"] != dept.parent_id:
        history = DeptHistory(
            department_id=dept.id,
            change_type="MOVE",
            old_value=str(dept.parent_id),
            new_value=str(update_data["parent_id"]),
            changed_by=changed_by,
        )
        db.add(history)

        employees = db.query(Employee).filter(Employee.dept_id == dept_id).all()
        for emp in employees:
            emp.dept_id = dept_id

    if "name" in update_data and update_data["name"] != dept.name:
        history = DeptHistory(
            department_id=dept.id,
            change_type="RENAME",
            old_value=dept.name,
            new_value=update_data["name"],
            changed_by=changed_by,
        )
        db.add(history)

    if "is_active" in update_data and not update_data["is_active"] and dept.is_active:
        history = DeptHistory(
            department_id=dept.id,
            change_type="DEACTIVATE",
            old_value="active",
            new_value="inactive",
            changed_by=changed_by,
        )
        db.add(history)

    for field, value in update_data.items():
        setattr(dept, field, value)

    db.commit()
    db.refresh(dept)
    return dept


def delete_department(db: Session, dept_id: int) -> tuple[bool, str]:
    dept = db.query(Department).filter(Department.id == dept_id).first()
    if dept is None:
        return False, "부서를 찾을 수 없습니다"

    emp_count = db.query(Employee).filter(Employee.dept_id == dept_id).count()
    if emp_count > 0:
        return False, f"소속 직원이 {emp_count}명 있어 삭제할 수 없습니다"

    child_count = db.query(Department).filter(Department.parent_id == dept_id).count()
    if child_count > 0:
        return False, f"하위 부서가 {child_count}개 있어 삭제할 수 없습니다"

    db.query(DeptHistory).filter(DeptHistory.department_id == dept_id).delete()
    db.delete(dept)
    db.commit()
    return True, "삭제되었습니다"


def build_department_tree(departments: list[Department]) -> list[dict]:
    dept_map = {}
    for d in departments:
        dept_map[d.id] = {
            "id": d.id,
            "code": d.code,
            "name": d.name,
            "parent_id": d.parent_id,
            "head_employee_id": d.head_employee_id,
            "is_active": d.is_active,
            "children": [],
        }

    roots = []
    for d in departments:
        node = dept_map[d.id]
        if d.parent_id and d.parent_id in dept_map:
            dept_map[d.parent_id]["children"].append(node)
        else:
            roots.append(node)

    return roots
