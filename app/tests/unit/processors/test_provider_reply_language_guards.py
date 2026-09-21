"""
Shared provider prompting contract (README): every LLM molds to app helpers.
"""
from __future__ import annotations

from pathlib import Path

from backend.processors.base_processor import (
    append_mandatory_reply_language,
    mandatory_reply_language_note,
    multimodal_describe_prompt,
    wrap_user_query_for_language,
)

PROCESSORS_DIR = Path(__file__).resolve().parents[3] / "backend" / "processors"

PROVIDER_FILES = (
    "deepseek_processor.py",
    "openai_processor.py",
    "anthropic_processor.py",
    "grok_processor.py",
    "perplexity_processor.py",
    "gemini_processor.py",
    "alibabacloud_processor.py",
)


def test_helpers_spanish_contract():
    note = mandatory_reply_language_note("es-MX", "Spanish")
    assert "privacidad" in note.lower()
    wrapped = wrap_user_query_for_language("hola", "es-MX", "Spanish")
    assert "ESPAÑOL" in wrapped
    prompt = multimodal_describe_prompt("Spanish", media="image")
    assert "Spanish" in prompt
    notes: list[str] = []
    code, name = append_mandatory_reply_language(notes, "es-MX", user_input="hola")
    assert code.startswith("es")
    assert name == "Spanish"
    assert notes and "INSTRUCCIÓN MANDATORIA" in notes[0]


def test_helpers_english_contract():
    note = mandatory_reply_language_note("en-US", "English")
    assert "MUST reply ONLY in English" in note
    wrapped = wrap_user_query_for_language("hi", "en-US", "English")
    assert "Reply entirely in English" in wrapped


def test_every_provider_uses_shared_language_helpers():
    for name in PROVIDER_FILES:
        src = (PROCESSORS_DIR / name).read_text(encoding="utf-8")
        assert "append_mandatory_reply_language" in src, f"{name} missing append_mandatory_reply_language"
        assert "El usuario acaba de hablar/escribir en Español" not in src, (
            f"{name} still has soft Spanish-only language note"
        )


def test_describe_paths_use_multimodal_helper():
    for name in ("deepseek_processor.py", "alibabacloud_processor.py"):
        src = (PROCESSORS_DIR / name).read_text(encoding="utf-8")
        assert "multimodal_describe_prompt" in src, f"{name} missing multimodal_describe_prompt"
        assert (
            "Analyze this image thoroughly. Write a detailed, natural, first-person narrative description of everything you see: objects, people, colors, text on screen, layout, mood, and any other relevant details. Do NOT use the words 'transcription', 'transcript', or 'description'. Write it as flowing prose as if you are directly observing it."
            not in src
        ), f"{name} still hardcodes English-only vision describe prompt"
