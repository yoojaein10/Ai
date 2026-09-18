"""Holiday schemas (PHASE 15)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class HolidayBase(BaseModel):
    date: date
    name: str = Field(min_length=1, max_length=100)
    is_recurring: bool = False


class HolidayCreate(HolidayBase):
    pass


class HolidayResponse(HolidayBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: Optional[datetime] = None
