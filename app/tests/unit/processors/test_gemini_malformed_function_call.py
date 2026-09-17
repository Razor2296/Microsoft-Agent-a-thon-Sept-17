"""Gemini recovery for empty / MALFORMED_FUNCTION_CALL replies during image analysis."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import backend.processors.gemini_processor as gp


def _chat() -> gp.GeminiChat:
    chat = gp.GeminiChat.__new__(gp.GeminiChat)
    chat.google_search_enabled = True
    chat.system_instruction = "test"
    chat.model_version = "gemini-test"
    chat.max_tokens = 4000
    chat.temperature = 0.7
    chat.top_p = 0.9
    chat.client = MagicMock()
    return chat


def _response(*, text: str = "", finish: str = "MALFORMED_FUNCTION_CALL", parts_text: str = "") -> SimpleNamespace:
    part = SimpleNamespace(text=parts_text or None, thought=False)
    candidate = SimpleNamespace(
        finish_reason=SimpleNamespace(name=finish),
        content=SimpleNamespace(parts=[part]),
    )
    return SimpleNamespace(
        text=text,
        candidates=[candidate],
        usage_metadata=None,
        prompt_feedback=None,
    )


class TestUnusableAssistantHistory:
    def test_empty_and_no_response(self):
        assert gp.GeminiChat._is_unusable_assistant_history("") is True
        assert gp.GeminiChat._is_unusable_assistant_history("No response") is True
        assert gp.GeminiChat._is_unusable_assistant_history("A photo of a beach") is False

    def test_malformed_function_call_error(self):
        msg = "Error: The model returned an empty response. Finish reason: MALFORMED_FUNCTION_CALL."
        assert gp.GeminiChat._is_unusable_assistant_history(msg) is True


class TestSearchSkipForImageAnalysis:
    def test_skips_search_for_photo_analysis(self):
        chat = _chat()
        files = [{"name": "photo.jpg", "mime_type": "image/jpeg"}]
        assert chat._should_attach_google_search(
            "por favor analiza estas fotos con detalle",
            files=files,
        ) is False

    def test_keeps_search_for_news_with_images(self):
        chat = _chat()
        files = [{"name": "photo.jpg", "mime_type": "image/jpeg"}]
        assert chat._should_attach_google_search(
            "analiza estas fotos de las noticias de hoy",
            files=files,
        ) is True

    def test_text_query_without_images_can_search(self):
        chat = _chat()
        assert chat._should_attach_google_search("cual es el clima en madrid hoy por la tarde") is True


class TestExtractResponseText:
    def test_uses_response_text_when_present(self):
        chat = _chat()
        resp = _response(text="Hola", finish="STOP")
        assert chat._extract_response_text(resp) == "Hola"

    def test_falls_back_to_parts_when_text_empty(self):
        chat = _chat()
        resp = _response(text="", finish="MALFORMED_FUNCTION_CALL", parts_text="Descripción visible")
        assert chat._extract_response_text(resp) == "Descripción visible"

    def test_skips_thought_parts(self):
        chat = _chat()
        thought = SimpleNamespace(text="internal", thought=True)
        visible = SimpleNamespace(text="respuesta", thought=False)
        resp = SimpleNamespace(
            text="",
            candidates=[SimpleNamespace(
                finish_reason=SimpleNamespace(name="STOP"),
                content=SimpleNamespace(parts=[thought, visible]),
            )],
        )
        assert chat._extract_response_text(resp) == "respuesta"


class TestMalformedRecovery:
    def test_retries_without_tools_on_malformed_function_call(self, monkeypatch):
        chat = _chat()
        malformed = _response(text="", finish="MALFORMED_FUNCTION_CALL")
        recovered = _response(text="Veo una foto en la playa al atardecer.", finish="STOP")
        chat.client.models.generate_content.side_effect = [malformed, recovered]
        chat._plain_text_tool_config = MagicMock(return_value=None)

        captured = []

        def fake_config(**kwargs):
            captured.append(kwargs)
            return SimpleNamespace(**kwargs)

        monkeypatch.setattr(gp.types, "GenerateContentConfig", fake_config)

        fake_tool = object()
        reply, response = chat._call_gemini_with_recovery(
            contents="analiza estas fotos",
            sys_instr="sys",
            tools=[fake_tool],
        )

        assert reply == "Veo una foto en la playa al atardecer."
        assert response is recovered
        assert chat.client.models.generate_content.call_count == 2
        assert captured[0].get("tools") == [fake_tool]
        assert "tools" not in captured[1]

    def test_handle_empty_response_includes_malformed_reason(self):
        chat = _chat()
        msg = chat._handle_empty_response(_response(text="", finish="MALFORMED_FUNCTION_CALL"))
        assert "MALFORMED_FUNCTION_CALL" in msg

    def test_inline_files_empty_reply_is_error_not_blank(self):
        """Regression: empty image replies used to become UI 'No response'."""
        chat = _chat()
        malformed = _response(text="", finish="MALFORMED_FUNCTION_CALL")
        assert not chat._extract_response_text(malformed)
        wrapped = f"Error: {chat._handle_empty_response(malformed)}."
        assert wrapped.startswith("Error:")
        assert wrapped != ""


class TestHistorySkipsPoisonTurns:
    def test_build_history_skips_no_response_and_merges_users(self):
        chat = _chat()
        history = [
            {"role": "user", "content": "analiza estas fotos", "files": []},
            {"role": "assistant", "content": "No response", "files": []},
            {"role": "user", "content": "no la reconoces?", "files": []},
        ]
        contents = chat._build_history_contents(history)
        assert len(contents) == 1
        assert contents[0].role == "user"
        texts = [getattr(p, "text", "") for p in (contents[0].parts or [])]
        joined = "\n".join(texts)
        assert "analiza estas fotos" in joined
        assert "no la reconoces?" in joined
        assert "No response" not in joined
