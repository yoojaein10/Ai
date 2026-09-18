from datetime import datetime

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.db.models import EvalObjection, EvalObjectionReview, Role, User, UserRole
from app.services import notification as notif_svc


def _hr_admin_user_ids(db: Session) -> list[int]:
    rows = (
        db.query(User.id)
        .join(UserRole, UserRole.user_id == User.id)
        .join(Role, Role.id == UserRole.role_id)
        .filter(Role.code.in_(["HR_ADMIN", "SYSTEM_ADMIN"]), User.is_active.is_(True))
        .all()
    )
    return [r[0] for r in rows]


def _user_id_for_employee(db: Session, employee_id: int) -> int | None:
    row = (
        db.query(User.id)
        .filter(User.employee_id == employee_id, User.is_active.is_(True))
        .first()
    )
    return row[0] if row else None


def create_objection(
    db: Session, emp_id: int, round_id: int, reason: str
) -> EvalObjection:
    if not reason or not reason.strip():
        raise HTTPException(status_code=400, detail="reason required")
    row = EvalObjection(
        emp_id=emp_id, round_id=round_id, reason=reason, status="PENDING"
    )
    db.add(row)
    db.flush()

    notif_svc.create_many(
        db,
        user_ids=_hr_admin_user_ids(db),
        type="EVAL_OBJECTION_CREATED",
        title="평가 이의신청이 접수되었습니다",
        message=reason[:200],
        link=f"/eval/objections?round_id={round_id}",
    )

    db.commit()
    db.refresh(row)
    return row


def list_objections(
    db: Session, round_id: int, emp_id: int | None = None
) -> list[EvalObjection]:
    q = db.query(EvalObjection).filter(EvalObjection.round_id == round_id)
    if emp_id is not None:
        q = q.filter(EvalObjection.emp_id == emp_id)
    return q.order_by(EvalObjection.created_at.desc()).all()


def review_objection(
    db: Session,
    objection_id: int,
    decision: str,
    comment: str | None,
    reviewer_id: int,
) -> EvalObjectionReview:
    if decision not in ("ACCEPTED", "REJECTED"):
        raise HTTPException(status_code=400, detail="decision must be ACCEPTED or REJECTED")
    objection = (
        db.query(EvalObjection).filter(EvalObjection.id == objection_id).first()
    )
    if objection is None:
        raise HTTPException(status_code=404, detail="objection not found")
    if objection.status not in ("PENDING", "REVIEWED"):
        raise HTTPException(status_code=400, detail=f"cannot review objection in status {objection.status}")
    review = EvalObjectionReview(
        objection_id=objection_id,
        reviewer_id=reviewer_id,
        decision=decision,
        comment=comment,
        reviewed_at=datetime.utcnow(),
    )
    db.add(review)
    objection.status = decision
    db.flush()

    target_user_id = _user_id_for_employee(db, objection.emp_id)
    if target_user_id is not None:
        decision_kr = "수용" if decision == "ACCEPTED" else "기각"
        notif_svc.create(
            db,
            user_id=target_user_id,
            type="EVAL_OBJECTION_REVIEWED",
            title=f"평가 이의신청이 {decision_kr}되었습니다",
            message=comment,
            link=f"/eval/objections?round_id={objection.round_id}",
        )

    db.commit()
    db.refresh(review)
    return review
