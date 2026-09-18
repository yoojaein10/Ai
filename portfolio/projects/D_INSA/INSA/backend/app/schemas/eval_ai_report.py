from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class GenerateRequest(BaseModel):
    round_id: int


class GenerateBatchResponse(BaseModel):
    round_id: int
    total: int
    success: int
    failed: int


class AiReportListItem(BaseModel):
    employee_id: int
    employee_name: str | None
    total_score: Decimal | None
    final_grade: str | None
    report_id: int | None
    version: int | None
    status: str | None  # None = 미생성
    generated_at: datetime | None
    error_message: str | None


class AiReportDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    round_id: int
    employee_id: int
    version: int
    is_latest: bool
    status: str
    error_message: str | None
    total_score: Decimal | None
    final_grade: str | None
    multi_response_count: int | None
    multi_included: bool
    content_strengths: str | None
    content_improvements: str | None
    content_coaching: str | None
    content_interview_guide: str | None
    model_version: str
    prompt_version: str
    generated_by: int
    generated_at: datetime


class AiReportHistoryItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    version: int
    is_latest: bool
    status: str
    generated_by: int
    generated_at: datetime
    model_version: str
    prompt_version: str
