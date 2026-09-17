"""Unit tests for multi-environment .env selection."""

import os
from main.env_config import load_environment, resolve_env_file


def test_resolve_env_file_staging(tmp_path):
    staging = tmp_path / ".env.staging"
    staging.write_text("FOO=1\n", encoding="utf-8")
    (tmp_path / ".env").write_text("FOO=0\n", encoding="utf-8")
    assert resolve_env_file(str(tmp_path), "staging").endswith(".env.staging")


def test_resolve_env_file_falls_back_to_default(tmp_path):
    (tmp_path / ".env").write_text("FOO=1\n", encoding="utf-8")
    path = resolve_env_file(str(tmp_path), "production")
    assert path.endswith(".env")


def test_load_environment_sets_vars(tmp_path, monkeypatch):
    monkeypatch.delenv("IGNITE_TEST_MARKER", raising=False)
    env = tmp_path / ".env"
    env.write_text("IGNITE_TEST_MARKER=from_env\n", encoding="utf-8")
    loaded = load_environment(str(tmp_path), "development")
    assert loaded.endswith(".env")
    assert os.getenv("IGNITE_TEST_MARKER") == "from_env"


def test_env_example_declares_budget_and_language_thresholds():
    example = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..", ".env.example")
    )
    text = open(example, encoding="utf-8").read()
    for key in (
        "IGNITE_BUDGET_USD",
        "IGNITE_BUDGET_WARN_REMAINING_PCT",
        "IGNITE_BUDGET_CRITICAL_REMAINING_PCT",
        "IGNITE_BUDGET_TOAST_MS",
        "IGNITE_LANG_UTTERANCE_SWITCH_MIN_CHARS",
        "IGNITE_LANG_SCRIPT_HINT_MIN_CHARS",
        "IGNITE_LANG_FUNCTION_WORD_MARGIN",
        "IGNITE_LANG_FUNCTION_WORD_MIN_SCORE",
    ):
        assert key in text, f"app/.env.example MUST declare {key}"


def test_env_example_declares_long_document_timeouts():
    example = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..", ".env.example")
    )
    text = open(example, encoding="utf-8").read()
    for key in (
        "IGNITE_DOCUMENT_API_TIMEOUT",
        "IGNITE_GENERATION_POLL_TIMEOUT_MS",
        "IGNITE_DOCUMENT_POLL_TIMEOUT_MS",
        "IGNITE_GEMINI_HTTP_TIMEOUT_MS",
        "IGNITE_PDF_MAX_FULL_TEXT_CHARS",
        "IGNITE_PDF_MAX_RETRIEVED_PAGES",
        "IGNITE_PDF_SUMMARY_SAMPLE_PAGES",
        "IGNITE_PDF_IMAGE_PAGE_SCAN_LIMIT",
        "IGNITE_PDF_NATIVE_MAX_BYTES",
        "IGNITE_PDF_NATIVE_MAX_PAGES",
        "IGNITE_LLM_HTTP_TIMEOUT",
        "IGNITE_GEMINI_HTTP_TIMEOUT_MS",
    ):
        assert key in text, f"app/.env.example MUST declare {key}"
