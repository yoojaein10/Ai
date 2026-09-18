from datetime import date, datetime

from pydantic import BaseModel


class CompSarBase(BaseModel):
    target_emp_id: int
    observed_date: date
    situation: str | None = None
    action: str | None = None
    result: str | None = None


class CompSarCreate(CompSarBase):
    pass


class CompSarUpdate(BaseModel):
    observed_date: date | None = None
    situation: str | None = None
    action: str | None = None
    result: str | None = None


class CompSarResponse(CompSarBase):
    id: int
    observer_id: int
    created_at: datetime | None = None

    model_config = {"from_attributes": True}
