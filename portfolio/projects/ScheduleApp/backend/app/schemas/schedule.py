"""
Schedule (Event) schemas.
"""
from typing import List, Optional
from pydantic import BaseModel, Field


class EventCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    location: Optional[str] = Field(None, max_length=200)
    event_color: Optional[str] = Field("#339AF0", max_length=7)
    event_icon: Optional[str] = Field(None, max_length=10)
    start_dt: str
    end_dt: str
    is_all_day: bool = False
    visibility: str = Field("company", pattern="^(company|dept|personal)$")
    dept_code: Optional[str] = None
    repeat_rule: Optional[str] = Field(None, max_length=200)
    repeat_end_dt: Optional[str] = None
    attendee_ids: Optional[List[int]] = None
    is_daou_noti_enabled: bool = False


class EventUpdate(BaseModel):
    title: Optional[str] = Field(None, max_length=200)
    description: Optional[str] = None
    location: Optional[str] = Field(None, max_length=200)
    event_color: Optional[str] = Field(None, max_length=7)
    event_icon: Optional[str] = Field(None, max_length=10)
    start_dt: Optional[str] = None
    end_dt: Optional[str] = None
    is_all_day: Optional[bool] = None
    visibility: Optional[str] = Field(None, pattern="^(company|dept|personal)$")
    dept_code: Optional[str] = None
    repeat_rule: Optional[str] = Field(None, max_length=200)
    repeat_end_dt: Optional[str] = None
    attendee_ids: Optional[List[int]] = None
    is_daou_noti_enabled: Optional[bool] = None
    version: int  # required for optimistic locking


