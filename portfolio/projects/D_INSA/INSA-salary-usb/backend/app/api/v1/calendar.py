"""API routes for shared company calendar (PHASE 13)."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.db.models import User
from app.db.session import get_db
from app.schemas.calendar import (
    CalendarCreate,
    CalendarResponse,
    CalendarUpdate,
)
from app.schemas.calendar_event import (
    AddParticipantsRequest,
    EventCreate,
    EventResponse,
    EventUpdate,
    ParticipantResponseRequest,
)
from app.services import calendar_service as svc

router = APIRouter(prefix="/calendar", tags=["calendar"])


def _map_error(exc: Exception) -> HTTPException:
    if isinstance(exc, svc.NotFound):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, svc.PermissionDenied):
        return HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, svc.InvalidInput):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=500, detail="internal error")


# ── Calendars ───────────────────────────────────────────────


@router.get("/calendars", response_model=list[CalendarResponse])
def list_calendars_route(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return svc.list_calendars(db, current_user)


@router.post(
    "/calendars",
    response_model=CalendarResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_calendar_route(
    body: CalendarCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return svc.create_calendar(
            db,
            current_user,
            name=body.name,
            color_hex=body.color_hex,
            scope=body.scope,
            scope_ref=body.scope_ref,
            is_default=body.is_default,
        )
    except svc.CalendarError as e:
        raise _map_error(e)


@router.put("/calendars/{calendar_id}", response_model=CalendarResponse)
def update_calendar_route(
    calendar_id: int,
    body: CalendarUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return svc.update_calendar(
            db,
            current_user,
            calendar_id,
            name=body.name,
            color_hex=body.color_hex,
            is_default=body.is_default,
        )
    except svc.CalendarError as e:
        raise _map_error(e)


@router.delete(
    "/calendars/{calendar_id}", status_code=status.HTTP_204_NO_CONTENT
)
def delete_calendar_route(
    calendar_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        svc.delete_calendar(db, current_user, calendar_id)
        return None
    except svc.CalendarError as e:
        raise _map_error(e)


# ── Events ──────────────────────────────────────────────────


@router.get("/events", response_model=list[EventResponse])
def list_events_route(
    start: datetime = Query(...),
    end: datetime = Query(...),
    calendar_ids: Optional[list[int]] = Query(default=None),
    event_types: Optional[list[str]] = Query(default=None),
    owner_id: Optional[int] = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return svc.list_events(
            db,
            current_user,
            start=start,
            end=end,
            calendar_ids=calendar_ids,
            event_types=event_types,
            owner_id=owner_id,
        )
    except svc.CalendarError as e:
        raise _map_error(e)


@router.get("/events/me", response_model=list[EventResponse])
def list_my_events_route(
    start: datetime = Query(...),
    end: datetime = Query(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return svc.get_my_events(db, current_user, start=start, end=end)
    except svc.CalendarError as e:
        raise _map_error(e)


@router.get("/events/dept", response_model=list[EventResponse])
def list_dept_events_route(
    start: datetime = Query(...),
    end: datetime = Query(...),
    dept_id: Optional[int] = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return svc.get_dept_events(
            db, current_user, start=start, end=end, dept_id=dept_id
        )
    except svc.CalendarError as e:
        raise _map_error(e)


@router.get("/events/{event_id}", response_model=EventResponse)
def get_event_route(
    event_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return svc.get_event(db, current_user, event_id)
    except svc.CalendarError as e:
        raise _map_error(e)


@router.post(
    "/events",
    response_model=EventResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_event_route(
    body: EventCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return svc.create_event(
            db,
            current_user,
            calendar_id=body.calendar_id,
            title=body.title,
            description=body.description,
            event_type=body.event_type,
            start_at=body.start_at,
            end_at=body.end_at,
            all_day=body.all_day,
            location=body.location,
            visibility=body.visibility,
            participant_emp_ids=body.participant_emp_ids,
        )
    except svc.CalendarError as e:
        raise _map_error(e)


@router.put("/events/{event_id}", response_model=EventResponse)
def update_event_route(
    event_id: int,
    body: EventUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return svc.update_event(
            db,
            current_user,
            event_id,
            calendar_id=body.calendar_id,
            title=body.title,
            description=body.description,
            event_type=body.event_type,
            start_at=body.start_at,
            end_at=body.end_at,
            all_day=body.all_day,
            location=body.location,
            visibility=body.visibility,
        )
    except svc.CalendarError as e:
        raise _map_error(e)


@router.delete("/events/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_event_route(
    event_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        svc.delete_event(db, current_user, event_id)
        return None
    except svc.CalendarError as e:
        raise _map_error(e)


# ── Participants ────────────────────────────────────────────


@router.post(
    "/events/{event_id}/participants",
    status_code=status.HTTP_201_CREATED,
)
def add_participants_route(
    event_id: int,
    body: AddParticipantsRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return svc.add_participants(
            db,
            current_user,
            event_id,
            emp_ids=body.emp_ids,
            role=body.role,
        )
    except svc.CalendarError as e:
        raise _map_error(e)


@router.post("/events/{event_id}/participants/respond")
def respond_participant_route(
    event_id: int,
    body: ParticipantResponseRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return svc.respond_participant(
            db, current_user, event_id, response=body.response
        )
    except svc.CalendarError as e:
        raise _map_error(e)
