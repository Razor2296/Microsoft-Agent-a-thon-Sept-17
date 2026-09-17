"""
app/tests/unit/test_api.py
Unit tests for main/api.py (PyWebView API event handlers and helper functions).
"""
import os
import re
from unittest.mock import MagicMock, patch

import pytest
from main.api import (
    PyWebViewApi,
    PyWebViewApi as Api,
    _extract_success_chrome,
    _friendly_error_message,
    _get_date_str,
    _get_iso_timestamp,
    _get_time_str,
    _is_goodbye_message,
    _media_chrome_message,
)


class TestApiHelpers:
    def test_get_time_str_format(self):
        time_str = _get_time_str()
        assert isinstance(time_str, str)
        assert "AM" in time_str or "PM" in time_str

    def test_get_iso_timestamp_format(self):
        iso_str = _get_iso_timestamp()
        assert isinstance(iso_str, str)
        assert "T" in iso_str
        assert ("+" in iso_str or "-" in iso_str or "Z" in iso_str)

    def test_get_date_str_format(self):
        date_str = _get_date_str()
        assert isinstance(date_str, str)
        assert len(date_str) == 10  # YYYY-MM-DD
        assert date_str.count("-") == 2

    def test_is_goodbye_message_spanish(self):
        assert _is_goodbye_message("chao nos vemos") is True
        assert _is_goodbye_message("hasta luego gracias") is True
        assert _is_goodbye_message("muchas gracias") is True
        assert _is_goodbye_message("hola buenos dias") is False

    def test_spanish_language_detection_with_urls(self):
        text = "Analiza este video https://www.youtube.com/watch?v=Ug88HO2mg44"
        clean_text = re.sub(r'https?://\S+', '', text).strip()
        spanish_keywords = ['analiza', 'este', 'video']
        text_lower = clean_text.lower()
        has_spanish_word = any(re.search(r'\b' + re.escape(w) + r'\b', text_lower) for w in spanish_keywords)
        assert has_spanish_word is True, "Short Spanish text with English URLs MUST be detected as Spanish"

    def test_is_goodbye_message_english(self):
        assert _is_goodbye_message("bye bye take care") is True
        assert _is_goodbye_message("thanks bye") is True
        assert _is_goodbye_message("what is the weather today?") is False

    def test_friendly_error_message_503(self):
        err = _friendly_error_message("503 Service Unavailable", lang="es-MX")
        assert "alta demanda" in err

    def test_friendly_error_message_403(self):
        err = _friendly_error_message("403 Forbidden Access", lang="en-US")
        assert "Access denied" in err

    def test_friendly_error_message_default(self):
        err = _friendly_error_message("Connection reset by peer", lang="es-MX")
        assert "Connection reset by peer" in err

    def test_friendly_error_message_french_not_english(self):
        err = _friendly_error_message("503 UNAVAILABLE", lang="fr-FR")
        assert "forte demande" in err.lower() or "forte demande" in err
        assert "high demand" not in err.lower()

    def test_friendly_error_message_german_not_english(self):
        err = _friendly_error_message("403 Forbidden", lang="de-DE")
        assert "Zugriff" in err
        assert "Access denied" not in err

    def test_friendly_error_message_malformed_function_call_spanish(self):
        err = _friendly_error_message(
            "Error: The model returned an empty response. Finish reason: MALFORMED_FUNCTION_CALL.",
            lang="es-MX",
        )
        assert "análisis" in err.lower() or "analisis" in err.lower()
        assert "MALFORMED_FUNCTION_CALL" not in err
        assert "inténtalo de nuevo" in err.lower() or "intentalo de nuevo" in err.lower()

    def test_friendly_error_message_malformed_function_call_french_not_english(self):
        err = _friendly_error_message(
            "Error: The model returned an empty response. Finish reason: MALFORMED_FUNCTION_CALL.",
            lang="fr-FR",
        )
        assert "analyse" in err.lower()
        assert "couldn't complete" not in err.lower()
        assert "MALFORMED_FUNCTION_CALL" not in err

    def test_friendly_error_message_empty_response_openai_tool_calls(self):
        err = _friendly_error_message(
            "Error: The model returned an empty response. Finish reason: tool_calls.",
            lang="es-MX",
        )
        assert "análisis" in err.lower() or "analisis" in err.lower()
        assert "tool_calls" not in err.lower()

    def test_media_chrome_french_image(self):
        msg = _media_chrome_message("image", "un chat", "fr-FR")
        assert "Image générée" in msg
        assert "Generated image" not in msg
        assert "Imagen generada" not in msg

    def test_media_chrome_german_audio(self):
        msg = _media_chrome_message("audio", "beethoven", "de-DE")
        assert "Audio generiert" in msg
        assert "Generated audio" not in msg

    def test_extract_success_chrome_french(self):
        msg = _extract_success_chrome("Bank_Statement", 3, "fr-FR", standalone=True)
        assert "Analyse structurée" in msg
        assert "Análisis estructurado" not in msg
        assert "3" in msg


class TestApiClassBindings:
    @pytest.fixture
    def api_instance(self):
        return PyWebViewApi()

    def test_get_initial_state_structure(self, api_instance):
        state = api_instance.get_initial_state()
        assert isinstance(state, dict)
        assert "providers" in state
        assert "generation_poll_timeout_ms" in state
        assert "document_poll_timeout_ms" in state
        assert int(state["generation_poll_timeout_ms"]) >= 60000
        assert int(state["document_poll_timeout_ms"]) >= 60000
        assert "current_provider" in state
        assert "user_name" in state
        assert "avatars" in state
        assert isinstance(state["avatars"], dict)
        assert len(state["avatars"].get("user", "")) > 0, "User avatar MUST NOT be empty (requires picture or SVG fallback)"
        assert isinstance(state["providers"], list)
        assert len(state["providers"]) >= 6

    def test_set_theme_window_size(self, api_instance):
        res = api_instance.set_theme_window_size("dark")
        assert res["status"] == "success"

    def test_open_external_link_invalid_protocol(self, api_instance):
        res = api_instance.open_external_link("file:///C:/test.txt")
        assert res["status"] == "error"
        assert "Invalid URL protocol" in res["message"]

    def test_determine_voice_category(self, api_instance):
        cat = api_instance.determine_voice_category("Hola soy una mujer investigadora")
        assert cat in ("adult_female", "adult_male", "child_female", "child_male", "young_female", "young_male", "senior_female", "senior_male", "Female", "Male")


    @patch.object(PyWebViewApi, "generate_cartesia_tts")
    def test_generate_cartesia_tts_delegation(self, mock_tts, api_instance):
        mock_tts.return_value = {"status": "success", "audio_base64": "fake_b64"}
        res = api_instance.generate_cartesia_tts("Hola mundo", "Male")
        assert res["status"] == "success"


class TestDocumentDirectiveExtraction:
    """Tests for LLM-driven document tag extraction (_extract_document_directive)."""

    def test_extract_docx_tag(self):
        from main.api import _extract_document_directive
        reply = "# Informe de Ventas\n\nContenido del informe.\n\n[GENERATE_DOCX]"
        doc_type, cleaned = _extract_document_directive(reply)
        assert doc_type == "docx"
        assert "[GENERATE_DOCX]" not in cleaned
        assert "# Informe de Ventas" in cleaned

    def test_extract_xlsx_tag(self):
        from main.api import _extract_document_directive
        reply = "| Producto | Precio |\n|---|---|\n| Item A | $10 |\n\n[GENERATE_XLSX]"
        doc_type, cleaned = _extract_document_directive(reply)
        assert doc_type == "xlsx"
        assert "[GENERATE_XLSX]" not in cleaned
        assert "| Producto |" in cleaned

    def test_extract_pptx_tag(self):
        from main.api import _extract_document_directive
        reply = "# Slide 1: Introducción\n- Punto 1\n\n[GENERATE_PPTX]"
        doc_type, cleaned = _extract_document_directive(reply)
        assert doc_type == "pptx"
        assert "[GENERATE_PPTX]" not in cleaned

    def test_extract_no_tag_conversational_phrases(self):
        from main.api import _extract_document_directive
        # Conversational phrases that previously triggered false positives must return None
        for text in [
            "I want a word with you about the project.",
            "Sí, podemos hablar ahora mismo. ¿De qué quieres que hablemos?",
            "Me gustaría ver una presentación de tu empresa.",
            "Quiero saber cómo funciona Microsoft Word.",
        ]:
            doc_type, cleaned = _extract_document_directive(text)
            assert doc_type is None
            assert cleaned == text


class TestMicrophoneLanguageDetection:
    """Regression tests for dynamic language detection from text and microphone transcription."""

    def test_detect_language_spanish_long_text(self):
        from main.api import _detect_language_from_text
        text = "¿Cuál es la que tal? ¿Cómo estás buen día? Yo soy Julián Curay, tengo 30 años y trabajo en sistemas."
        lang = _detect_language_from_text(text, default_language="en-US")
        assert lang == "es-MX"

    def test_detect_language_english_text(self):
        from main.api import _detect_language_from_text
        text = "Hello, I would like to learn more about the software engineering architecture."
        lang = _detect_language_from_text(text, default_language="es-MX")
        assert lang == "en-US"

    def test_detect_language_spanish_short_accented(self):
        from main.api import _detect_language_from_text
        text = "¿Cómo estás?"
        lang = _detect_language_from_text(text, default_language="en-US")
        assert lang == "es-MX"

    def test_preprocess_input_updates_language_after_mic_transcription(self):
        from main.api import PyWebViewApi
        api = PyWebViewApi()
        
        # Mock processor with transcribe_audio returning Spanish text
        mock_chat = MagicMock()
        mock_chat.transcribe_audio.return_value = (
            "¿Cómo estás? Quiero comentarte acerca de mis proyectos.",
            None,
            MagicMock()
        )
        api._chat_instances = {"Gemini": mock_chat}
        api._current_provider = "Gemini"
        
        # Fresh thread (no history): Spanish audio establishes sticky language
        files = [{"name": "mic_audio.wav", "mime_type": "audio/wav", "bytes": b"fake_wav_bytes"}]
        result = api._preprocess_input(
            text="",
            files=files,
            from_mic=True,
            language="en-US",
            chat=mock_chat,
            provider_for_fallback="Gemini",
            history=[],
        )
        
        assert result["language"] == "es-MX", "First-turn Spanish audio MUST establish es-MX"
        assert "¿Cómo estás?" in result["text"]

    def test_sticky_language_ignores_english_slang_mid_thread(self):
        from main.api import _resolve_conversation_language

        history = [
            {"role": "user", "content": "Hola, ¿cómo estás?", "conversation_language": "es-MX"},
            {"role": "assistant", "content": "¡Bien! ¿En qué te ayudo?"},
        ]
        lang = _resolve_conversation_language(
            "ok bro dame el link del meeting please",
            history=history,
            incoming_language="en-US",
        )
        assert lang.startswith("es"), "Slang/mixed English must not flip a Spanish thread"

    def test_explicit_language_switch_to_english(self):
        from main.api import _detect_explicit_language_switch, _resolve_conversation_language

        assert _detect_explicit_language_switch("háblame en inglés por favor") == "en-US"
        assert _detect_explicit_language_switch("switch to French") == "fr-FR"
        assert _detect_explicit_language_switch("ok bro thanks") is None

        history = [
            {"role": "user", "content": "Hola amigo", "conversation_language": "es-MX"},
        ]
        lang = _resolve_conversation_language(
            "por favor háblame en inglés de ahora en adelante",
            history=history,
            incoming_language="es-MX",
        )
        assert lang.startswith("en")

    def test_spanish_mic_after_english_thread_switches(self):
        """Regression: Grok kept en-US after Spanish STT because sticky ignored the utterance."""
        from main.api import _resolve_conversation_language

        history = [
            {
                "role": "user",
                "content": "analyze this song https://www.youtube.com/watch?v=u74gTjC_yUg",
                "conversation_language": "en-US",
            },
            {"role": "assistant", "content": "Easy Love by R5 is an upbeat pop-rock track."},
        ]
        spanish_mic = "Hola ¿qué tal? ¿Cómo estás? Buen día. Me escuchas claramente."
        lang = _resolve_conversation_language(
            spanish_mic,
            history=history,
            incoming_language="en-US",
        )
        assert lang.startswith("es"), f"Spanish mic after English thread MUST switch, got {lang}"

    def test_long_spanish_voice_without_inverted_punctuation_switches(self):
        from main.api import _resolve_conversation_language

        history = [
            {"role": "user", "content": "analyze this song", "conversation_language": "en-US"},
        ]
        spanish = (
            "nada estaba pensando en un par de cosas sobre literatura y necesito tu ayuda "
            "para saber que libros me recomendarias porque el conocimiento tecnico no basta"
        )
        lang = _resolve_conversation_language(
            spanish,
            history=history,
            incoming_language="en-US",
        )
        assert lang.startswith("es"), f"Monolingual Spanish STT MUST switch, got {lang}"

    def test_hola_en_espanol_after_english_switches(self):
        from main.api import _detect_explicit_language_switch, _resolve_conversation_language

        assert _detect_explicit_language_switch("Por favor, hola en español, no en otro diano.") == "es-MX"
        history = [
            {"role": "user", "content": "analyze this song", "conversation_language": "en-US"},
        ]
        lang = _resolve_conversation_language(
            "Por favor, hola en español, no en otro diano.",
            history=history,
            incoming_language="en-US",
        )
        assert lang.startswith("es")

    def test_preprocess_spanish_stt_after_english_history(self):
        from main.api import PyWebViewApi

        api = PyWebViewApi()
        mock_chat = MagicMock()
        mock_chat.transcribe_audio.return_value = (
            "Hola ¿qué tal? ¿Cómo estás? Buen día. Me escuchas claramente.",
            None,
            MagicMock(),
        )
        files = [{"name": "mic_audio.wav", "mime_type": "audio/wav", "bytes": b"fake_wav_bytes"}]
        history = [
            {"role": "user", "content": "analyze this song", "conversation_language": "en-US"},
            {"role": "assistant", "content": "Sure, here is the analysis."},
        ]
        result = api._preprocess_input(
            text="",
            files=files,
            from_mic=True,
            language="en-US",
            chat=mock_chat,
            provider_for_fallback="Grok",
            history=history,
        )
        assert result["language"].startswith("es")
        assert "Me escuchas claramente" in result["text"]

    def test_script_hint_min_chars_comes_from_env(self, monkeypatch):
        from backend.core.conversation_language import detect_clear_utterance_language

        monkeypatch.setenv("IGNITE_LANG_SCRIPT_HINT_MIN_CHARS", "80")
        hinted = "Hola ¿qué tal?"
        assert len(hinted) < 80
        assert detect_clear_utterance_language(hinted, sticky="en-US") is None


