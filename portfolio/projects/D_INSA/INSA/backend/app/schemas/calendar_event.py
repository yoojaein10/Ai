from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

EventType = Literal["MANUAL", "LEAVE", "TRAVEL", "MEETING", "OTHER"]
SourceType = Literal["APPROVAL_DOC", "MANUAL"]
Visibility = Literal["PUBLIC", "DEPT", "PRIVATE"]
ParticipantRole = Literal["ORGANIZER", "REQUIRED", "OPTIONAL"]
ParticipantResponseValue = Literal["PENDING", "ACCEPTED", "DECLINED", "TENTATIVE"]


class EventBase(BaseModel):
    calendar_id: int
    title: str = Field(..., max_length=200)
    description: Optional[str] = None
    event_type: EventType = "MANUAL"
    start_at: datetime
    end_at: datetime
    all_day: bool = False
    location: Optional[str] = Field(default=None, max_length=200)
    visibility: Visibility = "PUBLIC"


class EventCreate(EventBase):
    participant_emp_ids: Optional[list[int]] = None


class EventUpdate(BaseModel):
    calendar_id: Optional[int] = None
    title: Optional[str] = Field(default=None, max_length=200)
    description: Optional[str] = None
    event_type: Optional[EventType] = None
    start_at: Optional[datetime] = None
    end_at: Optional[datetime] = None
    all_day: Optional[bool] = None
    location: Optional[str] = Field(default=None, max_length=200)
    visibility: Optional[Visibility] = None


class ParticipantResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    event_id: int
    emp_id: int
    emp_name: Optional[str] = None
    role: ParticipantRole
    response: ParticipantResponseValue


class EventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    calendar_id: int
    calendar_name: Optional[str] = None
    calendar_color: Optional[str] = None
    title: str
    description: Optional[str] = None
    event_type: EventType
    source_type: SourceType
    source_ref: Optional[int] = None
    start_at: datetime
    end_at: datetime
    all_day: bool
    owner_id: int
    owner_name: Optional[str] = None
    location: Optional[str] = None
    visibility: Visibility
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    participants: list[ParticipantResponse] = Field(default_factory=list)


class AddParticipantsRequest(BaseModel):
    emp_ids: list[int] = Field(..., min_length=1)
    role: ParticipantRole = "REQUIRED"


class ParticipantResponseRequest(BaseModel):
    response: ParticipantResponseValue
