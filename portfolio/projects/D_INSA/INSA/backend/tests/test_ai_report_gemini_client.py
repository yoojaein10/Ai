import json

import httpx
import pytest

from app.services.ai_report.gemini_client import (
    GeminiClient,
    GeminiConfigError,
    GeminiError,
)


def _success_response_json() -> dict:
    return {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "text": json.dumps(
                                {
                                    "strengths": "성실함",
                                    "improvements": "발표 스킬",
                                    "coaching": "주 1회 발표 연습",
                                    "interview_guide": "최근 도전 경험을 묻기",
                                },
                                ensure_ascii=False,
                            )
                        }
                    ]
                }
            }
        ]
    }


def test_generate_returns_parsed_json():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_success_response_json())

    transport = httpx.MockTransport(handler)
    client = GeminiClient(api_key="fake", model="gemini-2.5-flash", timeout=10, transport=transport)
    result = client.generate(system_prompt="sys", user_prompt="user")
    assert result["strengths"] == "성실함"
    assert result["coaching"].startswith("주 1회")


def test_generate_raises_config_error_when_api_key_missing():
    with pytest.raises(GeminiConfigError):
        GeminiClient(api_key="", model="gemini-2.5-flash", timeout=10)


def test_generate_raises_on_4xx():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"message": "bad request"}})

    transport = httpx.MockTransport(handler)
    client = GeminiClient(api_key="fake", model="gemini-2.5-flash", timeout=10, transport=transport)
    with pytest.raises(GeminiError, match="400"):
        client.generate(system_prompt="sys", user_prompt="user")


def test_generate_raises_on_5xx():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": {"message": "service unavailable"}})

    transport = httpx.MockTransport(handler)
    client = GeminiClient(api_key="fake", model="gemini-2.5-flash", timeout=10, transport=transport)
    with pytest.raises(GeminiError, match="503"):
        client.generate(system_prompt="sys", user_prompt="user")


def test_generate_raises_on_invalid_json():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {"content": {"parts": [{"text": "not json"}]}}
                ]
            },
        )

    transport = httpx.MockTransport(handler)
    client = GeminiClient(api_key="fake", model="gemini-2.5-flash", timeout=10, transport=transport)
    with pytest.raises(GeminiError, match="JSON"):
        client.generate(system_prompt="sys", user_prompt="user")
