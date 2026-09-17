"""
Regression tests for welcome/clear/session invariants (SKILLS_CODING §12).
Prevents mid-thread welcome append, wiped-chat revival, and cross-model session ids.
"""
import json
import os
import threading
import time

import pytest

from main.api import PyWebViewApi


@pytest.fixture
def api(tmp_path, monkeypatch):
    instance = PyWebViewApi()
    sessions = tmp_path / "Sessions"
    sessions.mkdir()
    monkeypatch.setattr(
        instance, "_provider_log_dir", lambda provider, kind="Sessions", *parts: str(sessions)
    )
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
    instance._model_sessions = {}
    instance._chat_instances = {}
    instance._history_save_lock = threading.Lock()
    return instance


class TestSaveWelcomeMessageGuard:
    def test_welcome_appends_on_empty_history(self, api):
        res = api.save_welcome_message("Gemini", "Hello Julian! I'm your Gemini assistant.")
        assert res["status"] == "success"
        assert len(api._history["Gemini"]) == 1
        assert api._history["Gemini"][0]["is_welcome"] is True

    def test_welcome_ignored_when_history_has_real_turns(self, api):
        api._history["Gemini"] = [
            {"role": "user", "content": "hola", "is_welcome": False},
            {"role": "assistant", "content": "respuesta larga en español", "is_welcome": False},
        ]
        res = api.save_welcome_message(
            "Gemini", "Hello Julian Curay! I'm your Gemini assistant. How can I help you today?"
        )
        assert res["status"] == "ignored"
        assert len(api._history["Gemini"]) == 2
        assert all(not m.get("content", "").startswith("Hello Julian") for m in api._history["Gemini"])

    def test_welcome_allowed_when_only_prior_welcome(self, api):
        api._history["Gemini"] = [
            {
                "role": "assistant",
                "content": "Hello!",
                "is_welcome": True,
                "token_info": {"total_tokens": 0},
            }
        ]
        res = api.save_welcome_message("Gemini", "Hola! Soy tu asistente Gemini.")
        assert res["status"] == "success"
        assert len(api._history["Gemini"]) == 2
        assert all(m.get("is_welcome") for m in api._history["Gemini"])


class TestClearHistoryPersistsNewSession:
    def test_clear_writes_empty_session_as_newest(self, api):
        model = api._current_model["Gemini"]
        api._history["Gemini"] = [
            {"role": "user", "content": "old", "is_welcome": False},
            {"role": "assistant", "content": "old reply", "is_welcome": False},
        ]
        api._session_id = f"Gemini_{model}_20260101_000000"
        api._session_created_at = "2026-01-01 12:00:00 PM"
        api._model_sessions[("Gemini", model)] = {
            "history": api._history["Gemini"],
            "token_total": 10,
            "session_id": api._session_id,
            "session_created_at": api._session_created_at,
            "chat_instance": None,
        }

        api._save_conversation_history("Gemini")
        old_path = api._find_latest_session_file("Gemini", model)
        assert old_path and os.path.isfile(old_path)
        with open(old_path, encoding="utf-8") as f:
            old_data = json.load(f)
        assert len(old_data.get("messages") or []) >= 2

        api.clear_history("Gemini")
        assert api._history["Gemini"] == []

        # Prefer the active session_id file (authoritative after clear).
        log_dir = api._provider_log_dir("Gemini", "Sessions")
        active_path = os.path.join(log_dir, f"{api._session_id}.json")
        assert os.path.isfile(active_path), f"missing cleared session file {active_path}"
        with open(active_path, encoding="utf-8") as f:
            data = json.load(f)
        assert data.get("messages") == []
        assert str(data.get("session_id", "")).startswith(f"Gemini_{model}_")
        assert data["session_id"] != old_data["session_id"]

        latest = api._find_latest_session_file("Gemini", model)
        assert latest and os.path.isfile(latest)
        with open(latest, encoding="utf-8") as f:
            latest_data = json.load(f)
        assert latest_data.get("messages") == []
        assert latest_data.get("session_id") == data["session_id"]

    def test_clear_resets_provider_usd_cost_only(self, api):
        api._history["Gemini"] = [
            {
                "role": "user",
                "content": "old",
                "token_info": {"prompt_tokens": 10, "candidates_tokens": 0, "thinking_tokens": 0, "cost_usd": 0.12},
            },
            {
                "role": "assistant",
                "content": "old reply",
                "token_info": {"prompt_tokens": 0, "candidates_tokens": 20, "thinking_tokens": 0, "cost_usd": 0.34},
            },
        ]
        api._recalculate_token_totals("Gemini")
        api._cost_totals["OpenAI"] = 0.5
        assert api._cost_totals["Gemini"] > 0

        api.clear_history("Gemini")
        assert api._history["Gemini"] == []
        assert api._token_totals["Gemini"] == 0
        assert api._cost_totals["Gemini"] == 0.0
        assert api._cost_totals["OpenAI"] == 0.5
        stats = api.get_accumulated_cost_stats()
        gemini_row = next(row for row in stats["providers"] if row["provider"] == "Gemini")
        assert gemini_row["cost_usd"] == 0.0
        assert gemini_row["tokens"] == 0


class TestFindLatestSessionTieBreak:
    def test_same_mtime_prefers_newer_session_id_name(self, api, tmp_path, monkeypatch):
        """Regression: equal mtimes must not revive an older cleared chat."""
        sessions = tmp_path / "Sessions"
        sessions.mkdir(exist_ok=True)
        monkeypatch.setattr(
            api, "_provider_log_dir", lambda provider, kind="Sessions", *parts: str(sessions)
        )
        model = "gemini-3.1-flash-lite"
        older = sessions / f"Gemini_{model}_20260101_000000.json"
        newer = sessions / f"Gemini_{model}_20260904_234404.json"
        older.write_text(
            json.dumps({"session_id": older.stem, "messages": [{"role": "user", "content": "old"}]}),
            encoding="utf-8",
        )
        newer.write_text(
            json.dumps({"session_id": newer.stem, "messages": []}),
            encoding="utf-8",
        )
        # Collapse mtimes to the same second (the failure mode on Windows/temp).
        shared = time.time()
        os.utime(older, (shared, shared))
        os.utime(newer, (shared, shared))

        found = api._find_latest_session_file("Gemini", model)
        assert found == str(newer)
        with open(found, encoding="utf-8") as f:
            assert json.load(f).get("messages") == []


class TestSessionIdModelScope:
    def test_resolve_rejects_other_model_id(self, api):
        api._session_id = "OpenAI_gpt-4o_20260101_120000"
        api._model_sessions[("OpenAI", "o1")] = {
            "session_id": "OpenAI_gpt-4o_20260101_120000",
            "history": [],
            "token_total": 0,
            "session_created_at": "now",
            "chat_instance": None,
        }
        resolved = api._resolve_provider_session_id("OpenAI", "o1")
        assert resolved.startswith("OpenAI_o1_")
        assert "gpt-4o" not in resolved

    def test_is_valid_requires_model_segment(self, api):
        assert api._is_valid_session_id("Grok", "Grok_grok-4.5_20260101_1", "grok-4.5")
        assert not api._is_valid_session_id("Grok", "Grok_grok-4.5_20260101_1", "other-model")
        assert not api._is_valid_session_id("Gemini", "Grok_grok-4.5_20260101_1", "gemini-3.1-flash-lite")


class TestScrapedBodyCharCount:
    def test_guards_excluded_from_threshold(self):
        from backend.processors.base_processor import BaseChat

        padded = (
            "\n\n=====\n[INSTRUCCIÓN CRÍTICA DE IDIOMA]\n=====\n\n"
            "short body\n"
            "\n=====\n[RECORDATORIO FINAL DE IDIOMA]\n=====\n"
        )
        body_len = BaseChat.scraped_body_char_count(padded)
        assert body_len == len("short body")
        assert body_len < 800
