"""Unit tests for ACA API-key auth gate."""

import pytest
from fastapi import HTTPException

from server.auth import get_expected_api_key, require_api_key


def test_get_expected_api_key_prefers_ignite_api_key(monkeypatch):
    monkeypatch.setenv("IGNITE_API_KEY", "secret-a")
    monkeypatch.setenv("API_KEY", "secret-b")
    assert get_expected_api_key() == "secret-a"


def test_require_api_key_allows_when_unset(monkeypatch):
    monkeypatch.delenv("IGNITE_API_KEY", raising=False)
    monkeypatch.delenv("API_KEY", raising=False)
    assert require_api_key(x_api_key=None) is None


def test_require_api_key_rejects_mismatch(monkeypatch):
    monkeypatch.setenv("IGNITE_API_KEY", "expected")
    with pytest.raises(HTTPException) as exc:
        require_api_key(x_api_key="wrong")
    assert exc.value.status_code == 401


def test_require_api_key_accepts_match(monkeypatch):
    monkeypatch.setenv("IGNITE_API_KEY", "expected")
    assert require_api_key(x_api_key="expected") is None
