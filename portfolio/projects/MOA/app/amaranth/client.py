"""인증, 재시도, 오류 변환, 감사 로그를 담당하는 공통 HTTP 클라이언트."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any

import requests
from sqlalchemy.orm import Session

from app.amaranth.auth import AmaranthAuthenticationError, AmaranthSigner
from app.amaranth.exceptions import (
    AmaranthApiError,
    AmaranthHTTPError,
    AmaranthNetworkError,
    DuplicateVoucherError,
)
from app.config import Settings, get_settings
from app.models.api_log import ApiLog

RETRYABLE_STATUS_CODES = frozenset({500, 502, 503, 504})


class AmaranthClient:
    """모든 Amaranth 외부 호출이 통과해야 하는 단일 진입점."""

    def __init__(
        self,
        db: Session,
        settings: Settings | None = None,
        http: requests.Session | None = None,
        *,
        signer: AmaranthSigner | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.db = db
        self.settings = settings or get_settings()
        self.http = http or requests.Session()
        self.signer = signer or AmaranthSigner(self.settings)
        self.sleep = sleep

    def get(
        self,
        endpoint: str,
        *,
        params: dict[str, Any] | None = None,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        return self.request("GET", endpoint, params=params, timeout=timeout)

    def post(
        self,
        endpoint: str,
        *,
        json_body: dict[str, Any] | list[Any] | None = None,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        return self.request("POST", endpoint, json_body=json_body, timeout=timeout)

    def request(
        self,
        method: str,
        endpoint: str,
        *,
        json_body: dict[str, Any] | list[Any] | None = None,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: float = 30.0,
        retry_count: int = 2,
    ) -> dict[str, Any]:
        """요청을 실행하고 Amaranth 공통 응답을 dict로 반환한다.

        최초 1회에 더해 네트워크 오류/5xx에 최대 ``retry_count``회 재시도한다.
        각 실제 HTTP 시도는 성공/실패 여부와 무관하게 DB에 기록한다.
        """

        if retry_count < 0:
            raise ValueError("retry_count는 0 이상이어야 합니다.")
        if not self.settings.a10_base_url:
            raise AmaranthAuthenticationError("A10_BASE_URL이 설정되지 않았습니다.")

        endpoint = _normalize_endpoint(endpoint)
        url = f"{self.settings.a10_base_url.rstrip('/')}{endpoint}"
        attempts = retry_count + 1

        for attempt in range(attempts):
            response: requests.Response | None = None
            error: Exception | None = None
            started = time.perf_counter()
            try:
                auth_headers = self.signer.build_headers(endpoint)
                request_headers = {**auth_headers, **(headers or {})}
                response = self.http.request(
                    method=method.upper(),
                    url=url,
                    json=json_body,
                    params=params,
                    headers=request_headers,
                    timeout=timeout,
                )

                if response.status_code in RETRYABLE_STATUS_CODES:
                    error = AmaranthHTTPError(
                        response.status_code,
                        f"Amaranth 서버 오류(HTTP {response.status_code})",
                    )
                    if attempt < retry_count:
                        self.sleep(2**attempt)
                        continue
                    raise error

                if response.status_code in (401, 403):
                    raise AmaranthAuthenticationError(
                        f"Amaranth 인증이 거부되었습니다(HTTP {response.status_code})."
                    )
                if response.status_code >= 400:
                    raise AmaranthHTTPError(
                        response.status_code,
                        f"Amaranth HTTP 오류({response.status_code})",
                    )

                payload = _parse_json_response(response)
                _raise_for_api_error(payload)
                return payload
            except requests.RequestException as exc:
                error = AmaranthNetworkError(f"Amaranth 네트워크 오류: {exc}")
                if attempt < retry_count:
                    self.sleep(2**attempt)
                    continue
                raise error from exc
            except Exception as exc:
                error = exc
                raise
            finally:
                elapsed_ms = round((time.perf_counter() - started) * 1000)
                self._write_log(
                    endpoint=endpoint,
                    request_body=json_body,
                    response=response,
                    elapsed_ms=elapsed_ms,
                    error=error,
                )

        raise AssertionError("도달할 수 없는 요청 상태입니다.")

    def _write_log(
        self,
        endpoint: str,
        request_body: Any,
        response: requests.Response | None,
        elapsed_ms: int,
        error: Exception | None,
    ) -> None:
        log = ApiLog(
            direction="OUTBOUND",
            endpoint=endpoint,
            http_status=response.status_code if response is not None else None,
            req_body=_to_json(request_body),
            res_body=_response_text(response),
            elapsed_ms=elapsed_ms,
            error_msg=str(error) if error else None,
        )
        try:
            self.db.add(log)
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise


def _normalize_endpoint(endpoint: str) -> str:
    endpoint = endpoint.strip()
    if not endpoint:
        raise ValueError("endpoint가 비어 있습니다.")
    return endpoint if endpoint.startswith("/") else f"/{endpoint}"


def _parse_json_response(response: requests.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise AmaranthApiError("INVALID_JSON", "응답이 올바른 JSON이 아닙니다.") from exc
    if not isinstance(payload, dict):
        raise AmaranthApiError("INVALID_RESPONSE", "응답 최상위 값이 객체가 아닙니다.")
    return payload


def _raise_for_api_error(payload: dict[str, Any]) -> None:
    code = payload.get("resultCode")
    if code in (0, "0"):
        return

    message = str(payload.get("resultMsg") or "Amaranth API 처리 실패")
    data = payload.get("resultData")
    serialized_data = _to_json(data) or ""
    if str(code) == "21010" and "동일한 작성번호" in serialized_data:
        raise DuplicateVoucherError(code, message, data)
    raise AmaranthApiError(code if code is not None else "UNKNOWN", message, data)


def _to_json(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, default=str)


def _response_text(response: requests.Response | None) -> str | None:
    return response.text if response is not None else None
