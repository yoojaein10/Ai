from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


# ── User ──────────────────────────────────────────────────


class AdminUserRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    login_id: str
    employee_id: Optional[int] = None
    emp_no: Optional[str] = None
    name_ko: Optional[str] = None
    dept_name: Optional[str] = None
    is_active: bool
    role_codes: list[str] = []
    role_names: list[str] = []
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class AdminUserListResponse(BaseModel):
    total: int
    items: list[AdminUserRow]


class AdminUserCreate(BaseModel):
    login_id: str
    password: str
    employee_id: Optional[int] = None
    is_active: bool = True
    role_ids: list[int] = []


class AdminUserUpdate(BaseModel):
    employee_id: Optional[int] = None
    is_active: Optional[bool] = None
    role_ids: Optional[list[int]] = None


class AdminPasswordReset(BaseModel):
    new_password: str


# ── Role ──────────────────────────────────────────────────


class AdminRoleRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    description: Optional[str] = None
    user_count: int = 0
    menu_ids: list[int] = []


class AdminRoleListResponse(BaseModel):
    total: int
    items: list[AdminRoleRow]


class AdminRoleCreate(BaseModel):
    code: str
    name: str
    description: Optional[str] = None
    menu_ids: list[int] = []


class AdminRoleUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    menu_ids: Optional[list[int]] = None


class AdminMenuRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    parent_id: Optional[int] = None
    path: Optional[str] = None
    sort_order: int = 0
    is_active: bool = True


class AdminMenuListResponse(BaseModel):
    total: int
    items: list[AdminMenuRow]


# ── Code ──────────────────────────────────────────────────


class AdminCodeBase(BaseModel):
    group_code: str
    group_name: Optional[str] = None
    code: str
    name: str
    description: Optional[str] = None
    sort_order: int = 0
    is_active: bool = True


class AdminCodeCreate(AdminCodeBase):
    pass


class AdminCodeUpdate(BaseModel):
    group_name: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None


class AdminCodeOut(AdminCodeBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class AdminCodeListResponse(BaseModel):
    total: int
    items: list[AdminCodeOut]


class AdminCodeGroup(BaseModel):
    group_code: str
    group_name: Optional[str] = None
    count: int


class AdminCodeGroupsResponse(BaseModel):
    groups: list[AdminCodeGroup]


# ── Setting ───────────────────────────────────────────────


class AdminSettingBase(BaseModel):
    key: str
    value: Optional[str] = None
    category: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    value_type: str = "string"
    is_editable: bool = True


class AdminSettingCreate(AdminSettingBase):
    pass


class AdminSettingUpdate(BaseModel):
    value: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None


class AdminSettingOut(AdminSettingBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    updated_at: Optional[datetime] = None


class AdminSettingListResponse(BaseModel):
    total: int
    items: list[AdminSettingOut]
