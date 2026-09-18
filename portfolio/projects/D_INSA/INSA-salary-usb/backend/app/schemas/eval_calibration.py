from datetime import datetime

from pydantic import BaseModel


class EvalCalibrationGroupBase(BaseModel):
    year: int
    name: str


class EvalCalibrationGroupCreate(EvalCalibrationGroupBase):
    pass


class EvalCalibrationGroupUpdate(BaseModel):
    name: str | None = None


class EvalCalibrationMemberResponse(BaseModel):
    id: int
    emp_id: int
    emp_no: str | None = None
    emp_name: str | None = None

    model_config = {"from_attributes": True}


class EvalCalibrationGroupResponse(EvalCalibrationGroupBase):
    id: int
    created_by: int
    created_at: datetime | None = None
    member_count: int = 0

    model_config = {"from_attributes": True}


class EvalCalibrationGroupDetail(EvalCalibrationGroupResponse):
    members: list[EvalCalibrationMemberResponse] = []


class EvalCalibrationMemberAdd(BaseModel):
    emp_ids: list[int]
