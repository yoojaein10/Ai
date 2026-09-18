"""Amaranth 공통 응답 스키마."""

from typing import Any

from pydantic import BaseModel


class AmaranthResponse(BaseModel):
    resultCode: int | str
    resultMsg: str | None = None
    resultData: Any = None

