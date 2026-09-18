from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class LeaveAccrualRuleBase(BaseModel):
    year: int = Field(..., ge=2000, le=2100)
    under_1year_monthly: int = Field(default=1, ge=0, le=31)
    under_1year_max: int = Field(default=11, ge=0, le=31)
    base_days: int = Field(default=15, ge=0, le=365)
    tenure_bonus_start_years: int = Field(default=3, ge=0, le=50)
    tenure_bonus_interval: int = Field(default=2, ge=1, le=50)
    max_days: int = Field(default=25, ge=0, le=365)
    carry_over_enabled: bool = False


class LeaveAccrualRuleCreate(LeaveAccrualRuleBase):
    pass


class LeaveAccrualRuleUpdate(BaseModel):
    under_1year_monthly: Optional[int] = Field(default=None, ge=0, le=31)
    under_1year_max: Optional[int] = Field(default=None, ge=0, le=31)
    base_days: Optional[int] = Field(default=None, ge=0, le=365)
    tenure_bonus_start_years: Optional[int] = Field(default=None, ge=0, le=50)
    tenure_bonus_interval: Optional[int] = Field(default=None, ge=1, le=50)
    max_days: Optional[int] = Field(default=None, ge=0, le=365)
    carry_over_enabled: Optional[bool] = None


class LeaveAccrualRuleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    year: int
    under_1year_monthly: int
    under_1year_max: int
    base_days: int
    tenure_bonus_start_years: int
    tenure_bonus_interval: int
    max_days: int
    carry_over_enabled: bool
    updated_by: Optional[int] = None
    updated_at: Optional[datetime] = None
