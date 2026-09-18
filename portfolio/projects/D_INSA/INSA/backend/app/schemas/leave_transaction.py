from datetime import datetime
from decimal import Decimal
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict

LeaveTransactionType = Literal[
    "INITIAL_GRANT",
    "MONTHLY_GRANT",
    "ADDITIONAL",
    "USE",
    "CANCEL",
    "EXPIRE",
    "CARRY_OVER",
    "ADJUST",
]


class LeaveTransactionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    emp_id: int
    year: int
    transaction_type: LeaveTransactionType
    amount: Decimal
    reason: Optional[str] = None
    ref_doc_id: Optional[int] = None
    balance_after: Decimal
    created_by: Optional[int] = None
    created_at: Optional[datetime] = None
