"""
Pydantic v2 schemas package.
"""
from typing import Any, Optional
from pydantic import BaseModel


class ApiResponse(BaseModel):
    """Standard API response wrapper."""
    status: str = "success"
    data: Any = None
    message: str = ""
