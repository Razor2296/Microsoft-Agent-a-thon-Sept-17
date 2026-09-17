"""
app/tests/unit/test_base_processor_imports.py
Sprint 1.1 / FIX-1 — Verifies that all critical imports in base_processor.py
resolve without NameError, including pytesseract guard and google.genai in gemini_processor.
"""
import importlib
import os
import sys
import types

import backend.processors.base_processor as bp
from backend.core.schemas import TokenInfo
from backend.processors.base_processor import BaseChat


def test_pytesseract_guard_present():
    """FIX-1: pytesseract must be imported with a try/except guard so
    NameError never occurs even when Tesseract is not installed."""
    assert hasattr(bp, "pytesseract") or "pytesseract" in dir(bp), (
        "pytesseract attribute missing from base_processor — "
        "FIX-1 guard not applied correctly"
    )


def test_tokeninfo_importable_from_base_processor():
    """Skill 1.1 — TokenInfo schema must be importable via base_processor."""
    from backend.processors.base_processor import TokenInfo as ImportedTokenInfo
    assert ImportedTokenInfo is not None


def test_yt_dlp_guard_present():
    """yt_dlp must have a try/except ImportError guard and default to None."""
    assert hasattr(bp, "yt_dlp"), "yt_dlp attribute missing from base_processor"


def test_gemini_processor_genai_import_present():
    """Verify gemini_processor.py explicitly imports from google import genai."""
    gemini_path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "backend", "processors", "gemini_processor.py")
    )
    with open(gemini_path, "r", encoding="utf-8") as f:
        code = f.read()

    assert "from google import genai" in code, "gemini_processor.py MUST contain 'from google import genai'"
    assert "from google.genai import types" in code, "gemini_processor.py MUST contain 'from google.genai import types'"


def test_user_clipboard_text_import_across_processors():
    """Verify USER_CLIPBOARD_TEXT is imported in all provider processor modules."""
    processors_dir = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "backend", "processors")
    )
    processors = [
        "deepseek_processor.py",
        "openai_processor.py",
        "anthropic_processor.py",
        "perplexity_processor.py",
        "grok_processor.py",
        "alibabacloud_processor.py",
        "gemini_processor.py",
    ]
    for proc in processors:
        p_path = os.path.join(processors_dir, proc)
        with open(p_path, "r", encoding="utf-8") as f:
            code = f.read()
        assert "USER_CLIPBOARD_TEXT" in code, f"{proc} MUST import USER_CLIPBOARD_TEXT"


# ---------------------------------------------------------------------------
# Skill 1.1 — _flush_aux_tokens must return TokenInfo (not a raw dict)
# ---------------------------------------------------------------------------

class TestFlushAuxTokensTyping:
    """Verify that _flush_aux_tokens is Skill 1.1 compliant:
    accepts dict | TokenInfo | None, always returns a TokenInfo instance."""

    def _make_processor(self):
        """Return a minimal BaseChat-like object with _flush_aux_tokens."""
        # Instantiate without calling __init__ (avoids heavy cloud init)
        obj = object.__new__(BaseChat)
        obj._aux_gemini_tokens = {"prompt_tokens": 0, "candidates_tokens": 0, "total_tokens": 0}
        return obj

    def test_returns_token_info_from_dict(self):
        proc = self._make_processor()
        result = proc._flush_aux_tokens({"prompt_tokens": 10, "candidates_tokens": 5, "total_tokens": 15, "thinking_tokens": 0})
        assert isinstance(result, TokenInfo), "_flush_aux_tokens must return TokenInfo, not dict"

    def test_returns_token_info_from_none(self):
        proc = self._make_processor()
        result = proc._flush_aux_tokens(None)
        assert isinstance(result, TokenInfo)
        assert result.total_tokens == 0

    def test_returns_token_info_from_token_info_instance(self):
        proc = self._make_processor()
        ti = TokenInfo(prompt_tokens=20, completion_tokens=10)
        result = proc._flush_aux_tokens(ti)
        assert isinstance(result, TokenInfo)
        assert result.prompt_tokens == 20

    def test_aux_tokens_merged_correctly(self):
        proc = self._make_processor()
        # Simulate 50 accumulated auxiliary tokens
        proc._aux_gemini_tokens = {"prompt_tokens": 30, "candidates_tokens": 20, "total_tokens": 50}
        base_dict = {"prompt_tokens": 100, "candidates_tokens": 200, "total_tokens": 300, "thinking_tokens": 0}
        result = proc._flush_aux_tokens(base_dict)
        assert isinstance(result, TokenInfo)
        assert result.total_tokens == 350   # 300 base + 50 aux
        assert result.prompt_tokens == 130  # 100 base + 30 aux

    def test_accumulator_reset_after_flush(self):
        proc = self._make_processor()
        proc._aux_gemini_tokens = {"prompt_tokens": 10, "candidates_tokens": 5, "total_tokens": 15}
        proc._flush_aux_tokens({"prompt_tokens": 0, "candidates_tokens": 0, "total_tokens": 0})
        assert proc._aux_gemini_tokens["total_tokens"] == 0, "Accumulator must reset to 0 after flush"


def test_local_whisper_failure_returns_none_not_empty_string():
    """Skill §12.3: ImportError/Exception from local Whisper must return None so cloud fallbacks run."""
    from backend.processors.base_processor import BaseChat

    class _Stub(BaseChat):
        def __init__(self):
            pass

    stub = _Stub()
    # Force ImportError path by patching WhisperModel import failure inside method via empty audio
    # and making faster_whisper unavailable.
    import backend.processors.base_processor as bp_mod

    real_import = __import__

    def fake_import(name, *args, **kwargs):
        if name == "faster_whisper" or name.startswith("faster_whisper"):
            raise ImportError("forced missing faster-whisper")
        return real_import(name, *args, **kwargs)

    import builtins
    original = builtins.__import__
    try:
        builtins.__import__ = fake_import
        result = stub._transcribe_audio_local(b"RIFF....", "audio/wav", None)
    finally:
        builtins.__import__ = original
    assert result is None, f"Expected None on local Whisper failure, got {result!r}"
