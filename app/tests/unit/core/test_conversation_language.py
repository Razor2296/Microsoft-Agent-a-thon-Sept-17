"""
Conversation language policy: sticky slang, explicit switch, clear utterance.

Regression: Spanish microphone STT after an English Grok thread must become es-*.
Thresholds come from env (skill: no hardcode).
"""
from backend.core.conversation_language import (
    detect_clear_utterance_language,
    detect_explicit_language_switch,
    resolve_conversation_language,
    script_hint_min_chars,
    utterance_switch_min_chars,
)
from backend.processors.base_processor import resolve_reply_language

_ENGLISH_HISTORY = [
    {
        "role": "user",
        "content": "analyze this song https://www.youtube.com/watch?v=u74gTjC_yUg",
        "conversation_language": "en-US",
    },
    {"role": "assistant", "content": "Easy Love by R5 is an upbeat pop-rock track."},
]

_SPANISH_HISTORY = [
    {"role": "user", "content": "Hola, ¿cómo estás?", "conversation_language": "es-MX"},
    {"role": "assistant", "content": "¡Bien! ¿En qué te ayudo?"},
]


class TestGrokSpanishMicRegression:
    def test_logged_spanish_mic_switches_english_thread(self):
        lang = resolve_conversation_language(
            "Hola ¿qué tal? ¿Cómo estás? Buen día. Me escuchas claramente.",
            history=_ENGLISH_HISTORY,
            incoming_language="en-US",
        )
        assert lang.startswith("es")

    def test_logged_long_spanish_voice_switches(self):
        lang = resolve_conversation_language(
            (
                "nada estaba pensando en un par de cosas sobre literatura y necesito tu ayuda "
                "para saber que libros me recomendarias porque el conocimiento tecnico no basta"
            ),
            history=_ENGLISH_HISTORY,
            incoming_language="en-US",
        )
        assert lang.startswith("es")

    def test_preprocess_force_language_feeds_spanish_reply_instruction(self):
        force = resolve_conversation_language(
            "Hola ¿qué tal? ¿Cómo estás? Buen día. Me escuchas claramente.",
            history=_ENGLISH_HISTORY,
            incoming_language="en-US",
        )
        code, name = resolve_reply_language(force, user_input="Hola ¿qué tal?")
        assert code.startswith("es")
        assert "Spanish" in name


class TestIncomingDetectAgreesWithText:
    def test_spanish_invoice_prompt_after_english_thread(self):
        lang = resolve_conversation_language(
            "Analiza estas boletas de pago",
            history=_ENGLISH_HISTORY,
            incoming_language="es-MX",
        )
        assert lang.startswith("es")


class TestStickyAndSlang:
    def test_mixed_slang_does_not_leave_spanish(self):
        lang = resolve_conversation_language(
            "ok bro dame el link del meeting please",
            history=_SPANISH_HISTORY,
            incoming_language="en-US",
        )
        assert lang.startswith("es")

    def test_short_ok_keeps_spanish(self):
        lang = resolve_conversation_language(
            "ok",
            history=_SPANISH_HISTORY,
            incoming_language="en-US",
        )
        assert lang.startswith("es")

    def test_short_hola_does_not_flip_english_thread(self):
        lang = resolve_conversation_language(
            "Hola",
            history=_ENGLISH_HISTORY,
            incoming_language="en-US",
        )
        assert lang.startswith("en")


class TestExplicitSwitch:
    def test_hablame_en_ingles(self):
        assert detect_explicit_language_switch("háblame en inglés por favor") == "en-US"

    def test_hola_en_espanol(self):
        assert detect_explicit_language_switch("Por favor, hola en español, no en otro diano.") == "es-MX"

    def test_switch_to_french(self):
        assert detect_explicit_language_switch("switch to French") == "fr-FR"


class TestClearUtteranceBothDirections:
    def test_english_paragraph_after_spanish_switches(self):
        lang = resolve_conversation_language(
            (
                "Can you please analyze this architecture reading list and tell me which "
                "titles I should read first for enterprise data platforms?"
            ),
            history=_SPANISH_HISTORY,
            incoming_language="es-MX",
        )
        assert lang.startswith("en")

    def test_french_paragraph_after_english_switches(self):
        lang = resolve_conversation_language(
            (
                "Bonjour, je voudrais que tu m'aides avec mon projet d'architecture "
                "logicielle pour l'entreprise et les donnees."
            ),
            history=_ENGLISH_HISTORY,
            incoming_language="en-US",
        )
        assert lang.startswith("fr")


class TestEnvThresholds:
    def test_utterance_min_chars_from_env(self, monkeypatch):
        monkeypatch.setenv("IGNITE_LANG_UTTERANCE_SWITCH_MIN_CHARS", "40")
        assert utterance_switch_min_chars() == 40

    def test_script_hint_min_chars_from_env(self, monkeypatch):
        monkeypatch.setenv("IGNITE_LANG_SCRIPT_HINT_MIN_CHARS", "80")
        assert script_hint_min_chars() == 80
        hinted = "Hola ¿qué tal?"
        assert detect_clear_utterance_language(hinted, sticky="en-US") is None

    def test_invalid_env_falls_back_to_example_default(self, monkeypatch):
        monkeypatch.setenv("IGNITE_LANG_UTTERANCE_SWITCH_MIN_CHARS", "not-a-number")
        assert utterance_switch_min_chars() == 24
        monkeypatch.setenv("IGNITE_LANG_SCRIPT_HINT_MIN_CHARS", "nope")
        assert script_hint_min_chars() == 8
