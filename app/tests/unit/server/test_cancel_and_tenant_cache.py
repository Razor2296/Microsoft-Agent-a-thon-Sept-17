"""Regression tests for cancel_generation, tenant-scoped caches, attachment bytes."""
import threading
import time

import pytest

from backend.processors.base_processor import BaseChat
from main.api import PyWebViewApi


class TestCancelGeneration:
    def test_cancel_marks_active_request(self):
        api = PyWebViewApi()
        with api._request_lock:
            api._requests["rid-1"] = {
                "status": "processing",
                "cancelled": False,
                "provider": "Gemini",
                "replies": [],
            }
            api._active_request_by_provider["Gemini"] = "rid-1"
        res = api.cancel_generation(provider="Gemini")
        assert res["status"] == "success"
        assert "rid-1" in res["cancelled"]
        assert api._requests["rid-1"]["status"] == "cancelled"
        assert api._requests["rid-1"]["cancelled"] is True

    def test_send_async_supersedes_previous(self, monkeypatch):
        api = PyWebViewApi()
        # Stall the sync path so the second send can observe single-flight bookkeeping.
        gate = threading.Event()

        def slow_sync(*a, **k):
            gate.wait(timeout=2.0)
            return {"status": "success", "reply": "ok"}

        monkeypatch.setattr(api, "_send_message_sync", slow_sync)
        monkeypatch.setattr(api, "_run_group_generation_flow", lambda *a, **k: None)

        r1 = api.send_message_async("hi", provider="OpenAI")
        rid1 = r1["request_id"]
        # Give worker a moment to mark processing
        time.sleep(0.05)
        with api._request_lock:
            api._requests[rid1]["status"] = "processing"
            api._active_request_by_provider["OpenAI"] = rid1

        r2 = api.send_message_async("hi again", provider="OpenAI")
        with api._request_lock:
            assert api._requests[rid1]["cancelled"] is True
            assert api._active_request_by_provider.get("OpenAI") == r2["request_id"]
        gate.set()

class TestTenantScopedCaches:
    def test_scoped_keys_differ_by_tenant(self):
        a = BaseChat.__new__(BaseChat)
        b = BaseChat.__new__(BaseChat)
        a._tenant_key = "tenant-A"
        b._tenant_key = "tenant-B"
        key_a = a._transcription_cache_key(b"audio", "audio/wav", "es")
        key_b = b._transcription_cache_key(b"audio", "audio/wav", "es")
        assert key_a != key_b
        assert key_a.startswith("tenant-A::")
        assert key_b.startswith("tenant-B::")


class TestResolveAttachmentBytes:
    def test_prefers_bytes_over_base64(self):
        api = PyWebViewApi()
        data = api._resolve_attachment_bytes({"bytes": b"hello", "base64": "aGVsbG8="})
        assert data == b"hello"

    def test_decodes_base64(self):
        api = PyWebViewApi()
        import base64
        raw = b"payload"
        data = api._resolve_attachment_bytes({"base64": base64.b64encode(raw).decode()})
        assert data == raw
