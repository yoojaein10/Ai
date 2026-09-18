from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, field_validator


class PolicyUpsert(BaseModel):
    owner_user_id: int
    allowed_ip: str

    @field_validator("allowed_ip")
    @classmethod
    def valid_ip(cls, v: str) -> str:
        import ipaddress

        try:
            ipaddress.ip_address(v)
        except ValueError as exc:
            raise ValueError("올바른 IP 주소가 아닙니다") from exc
        return v


class PolicyRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    owner_user_id: int
    allowed_ip: str
    is_active: bool
    updated_by: int
    updated_at: datetime


class PolicyCheckResponse(BaseModel):
    allowed: bool
    current_ip: Optional[str]
    login_id: Optional[str] = None
    # 이 사용자에게 수동 허용 정책이 있는지
    configured: bool
    # 좌석(SEAT_USERINFO) 규칙으로 계산한 기대 IP. 매핑이 없으면 None
    seat_expected_ip: Optional[str] = None
    # 통과 경로: "seat" | "manual" | None(거부)
    via: Optional[str] = None
    reason: Optional[str] = None
