"""Schemas for EmpPersonal change request workflow."""

from datetime import datetime

from pydantic import BaseModel


class ChangeRequestCreate(BaseModel):
    field_name: str
    new_value: str | None = None
    reason: str | None = None


class ChangeRequestReview(BaseModel):
    comment: str | None = None


class ChangeRequestResponse(BaseModel):
    id: int
    employee_id: int
    emp_name: str | None = None
    emp_no: str | None = None
    field_name: str
    field_label: str | None = None
    old_value: str | None = None
    new_value: str | None = None
    reason: str | None = None
    status: str
    requested_by: int
    requested_at: datetime
    reviewed_by: int | None = None
    reviewed_at: datetime | None = None
    review_comment: str | None = None

    model_config = {"from_attributes": True}
