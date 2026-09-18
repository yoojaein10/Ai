from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

DocStatus = Literal[
    "DRAFT", "PENDING", "IN_PROGRESS", "APPROVED", "REJECTED", "RECALLED"
]
HistoryAction = Literal[
    "PENDING", "APPROVED", "REJECTED", "DELEGATED", "COMMENTED", "RECALLED"
]


class DocBase(BaseModel):
    doc_type_id: int
    title: str = Field(..., max_length=200)
    content: Optional[dict[str, Any]] = None


class DocCreate(DocBase):
    line_template_id: int


class DocUpdate(BaseModel):
    title: Optional[str] = Field(default=None, max_length=200)
    content: Optional[dict[str, Any]] = None


class DocActionRequest(BaseModel):
    comment: Optional[str] = Field(default=None, max_length=1000)


class DocHistoryItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    step_order: int
    approver_id: int
    approver_name: Optional[str] = None
    action: HistoryAction
    comment: Optional[str] = None
    acted_at: datetime


class DocLineStep(BaseModel):
    step_order: int
    approver_type: str
    approver_ref: Optional[str] = None
    resolved_user_id: Optional[int] = None
    resolved_name: Optional[str] = None
    is_required: bool = True


class DocResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    doc_type_id: int
    doc_type_code: Optional[str] = None
    doc_type_name: Optional[str] = None
    doc_no: Optional[str] = None
    title: str
    drafter_id: int
    drafter_name: Optional[str] = None
    status: DocStatus
    current_step: int
    total_steps: int
    drafted_at: datetime
    completed_at: Optional[datetime] = None


class DocDetailResponse(DocResponse):
    content: Optional[dict[str, Any]] = None
    line_steps: list[DocLineStep] = Field(default_factory=list)
    history: list[DocHistoryItem] = Field(default_factory=list)


class AttachmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    doc_id: int
    filename: str
    filesize: int
    uploaded_at: datetime
