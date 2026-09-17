"""Unit tests for Pydantic V2 DTOs."""

from backend.core.schemas import APIRequestPayload, APIResponsePayload, TokenInfo


def test_token_info_computes_total_from_parts():
    info = TokenInfo(prompt_tokens=10, completion_tokens=5, thinking_tokens=2)
    assert info.total_tokens == 17


def test_token_info_legacy_roundtrip():
    legacy = {
        "prompt_tokens": 3,
        "candidates_tokens": 7,
        "thinking_tokens": 1,
        "total_tokens": 11,
        "cost_usd": 0.01,
    }
    info = TokenInfo.from_dict(legacy)
    back = info.to_legacy_dict()
    assert back["prompt_tokens"] == 3
    assert back["candidates_tokens"] == 7
    assert back["total_tokens"] == 11


def test_api_request_payload_defaults():
    payload = APIRequestPayload(provider="Gemini", model="gemini-2.5-flash")
    assert payload.text == ""
    assert payload.from_mic is False
    assert payload.files == []


def test_api_response_payload_status_literal():
    ok = APIResponsePayload(status="success", message="ok")
    assert ok.status == "success"
