"""Gemini API 어댑터 — 표준 generativelanguage REST.

JSON 모드 응답 강제, 4xx/5xx/timeout/JSON 파싱 실패 → GeminiError로 통일.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import httpx


class GeminiError(Exception):
    """Gemini 호출 실패 (4xx, 5xx, timeout, JSON 파싱 실패 등)."""


class GeminiConfigError(Exception):
    """API 키 미설정 등 환경 오류."""


_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"


@dataclass
class GeminiClient:
    api_key: str
    model: str = "gemini-2.5-flash"
    timeout: int = 30
    transport: httpx.BaseTransport | None = None

    def __post_init__(self) -> None:
        if not self.api_key:
            raise GeminiConfigError("GEMINI_API_KEY is not configured")

    def generate(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        url = f"{_BASE_URL}/{self.model}:generateContent"
        params = {"key": self.api_key}
        payload = {
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
            "generationConfig": {"response_mime_type": "application/json"},
        }
        try:
            with httpx.Client(timeout=self.timeout, transport=self.transport) as client:
                resp = client.post(url, params=params, json=payload)
        except httpx.TimeoutException as e:
            raise GeminiError(f"timeout: {e}") from e
        except httpx.HTTPError as e:
            raise GeminiError(f"http error: {e}") from e

        if resp.status_code >= 400:
            raise GeminiError(f"{resp.status_code}: {resp.text[:300]}")

        try:
            data = resp.json()
            text = data["candidates"][0]["content"]["parts"][0]["text"]
            return json.loads(text)
        except (KeyError, IndexError, ValueError, json.JSONDecodeError) as e:
            raise GeminiError(f"JSON parse failed: {e}") from e
