"""PHASE 12 electronic-approval service tests.

Covers:
- resolve_approver: USER / ROLE / POSITION / DEPT_HEAD / DIRECT_MANAGER
- doc type & line template CRUD (+ default uniqueness)
- submit flow (status transition, doc_no, notification)
- approve_step sequential advance + final completion
- reject_step & recall_doc
- inbox / drafts / detail authorization
- doc_no sequencing
"""

from datetime import date

import pytest

from app.core.security import hash_password
from app.db.models import (
    ApprovalDoc,
    ApprovalDocType,
    ApprovalLineStep,
    ApprovalLineTemplate,
    ApprovalStepHistory,
    Department,
    Employee,
    Notification,
    Role,
    User,
    UserRole,
)
from app.services import approval_service as svc


# ── Fixtures ────────────────────────────────────────────────


@pytest.fixture
def dept_dev(db_session):
    d = Department(code="D-DEV", name="개발팀")
    db_session.add(d)
    db_session.commit()
    return d


@pytest.fixture
def dept_hr(db_session):
    d = Department(code="D-HR", name="인사팀")
    db_session.add(d)
    db_session.commit()
    return d


@pytest.fixture
def emp_dev(db_session, dept_dev):
    e = Employee(
        emp_no="E-DEV-1",
        name_ko="김기안",
        hire_date=date(2023, 1, 1),
        dept_id=dept_dev.id,
        job_position="사원",
        emp_status="재직",
        gender="M",
    )
    db_session.add(e)
    db_session.commit()
    return e


@pytest.fixture
def emp_leader(db_session, dept_dev):
    e = Employee(
        emp_no="E-DEV-2",
        name_ko="이팀장",
        hire_date=date(2020, 1, 1),
        dept_id=dept_dev.id,
        job_position="팀장",
        emp_status="재직",
        gender="M",
    )
    db_session.add(e)
    db_session.commit()
    return e


@pytest.fixture
def emp_head(db_session, dept_dev):
    e = Employee(
        emp_no="E-DEV-3",
        name_ko="박부장",
        hire_date=date(2015, 1, 1),
        dept_id=dept_dev.id,
        job_position="부장",
        emp_status="재직",
        gender="M",
    )
    db_session.add(e)
    db_session.commit()
    dept_dev  # noqa
    return e


@pytest.fixture
def user_drafter(db_session, emp_dev):
    u = User(
        login_id="drafter",
        password_hash=hash_password("p"),
        employee_id=emp_dev.id,
        is_active=True,
    )
    db_session.add(u)
    db_session.commit()
    return u


@pytest.fixture
def user_leader(db_session, emp_leader):
    u = User(
        login_id="leader",
        password_hash=hash_password("p"),
        employee_id=emp_leader.id,
        is_active=True,
    )
    db_session.add(u)
    db_session.commit()
    return u


@pytest.fixture
def user_head(db_session, emp_head, dept_dev):
    u = User(
        login_id="head",
        password_hash=hash_password("p"),
        employee_id=emp_head.id,
        is_active=True,
    )
    db_session.add(u)
    dept_dev.head_employee_id = emp_head.id
    db_session.commit()
    return u


@pytest.fixture
def role_hr(db_session):
    r = Role(code="HR_ADMIN", name="인사 담당자")
    db_session.add(r)
    db_session.commit()
    return r


@pytest.fixture
def user_hr_admin(db_session, role_hr):
    u = User(
        login_id="hradmin",
        password_hash=hash_password("p"),
        is_active=True,
    )
    db_session.add(u)
    db_session.flush()
    db_session.add(UserRole(user_id=u.id, role_id=role_hr.id))
    db_session.commit()
    db_session.refresh(u)
    return u


@pytest.fixture
def doc_type(db_session):
    dt = ApprovalDocType(
        code="TEST_DOC",
        name="테스트문서",
        category="OTHER",
        is_active=True,
    )
    db_session.add(dt)
    db_session.commit()
    return dt


def _build_template(
    db_session,
    doc_type,
    *,
    steps,
    is_default=True,
    name="기본결재선",
):
    tpl = ApprovalLineTemplate(
        doc_type_id=doc_type.id,
        name=name,
        scope="GLOBAL",
        is_default=is_default,
    )
    db_session.add(tpl)
    db_session.flush()
    for i, (atype, aref) in enumerate(steps, start=1):
        db_session.add(
            ApprovalLineStep(
                template_id=tpl.id,
                step_order=i,
                approver_type=atype,
                approver_ref=aref,
                is_required=True,
            )
        )
    db_session.commit()
    db_session.refresh(tpl)
    return tpl


# ── resolve_approver ─────────────────────────────────────────


def test_resolve_user_type(db_session, doc_type, user_drafter, user_leader, emp_dev):
    tpl = _build_template(db_session, doc_type, steps=[("USER", str(user_leader.id))])
    doc = ApprovalDoc(
        doc_type_id=doc_type.id,
        title="t",
        drafter_id=emp_dev.id,
        status="DRAFT",
        total_steps=1,
    )
    db_session.add(doc)
    db_session.commit()
    resolved = svc.resolve_approver(db_session, tpl.steps[0], doc)
    assert resolved is not None
    assert resolved.id == user_leader.id


def test_resolve_user_invalid_ref_returns_none(
    db_session, doc_type, user_drafter, emp_dev
):
    tpl = _build_template(db_session, doc_type, steps=[("USER", "not-a-number")])
    doc = ApprovalDoc(
        doc_type_id=doc_type.id,
        title="t",
        drafter_id=emp_dev.id,
        status="DRAFT",
        total_steps=1,
    )
    db_session.add(doc)
    db_session.commit()
    assert svc.resolve_approver(db_session, tpl.steps[0], doc) is None


def test_resolve_role_type(
    db_session, doc_type, role_hr, user_hr_admin, user_drafter, emp_dev
):
    tpl = _build_template(db_session, doc_type, steps=[("ROLE", "HR_ADMIN")])
    doc = ApprovalDoc(
        doc_type_id=doc_type.id,
        title="t",
        drafter_id=emp_dev.id,
        status="DRAFT",
        total_steps=1,
    )
    db_session.add(doc)
    db_session.commit()
    resolved = svc.resolve_approver(db_session, tpl.steps[0], doc)
    assert resolved is not None
    assert resolved.id == user_hr_admin.id


def test_resolve_role_type_not_found(db_session, doc_type, user_drafter, emp_dev):
    tpl = _build_template(db_session, doc_type, steps=[("ROLE", "NO_SUCH_ROLE")])
    doc = ApprovalDoc(
        doc_type_id=doc_type.id,
        title="t",
        drafter_id=emp_dev.id,
        status="DRAFT",
        total_steps=1,
    )
    db_session.add(doc)
    db_session.commit()
    assert svc.resolve_approver(db_session, tpl.steps[0], doc) is None


def test_resolve_position_same_dept_preferred(
    db_session, doc_type, user_drafter, user_leader, emp_dev
):
    tpl = _build_template(db_session, doc_type, steps=[("POSITION", "팀장")])
    doc = ApprovalDoc(
        doc_type_id=doc_type.id,
        title="t",
        drafter_id=emp_dev.id,
        status="DRAFT",
        total_steps=1,
    )
    db_session.add(doc)
    db_session.commit()
    resolved = svc.resolve_approver(db_session, tpl.steps[0], doc)
    assert resolved is not None
    assert resolved.id == user_leader.id


def test_resolve_dept_head(
    db_session, doc_type, user_drafter, user_head, emp_dev
):
    tpl = _build_template(db_session, doc_type, steps=[("DEPT_HEAD", None)])
    doc = ApprovalDoc(
        doc_type_id=doc_type.id,
        title="t",
        drafter_id=emp_dev.id,
        status="DRAFT",
        total_steps=1,
    )
    db_session.add(doc)
    db_session.commit()
    resolved = svc.resolve_approver(db_session, tpl.steps[0], doc)
    assert resolved is not None
    assert resolved.id == user_head.id


def test_resolve_dept_head_missing_returns_none(
    db_session, doc_type, user_drafter, emp_dev, dept_dev
):
    # dept_dev.head_employee_id is None by default in this fixture
    dept_dev.head_employee_id = None
    db_session.commit()
    tpl = _build_template(db_session, doc_type, steps=[("DEPT_HEAD", None)])
    doc = ApprovalDoc(
        doc_type_id=doc_type.id,
        title="t",
        drafter_id=emp_dev.id,
        status="DRAFT",
        total_steps=1,
    )
    db_session.add(doc)
    db_session.commit()
    assert svc.resolve_approver(db_session, tpl.steps[0], doc) is None


def test_resolve_direct_manager_prefers_team_lead(
    db_session, doc_type, user_drafter, user_leader, emp_dev
):
    tpl = _build_template(db_session, doc_type, steps=[("DIRECT_MANAGER", None)])
    doc = ApprovalDoc(
        doc_type_id=doc_type.id,
        title="t",
        drafter_id=emp_dev.id,
        status="DRAFT",
        total_steps=1,
    )
    db_session.add(doc)
    db_session.commit()
    resolved = svc.resolve_approver(db_session, tpl.steps[0], doc)
    assert resolved is not None
    assert resolved.id == user_leader.id


def test_resolve_direct_manager_falls_back_to_dept_head(
    db_session, doc_type, user_drafter, user_head, emp_dev, emp_leader
):
    # Remove the team lead from 재직 to force fallback
    emp_leader.emp_status = "퇴직"
    db_session.commit()
    tpl = _build_template(db_session, doc_type, steps=[("DIRECT_MANAGER", None)])
    doc = ApprovalDoc(
        doc_type_id=doc_type.id,
        title="t",
        drafter_id=emp_dev.id,
        status="DRAFT",
        total_steps=1,
    )
    db_session.add(doc)
    db_session.commit()
    resolved = svc.resolve_approver(db_session, tpl.steps[0], doc)
    assert resolved is not None
    assert resolved.id == user_head.id


# ── Doc type CRUD ───────────────────────────────────────────


def test_create_doc_type_duplicate_code_raises(db_session):
    svc.create_doc_type(
        db_session, code="DUP", name="중복", category="OTHER"
    )
    with pytest.raises(svc.InvalidState, match="이미 존재"):
        svc.create_doc_type(
            db_session, code="DUP", name="중복2", category="OTHER"
        )


def test_list_doc_types_active_only(db_session):
    svc.create_doc_type(db_session, code="A", name="A", category="OTHER")
    svc.create_doc_type(
        db_session, code="B", name="B", category="OTHER", is_active=False
    )
    active = svc.list_doc_types(db_session, active_only=True)
    assert len(active) == 1
    all_ = svc.list_doc_types(db_session, active_only=False)
    assert len(all_) == 2


def test_update_doc_type(db_session, doc_type):
    updated = svc.update_doc_type(
        db_session, doc_type.id, name="새이름", is_active=False
    )
    assert updated.name == "새이름"
    assert updated.is_active is False


# ── Line template CRUD ──────────────────────────────────────


def test_create_template_requires_steps(db_session, doc_type):
    with pytest.raises(svc.InvalidState, match="최소 1단계"):
        svc.create_template(
            db_session,
            doc_type_id=doc_type.id,
            name="empty",
            steps=[],
        )


def test_create_template_enforces_single_default(db_session, doc_type):
    t1 = svc.create_template(
        db_session,
        doc_type_id=doc_type.id,
        name="first",
        is_default=True,
        steps=[{"step_order": 1, "approver_type": "DEPT_HEAD"}],
    )
    t2 = svc.create_template(
        db_session,
        doc_type_id=doc_type.id,
        name="second",
        is_default=True,
        steps=[{"step_order": 1, "approver_type": "DEPT_HEAD"}],
    )
    db_session.refresh(t1)
    assert t1.is_default is False
    assert t2.is_default is True


def test_update_template_replaces_steps(db_session, doc_type):
    tpl = svc.create_template(
        db_session,
        doc_type_id=doc_type.id,
        name="t",
        is_default=True,
        steps=[
            {"step_order": 1, "approver_type": "DIRECT_MANAGER"},
            {"step_order": 2, "approver_type": "DEPT_HEAD"},
        ],
    )
    svc.update_template(
        db_session,
        tpl.id,
        steps=[{"step_order": 1, "approver_type": "DEPT_HEAD"}],
    )
    db_session.refresh(tpl)
    assert len(tpl.steps) == 1
    assert tpl.steps[0].approver_type == "DEPT_HEAD"


def test_delete_template(db_session, doc_type):
    tpl = svc.create_template(
        db_session,
        doc_type_id=doc_type.id,
        name="t",
        steps=[{"step_order": 1, "approver_type": "DEPT_HEAD"}],
    )
    svc.delete_template(db_session, tpl.id)
    assert (
        db_session.query(ApprovalLineTemplate)
        .filter(ApprovalLineTemplate.id == tpl.id)
        .first()
        is None
    )


# ── Draft / submit ──────────────────────────────────────────


def test_create_draft_stores_content_json(
    db_session, doc_type, user_drafter, user_leader
):
    tpl = _build_template(
        db_session, doc_type, steps=[("USER", str(user_leader.id))]
    )
    doc = svc.create_draft(
        db_session,
        user=user_drafter,
        doc_type_id=doc_type.id,
        title="제목",
        content={"reason": "휴가", "days": 3},
        line_template_id=tpl.id,
    )
    assert doc.status == "DRAFT"
    assert doc.doc_no is None
    assert doc.total_steps == 1
    # template binding sentinel
    bound = svc._template_id_for_doc(db_session, doc.id)
    assert bound == tpl.id


def test_create_draft_mismatched_template_raises(
    db_session, doc_type, user_drafter, user_leader
):
    other = ApprovalDocType(code="OTHER", name="other", category="OTHER")
    db_session.add(other)
    db_session.commit()
    tpl = _build_template(
        db_session, other, steps=[("USER", str(user_leader.id))]
    )
    with pytest.raises(svc.InvalidState, match="일치하지 않습니다"):
        svc.create_draft(
            db_session,
            user=user_drafter,
            doc_type_id=doc_type.id,
            title="t",
            content=None,
            line_template_id=tpl.id,
        )


def test_submit_assigns_doc_no_and_creates_notification(
    db_session, doc_type, user_drafter, user_leader
):
    tpl = _build_template(
        db_session, doc_type, steps=[("USER", str(user_leader.id))]
    )
    doc = svc.create_draft(
        db_session,
        user=user_drafter,
        doc_type_id=doc_type.id,
        title="t",
        content=None,
        line_template_id=tpl.id,
    )
    submitted = svc.submit_doc(db_session, doc.id, user_drafter)
    assert submitted.status == "PENDING"
    assert submitted.current_step == 1
    assert submitted.doc_no is not None
    notes = (
        db_session.query(Notification)
        .filter(Notification.user_id == user_leader.id)
        .all()
    )
    assert len(notes) == 1
    assert notes[0].type == "APPROVAL_REQUESTED"


def test_submit_only_drafter_allowed(
    db_session, doc_type, user_drafter, user_leader
):
    tpl = _build_template(
        db_session, doc_type, steps=[("USER", str(user_leader.id))]
    )
    doc = svc.create_draft(
        db_session,
        user=user_drafter,
        doc_type_id=doc_type.id,
        title="t",
        content=None,
        line_template_id=tpl.id,
    )
    with pytest.raises(svc.PermissionDenied):
        svc.submit_doc(db_session, doc.id, user_leader)


def test_submit_twice_raises(db_session, doc_type, user_drafter, user_leader):
    tpl = _build_template(
        db_session, doc_type, steps=[("USER", str(user_leader.id))]
    )
    doc = svc.create_draft(
        db_session,
        user=user_drafter,
        doc_type_id=doc_type.id,
        title="t",
        content=None,
        line_template_id=tpl.id,
    )
    svc.submit_doc(db_session, doc.id, user_drafter)
    with pytest.raises(svc.InvalidState, match="DRAFT 상태"):
        svc.submit_doc(db_session, doc.id, user_drafter)


# ── approve / reject ────────────────────────────────────────


def _two_step_submitted(db_session, doc_type, user_drafter, user_leader, user_head):
    tpl = _build_template(
        db_session,
        doc_type,
        steps=[
            ("USER", str(user_leader.id)),
            ("USER", str(user_head.id)),
        ],
    )
    doc = svc.create_draft(
        db_session,
        user=user_drafter,
        doc_type_id=doc_type.id,
        title="2단계",
        content=None,
        line_template_id=tpl.id,
    )
    return svc.submit_doc(db_session, doc.id, user_drafter)


def test_approve_advances_to_next_step(
    db_session, doc_type, user_drafter, user_leader, user_head
):
    doc = _two_step_submitted(
        db_session, doc_type, user_drafter, user_leader, user_head
    )
    updated = svc.approve_step(db_session, doc.id, user_leader, comment="ok")
    assert updated.status == "IN_PROGRESS"
    assert updated.current_step == 2
    # Next approver got a notification
    head_notes = (
        db_session.query(Notification)
        .filter(
            Notification.user_id == user_head.id,
            Notification.type == "APPROVAL_REQUESTED",
        )
        .all()
    )
    assert len(head_notes) == 1


def test_approve_final_step_completes(
    db_session, doc_type, user_drafter, user_leader, user_head
):
    doc = _two_step_submitted(
        db_session, doc_type, user_drafter, user_leader, user_head
    )
    svc.approve_step(db_session, doc.id, user_leader)
    final = svc.approve_step(db_session, doc.id, user_head)
    assert final.status == "APPROVED"
    assert final.completed_at is not None
    # Drafter got completion notification
    drafter_notes = (
        db_session.query(Notification)
        .filter(
            Notification.user_id == user_drafter.id,
            Notification.type == "APPROVAL_APPROVED",
        )
        .all()
    )
    assert len(drafter_notes) == 1


def test_approve_wrong_user_denied(
    db_session, doc_type, user_drafter, user_leader, user_head
):
    doc = _two_step_submitted(
        db_session, doc_type, user_drafter, user_leader, user_head
    )
    with pytest.raises(svc.PermissionDenied):
        svc.approve_step(db_session, doc.id, user_head)  # step 2 user at step 1


def test_reject_ends_flow_and_notifies(
    db_session, doc_type, user_drafter, user_leader, user_head
):
    doc = _two_step_submitted(
        db_session, doc_type, user_drafter, user_leader, user_head
    )
    rejected = svc.reject_step(db_session, doc.id, user_leader, comment="부적합")
    assert rejected.status == "REJECTED"
    assert rejected.completed_at is not None
    notes = (
        db_session.query(Notification)
        .filter(
            Notification.user_id == user_drafter.id,
            Notification.type == "APPROVAL_REJECTED",
        )
        .all()
    )
    assert len(notes) == 1


def test_reject_by_wrong_user_denied(
    db_session, doc_type, user_drafter, user_leader, user_head
):
    doc = _two_step_submitted(
        db_session, doc_type, user_drafter, user_leader, user_head
    )
    with pytest.raises(svc.PermissionDenied):
        svc.reject_step(db_session, doc.id, user_head)


# ── recall ──────────────────────────────────────────────────


def test_recall_only_pending_step_one(
    db_session, doc_type, user_drafter, user_leader, user_head
):
    doc = _two_step_submitted(
        db_session, doc_type, user_drafter, user_leader, user_head
    )
    recalled = svc.recall_doc(db_session, doc.id, user_drafter)
    assert recalled.status == "RECALLED"


def test_recall_after_first_approve_fails(
    db_session, doc_type, user_drafter, user_leader, user_head
):
    doc = _two_step_submitted(
        db_session, doc_type, user_drafter, user_leader, user_head
    )
    svc.approve_step(db_session, doc.id, user_leader)
    with pytest.raises(svc.InvalidState, match="PENDING 상태"):
        svc.recall_doc(db_session, doc.id, user_drafter)


def test_recall_by_non_drafter_denied(
    db_session, doc_type, user_drafter, user_leader, user_head
):
    doc = _two_step_submitted(
        db_session, doc_type, user_drafter, user_leader, user_head
    )
    with pytest.raises(svc.PermissionDenied):
        svc.recall_doc(db_session, doc.id, user_leader)


# ── inbox / drafts / detail ─────────────────────────────────


def test_inbox_shows_only_active_approver(
    db_session, doc_type, user_drafter, user_leader, user_head
):
    doc = _two_step_submitted(
        db_session, doc_type, user_drafter, user_leader, user_head
    )
    # leader is step 1 active — should see it
    leader_inbox = svc.get_inbox(db_session, user_leader)
    assert len(leader_inbox) == 1
    assert leader_inbox[0]["id"] == doc.id
    # head is step 2 — should NOT see it yet
    head_inbox = svc.get_inbox(db_session, user_head)
    assert head_inbox == []

    svc.approve_step(db_session, doc.id, user_leader)
    # Now head should see it, leader should not
    assert svc.get_inbox(db_session, user_leader) == []
    head_inbox2 = svc.get_inbox(db_session, user_head)
    assert len(head_inbox2) == 1


def test_drafts_filter_by_status(
    db_session, doc_type, user_drafter, user_leader
):
    tpl = _build_template(
        db_session, doc_type, steps=[("USER", str(user_leader.id))]
    )
    svc.create_draft(
        db_session,
        user=user_drafter,
        doc_type_id=doc_type.id,
        title="draft1",
        content=None,
        line_template_id=tpl.id,
    )
    doc2 = svc.create_draft(
        db_session,
        user=user_drafter,
        doc_type_id=doc_type.id,
        title="draft2",
        content=None,
        line_template_id=tpl.id,
    )
    svc.submit_doc(db_session, doc2.id, user_drafter)

    all_drafts = svc.get_drafts(db_session, user_drafter)
    assert len(all_drafts) == 2
    only_draft = svc.get_drafts(db_session, user_drafter, status_filter="DRAFT")
    assert len(only_draft) == 1
    only_pending = svc.get_drafts(
        db_session, user_drafter, status_filter="PENDING"
    )
    assert len(only_pending) == 1


def test_detail_authorization_outsider_denied(
    db_session, doc_type, user_drafter, user_leader, user_head
):
    doc = _two_step_submitted(
        db_session, doc_type, user_drafter, user_leader, user_head
    )
    outsider = User(
        login_id="outsider", password_hash=hash_password("p"), is_active=True
    )
    db_session.add(outsider)
    db_session.commit()
    with pytest.raises(svc.PermissionDenied):
        svc.get_doc_detail(db_session, doc.id, outsider)


def test_detail_admin_can_view(
    db_session, doc_type, user_drafter, user_leader, user_head, user_hr_admin
):
    doc = _two_step_submitted(
        db_session, doc_type, user_drafter, user_leader, user_head
    )
    detail = svc.get_doc_detail(db_session, doc.id, user_hr_admin)
    assert detail["id"] == doc.id
    assert len(detail["line_steps"]) == 2


def test_detail_drafter_can_view(
    db_session, doc_type, user_drafter, user_leader
):
    tpl = _build_template(
        db_session, doc_type, steps=[("USER", str(user_leader.id))]
    )
    doc = svc.create_draft(
        db_session,
        user=user_drafter,
        doc_type_id=doc_type.id,
        title="t",
        content={"k": "v"},
        line_template_id=tpl.id,
    )
    detail = svc.get_doc_detail(db_session, doc.id, user_drafter)
    assert detail["content"] == {"k": "v"}


# ── doc_no sequencing ───────────────────────────────────────


def test_doc_no_increments_within_same_day(
    db_session, doc_type, user_drafter, user_leader
):
    tpl = _build_template(
        db_session, doc_type, steps=[("USER", str(user_leader.id))]
    )
    docs = []
    for i in range(3):
        d = svc.create_draft(
            db_session,
            user=user_drafter,
            doc_type_id=doc_type.id,
            title=f"d{i}",
            content=None,
            line_template_id=tpl.id,
        )
        svc.submit_doc(db_session, d.id, user_drafter)
        db_session.refresh(d)
        docs.append(d.doc_no)
    # Strictly monotonic same-prefix sequence
    prefixes = {n.split("-")[0] for n in docs}
    assert len(prefixes) == 1
    seqs = [int(n.split("-")[1]) for n in docs]
    assert seqs == sorted(seqs)
    assert seqs[-1] - seqs[0] == 2


# ── transaction atomicity ──────────────────────────────────


def test_approve_creates_history_row(
    db_session, doc_type, user_drafter, user_leader, user_head
):
    doc = _two_step_submitted(
        db_session, doc_type, user_drafter, user_leader, user_head
    )
    svc.approve_step(db_session, doc.id, user_leader, comment="ok1")
    hist = (
        db_session.query(ApprovalStepHistory)
        .filter(
            ApprovalStepHistory.doc_id == doc.id,
            ApprovalStepHistory.step_order > 0,
        )
        .order_by(ApprovalStepHistory.id)
        .all()
    )
    actions = [h.action for h in hist]
    # Expect: PENDING (step1 at submit) → APPROVED (step1) → PENDING (step2)
    assert "APPROVED" in actions
    assert actions.count("PENDING") == 2
