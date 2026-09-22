"""User bubbles must never show RAG / multimodal model assembly."""
from __future__ import annotations

import inspect

from main.api import (
    PyWebViewApi,
    _clean_history_for_frontend,
    _clean_history_for_saving,
    strip_model_context_from_user_content,
)


def test_strip_keeps_user_text_after_rag_prefix():
    polluted = (
        "[LOCAL PERSISTENT MEMORY RECALLED] Relevant past memories/notes:\n"
        "- Memory 1 (Score 0.5): old youtube turn\n"
        "Use these recalled factual memories to provide consistent, personalized answers.\n\n"
        "[USER QUERY]\n"
        "describe esta foto"
    )
    assert strip_model_context_from_user_content(polluted) == "describe esta foto"


def test_strip_image_only_assembly_to_empty():
    polluted = (
        "[LOCAL PERSISTENT MEMORY RECALLED] Relevant past memories/notes:\n"
        "- Memory 1: foo\n\n"
        "[USER QUERY]\n"
        '<image_file name="pasted.png">\n'
        "[What I can see in this image:]\n"
        "A woman in a room.\n"
        "</image_file>\n\n"
        "[Consulta del Usuario (Responde enteramente en ESPAÑOL)]:\n"
    )
    assert strip_model_context_from_user_content(polluted) == ""


def test_frontend_and_save_cleaners_strip_user_role():
    history = [
        {
            "role": "user",
            "content": (
                "[LOCAL PERSISTENT MEMORY RECALLED] x\n\n[USER QUERY]\nhola\n"
                "<image_file name='a.png'>desc</image_file>"
            ),
            "files": [{"name": "a.png", "preview_base64": "xx"}],
        },
        {"role": "assistant", "content": "ok"},
    ]
    front = _clean_history_for_frontend(history)
    assert front[0]["content"] == "hola"
    assert "[LOCAL PERSISTENT MEMORY RECALLED]" not in front[0]["content"]
    saved = _clean_history_for_saving(history, provider="OpenAI", session_id="s1")
    assert saved[0]["content"] == "hola"


def test_send_path_never_overwrites_user_bubble_with_enriched_text():
    """Static anti-regression: skill user-bubble-isolation."""
    send_src = inspect.getsource(PyWebViewApi._send_message_sync)
    assert '[-1]["content"] = enriched_text' not in send_src
    assert '[-1]["content"] = _model_facing_user_text' not in send_src
    assert "_text_for_model_with_rag" in send_src
    # 3-tuple may still be unpacked, but must not mutate user history content
    if "len(res) == 3" in send_src:
        assert "enriched_text" not in send_src or "content\"] = enriched_text" not in send_src


def test_strip_helper_and_cleaners_are_wired():
    front_src = inspect.getsource(_clean_history_for_frontend)
    save_src = inspect.getsource(_clean_history_for_saving)
    assert "strip_model_context_from_user_content" in front_src
    assert "strip_model_context_from_user_content" in save_src
