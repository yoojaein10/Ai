"""Amaranth 호출 오류 계층."""

from typing import Any


class AmaranthError(RuntimeError):
    """모든 Amaranth 연동 오류의 기반 클래스."""


class AmaranthNetworkError(AmaranthError):
    pass


class AmaranthHTTPError(AmaranthError):
    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        super().__init__(message)


class AmaranthApiError(AmaranthError):
    def __init__(
        self,
        code: int | str,
        message: str,
        data: Any = None,
    ) -> None:
        self.code = code
        self.data = data
        super().__init__(message)


class DuplicateVoucherError(AmaranthApiError):
    """자동전표 작성번호 중복 오류(문서 예시 resultCode 21010)."""
