"""Amaranth 10 외부연동 요청 인증 헤더 생성."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
from collections.abc import Callable

from app.config import Settings, get_settings


class AmaranthAuthenticationError(RuntimeError):
    """인증 설정 또는 인증 응답 오류."""


class AmaranthSigner:
    """사전 발급 accessToken/hashKey로 요청별 HMAC 서명을 생성한다."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        clock: Callable[[], float] = time.time,
        transaction_id_factory: Callable[[], str] | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.clock = clock
        self.transaction_id_factory = transaction_id_factory or _transaction_id

    def build_headers(self, endpoint: str) -> dict[str, str]:
        self._validate_settings()
        normalized_endpoint = _normalize_endpoint(endpoint)
        transaction_id = self.transaction_id_factory()
        if len(transaction_id) != 30:
            raise AmaranthAuthenticationError(
                "transaction-id는 정확히 30자리여야 합니다."
            )
        timestamp = str(int(self.clock()))
        access_token = self.settings.a10_access_token.get_secret_value()
        message = f"{access_token}{transaction_id}{timestamp}{normalized_endpoint}"
        signature = _hmac_sha256_base64(
            self.settings.a10_hash_key.get_secret_value(), message
        )

        return {
            "callerName": self.settings.a10_caller_name,
            "Authorization": f"Bearer {access_token}",
            "transaction-id": transaction_id,
            "timestamp": timestamp,
            "groupSeq": self.settings.a10_group_seq,
            "wehago-sign": signature,
            "Content-Type": "application/json",
        }

    def _validate_settings(self) -> None:
        if not self.settings.is_amaranth_configured:
            raise AmaranthAuthenticationError(
                "Amaranth 인증 설정이 없습니다. A10_BASE_URL, A10_CALLER_NAME, "
                "A10_ACCESS_TOKEN, A10_HASH_KEY, A10_GROUP_SEQ를 확인하세요."
            )


def _normalize_endpoint(endpoint: str) -> str:
    path = endpoint.strip()
    if not path:
        raise AmaranthAuthenticationError("서명할 API 경로가 비어 있습니다.")
    if not path.startswith("/"):
        path = f"/{path}"
    return path


def _transaction_id() -> str:
    return secrets.token_hex(15)


def _hmac_sha256_base64(key: str, message: str) -> str:
    digest = hmac.new(
        key.encode("utf-8"), message.encode("utf-8"), hashlib.sha256
    ).digest()
    return base64.b64encode(digest).decode("ascii")
