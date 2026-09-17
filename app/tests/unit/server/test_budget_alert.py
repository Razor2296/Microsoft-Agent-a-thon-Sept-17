"""
Local estimated-budget remaining alert.

This is estimated spend vs IGNITE_BUDGET_USD, not live provider billing.
Lifetime spend must survive clear_history.
"""
import json
import threading

import pytest

from main.api import (
    PyWebViewApi,
    _budget_alert_chrome,
    _budget_alert_level,
    _budget_config,
)


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("IGNITE_BUDGET_USD", "10")
    monkeypatch.setenv("IGNITE_BUDGET_WARN_REMAINING_PCT", "0.20")
    monkeypatch.setenv("IGNITE_BUDGET_CRITICAL_REMAINING_PCT", "0.05")
    monkeypatch.setenv("IGNITE_BUDGET_TOAST_MS", "7000")
    instance = PyWebViewApi()
    monkeypatch.setattr(instance, "_tenant_log_root", lambda: str(tmp_path))
    sessions = tmp_path / "Sessions"
    sessions.mkdir(exist_ok=True)
    monkeypatch.setattr(
        instance, "_provider_log_dir", lambda provider, kind="Sessions", *parts: str(sessions)
    )
    instance._lifetime_cost_usd = 0.0
    instance._last_budget_alert_level = "ok"
    instance._lifetime_spend_lock = threading.Lock()
    instance._history = {
        "Gemini": [],
        "Grok": [],
        "OpenAI": [],
    }
    instance._token_totals = {"Gemini": 0, "Grok": 0, "OpenAI": 0}
    instance._cost_totals = {"Gemini": 0.0, "Grok": 0.0, "OpenAI": 0.0}
    instance._current_model = {
        "Gemini": "gemini-3.1-flash-lite",
        "Grok": "grok-4.5",
        "OpenAI": "gpt-4o",
    }
    instance._current_provider = "Gemini"
    instance._providers = ["Gemini", "Grok", "OpenAI"]
    instance._model_sessions = {}
    instance._chat_instances = {}
    instance._session_id = "Gemini_gemini-3.1-flash-lite_20260910_000000"
    return instance


def _paid_turn(cost_usd):
    return [
        {
            "role": "user",
            "content": "hi",
            "token_info": {"prompt_tokens": 0, "candidates_tokens": 0, "thinking_tokens": 0, "cost_usd": 0.0},
        },
        {
            "role": "assistant",
            "content": "hello",
            "token_info": {
                "prompt_tokens": 0,
                "candidates_tokens": 20,
                "thinking_tokens": 0,
                "cost_usd": cost_usd,
            },
        },
    ]


class TestBudgetConfig:
    def test_zero_budget_disables(self, monkeypatch):
        monkeypatch.setenv("IGNITE_BUDGET_USD", "0")
        cfg = _budget_config()
        assert cfg["budget_usd"] == 0.0
        assert _budget_alert_level(0.0, 0.0, 0.20, 0.05) == "disabled"

    def test_toast_ms_from_env(self, monkeypatch):
        monkeypatch.setenv("IGNITE_BUDGET_TOAST_MS", "4500")
        cfg = _budget_config()
        assert cfg["toast_ms"] == 4500

    def test_level_thresholds(self):
        assert _budget_alert_level(10.0, 10.0, 0.20, 0.05) == "ok"
        assert _budget_alert_level(2.0, 10.0, 0.20, 0.05) == "warn"
        assert _budget_alert_level(0.4, 10.0, 0.20, 0.05) == "critical"
        assert _budget_alert_level(0.0, 10.0, 0.20, 0.05) == "exhausted"


class TestBudgetChrome:
    def test_six_locales_exhausted(self):
        for lang, needle in (
            ("es", "Se acabó"),
            ("en", "used up"),
            ("fr", "épuisé"),
            ("de", "aufgebraucht"),
            ("it", "esaurito"),
            ("pt", "esgotado"),
        ):
            msg = _budget_alert_chrome("exhausted", 0.0, 10.0, lang)
            assert needle.lower() in msg.lower() or needle in msg

    def test_ok_has_no_chrome(self):
        assert _budget_alert_chrome("ok", 8.0, 10.0, "es") == ""


class TestLifetimeBudget:
    def test_remaining_and_notify_once(self, api):
        api._lifetime_cost_usd = 8.5
        stats = api.get_accumulated_cost_stats("es")
        assert stats["budget_enabled"] is True
        assert stats["remaining_usd"] == pytest.approx(1.5, abs=1e-6)
        assert stats["alert_level"] == "warn"
        assert stats["budget_notify"] is True
        assert "poco saldo" in stats["alert_message"]

        again = api.get_accumulated_cost_stats("es")
        assert again["alert_level"] == "warn"
        assert again["budget_notify"] is False

    def test_disabled_hides_remaining(self, api, monkeypatch):
        monkeypatch.setenv("IGNITE_BUDGET_USD", "0")
        stats = api.get_accumulated_cost_stats("en")
        assert stats["budget_enabled"] is False
        assert stats["remaining_usd"] is None
        assert stats["alert_level"] == "disabled"
        assert stats["budget_notify"] is False

    def test_accrue_then_clear_keeps_lifetime(self, api):
        api._history["Gemini"] = _paid_turn(0.34)
        api._recalculate_token_totals("Gemini", accrue_lifetime=True)
        assert api._cost_totals["Gemini"] == pytest.approx(0.34)
        assert api._lifetime_cost_usd == pytest.approx(0.34)

        api.clear_history("Gemini")
        assert api._cost_totals["Gemini"] == 0.0
        assert api._lifetime_cost_usd == pytest.approx(0.34)
        stats = api.get_accumulated_cost_stats("en")
        assert stats["lifetime_cost_usd"] == pytest.approx(0.34)
        assert stats["remaining_usd"] == pytest.approx(9.66)

    def test_restore_recalc_does_not_accrue(self, api):
        api._history["Gemini"] = _paid_turn(1.25)
        api._recalculate_token_totals("Gemini")
        assert api._cost_totals["Gemini"] == pytest.approx(1.25)
        assert api._lifetime_cost_usd == 0.0

    def test_ledger_persists_to_tenant_dir(self, api, tmp_path):
        api._add_lifetime_spend(2.5)
        path = tmp_path / "lifetime_spend.json"
        assert path.is_file()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["lifetime_cost_usd"] == pytest.approx(2.5)

    def test_exhausted_notify(self, api):
        api._lifetime_cost_usd = 10.0
        stats = api.get_accumulated_cost_stats("en")
        assert stats["alert_level"] == "exhausted"
        assert stats["remaining_usd"] == 0.0
        assert stats["budget_notify"] is True
        assert "used up" in stats["alert_message"].lower()
        assert stats["toast_ms"] == 7000

    def test_notify_escalates_warn_then_critical(self, api):
        api._lifetime_cost_usd = 8.5
        warn = api.get_accumulated_cost_stats("en")
        assert warn["alert_level"] == "warn"
        assert warn["budget_notify"] is True

        api._lifetime_cost_usd = 9.6
        critical = api.get_accumulated_cost_stats("en")
        assert critical["alert_level"] == "critical"
        assert critical["budget_notify"] is True

        again = api.get_accumulated_cost_stats("en")
        assert again["alert_level"] == "critical"
        assert again["budget_notify"] is False

    def test_warn_chrome_six_locales(self):
        for lang in ("es", "en", "fr", "de", "it", "pt"):
            msg = _budget_alert_chrome("warn", 1.5, 10.0, lang)
            assert msg
            assert "1.5000" in msg

    def test_critical_chrome_six_locales(self):
        for lang in ("es", "en", "fr", "de", "it", "pt"):
            msg = _budget_alert_chrome("critical", 0.40, 10.0, lang)
            assert msg
            assert "0.4000" in msg

    def test_invalid_budget_env_uses_example_default(self, monkeypatch):
        monkeypatch.setenv("IGNITE_BUDGET_USD", "not-a-number")
        monkeypatch.setenv("IGNITE_BUDGET_TOAST_MS", "nope")
        cfg = _budget_config()
        assert cfg["budget_usd"] == 10.0
        assert cfg["toast_ms"] == 7000

    def test_warn_pct_from_env_changes_level(self, api, monkeypatch):
        monkeypatch.setenv("IGNITE_BUDGET_USD", "10")
        monkeypatch.setenv("IGNITE_BUDGET_WARN_REMAINING_PCT", "0.50")
        monkeypatch.setenv("IGNITE_BUDGET_CRITICAL_REMAINING_PCT", "0.10")
        api._lifetime_cost_usd = 6.0
        stats = api.get_accumulated_cost_stats("en")
        assert stats["remaining_usd"] == pytest.approx(4.0)
        assert stats["alert_level"] == "warn"

    def test_negative_recalc_does_not_reduce_lifetime(self, api):
        api._lifetime_cost_usd = 1.0
        api._cost_totals["Gemini"] = 0.5
        api._history["Gemini"] = []
        api._recalculate_token_totals("Gemini", accrue_lifetime=True)
        assert api._cost_totals["Gemini"] == 0.0
        assert api._lifetime_cost_usd == pytest.approx(1.0)

    def test_persist_last_alert_level(self, api, tmp_path):
        api._lifetime_cost_usd = 8.5
        api.get_accumulated_cost_stats("en")
        data = json.loads((tmp_path / "lifetime_spend.json").read_text(encoding="utf-8"))
        assert data["last_alert_level"] == "warn"

