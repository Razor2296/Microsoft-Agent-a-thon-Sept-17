"""Perplexity Sonar: prompt truncation + user-safe API error mapping."""
from backend.processors.perplexity_processor import PerplexityChat


def test_truncate_for_perplexity_short_unchanged():
    text = "hola mundo"
    assert PerplexityChat._truncate_for_perplexity(text, max_chars=100) == text


def test_truncate_for_perplexity_long_adds_marker():
    text = "x" * 5000
    out = PerplexityChat._truncate_for_perplexity(text, max_chars=800)
    assert len(out) <= 800
    assert "truncated for Perplexity" in out
    assert out.startswith("x")


def test_useful_image_desc_filters_noise():
    assert PerplexityChat._useful_image_desc("A blue logo on white.") is True
    assert PerplexityChat._useful_image_desc("[Skipped tiny decorative image below vision minimum.]") is False
    assert PerplexityChat._useful_image_desc("[Error analyzing image: boom]") is False
    assert PerplexityChat._useful_image_desc("") is False


def test_format_perplexity_api_error_rate_limit():
    msg = PerplexityChat._format_perplexity_api_error(Exception("Error code: 429 - rate limit exceeded"))
    assert "rate limit" in msg.lower()


def test_format_perplexity_api_error_context():
    msg = PerplexityChat._format_perplexity_api_error(Exception("maximum context length exceeded"))
    assert "too large" in msg.lower()


def test_format_perplexity_api_error_timeout():
    msg = PerplexityChat._format_perplexity_api_error(Exception("Request timed out"))
    assert "timed out" in msg.lower()
