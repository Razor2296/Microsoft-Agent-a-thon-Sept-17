"""
app/tests/unit/test_llm_processors.py
Unit tests for backend AI provider processors (BaseChat & helpers).
"""
import inspect
import pytest

import backend.processors.alibabacloud_processor as alp
import backend.processors.anthropic_processor as ap
import backend.processors.deepseek_processor as dp
import backend.processors.gemini_processor as gp
import backend.processors.grok_processor as grp
import backend.processors.openai_processor as op
import backend.processors.perplexity_processor as pp
from backend.processors.base_processor import BaseChat, resolve_lang_name
from backend.user.windows_user import get_system_language


class TestBaseChatUtilities:
    def test_resolve_lang_name_spanish(self):
        assert resolve_lang_name("es-MX") == "Spanish"
        assert resolve_lang_name("es-ES") == "Spanish"

    def test_get_system_language(self):
        name = get_system_language()
        assert isinstance(name, str)
        assert len(name) > 0

    def test_base_chat_abstract_methods(self):
        base = BaseChat()
        assert hasattr(base, "generate_response")
        assert hasattr(base, "generate_response_with_inline_files")
        with pytest.raises(NotImplementedError):
            base.generate_response("hello")
        with pytest.raises(NotImplementedError):
            base.generate_response_with_inline_files("hello")


class TestDocumentRequestDetection:
    def test_detect_document_request_word(self):
        res = BaseChat.detect_document_request("crea un archivo de docx con el resumen")
        assert res in ("docx", "xlsx", "pptx")

    def test_detect_document_request_excel(self):
        res = BaseChat.detect_document_request("genera una hoja de calculo xlsx de ventas")
        assert res == "xlsx"

    def test_detect_document_request_none(self):
        res = BaseChat.detect_document_request("explicame la teoria de la relatividad")
        assert res is None


class TestGeminiProcessorConstants:
    """Verify Gemini processor imports image and audio model constants properly."""

    def test_gemini_image_constants_imported(self):
        assert hasattr(gp, "GEMINI_IMAGE_MODEL_VERSION")
        assert hasattr(gp, "GEMINI_FALLBACK_IMAGE_MODEL")
        assert hasattr(gp, "GEMINI_AUDIO_MODEL_VERSION")
        assert hasattr(gp, "GEMINI_FALLBACK_AUDIO_MODEL_VERSION")
        assert hasattr(gp, "GEMINI_TTS_VOICE")
        assert isinstance(gp.GEMINI_IMAGE_MODEL_VERSION, str)
        assert isinstance(gp.GEMINI_FALLBACK_IMAGE_MODEL, str)

    def test_openai_processor_constants_imported(self):
        assert hasattr(op, "OPENAI_IMAGE_MODEL_VERSION")
        assert hasattr(op, "OPENAI_FALLBACK_IMAGE_MODEL")
        assert hasattr(op, "OPENAI_RETRY_SEQUENCE")

    def test_all_processors_import_constants_without_nameerror(self):
        assert hasattr(ap, "ANTHROPIC_RETRY_SEQUENCE")
        assert hasattr(dp, "DEEPSEEK_RETRY_SEQUENCE")
        assert hasattr(pp, "PERPLEXITY_RETRY_SEQUENCE")
        assert hasattr(alp, "ALIBABACLOUD_RETRY_SEQUENCE")
        assert hasattr(grp, "GROK_RETRY_SEQUENCE")

    def test_processor_generate_response_signatures_match_base(self):
        base_sig = list(inspect.signature(BaseChat.generate_response).parameters.keys())
        assert base_sig[1] == "user_input"

        classes = [
            alp.AlibabaCloudChat,
            op.OpenAIChat,
            ap.AnthropicChat,
            dp.DeepSeekChat,
            grp.GrokChat,
            pp.PerplexityChat,
            gp.GeminiChat,
        ]

        for cls in classes:
            sig = list(inspect.signature(cls.generate_response).parameters.keys())
            assert sig[1] == "user_input", f"{cls.__name__}.generate_response first arg must be 'user_input', got '{sig[1]}'"

            inline_sig = list(inspect.signature(cls.generate_response_with_inline_files).parameters.keys())
            assert inline_sig[1] == "user_input", f"{cls.__name__}.generate_response_with_inline_files first arg must be 'user_input', got '{inline_sig[1]}'"

    def test_processor_clean_messages_alternation(self):

        # Test message cleaner handles repeated user messages by merging
        messages = [
            {"role": "system", "content": "System instruction"},
            {"role": "user", "content": "First message"},
            {"role": "user", "content": "Second message"},
            {"role": "assistant", "content": "Reply 1"},
            {"role": "assistant", "content": "Reply 2"},
            {"role": "user", "content": "Third message"},
        ]

        # Test in GrokChat
        grok_chat = grp.GrokChat.__new__(grp.GrokChat)
        cleaned_grok = grok_chat._clean_messages_for_alternation(messages)
        non_sys_grok = [m for m in cleaned_grok if m["role"] != "system"]
        assert len(non_sys_grok) == 3
        assert non_sys_grok[0]["role"] == "user"
        assert "First message" in non_sys_grok[0]["content"] and "Second message" in non_sys_grok[0]["content"]
        assert non_sys_grok[1]["role"] == "assistant"
        assert non_sys_grok[2]["role"] == "user"

        # Test in OpenAIChat
        openai_chat = op.OpenAIChat.__new__(op.OpenAIChat)
        cleaned_openai = openai_chat._clean_messages_for_alternation(messages)
        non_sys_openai = [m for m in cleaned_openai if m["role"] != "system"]
        assert len(non_sys_openai) == 3
        assert non_sys_openai[0]["role"] == "user"
        assert non_sys_openai[1]["role"] == "assistant"
        assert non_sys_openai[2]["role"] == "user"

        # Test in AnthropicChat (system messages omitted from messages list)
        anthropic_chat = ap.AnthropicChat.__new__(ap.AnthropicChat)
        cleaned_anthropic = anthropic_chat._clean_messages_for_alternation(messages)
        assert all(m["role"] != "system" for m in cleaned_anthropic)
        assert len(cleaned_anthropic) == 3
        assert cleaned_anthropic[0]["role"] == "user"
        assert cleaned_anthropic[1]["role"] == "assistant"
        assert cleaned_anthropic[2]["role"] == "user"

        # Test in BaseChat
        base_chat = BaseChat()
        cleaned_base = base_chat._clean_messages_for_alternation(messages)
        non_sys_base = [m for m in cleaned_base if m["role"] != "system"]
        assert len(non_sys_base) == 3
        assert non_sys_base[0]["role"] == "user"
        assert non_sys_base[1]["role"] == "assistant"
        assert non_sys_base[2]["role"] == "user"


class TestProviderBaseUrls:
    """Verify provider base URLs are configurable and exported."""

    def test_base_urls_exported_from_processor_module(self):
        from backend.processors.processor import (
            DEEPSEEK_BASE_URL,
            GROK_BASE_URL,
            PERPLEXITY_BASE_URL,
        )
        assert DEEPSEEK_BASE_URL.startswith("http")
        assert GROK_BASE_URL.startswith("http")
        assert PERPLEXITY_BASE_URL.startswith("http")

    def test_deepseek_base_url_default(self):
        assert dp.DEEPSEEK_BASE_URL == "https://api.deepseek.com"

    def test_grok_base_url_default(self):
        assert grp.GROK_BASE_URL == "https://api.x.ai/v1"

    def test_perplexity_base_url_default(self):
        assert pp.PERPLEXITY_BASE_URL == "https://api.perplexity.ai"


class TestConversationalAndLanguageFixes:
    """Verify Unicode conversational phrases and language detection behavior."""

    def test_conversational_phrases_unicode_no_mojibake(self):
        base = BaseChat()
        # Verify accented phrases correctly skip search (no mojibake)
        for phrase in ["sí", "si", "continúa", "continua", "más", "mas", "adiós", "adios", "gracias", "ok"]:
            assert base._needs_web_search(phrase) is False, f"Phrase '{phrase}' should skip web search"

    def test_document_guidelines_injection(self):
        base = BaseChat()
        base.system_instruction = "Initial instruction."
        base.inject_document_guidelines()
        assert "Special Document Generation Commands" in base.system_instruction
        assert "[GENERATE_DOCX]" in base.system_instruction
        assert "[GENERATE_XLSX]" in base.system_instruction
        assert "[GENERATE_PPTX]" in base.system_instruction


class TestSharedEmptyReplyAndVisualSearchSkip:
    """All providers share BaseChat helpers for photo-analysis search skip and empty replies."""

    def test_skips_search_for_photo_analysis(self):
        base = BaseChat()
        base.google_search_enabled = True
        base.system_instruction = "test"
        files = [{"name": "photo.jpg", "mime_type": "image/jpeg"}]
        assert base._should_attach_web_search(
            "por favor analiza estas fotos con detalle",
            files=files,
        ) is False

    def test_keeps_search_for_news_with_images(self):
        base = BaseChat()
        base.google_search_enabled = True
        base.system_instruction = "test"
        files = [{"name": "photo.jpg", "mime_type": "image/jpeg"}]
        assert base._should_attach_web_search(
            "analiza estas fotos de las noticias de hoy",
            files=files,
        ) is True

    def test_openai_compat_processors_use_shared_search_helper(self):
        for cls in (op.OpenAIChat, ap.AnthropicChat, dp.DeepSeekChat, grp.GrokChat, pp.PerplexityChat, alp.AlibabaCloudChat):
            assert hasattr(cls, "_should_attach_web_search")
            chat = cls.__new__(cls)
            chat.google_search_enabled = True
            chat.system_instruction = "test"
            files = [{"mime_type": "image/png"}]
            assert chat._should_attach_web_search(
                "por favor analiza estas fotos con detalle",
                files=files,
            ) is False

    def test_filter_history_drops_poison_assistant(self):
        history = [
            {"role": "user", "content": "analiza estas fotos", "files": []},
            {"role": "assistant", "content": "No response", "files": []},
            {"role": "assistant", "content": "Error: The model returned an empty response. Finish reason: tool_calls.", "files": []},
            {"role": "user", "content": "no la reconoces?", "files": []},
        ]
        filtered = BaseChat.filter_history_for_model(history)
        assert [m["role"] for m in filtered] == ["user", "user"]
        assert all("No response" not in (m.get("content") or "") for m in filtered)

    def test_coerce_non_empty_reply(self):
        assert BaseChat.coerce_non_empty_reply("") == "Error: The model returned an empty response."
        assert BaseChat.coerce_non_empty_reply("No response").startswith("Error:")
        assert BaseChat.coerce_non_empty_reply("Veo una playa") == "Veo una playa"


class TestProcessorReplyLanguageMandate:
    def test_providers_follow_latest_utterance_not_first_turn_only(self):
        modules = (gp, op, ap, dp, pp, grp, alp)
        for mod in modules:
            path = inspect.getfile(mod)
            with open(path, encoding="utf-8") as fh:
                source = fh.read()
            assert "latest message" in source, (
                f"{mod.__name__} MUST instruct the model to follow the latest user language"
            )
            assert "initiated and is using in the conversation" not in source, (
                f"{mod.__name__} must not keep the old first-turn-only language mandate"
            )


class TestLongPdfNativePath:
    def test_gemini_sends_native_pdf_instead_of_truncating(self):
        path = inspect.getfile(gp)
        source = open(path, encoding="utf-8").read()
        assert "should_send_native_pdf" in source
        assert 'mime_type="application/pdf"' in source or "mime_type='application/pdf'" in source

    def test_anthropic_native_page_limit_comes_from_env(self):
        path = inspect.getfile(ap)
        source = open(path, encoding="utf-8").read()
        assert "pdf_native_max_pages" in source
        assert "len(reader.pages) > 15" not in source







