"""Service layer for change request workflow (EmpPersonal self-service updates)."""

from datetime import datetime

from sqlalchemy.orm import Session

from app.db.models import ChangeRequest, EmpPersonal, User
from app.schemas.change_request import ChangeRequestCreate
from app.services import notification as notif_svc

FIELD_LABELS: dict[str, str] = {
    "address": "주소",
    "phone": "연락처",
    "email": "이메일",
    "emergency_contact": "비상연락인",
    "emergency_phone": "비상연락처",
}


def create_change_request(db: Session, user: User, body: ChangeRequestCreate) -> ChangeRequest:
    if body.field_name not in FIELD_LABELS:
        raise ValueError(f"지원하지 않는 필드: {body.field_name}")
    if user.employee_id is None:
        raise ValueError("로그인 계정에 연결된 사원 정보가 없습니다")

    personal = (
        db.query(EmpPersonal).filter(EmpPersonal.employee_id == user.employee_id).first()
    )
    old_value = getattr(personal, body.field_name, None) if personal else None

    req = ChangeRequest(
        employee_id=user.employee_id,
        field_name=body.field_name,
        old_value=old_value,
        new_value=body.new_value,
        reason=body.reason,
        status="PENDING",
        requested_by=user.id,
    )
    db.add(req)
    db.commit()
    db.refresh(req)
    return req


def list_all(db: Session, status_filter: str | None = None) -> list[ChangeRequest]:
    q = db.query(ChangeRequest)
    if status_filter:
        q = q.filter(ChangeRequest.status == status_filter)
    return q.order_by(ChangeRequest.requested_at.desc()).all()


def list_mine(db: Session, user: User) -> list[ChangeRequest]:
    return (
        db.query(ChangeRequest)
        .filter(ChangeRequest.requested_by == user.id)
        .order_by(ChangeRequest.requested_at.desc())
        .all()
    )


def approve(
    db: Session, req_id: int, reviewer: User, comment: str | None = None
) -> ChangeRequest:
    req = db.query(ChangeRequest).filter(ChangeRequest.id == req_id).first()
    if req is None:
        raise ValueError("요청을 찾을 수 없습니다")
    if req.status != "PENDING":
        raise ValueError("이미 처리된 요청입니다")
    if req.field_name not in FIELD_LABELS:
        raise ValueError(f"지원하지 않는 필드: {req.field_name}")

    personal = (
        db.query(EmpPersonal).filter(EmpPersonal.employee_id == req.employee_id).first()
    )
    if personal is None:
        personal = EmpPersonal(employee_id=req.employee_id)
        db.add(personal)
        db.flush()
    setattr(personal, req.field_name, req.new_value)

    req.status = "APPROVED"
    req.reviewed_by = reviewer.id
    req.reviewed_at = datetime.utcnow()
    req.review_comment = comment

    field_label = FIELD_LABELS.get(req.field_name, req.field_name)
    notif_svc.create(
        db,
        user_id=req.requested_by,
        type="CHANGE_REQUEST_APPROVED",
        title=f"{field_label} 변경 요청이 승인되었습니다",
        message=comment,
        link="/hr/change-requests/mine",
    )

    db.commit()
    db.refresh(req)
    return req


def reject(
    db: Session, req_id: int, reviewer: User, comment: str | None = None
) -> ChangeRequest:
    req = db.query(ChangeRequest).filter(ChangeRequest.id == req_id).first()
    if req is None:
        raise ValueError("요청을 찾을 수 없습니다")
    if req.status != "PENDING":
        raise ValueError("이미 처리된 요청입니다")

    req.status = "REJECTED"
    req.reviewed_by = reviewer.id
    req.reviewed_at = datetime.utcnow()
    req.review_comment = comment

    field_label = FIELD_LABELS.get(req.field_name, req.field_name)
    notif_svc.create(
        db,
        user_id=req.requested_by,
        type="CHANGE_REQUEST_REJECTED",
        title=f"{field_label} 변경 요청이 반려되었습니다",
        message=comment,
        link="/hr/change-requests/mine",
    )

    db.commit()
    db.refresh(req)
    return req
