from typing import Any

from pydantic import BaseModel


class ApiResponse(BaseModel):
    success: bool
    code: str
    message: str
    data: Any = None

