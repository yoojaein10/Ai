from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import (
    Employee,
    EvalCalibrationGroup,
    EvalCalibrationMember,
)
from app.schemas.eval_calibration import (
    EvalCalibrationGroupCreate,
    EvalCalibrationGroupUpdate,
)


def list_groups(db: Session, year: int | None = None) -> list[dict]:
    count_sq = (
        db.query(
            EvalCalibrationMember.group_id.label("group_id"),
            func.count(EvalCalibrationMember.id).label("member_count"),
        )
        .group_by(EvalCalibrationMember.group_id)
        .subquery()
    )

    query = (
        db.query(EvalCalibrationGroup, count_sq.c.member_count)
        .outerjoin(count_sq, count_sq.c.group_id == EvalCalibrationGroup.id)
    )
    if year is not None:
        query = query.filter(EvalCalibrationGroup.year == year)

    rows = query.order_by(EvalCalibrationGroup.year.desc(), EvalCalibrationGroup.id.desc()).all()
    return [
        {
            "id": g.id,
            "year": g.year,
            "name": g.name,
            "created_by": g.created_by,
            "created_at": g.created_at,
            "member_count": int(count or 0),
        }
        for g, count in rows
    ]


def get_group_detail(db: Session, group_id: int) -> dict | None:
    group = db.query(EvalCalibrationGroup).filter(EvalCalibrationGroup.id == group_id).first()
    if group is None:
        return None

    rows = (
        db.query(EvalCalibrationMember, Employee.emp_no, Employee.name_ko)
        .join(Employee, EvalCalibrationMember.emp_id == Employee.id)
        .filter(EvalCalibrationMember.group_id == group_id)
        .order_by(EvalCalibrationMember.id.asc())
        .all()
    )

    members = [
        {"id": m.id, "emp_id": m.emp_id, "emp_no": emp_no, "emp_name": name_ko}
        for m, emp_no, name_ko in rows
    ]

    return {
        "id": group.id,
        "year": group.year,
        "name": group.name,
        "created_by": group.created_by,
        "created_at": group.created_at,
        "member_count": len(members),
        "members": members,
    }


def create_group(db: Session, data: EvalCalibrationGroupCreate, created_by: int) -> EvalCalibrationGroup:
    group = EvalCalibrationGroup(
        year=data.year,
        name=data.name,
        created_by=created_by,
    )
    db.add(group)
    db.commit()
    db.refresh(group)
    return group


def update_group(
    db: Session, group_id: int, data: EvalCalibrationGroupUpdate
) -> EvalCalibrationGroup:
    group = db.query(EvalCalibrationGroup).filter(EvalCalibrationGroup.id == group_id).first()
    if group is None:
        raise ValueError(f"EvalCalibrationGroup {group_id} not found")
    if data.name is not None:
        group.name = data.name
    db.commit()
    db.refresh(group)
    return group


def add_members(db: Session, group_id: int, emp_ids: list[int]) -> list[EvalCalibrationMember]:
    group = db.query(EvalCalibrationGroup).filter(EvalCalibrationGroup.id == group_id).first()
    if group is None:
        raise ValueError(f"EvalCalibrationGroup {group_id} not found")

    existing = {
        m.emp_id
        for m in db.query(EvalCalibrationMember)
        .filter(EvalCalibrationMember.group_id == group_id)
        .all()
    }

    added: list[EvalCalibrationMember] = []
    for emp_id in emp_ids:
        if emp_id in existing:
            continue
        emp = db.query(Employee).filter(Employee.id == emp_id).first()
        if emp is None:
            raise ValueError(f"Employee {emp_id} not found")
        member = EvalCalibrationMember(group_id=group_id, emp_id=emp_id)
        db.add(member)
        added.append(member)
    db.commit()
    for m in added:
        db.refresh(m)
    return added


def remove_member(db: Session, group_id: int, emp_id: int) -> None:
    member = (
        db.query(EvalCalibrationMember)
        .filter(
            EvalCalibrationMember.group_id == group_id,
            EvalCalibrationMember.emp_id == emp_id,
        )
        .first()
    )
    if member is None:
        raise ValueError(f"Member not found (group={group_id}, emp={emp_id})")
    db.delete(member)
    db.commit()
