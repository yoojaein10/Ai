"""Electronic approval workflow service (PHASE 12).

Design:
- Immutable state transitions (no in-place mutation of domain concepts).
- All state changes go through single-transaction helpers; caller can wrap
  multiple calls but each public function commits its own atomic work unit.
- `resolve_approver` centralizes approver-type logic.
- Notifications are emitted within the same transaction as state changes.
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import and_, desc, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import (
    ApprovalAttachment,
    ApprovalDoc,
    ApprovalDocType,
    ApprovalLineStep,
    ApprovalLineTemplate,
    ApprovalStepHistory,
    Department,
    Employee,
    Role,
    User,
    UserRole,
)
from app.services import notification as notif_svc
from app.services import doc_hooks


# ── Errors ──────────────────────────────────────────────────


class ApprovalError(Exception):
    """Business-rule violation inside the approval workflow."""


class NotFound(ApprovalError):
    pass


class PermissionDenied(ApprovalError):
    pass


class InvalidState(ApprovalError):
    pass


# ── Helpers ─────────────────────────────────────────────────


def _user_role_codes(user: User) -> set[str]:
    return {ur.role.code for ur in user.roles}


def _is_admin(user: User) -> bool:
    codes = _user_role_codes(user)
    return "SYSTEM_ADMIN" in codes or "HR_ADMIN" in codes


def _employee_user(db: Session, employee_id: int) -> Optional[User]:
    return (
        db.query(User)
        .filter(User.employee_id == employee_id, User.is_active.is_(True))
        .first()
    )


def _dumps_content(content: Optional[dict[str, Any]]) -> Optional[str]:
    return None if content is None else json.dumps(content, ensure_ascii=False)


def _loads_content(raw: Optional[str]) -> Optional[dict[str, Any]]:
    if raw is None or raw == "":
        return None
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return None


# ── Approver resolution ─────────────────────────────────────


def resolve_approver(
    db: Session, step: ApprovalLineStep, doc: ApprovalDoc
) -> Optional[User]:
    """Resolve a line step into the user who must act on it.

    Returns None when the mapping cannot be satisfied (e.g. dept has no head).
    Filters out inactive / resigned employees.
    """
    drafter = (
        db.query(Employee).filter(Employee.id == doc.drafter_id).first()
    )
    drafter_dept_id = drafter.dept_id if drafter else None
    approver_type = step.approver_type
    ref = step.approver_ref

    if approver_type == "USER":
        if ref is None:
            return None
        try:
            uid = int(ref)
        except (TypeError, ValueError):
            return None
        return (
            db.query(User)
            .filter(User.id == uid, User.is_active.is_(True))
            .first()
        )

    if approver_type == "ROLE":
        if ref is None:
            return None
        return (
            db.query(User)
            .join(UserRole, UserRole.user_id == User.id)
            .join(Role, Role.id == UserRole.role_id)
            .filter(Role.code == ref, User.is_active.is_(True))
            .order_by(User.id)
            .first()
        )

    if approver_type == "POSITION":
        if ref is None:
            return None
        q = (
            db.query(User)
            .join(Employee, Employee.id == User.employee_id)
            .filter(
                Employee.job_position == ref,
                Employee.emp_status == "재직",
                User.is_active.is_(True),
            )
        )
        if drafter_dept_id is not None:
            same_dept = (
                q.filter(Employee.dept_id == drafter_dept_id)
                .order_by(Employee.id)
                .first()
            )
            if same_dept is not None:
                return same_dept
        return q.order_by(Employee.id).first()

    if approver_type == "DEPT_HEAD":
        if drafter_dept_id is None:
            return None
        dept = (
            db.query(Department)
            .filter(Department.id == drafter_dept_id)
            .first()
        )
        if dept is None or dept.head_employee_id is None:
            return None
        return _employee_user(db, dept.head_employee_id)

    if approver_type == "DIRECT_MANAGER":
        # Fallback strategy: same-dept 팀장 with lowest id (see PHASE 12 plan R1).
        if drafter_dept_id is None:
            return None
        emp = (
            db.query(Employee)
            .filter(
                Employee.dept_id == drafter_dept_id,
                Employee.job_position == "팀장",
                Employee.emp_status == "재직",
                Employee.id != doc.drafter_id,
            )
            .order_by(Employee.id)
            .first()
        )
        if emp is None:
            # Escalate to DEPT_HEAD as a last resort.
            dept = (
                db.query(Department)
                .filter(Department.id == drafter_dept_id)
                .first()
            )
            if dept is not None and dept.head_employee_id is not None:
                return _employee_user(db, dept.head_employee_id)
            return None
        return _employee_user(db, emp.id)

    return None


# ── Document numbering ──────────────────────────────────────


def _next_doc_no(db: Session, *, today: Optional[datetime] = None) -> str:
    now = today or datetime.now()
    prefix = now.strftime("%Y%m%d")
    pattern = f"{prefix}-%"
    last = (
        db.query(ApprovalDoc.doc_no)
        .filter(ApprovalDoc.doc_no.like(pattern))
        .order_by(desc(ApprovalDoc.doc_no))
        .first()
    )
    if last is None or last[0] is None:
        seq = 1
    else:
        try:
            seq = int(last[0].split("-")[1]) + 1
        except (IndexError, ValueError):
            seq = 1
    return f"{prefix}-{seq:04d}"


# ── Line template helpers ───────────────────────────────────


def _load_template(db: Session, template_id: int) -> ApprovalLineTemplate:
    tpl = (
        db.query(ApprovalLineTemplate)
        .filter(ApprovalLineTemplate.id == template_id)
        .first()
    )
    if tpl is None:
        raise NotFound(f"결재선 템플릿을 찾을 수 없습니다 (id={template_id})")
    return tpl


def _sorted_steps(template: ApprovalLineTemplate) -> list[ApprovalLineStep]:
    return sorted(template.steps, key=lambda s: s.step_order)


def _doc_steps(db: Session, doc: ApprovalDoc) -> list[ApprovalLineStep]:
    """Snapshot the latest template steps bound to this doc's type.

    NOTE: steps are currently referenced through the originating template.
    A future enhancement may snapshot steps onto the document itself.
    """
    # We persist the template_id via the doc's first history entry's doc_id;
    # for now we look up the most recent default template for the doc type.
    # To keep behavior deterministic per-doc, the caller should pass the
    # resolved steps. This helper is used only for detail views where we
    # fall back to the default template.
    tpl = (
        db.query(ApprovalLineTemplate)
        .filter(
            ApprovalLineTemplate.doc_type_id == doc.doc_type_id,
            ApprovalLineTemplate.is_default.is_(True),
        )
        .order_by(desc(ApprovalLineTemplate.id))
        .first()
    )
    if tpl is None:
        return []
    return _sorted_steps(tpl)


# ── Doc type / line template CRUD ───────────────────────────


def list_doc_types(db: Session, *, active_only: bool = True) -> list[ApprovalDocType]:
    q = db.query(ApprovalDocType)
    if active_only:
        q = q.filter(ApprovalDocType.is_active.is_(True))
    return q.order_by(ApprovalDocType.id).all()


def get_doc_type(db: Session, doc_type_id: int) -> ApprovalDocType:
    dt = db.query(ApprovalDocType).filter(ApprovalDocType.id == doc_type_id).first()
    if dt is None:
        raise NotFound("문서 타입을 찾을 수 없습니다")
    return dt


def create_doc_type(
    db: Session,
    *,
    code: str,
    name: str,
    category: str,
    description: Optional[str] = None,
    is_active: bool = True,
) -> ApprovalDocType:
    if db.query(ApprovalDocType).filter(ApprovalDocType.code == code).first():
        raise InvalidState(f"이미 존재하는 코드입니다: {code}")
    dt = ApprovalDocType(
        code=code,
        name=name,
        category=category,
        description=description,
        is_active=is_active,
    )
    db.add(dt)
    db.commit()
    db.refresh(dt)
    return dt


def update_doc_type(
    db: Session,
    doc_type_id: int,
    *,
    name: Optional[str] = None,
    category: Optional[str] = None,
    description: Optional[str] = None,
    is_active: Optional[bool] = None,
) -> ApprovalDocType:
    dt = get_doc_type(db, doc_type_id)
    if name is not None:
        dt.name = name
    if category is not None:
        dt.category = category
    if description is not None:
        dt.description = description
    if is_active is not None:
        dt.is_active = is_active
    db.commit()
    db.refresh(dt)
    return dt


def list_templates(
    db: Session, *, doc_type_id: Optional[int] = None
) -> list[ApprovalLineTemplate]:
    q = db.query(ApprovalLineTemplate)
    if doc_type_id is not None:
        q = q.filter(ApprovalLineTemplate.doc_type_id == doc_type_id)
    return q.order_by(
        ApprovalLineTemplate.doc_type_id, desc(ApprovalLineTemplate.is_default),
        ApprovalLineTemplate.id,
    ).all()


def get_template(db: Session, template_id: int) -> ApprovalLineTemplate:
    return _load_template(db, template_id)


def create_template(
    db: Session,
    *,
    doc_type_id: int,
    name: str,
    scope: str = "GLOBAL",
    scope_ref: Optional[int] = None,
    is_default: bool = False,
    steps: list[dict[str, Any]],
) -> ApprovalLineTemplate:
    if not steps:
        raise InvalidState("결재선에는 최소 1단계가 필요합니다")
    # Enforce single default per doc_type
    if is_default:
        db.query(ApprovalLineTemplate).filter(
            ApprovalLineTemplate.doc_type_id == doc_type_id,
            ApprovalLineTemplate.is_default.is_(True),
        ).update({ApprovalLineTemplate.is_default: False}, synchronize_session=False)

    tpl = ApprovalLineTemplate(
        doc_type_id=doc_type_id,
        name=name,
        scope=scope,
        scope_ref=scope_ref,
        is_default=is_default,
    )
    db.add(tpl)
    db.flush()

    ordered = sorted(steps, key=lambda s: s.get("step_order", 0))
    for idx, s in enumerate(ordered, start=1):
        db.add(
            ApprovalLineStep(
                template_id=tpl.id,
                step_order=idx,
                approver_type=s["approver_type"],
                approver_ref=s.get("approver_ref"),
                is_required=s.get("is_required", True),
            )
        )
    db.commit()
    db.refresh(tpl)
    return tpl


def update_template(
    db: Session,
    template_id: int,
    *,
    name: Optional[str] = None,
    scope: Optional[str] = None,
    scope_ref: Optional[int] = None,
    is_default: Optional[bool] = None,
    steps: Optional[list[dict[str, Any]]] = None,
) -> ApprovalLineTemplate:
    tpl = _load_template(db, template_id)
    if name is not None:
        tpl.name = name
    if scope is not None:
        tpl.scope = scope
    if scope_ref is not None:
        tpl.scope_ref = scope_ref
    if is_default is True:
        db.query(ApprovalLineTemplate).filter(
            ApprovalLineTemplate.doc_type_id == tpl.doc_type_id,
            ApprovalLineTemplate.is_default.is_(True),
            ApprovalLineTemplate.id != tpl.id,
        ).update({ApprovalLineTemplate.is_default: False}, synchronize_session=False)
        tpl.is_default = True
    elif is_default is False:
        tpl.is_default = False

    if steps is not None:
        # Full replacement
        db.query(ApprovalLineStep).filter(
            ApprovalLineStep.template_id == tpl.id
        ).delete(synchronize_session=False)
        db.flush()
        ordered = sorted(steps, key=lambda s: s.get("step_order", 0))
        for idx, s in enumerate(ordered, start=1):
            db.add(
                ApprovalLineStep(
                    template_id=tpl.id,
                    step_order=idx,
                    approver_type=s["approver_type"],
                    approver_ref=s.get("approver_ref"),
                    is_required=s.get("is_required", True),
                )
            )
    db.commit()
    db.refresh(tpl)
    return tpl


def delete_template(db: Session, template_id: int) -> None:
    tpl = _load_template(db, template_id)
    db.delete(tpl)
    db.commit()


# ── Draft / submit / approve / reject / recall ──────────────


def _owner_employee(db: Session, user: User) -> Employee:
    if user.employee_id is None:
        raise InvalidState("로그인 계정에 연결된 사원 정보가 없습니다")
    emp = db.query(Employee).filter(Employee.id == user.employee_id).first()
    if emp is None:
        raise InvalidState("사원 정보를 찾을 수 없습니다")
    return emp


def create_draft(
    db: Session,
    *,
    user: User,
    doc_type_id: int,
    title: str,
    content: Optional[dict[str, Any]],
    line_template_id: int,
) -> ApprovalDoc:
    drafter = _owner_employee(db, user)
    doc_type = get_doc_type(db, doc_type_id)
    if not doc_type.is_active:
        raise InvalidState("비활성 문서 타입입니다")
    tpl = _load_template(db, line_template_id)
    if tpl.doc_type_id != doc_type_id:
        raise InvalidState("결재선 템플릿이 문서 타입과 일치하지 않습니다")
    total_steps = len(tpl.steps)
    if total_steps == 0:
        raise InvalidState("결재선에 단계가 없습니다")

    doc = ApprovalDoc(
        doc_type_id=doc_type_id,
        doc_no=None,
        title=title,
        drafter_id=drafter.id,
        content=_dumps_content(content),
        status="DRAFT",
        current_step=0,
        total_steps=total_steps,
    )
    db.add(doc)
    db.flush()

    # Persist the binding between doc and template via a seed history row
    # (step_order=0, action=COMMENTED) — keeps a single source of truth.
    db.add(
        ApprovalStepHistory(
            doc_id=doc.id,
            step_order=0,
            approver_id=user.id,
            action="COMMENTED",
            comment=f"__TEMPLATE__:{tpl.id}",
        )
    )
    db.commit()
    db.refresh(doc)
    return doc


def update_draft(
    db: Session,
    doc_id: int,
    *,
    user: User,
    title: Optional[str] = None,
    content: Optional[dict[str, Any]] = None,
) -> ApprovalDoc:
    doc = _load_doc(db, doc_id)
    if doc.drafter_id != (user.employee_id or -1):
        raise PermissionDenied("기안자만 수정할 수 있습니다")
    if doc.status != "DRAFT":
        raise InvalidState("DRAFT 상태에서만 수정할 수 있습니다")
    if title is not None:
        doc.title = title
    if content is not None:
        doc.content = _dumps_content(content)
    db.commit()
    db.refresh(doc)
    return doc


def _template_id_for_doc(db: Session, doc_id: int) -> Optional[int]:
    row = (
        db.query(ApprovalStepHistory)
        .filter(
            ApprovalStepHistory.doc_id == doc_id,
            ApprovalStepHistory.step_order == 0,
            ApprovalStepHistory.action == "COMMENTED",
        )
        .order_by(ApprovalStepHistory.id)
        .first()
    )
    if row is None or not row.comment or not row.comment.startswith("__TEMPLATE__:"):
        return None
    try:
        return int(row.comment.split(":")[1])
    except (IndexError, ValueError):
        return None


def _load_doc(db: Session, doc_id: int) -> ApprovalDoc:
    doc = db.query(ApprovalDoc).filter(ApprovalDoc.id == doc_id).first()
    if doc is None:
        raise NotFound("결재 문서를 찾을 수 없습니다")
    return doc


def _assign_doc_no(db: Session, doc: ApprovalDoc, max_retries: int = 3) -> None:
    for attempt in range(max_retries):
        doc.doc_no = _next_doc_no(db)
        try:
            db.flush()
            return
        except IntegrityError:
            db.rollback()
            time.sleep(0.02 * (attempt + 1))
    raise InvalidState("문서번호 채번에 실패했습니다. 다시 시도해주세요")


def submit_doc(db: Session, doc_id: int, user: User) -> ApprovalDoc:
    doc = _load_doc(db, doc_id)
    if doc.drafter_id != (user.employee_id or -1):
        raise PermissionDenied("기안자만 상신할 수 있습니다")
    if doc.status != "DRAFT":
        raise InvalidState("DRAFT 상태에서만 상신할 수 있습니다")

    template_id = _template_id_for_doc(db, doc.id)
    if template_id is None:
        raise InvalidState("문서에 연결된 결재선이 없습니다")
    tpl = _load_template(db, template_id)
    steps = _sorted_steps(tpl)
    if not steps:
        raise InvalidState("결재선에 단계가 없습니다")

    first_step = steps[0]
    approver = resolve_approver(db, first_step, doc)
    if approver is None:
        raise InvalidState("1단계 결재자를 찾을 수 없습니다")

    doc.status = "PENDING"
    doc.current_step = 1
    doc.total_steps = len(steps)
    _assign_doc_no(db, doc)

    db.add(
        ApprovalStepHistory(
            doc_id=doc.id,
            step_order=1,
            approver_id=approver.id,
            action="PENDING",
            comment="상신",
        )
    )

    notif_svc.create(
        db,
        user_id=approver.id,
        type="APPROVAL_REQUESTED",
        title="새 결재 요청",
        message=f"[{doc.doc_no}] {doc.title}",
        link=f"/approval/docs/{doc.id}",
    )
    db.commit()
    db.refresh(doc)
    return doc


def _current_step(db: Session, doc: ApprovalDoc) -> Optional[ApprovalLineStep]:
    template_id = _template_id_for_doc(db, doc.id)
    if template_id is None:
        return None
    tpl = _load_template(db, template_id)
    for s in _sorted_steps(tpl):
        if s.step_order == doc.current_step:
            return s
    return None


def approve_step(
    db: Session, doc_id: int, user: User, comment: Optional[str] = None
) -> ApprovalDoc:
    doc = _load_doc(db, doc_id)
    if doc.status not in ("PENDING", "IN_PROGRESS"):
        raise InvalidState("진행 중인 문서만 결재할 수 있습니다")

    step = _current_step(db, doc)
    if step is None:
        raise InvalidState("현재 결재 단계를 해석할 수 없습니다")
    approver = resolve_approver(db, step, doc)
    if approver is None or approver.id != user.id:
        raise PermissionDenied("결재 권한이 없습니다")

    db.add(
        ApprovalStepHistory(
            doc_id=doc.id,
            step_order=doc.current_step,
            approver_id=user.id,
            action="APPROVED",
            comment=comment,
        )
    )

    is_final = doc.current_step >= doc.total_steps
    if is_final:
        doc.status = "APPROVED"
        doc.completed_at = datetime.now()
        drafter_user = _employee_user(db, doc.drafter_id)
        if drafter_user is not None:
            notif_svc.create(
                db,
                user_id=drafter_user.id,
                type="APPROVAL_APPROVED",
                title="결재 완료",
                message=f"[{doc.doc_no}] {doc.title}",
                link=f"/approval/docs/{doc.id}",
            )
    else:
        doc.current_step += 1
        doc.status = "IN_PROGRESS"
        template_id = _template_id_for_doc(db, doc.id)
        tpl = _load_template(db, template_id) if template_id else None
        next_step = None
        if tpl is not None:
            for s in _sorted_steps(tpl):
                if s.step_order == doc.current_step:
                    next_step = s
                    break
        if next_step is None:
            raise InvalidState("다음 결재 단계를 찾을 수 없습니다")
        next_approver = resolve_approver(db, next_step, doc)
        if next_approver is None:
            raise InvalidState("다음 결재자를 찾을 수 없습니다")
        db.add(
            ApprovalStepHistory(
                doc_id=doc.id,
                step_order=doc.current_step,
                approver_id=next_approver.id,
                action="PENDING",
                comment=None,
            )
        )
        notif_svc.create(
            db,
            user_id=next_approver.id,
            type="APPROVAL_REQUESTED",
            title="새 결재 요청",
            message=f"[{doc.doc_no}] {doc.title}",
            link=f"/approval/docs/{doc.id}",
        )

    db.commit()
    db.refresh(doc)
    if is_final:
        doc_hooks.dispatch(db, doc, "approved")
    return doc


def reject_step(
    db: Session, doc_id: int, user: User, comment: Optional[str] = None
) -> ApprovalDoc:
    doc = _load_doc(db, doc_id)
    if doc.status not in ("PENDING", "IN_PROGRESS"):
        raise InvalidState("진행 중인 문서만 반려할 수 있습니다")

    step = _current_step(db, doc)
    if step is None:
        raise InvalidState("현재 결재 단계를 해석할 수 없습니다")
    approver = resolve_approver(db, step, doc)
    if approver is None or approver.id != user.id:
        raise PermissionDenied("결재 권한이 없습니다")

    doc.status = "REJECTED"
    doc.completed_at = datetime.now()
    db.add(
        ApprovalStepHistory(
            doc_id=doc.id,
            step_order=doc.current_step,
            approver_id=user.id,
            action="REJECTED",
            comment=comment,
        )
    )

    drafter_user = _employee_user(db, doc.drafter_id)
    if drafter_user is not None:
        notif_svc.create(
            db,
            user_id=drafter_user.id,
            type="APPROVAL_REJECTED",
            title="결재 반려",
            message=f"[{doc.doc_no}] {doc.title}",
            link=f"/approval/docs/{doc.id}",
        )
    db.commit()
    db.refresh(doc)
    doc_hooks.dispatch(db, doc, "rejected")
    return doc


def recall_doc(db: Session, doc_id: int, user: User) -> ApprovalDoc:
    doc = _load_doc(db, doc_id)
    if doc.drafter_id != (user.employee_id or -1):
        raise PermissionDenied("기안자만 회수할 수 있습니다")
    if doc.status != "PENDING":
        raise InvalidState("PENDING 상태에서만 회수할 수 있습니다 (1단계 결재 전)")

    doc.status = "RECALLED"
    doc.completed_at = datetime.now()
    db.add(
        ApprovalStepHistory(
            doc_id=doc.id,
            step_order=doc.current_step,
            approver_id=user.id,
            action="RECALLED",
            comment="기안자 회수",
        )
    )
    db.commit()
    db.refresh(doc)
    doc_hooks.dispatch(db, doc, "recalled")
    return doc


# ── Listings ────────────────────────────────────────────────


def _enrich_doc_row(db: Session, doc: ApprovalDoc) -> dict[str, Any]:
    doc_type = (
        db.query(ApprovalDocType)
        .filter(ApprovalDocType.id == doc.doc_type_id)
        .first()
    )
    drafter = db.query(Employee).filter(Employee.id == doc.drafter_id).first()
    return {
        "id": doc.id,
        "doc_type_id": doc.doc_type_id,
        "doc_type_code": doc_type.code if doc_type else None,
        "doc_type_name": doc_type.name if doc_type else None,
        "doc_no": doc.doc_no,
        "title": doc.title,
        "drafter_id": doc.drafter_id,
        "drafter_name": drafter.name_ko if drafter else None,
        "status": doc.status,
        "current_step": doc.current_step,
        "total_steps": doc.total_steps,
        "drafted_at": doc.drafted_at,
        "completed_at": doc.completed_at,
    }


def get_inbox(
    db: Session, user: User, *, status_filter: Optional[str] = None
) -> list[dict[str, Any]]:
    """Documents where the current user is the active approver.

    We query by latest step_history rows with action=PENDING pointing at this user.
    """
    pending_rows = (
        db.query(ApprovalStepHistory.doc_id, ApprovalStepHistory.step_order)
        .filter(
            ApprovalStepHistory.approver_id == user.id,
            ApprovalStepHistory.action == "PENDING",
            ApprovalStepHistory.step_order > 0,
        )
        .all()
    )
    doc_ids = {row.doc_id for row in pending_rows}
    if not doc_ids:
        return []

    q = db.query(ApprovalDoc).filter(ApprovalDoc.id.in_(doc_ids))
    if status_filter:
        q = q.filter(ApprovalDoc.status == status_filter)
    else:
        q = q.filter(ApprovalDoc.status.in_(["PENDING", "IN_PROGRESS"]))
    docs = q.order_by(desc(ApprovalDoc.drafted_at)).all()

    # Only those where this user is the ACTIVE step approver (current_step match)
    active_pairs = {(row.doc_id, row.step_order) for row in pending_rows}
    return [
        _enrich_doc_row(db, d)
        for d in docs
        if (d.id, d.current_step) in active_pairs
    ]


def get_drafts(
    db: Session, user: User, *, status_filter: Optional[str] = None
) -> list[dict[str, Any]]:
    if user.employee_id is None:
        return []
    q = db.query(ApprovalDoc).filter(ApprovalDoc.drafter_id == user.employee_id)
    if status_filter:
        q = q.filter(ApprovalDoc.status == status_filter)
    docs = q.order_by(desc(ApprovalDoc.drafted_at)).all()
    return [_enrich_doc_row(db, d) for d in docs]


def get_doc_detail(db: Session, doc_id: int, user: User) -> dict[str, Any]:
    doc = _load_doc(db, doc_id)

    # Authorization: drafter OR any approver involved OR admin
    can_view = _is_admin(user) or doc.drafter_id == (user.employee_id or -1)
    if not can_view:
        involved = (
            db.query(ApprovalStepHistory.id)
            .filter(
                ApprovalStepHistory.doc_id == doc.id,
                ApprovalStepHistory.approver_id == user.id,
                ApprovalStepHistory.step_order > 0,
            )
            .first()
        )
        can_view = involved is not None
    if not can_view:
        raise PermissionDenied("문서를 열람할 권한이 없습니다")

    base = _enrich_doc_row(db, doc)

    # Line steps (resolve against current template binding)
    template_id = _template_id_for_doc(db, doc.id)
    line_steps: list[dict[str, Any]] = []
    if template_id is not None:
        tpl = _load_template(db, template_id)
        for s in _sorted_steps(tpl):
            approver_user = resolve_approver(db, s, doc)
            approver_name = None
            if approver_user is not None:
                emp = (
                    db.query(Employee)
                    .filter(Employee.id == approver_user.employee_id)
                    .first()
                )
                approver_name = emp.name_ko if emp else approver_user.login_id
            line_steps.append(
                {
                    "step_order": s.step_order,
                    "approver_type": s.approver_type,
                    "approver_ref": s.approver_ref,
                    "resolved_user_id": approver_user.id if approver_user else None,
                    "resolved_name": approver_name,
                    "is_required": s.is_required,
                }
            )

    history_rows = (
        db.query(ApprovalStepHistory)
        .filter(
            ApprovalStepHistory.doc_id == doc.id,
            ApprovalStepHistory.step_order > 0,
        )
        .order_by(ApprovalStepHistory.acted_at, ApprovalStepHistory.id)
        .all()
    )
    history = []
    for h in history_rows:
        approver = db.query(User).filter(User.id == h.approver_id).first()
        approver_name = None
        if approver and approver.employee_id:
            emp = db.query(Employee).filter(Employee.id == approver.employee_id).first()
            approver_name = emp.name_ko if emp else approver.login_id
        history.append(
            {
                "id": h.id,
                "step_order": h.step_order,
                "approver_id": h.approver_id,
                "approver_name": approver_name,
                "action": h.action,
                "comment": h.comment,
                "acted_at": h.acted_at,
            }
        )

    return {
        **base,
        "content": _loads_content(doc.content),
        "line_steps": line_steps,
        "history": history,
    }


def get_history(db: Session, doc_id: int, user: User) -> list[dict[str, Any]]:
    detail = get_doc_detail(db, doc_id, user)
    return detail["history"]


def inbox_unread_count(db: Session, user: User) -> int:
    return len(get_inbox(db, user, status_filter=None))


# ── Attachments ─────────────────────────────────────────────


def add_attachment(
    db: Session,
    doc_id: int,
    user: User,
    *,
    filename: str,
    filesize: int,
    filepath: str,
) -> ApprovalAttachment:
    doc = _load_doc(db, doc_id)
    if doc.drafter_id != (user.employee_id or -1) and not _is_admin(user):
        raise PermissionDenied("첨부 권한이 없습니다")
    if doc.status not in ("DRAFT", "PENDING", "IN_PROGRESS"):
        raise InvalidState("종료된 문서에는 첨부할 수 없습니다")
    att = ApprovalAttachment(
        doc_id=doc_id,
        filename=filename,
        filesize=filesize,
        filepath=filepath,
    )
    db.add(att)
    db.commit()
    db.refresh(att)
    return att


def list_attachments(db: Session, doc_id: int) -> list[ApprovalAttachment]:
    return (
        db.query(ApprovalAttachment)
        .filter(ApprovalAttachment.doc_id == doc_id)
        .order_by(ApprovalAttachment.id)
        .all()
    )
