from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, model_validator

SalaryAction = Literal[
    "OPEN",
    "UNLOCK_FAIL",
    "SAVE",
    "CREATE_VAULT",
    "LOCK",
    "PASSWORD_CHANGE",
    "DELEGATE",
    "IP_DENIED",
    "POLICY_CHANGE",
]


class AccessLogCreate(BaseModel):
    """클라이언트가 보낼 수 있는 값은 이 셋뿐이다.

    user_id·ip_address·user_agent·occurred_at은 서버가 채운다.
    """

    action: SalaryAction
    record_count: Optional[int] = None
    target_user_id: Optional[int] = None

    @model_validator(mode="after")
    def target_only_for_delegate(self) -> "AccessLogCreate":
        if self.target_user_id is not None and self.action != "DELEGATE":
            raise ValueError("target_user_id는 DELEGATE에만 사용할 수 있습니다")
        return self


class AccessLogRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    action: str
    target_user_id: Optional[int]
    record_count: Optional[int]
    ip_address: Optional[str]
    user_agent: Optional[str]
    occurred_at: datetime


class AccessLogListResponse(BaseModel):
    items: list[AccessLogRow]
    total: int
