"""Shared calendar service (PHASE 13).

Design:
- Scope: COMPANY / DEPT / PERSONAL calendars + events + participants.
- Visibility filtering (PUBLIC / DEPT / PRIVATE) is applied at the application
  layer — the DB keeps raw rows so admins can audit.
- KST naive datetimes throughout. No timezone conversion.
- Approval bridge: `create_event_from_approval` / `delete_events_from_approval`
  are idempotent by (source_type='APPROVAL_DOC', source_ref=doc_id).
- No notification wiring (explicit PHASE 13 non-goal).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.db.models import (
    Calendar,
    CalendarEvent,
    CalendarEventParticipant,
    Employee,
    User,
)


# ── Errors ──────────────────────────────────────────────────


class CalendarError(Exception):
    """Business-rule violation inside the calendar domain."""


class NotFound(CalendarError):
    pass


class PermissionDenied(CalendarError):
    pass


class InvalidInput(CalendarError):
    pass


# ── Helpers ─────────────────────────────────────────────────


def _user_role_codes(user: User) -> set[str]:
    return {ur.role.code for ur in user.roles}


def _is_admin(user: User) -> bool:
    codes = _user_role_codes(user)
    return "SYSTEM_ADMIN" in codes or "HR_ADMIN" in codes


def _owner_employee_id(user: User) -> Optional[int]:
    return user.employee_id


def _employee_dept_id(db: Session, employee_id: Optional[int]) -> Optional[int]:
    if employee_id is None:
        return None
    emp = db.get(Employee, employee_id)
    return emp.dept_id if emp else None


def _ensure_range(start_at: datetime, end_at: datetime) -> None:
    if end_at < start_at:
        raise InvalidInput("end_at must be >= start_at")


def _serialize_event(db: Session, event: CalendarEvent) -> dict[str, Any]:
    cal = event.calendar
    owner = db.get(Employee, event.owner_id) if event.owner_id else None

    participants = []
    for p in event.participants:
        emp = db.get(Employee, p.emp_id) if p.emp_id else None
        participants.append(
            {
                "id": p.id,
                "event_id": p.event_id,
                "emp_id": p.emp_id,
                "emp_name": emp.name_ko if emp else None,
                "role": p.role,
                "response": p.response,
            }
        )

    return {
        "id": event.id,
        "calendar_id": event.calendar_id,
        "calendar_name": cal.name if cal else None,
        "calendar_color": cal.color_hex if cal else None,
        "title": event.title,
        "description": event.description,
        "event_type": event.event_type,
        "source_type": event.source_type,
        "source_ref": event.source_ref,
        "start_at": event.start_at,
        "end_at": event.end_at,
        "all_day": event.all_day,
        "owner_id": event.owner_id,
        "owner_name": owner.name_ko if owner else None,
        "location": event.location,
        "visibility": event.visibility,
        "created_at": event.created_at,
        "updated_at": event.updated_at,
        "participants": participants,
    }


def _can_view_event(
    db: Session, event: CalendarEvent, user: User
) -> bool:
    """Visibility rule:
    - PUBLIC: anyone.
    - DEPT: same department as owner OR admin OR the owner/participant.
    - PRIVATE: owner + participants + admin only.
    """
    if _is_admin(user):
        return True

    my_emp_id = _owner_employee_id(user)

    if event.owner_id == my_emp_id:
        return True

    participant_emp_ids = {p.emp_id for p in event.participants}
    if my_emp_id in participant_emp_ids:
        return True

    if event.visibility == "PUBLIC":
        return True

    if event.visibility == "DEPT":
        my_dept = _employee_dept_id(db, my_emp_id)
        owner_dept = _employee_dept_id(db, event.owner_id)
        return my_dept is not None and my_dept == owner_dept

    return False


def _can_edit_event(event: CalendarEvent, user: User) -> bool:
    """Edit: owner user or admin."""
    if _is_admin(user):
        return True
    my_emp_id = _owner_employee_id(user)
    return my_emp_id is not None and event.owner_id == my_emp_id


# ── Calendars ───────────────────────────────────────────────


def list_calendars(db: Session, user: User) -> list[Calendar]:
    """All COMPANY calendars + DEPT calendars matching user's dept + PERSONAL of self."""
    my_emp_id = _owner_employee_id(user)
    my_dept = _employee_dept_id(db, my_emp_id)

    q = db.query(Calendar)
    conds = [Calendar.scope == "COMPANY"]
    if my_dept is not None:
        conds.append(and_(Calendar.scope == "DEPT", Calendar.scope_ref == my_dept))
    if my_emp_id is not None:
        conds.append(
            and_(Calendar.scope == "PERSONAL", Calendar.scope_ref == user.id)
        )
    if _is_admin(user):
        return q.order_by(Calendar.id).all()
    return q.filter(or_(*conds)).order_by(Calendar.id).all()


def create_calendar(
    db: Session,
    user: User,
    *,
    name: str,
    color_hex: str = "#1677ff",
    scope: str = "COMPANY",
    scope_ref: Optional[int] = None,
    is_default: bool = False,
) -> Calendar:
    if scope == "COMPANY" and not _is_admin(user):
        raise PermissionDenied("only admins can create company calendars")
    if scope == "DEPT":
        if scope_ref is None:
            raise InvalidInput("dept calendar requires scope_ref")
        if not _is_admin(user):
            my_dept = _employee_dept_id(db, _owner_employee_id(user))
            if my_dept != scope_ref:
                raise PermissionDenied(
                    "cannot create dept calendar for a foreign dept"
                )
    if scope == "PERSONAL":
        scope_ref = user.id

    cal = Calendar(
        name=name,
        color_hex=color_hex,
        scope=scope,
        scope_ref=scope_ref,
        is_default=is_default,
        created_by=user.id,
    )
    db.add(cal)
    db.commit()
    db.refresh(cal)
    return cal


def update_calendar(
    db: Session,
    user: User,
    calendar_id: int,
    *,
    name: Optional[str] = None,
    color_hex: Optional[str] = None,
    is_default: Optional[bool] = None,
) -> Calendar:
    cal = db.get(Calendar, calendar_id)
    if cal is None:
        raise NotFound("calendar not found")
    if cal.scope == "COMPANY" and not _is_admin(user):
        raise PermissionDenied("only admins can edit company calendars")
    if cal.scope == "PERSONAL" and cal.scope_ref != user.id and not _is_admin(user):
        raise PermissionDenied("cannot edit other user's personal calendar")

    if name is not None:
        cal.name = name
    if color_hex is not None:
        cal.color_hex = color_hex
    if is_default is not None:
        cal.is_default = is_default
    db.commit()
    db.refresh(cal)
    return cal


def delete_calendar(db: Session, user: User, calendar_id: int) -> None:
    cal = db.get(Calendar, calendar_id)
    if cal is None:
        raise NotFound("calendar not found")
    if cal.scope == "COMPANY" and not _is_admin(user):
        raise PermissionDenied("only admins can delete company calendars")
    if cal.scope == "PERSONAL" and cal.scope_ref != user.id and not _is_admin(user):
        raise PermissionDenied("cannot delete other user's personal calendar")
    if cal.is_default:
        raise InvalidInput("cannot delete default calendar")
    db.delete(cal)
    db.commit()


# ── Events ──────────────────────────────────────────────────


def list_events(
    db: Session,
    user: User,
    *,
    start: datetime,
    end: datetime,
    calendar_ids: Optional[list[int]] = None,
    event_types: Optional[list[str]] = None,
    owner_id: Optional[int] = None,
) -> list[dict[str, Any]]:
    """Return events overlapping [start, end], filtered by visibility."""
    if end < start:
        raise InvalidInput("end must be >= start")

    q = db.query(CalendarEvent).filter(
        CalendarEvent.start_at < end,
        CalendarEvent.end_at >= start,
    )
    if calendar_ids:
        q = q.filter(CalendarEvent.calendar_id.in_(calendar_ids))
    if event_types:
        q = q.filter(CalendarEvent.event_type.in_(event_types))
    if owner_id is not None:
        q = q.filter(CalendarEvent.owner_id == owner_id)

    events = q.order_by(CalendarEvent.start_at).all()
    visible = [e for e in events if _can_view_event(db, e, user)]
    return [_serialize_event(db, e) for e in visible]


def get_event(db: Session, user: User, event_id: int) -> dict[str, Any]:
    event = db.get(CalendarEvent, event_id)
    if event is None:
        raise NotFound("event not found")
    if not _can_view_event(db, event, user):
        raise PermissionDenied("cannot view this event")
    return _serialize_event(db, event)


def create_event(
    db: Session,
    user: User,
    *,
    calendar_id: int,
    title: str,
    start_at: datetime,
    end_at: datetime,
    description: Optional[str] = None,
    event_type: str = "MANUAL",
    all_day: bool = False,
    location: Optional[str] = None,
    visibility: str = "PUBLIC",
    participant_emp_ids: Optional[list[int]] = None,
) -> dict[str, Any]:
    cal = db.get(Calendar, calendar_id)
    if cal is None:
        raise NotFound("calendar not found")
    _ensure_range(start_at, end_at)
    my_emp_id = _owner_employee_id(user)
    if my_emp_id is None:
        raise InvalidInput("user has no linked employee")

    event = CalendarEvent(
        calendar_id=calendar_id,
        title=title,
        description=description,
        event_type=event_type,
        source_type="MANUAL",
        source_ref=None,
        start_at=start_at,
        end_at=end_at,
        all_day=all_day,
        owner_id=my_emp_id,
        location=location,
        visibility=visibility,
    )
    db.add(event)
    db.flush()

    # Organizer = owner, auto-added
    db.add(
        CalendarEventParticipant(
            event_id=event.id,
            emp_id=my_emp_id,
            role="ORGANIZER",
            response="ACCEPTED",
        )
    )

    if participant_emp_ids:
        seen = {my_emp_id}
        for emp_id in participant_emp_ids:
            if emp_id in seen:
                continue
            seen.add(emp_id)
            db.add(
                CalendarEventParticipant(
                    event_id=event.id,
                    emp_id=emp_id,
                    role="REQUIRED",
                    response="PENDING",
                )
            )

    db.commit()
    db.refresh(event)
    return _serialize_event(db, event)


def update_event(
    db: Session,
    user: User,
    event_id: int,
    *,
    calendar_id: Optional[int] = None,
    title: Optional[str] = None,
    description: Optional[str] = None,
    event_type: Optional[str] = None,
    start_at: Optional[datetime] = None,
    end_at: Optional[datetime] = None,
    all_day: Optional[bool] = None,
    location: Optional[str] = None,
    visibility: Optional[str] = None,
) -> dict[str, Any]:
    event = db.get(CalendarEvent, event_id)
    if event is None:
        raise NotFound("event not found")
    if not _can_edit_event(event, user):
        raise PermissionDenied("only owner or admin can edit")

    new_start = start_at if start_at is not None else event.start_at
    new_end = end_at if end_at is not None else event.end_at
    _ensure_range(new_start, new_end)

    if calendar_id is not None:
        if db.get(Calendar, calendar_id) is None:
            raise NotFound("calendar not found")
        event.calendar_id = calendar_id
    if title is not None:
        event.title = title
    if description is not None:
        event.description = description
    if event_type is not None:
        event.event_type = event_type
    if start_at is not None:
        event.start_at = start_at
    if end_at is not None:
        event.end_at = end_at
    if all_day is not None:
        event.all_day = all_day
    if location is not None:
        event.location = location
    if visibility is not None:
        event.visibility = visibility

    db.commit()
    db.refresh(event)
    return _serialize_event(db, event)


def delete_event(db: Session, user: User, event_id: int) -> None:
    event = db.get(CalendarEvent, event_id)
    if event is None:
        raise NotFound("event not found")
    if not _can_edit_event(event, user):
        raise PermissionDenied("only owner or admin can delete")
    db.delete(event)
    db.commit()


# ── Participants ────────────────────────────────────────────


def add_participants(
    db: Session,
    user: User,
    event_id: int,
    *,
    emp_ids: list[int],
    role: str = "REQUIRED",
) -> list[dict[str, Any]]:
    event = db.get(CalendarEvent, event_id)
    if event is None:
        raise NotFound("event not found")
    if not _can_edit_event(event, user):
        raise PermissionDenied("only owner or admin can add participants")

    existing = {p.emp_id for p in event.participants}
    added: list[CalendarEventParticipant] = []
    for emp_id in emp_ids:
        if emp_id in existing:
            continue
        existing.add(emp_id)
        p = CalendarEventParticipant(
            event_id=event.id,
            emp_id=emp_id,
            role=role,
            response="PENDING",
        )
        db.add(p)
        added.append(p)
    db.commit()
    for p in added:
        db.refresh(p)

    out = []
    for p in added:
        emp = db.get(Employee, p.emp_id)
        out.append(
            {
                "id": p.id,
                "event_id": p.event_id,
                "emp_id": p.emp_id,
                "emp_name": emp.name_ko if emp else None,
                "role": p.role,
                "response": p.response,
            }
        )
    return out


def respond_participant(
    db: Session,
    user: User,
    event_id: int,
    *,
    response: str,
) -> dict[str, Any]:
    event = db.get(CalendarEvent, event_id)
    if event is None:
        raise NotFound("event not found")
    my_emp_id = _owner_employee_id(user)
    if my_emp_id is None:
        raise InvalidInput("user has no linked employee")

    participant = (
        db.query(CalendarEventParticipant)
        .filter(
            CalendarEventParticipant.event_id == event_id,
            CalendarEventParticipant.emp_id == my_emp_id,
        )
        .first()
    )
    if participant is None:
        raise NotFound("you are not a participant of this event")

    participant.response = response
    db.commit()
    db.refresh(participant)

    emp = db.get(Employee, participant.emp_id)
    return {
        "id": participant.id,
        "event_id": participant.event_id,
        "emp_id": participant.emp_id,
        "emp_name": emp.name_ko if emp else None,
        "role": participant.role,
        "response": participant.response,
    }


# ── Convenience views ───────────────────────────────────────


def get_my_events(
    db: Session,
    user: User,
    *,
    start: datetime,
    end: datetime,
) -> list[dict[str, Any]]:
    """Events where user is owner OR participant, regardless of visibility."""
    if end < start:
        raise InvalidInput("end must be >= start")
    my_emp_id = _owner_employee_id(user)
    if my_emp_id is None:
        return []

    owner_q = db.query(CalendarEvent).filter(
        CalendarEvent.owner_id == my_emp_id,
        CalendarEvent.start_at < end,
        CalendarEvent.end_at >= start,
    )
    participant_q = (
        db.query(CalendarEvent)
        .join(
            CalendarEventParticipant,
            CalendarEventParticipant.event_id == CalendarEvent.id,
        )
        .filter(
            CalendarEventParticipant.emp_id == my_emp_id,
            CalendarEvent.start_at < end,
            CalendarEvent.end_at >= start,
        )
    )
    seen: dict[int, CalendarEvent] = {}
    for e in owner_q.all():
        seen[e.id] = e
    for e in participant_q.all():
        seen[e.id] = e
    events = sorted(seen.values(), key=lambda e: e.start_at)
    return [_serialize_event(db, e) for e in events]


def get_dept_events(
    db: Session,
    user: User,
    *,
    start: datetime,
    end: datetime,
    dept_id: Optional[int] = None,
) -> list[dict[str, Any]]:
    """Events by members of a given dept (defaults to user's own)."""
    if end < start:
        raise InvalidInput("end must be >= start")
    target_dept = dept_id
    if target_dept is None:
        target_dept = _employee_dept_id(db, _owner_employee_id(user))
    if target_dept is None:
        return []

    emp_ids = [
        e.id for e in db.query(Employee).filter(Employee.dept_id == target_dept).all()
    ]
    if not emp_ids:
        return []

    events = (
        db.query(CalendarEvent)
        .filter(
            CalendarEvent.owner_id.in_(emp_ids),
            CalendarEvent.start_at < end,
            CalendarEvent.end_at >= start,
        )
        .order_by(CalendarEvent.start_at)
        .all()
    )
    visible = [e for e in events if _can_view_event(db, e, user)]
    return [_serialize_event(db, e) for e in visible]


# ── Approval bridge (PHASE 15/16 hooks) ─────────────────────


_EVENT_TYPE_TO_CALENDAR_NAME = {
    "LEAVE": "휴가",
    "TRAVEL": "출장",
    "MEETING": "회사 전사",
    "MANUAL": "회사 전사",
    "OTHER": "회사 전사",
}


def _pick_bridge_calendar(
    db: Session, *, calendar_code: Optional[str], event_type: str
) -> Calendar:
    """Resolve a calendar for approval-sourced events.

    Order:
    1. explicit `calendar_code` (matched by name)
    2. default mapping by event_type
    3. first is_default=True COMPANY calendar
    """
    if calendar_code:
        cal = db.query(Calendar).filter(Calendar.name == calendar_code).first()
        if cal:
            return cal

    name = _EVENT_TYPE_TO_CALENDAR_NAME.get(event_type, "회사 전사")
    cal = db.query(Calendar).filter(Calendar.name == name).first()
    if cal:
        return cal

    cal = (
        db.query(Calendar)
        .filter(Calendar.scope == "COMPANY", Calendar.is_default.is_(True))
        .first()
    )
    if cal is None:
        raise NotFound("no suitable company calendar for approval bridge")
    return cal


def create_event_from_approval(
    db: Session,
    doc_id: int,
    *,
    event_type: str,
    start_at: datetime,
    end_at: datetime,
    owner_id: int,
    title: str,
    all_day: bool = False,
    calendar_code: Optional[str] = None,
    description: Optional[str] = None,
    location: Optional[str] = None,
    visibility: str = "PUBLIC",
    participant_emp_ids: Optional[list[int]] = None,
) -> CalendarEvent:
    """Idempotent: (source_type='APPROVAL_DOC', source_ref=doc_id) is unique.

    A second call with the same doc_id updates the existing event in place
    rather than creating a duplicate — supports re-approval / resubmission.
    """
    _ensure_range(start_at, end_at)
    cal = _pick_bridge_calendar(
        db, calendar_code=calendar_code, event_type=event_type
    )

    existing = (
        db.query(CalendarEvent)
        .filter(
            CalendarEvent.source_type == "APPROVAL_DOC",
            CalendarEvent.source_ref == doc_id,
        )
        .first()
    )

    if existing is not None:
        existing.calendar_id = cal.id
        existing.title = title
        existing.description = description
        existing.event_type = event_type
        existing.start_at = start_at
        existing.end_at = end_at
        existing.all_day = all_day
        existing.owner_id = owner_id
        existing.location = location
        existing.visibility = visibility
        db.commit()
        db.refresh(existing)
        return existing

    event = CalendarEvent(
        calendar_id=cal.id,
        title=title,
        description=description,
        event_type=event_type,
        source_type="APPROVAL_DOC",
        source_ref=doc_id,
        start_at=start_at,
        end_at=end_at,
        all_day=all_day,
        owner_id=owner_id,
        location=location,
        visibility=visibility,
    )
    db.add(event)
    db.flush()

    db.add(
        CalendarEventParticipant(
            event_id=event.id,
            emp_id=owner_id,
            role="ORGANIZER",
            response="ACCEPTED",
        )
    )
    if participant_emp_ids:
        seen = {owner_id}
        for emp_id in participant_emp_ids:
            if emp_id in seen:
                continue
            seen.add(emp_id)
            db.add(
                CalendarEventParticipant(
                    event_id=event.id,
                    emp_id=emp_id,
                    role="REQUIRED",
                    response="PENDING",
                )
            )

    db.commit()
    db.refresh(event)
    return event


def delete_events_from_approval(db: Session, doc_id: int) -> int:
    """Remove all events spawned from a given approval doc.

    Returns the number of deleted events.
    """
    events = (
        db.query(CalendarEvent)
        .filter(
            CalendarEvent.source_type == "APPROVAL_DOC",
            CalendarEvent.source_ref == doc_id,
        )
        .all()
    )
    count = len(events)
    for e in events:
        db.delete(e)
    db.commit()
    return count
