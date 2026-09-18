from datetime import datetime

from pydantic import BaseModel


class DepartmentBase(BaseModel):
    code: str
    name: str
    parent_id: int | None = None
    head_employee_id: int | None = None


class DepartmentCreate(DepartmentBase):
    pass


class DepartmentUpdate(BaseModel):
    name: str | None = None
    parent_id: int | None = None
    head_employee_id: int | None = None
    is_active: bool | None = None


class DepartmentResponse(DepartmentBase):
    id: int
    is_active: bool
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


class DepartmentTreeNode(DepartmentResponse):
    children: list["DepartmentTreeNode"] = []
