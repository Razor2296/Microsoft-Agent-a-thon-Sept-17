"""
app/tests/unit/test_stability_fixes.py
Regression tests for the inactivity / group-performance stability fixes:
- Remote proxy cold-start warmup + transient retries
- _requests TTL pruning (memory leak guard)
- Session file fallback when the default model changes
- Rotating activity log handlers
"""
import logging
import time
from logging.handlers import RotatingFileHandler
from unittest.mock import MagicMock, patch

import pytest
import requests as requests_lib
from backend.core.libraries import get_assistant_logger
from main.api import PyWebViewApi
from main.remote_api_proxy import RemotePyWebViewApi


class TestRemoteProxyColdStart:
    @pytest.fixture
    def proxy(self, monkeypatch, tmp_path):
        monkeypatch.setenv("IGNITE_SESSION_FILE", str(tmp_path / "sid.txt"))
        monkeypatch.setenv("IGNITE_WARMUP_TIMEOUT", "1")
        monkeypatch.setenv("IGNITE_API_RETRIES", "2")
        return RemotePyWebViewApi(base_url="http://example.test", api_key="k")

    def test_invoke_retries_transient_503_then_succeeds(self, proxy):
        cold = MagicMock(status_code=503, headers={}, text="cold")
        warm = MagicMock(status_code=200, headers={})
        warm.json.return_value = {"status": "success", "result": {"ok": True}}
        health = MagicMock(status_code=200, headers={})
        with patch("main.remote_api_proxy.requests.post", side_effect=[cold, warm]) as post, \
                patch("main.remote_api_proxy.requests.get", return_value=health), \
                patch("main.remote_api_proxy.time.sleep"):
            result = proxy._invoke("get_initial_state")
        assert result == {"ok": True}
        assert post.call_count == 2

    def test_invoke_warms_up_before_first_call(self, proxy):
        ok = MagicMock(status_code=200, headers={})
        ok.json.return_value = {"status": "success", "result": 1}
        health = MagicMock(status_code=200, headers={})
        with patch("main.remote_api_proxy.requests.get", return_value=health) as get, \
                patch("main.remote_api_proxy.requests.post", return_value=ok):
            proxy._invoke("get_history")
        assert get.call_count >= 1
        assert proxy._warm is True

    def test_invoke_returns_error_after_exhausted_retries(self, proxy):
        health = MagicMock(status_code=200, headers={})
        with patch(
            "main.remote_api_proxy.requests.post",
            side_effect=requests_lib.ConnectionError("refused"),
        ), patch("main.remote_api_proxy.requests.get", return_value=health), \
                patch("main.remote_api_proxy.time.sleep"):
            result = proxy._invoke("get_history")
        assert result["status"] == "error"
        assert "Remote API unavailable" in result["message"]


class TestRequestPruning:
    @pytest.fixture
    def api_instance(self):
        return PyWebViewApi()

    def test_finished_requests_are_pruned_after_ttl(self, api_instance, monkeypatch):
        monkeypatch.setenv("IGNITE_REQUEST_TTL_SECONDS", "60")
        old = time.time() - 3600
        with api_instance._request_lock:
            api_instance._requests["old_done"] = {
                "status": "done",
                "finished_at": old,
                "replies": [],
            }
            api_instance._requests["fresh_done"] = {
                "status": "done",
                "finished_at": time.time(),
                "replies": [],
            }
            api_instance._requests["in_flight"] = {
                "status": "processing",
                "replies": [],
            }
            api_instance._prune_requests_locked()
        assert "old_done" not in api_instance._requests
        assert "fresh_done" in api_instance._requests
        assert "in_flight" in api_instance._requests

    def test_prune_lazily_stamps_finished_entries(self, api_instance):
        with api_instance._request_lock:
            api_instance._requests["done_no_stamp"] = {"status": "done", "replies": []}
            api_instance._prune_requests_locked()
            assert api_instance._requests["done_no_stamp"]["finished_at"] is not None

    def test_get_generation_status_prunes(self, api_instance, monkeypatch):
        monkeypatch.setenv("IGNITE_REQUEST_TTL_SECONDS", "1")
        with api_instance._request_lock:
            api_instance._requests["stale"] = {
                "status": "error",
                "error": "x",
                "finished_at": time.time() - 999,
                "replies": [],
            }
        status = api_instance.get_generation_status("stale")
        assert status["status"] == "unknown"


class TestSessionFileFallback:
    @pytest.fixture
    def api_instance(self):
        return PyWebViewApi()

    def test_exact_model_prefix_wins(self, api_instance, tmp_path, monkeypatch):
        sessions = tmp_path / "Sessions"
        sessions.mkdir()
        exact = sessions / "Gemini_gemini-2.5-flash_20260101_010101.json"
        other = sessions / "Gemini_gemini-1.5-pro_20260102_010101.json"
        exact.write_text("{}", encoding="utf-8")
        other.write_text("{}", encoding="utf-8")
        monkeypatch.setattr(
            api_instance, "_provider_log_dir", lambda provider, kind: str(sessions)
        )
        found = api_instance._find_latest_session_file("Gemini", "gemini-2.5-flash")
        assert found == str(exact)

    def test_falls_back_to_provider_sessions_when_model_changed(
        self, api_instance, tmp_path, monkeypatch
    ):
        sessions = tmp_path / "Sessions"
        sessions.mkdir()
        old_model = sessions / "Gemini_gemini-1.5-pro_20260102_010101.json"
        old_model.write_text("{}", encoding="utf-8")
        monkeypatch.setattr(
            api_instance, "_provider_log_dir", lambda provider, kind: str(sessions)
        )
        found = api_instance._find_latest_session_file("Gemini", "gemini-9.9-new")
        assert found == str(old_model)

    def test_returns_none_when_no_sessions(self, api_instance, tmp_path, monkeypatch):
        sessions = tmp_path / "Sessions"
        sessions.mkdir()
        monkeypatch.setattr(
            api_instance, "_provider_log_dir", lambda provider, kind: str(sessions)
        )
        assert api_instance._find_latest_session_file("Gemini", "any") is None


class TestRotatingActivityLogs:
    def test_assistant_logger_uses_rotating_file_handler(self):
        log = get_assistant_logger("rotation_probe")
        file_handlers = [
            h for h in log.handlers if isinstance(h, logging.FileHandler)
        ]
        assert file_handlers, "expected a file handler"
        assert all(isinstance(h, RotatingFileHandler) for h in file_handlers)
        assert all(h.maxBytes > 0 for h in file_handlers)
