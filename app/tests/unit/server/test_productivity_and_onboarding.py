"""
app/tests/unit/server/test_productivity_and_onboarding.py
Layer server: PyWebViewApi wizard, capabilities, live key validation, ROI, fallbacks.
"""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest
from main.api import PyWebViewApi


class TestSystemCapabilities:
    """Tests for get_system_capabilities hardware and environment diagnosis."""

    def test_get_system_capabilities_structure(self):
        api = PyWebViewApi()
        caps = api.get_system_capabilities()
        assert caps["status"] == "success"
        assert "cuda_available" in caps
        assert "gpu_name" in caps
        assert "tesseract_available" in caps
        assert "microphone_available" in caps
        assert "configured_providers" in caps
        assert "is_first_run" in caps
        assert "runtime_mode" in caps
        assert "user_name" in caps
        assert isinstance(caps["configured_providers"], dict)

    def test_runtime_mode_defaults_to_local(self, monkeypatch):
        """Desktop default must match launcher_webview.py / .env.example (skill 12.5)."""
        api = PyWebViewApi()  # may load .env and set IGNITE_RUNTIME_MODE
        monkeypatch.delenv("IGNITE_RUNTIME_MODE", raising=False)
        caps = api.get_system_capabilities()
        assert caps["runtime_mode"] == "local"


class TestValidateAndSaveApiKey:
    """Tests for live API key validation and hot-reloading."""

    def test_empty_key_or_unknown_provider(self):
        api = PyWebViewApi()
        res_empty = api.validate_and_save_api_key("Gemini", "")
        assert res_empty["status"] == "error"
        assert "empty" in res_empty["message"].lower()

        res_unknown = api.validate_and_save_api_key("UnknownProvider", "valid_looking_key")
        assert res_unknown["status"] == "error"
        assert "unsupported" in res_unknown["message"].lower()

    def test_mocked_successful_gemini_validation(self, tmp_path, monkeypatch):
        api = PyWebViewApi()
        test_env = tmp_path / ".env"
        test_env.write_text("GEMINI_API_KEY=old_key\n", encoding="utf-8")
        monkeypatch.setattr("main.api.app_dir", str(tmp_path))

        with patch("google.genai.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_token_resp = MagicMock()
            mock_token_resp.total_tokens = 1
            mock_client.models.count_tokens.return_value = mock_token_resp
            mock_client_cls.return_value = mock_client

            res = api.validate_and_save_api_key("Gemini", "AIzaSyTestValidKey123")
            assert res["status"] == "success"
            assert "verified" in res["message"].lower()
            assert os.getenv("GEMINI_API_KEY") == "AIzaSyTestValidKey123"

            # Check that file was updated
            content = test_env.read_text(encoding="utf-8")
            assert "AIzaSyTestValidKey123" in content


class TestProductivityMetrics:
    """Tests for executive ROI & productivity value calculations."""

    def test_productivity_metrics_calculation(self):
        api = PyWebViewApi()
        api._token_totals = {"Gemini": 10000, "DeepSeek": 5000}
        api._cost_totals = {"Gemini": 0.005, "DeepSeek": 0.003}

        metrics = api.get_productivity_metrics()
        assert metrics["status"] == "success"
        assert metrics["total_tokens"] >= 15000
        assert metrics["total_words_generated"] > 0
        assert metrics["typing_hours_saved"] > 0
        assert "doc_hours_saved" in metrics
        assert metrics["total_hours_saved"] >= metrics["typing_hours_saved"]
        assert metrics["equivalent_human_cost_usd"] > 0
        assert metrics["roi_multiplier"] > 0
        assert "provider_breakdown" in metrics
        assert "Gemini" in metrics["provider_breakdown"]


class TestSmartFallback:
    """Tests for proactive error fallback suggestions."""

    def test_get_smart_fallback_recommendations(self):
        api = PyWebViewApi()
        fallback_res = api.get_smart_fallback("DeepSeek")
        assert fallback_res["status"] == "success"
        assert fallback_res["failed_provider"] == "DeepSeek"
        assert "primary_fallback" in fallback_res
        assert fallback_res["primary_fallback"] != "DeepSeek"
        assert len(fallback_res["alternatives"]) > 0
        assert "DeepSeek" not in fallback_res["alternatives"]
