"""Local RAG must recall archived chats after clear (Memory Bank across sessions)."""
from __future__ import annotations

import inspect
import json

from backend.tools.rag_engine import LocalRAGEngine
from main.api import PyWebViewApi


def test_send_path_indexes_turns_and_source_wires_helpers():
    send_src = inspect.getsource(PyWebViewApi._send_message_sync)
    group_src = inspect.getsource(PyWebViewApi._run_group_generation_flow)
    assert "_index_conversation_turn_for_rag" in send_src
    assert "_text_for_model_with_rag" in send_src
    assert "_text_for_model_with_rag" in group_src
    assert "_index_conversation_turn_for_rag" in group_src


def test_backfill_old_session_is_recalled_after_clear(tmp_path, monkeypatch):
    sessions = tmp_path / "Sessions"
    sessions.mkdir()
    old_id = "Gemini_gemini-3.1-flash-lite_20260101_000000"
    (sessions / f"{old_id}.json").write_text(
        json.dumps(
            {
                "session_id": old_id,
                "messages": [
                    {"role": "assistant", "content": "Hola", "is_welcome": True},
                    {"role": "user", "content": "The vault code is Harbor-42."},
                    {
                        "role": "assistant",
                        "content": "Understood. I will remember Harbor-42 as the vault code.",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    api = PyWebViewApi()
    monkeypatch.setattr(
        api, "_provider_log_dir", lambda provider, kind="Sessions", *parts: str(sessions)
    )
    api.rag_engine = LocalRAGEngine(db_path=str(tmp_path / "rag_memory.db"))
    api._rag_sessions_backfilled = False
    api._history = {"Gemini": [], "OpenAI": []}
    api._session_id = "Gemini_gemini-3.1-flash-lite_20260908_120000"

    api._ensure_rag_session_backfill()
    snippet = api.rag_engine.get_rag_system_prompt_snippet("vault code Harbor", top_k=2)
    assert "Harbor-42" in snippet

    api._history["Gemini"] = [{"role": "user", "content": "new chat"}]
    api.clear_history("Gemini")
    assert api._history["Gemini"] == []

    still = api.rag_engine.get_rag_system_prompt_snippet("vault code", top_k=2)
    assert "Harbor-42" in still
    prefixed = api._text_for_model_with_rag("what was the vault code?")
    assert "Harbor-42" in prefixed
    assert "[USER QUERY]" in prefixed


def test_live_turn_indexed_and_skipped_errors(tmp_path):
    api = PyWebViewApi()
    api.rag_engine = LocalRAGEngine(db_path=str(tmp_path / "rag_live.db"))
    api._rag_sessions_backfilled = True
    api._session_id = "Gemini_live_1"
    api._history = {
        "Gemini": [
            {"role": "user", "content": "Remember the client is Northwind."},
            {"role": "assistant", "content": "Got it, client is Northwind."},
        ]
    }
    api._index_conversation_turn_for_rag(
        "Remember the client is Northwind.",
        "Got it, client is Northwind.",
        provider="Gemini",
    )
    snippet = api.rag_engine.get_rag_system_prompt_snippet("Northwind client", top_k=1)
    assert "Northwind" in snippet

    before = api.rag_engine.get_rag_system_prompt_snippet("fail please boom", top_k=3)
    api._index_conversation_turn_for_rag("fail please", "Error: boom", provider="Gemini")
    api._index_conversation_turn_for_rag("fail please", "⚠️ Failed", provider="Gemini")
    after = api.rag_engine.get_rag_system_prompt_snippet("fail please boom", top_k=3)
    assert before == after
