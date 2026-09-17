"""Long-document PDF extraction: full-book summaries must not be capped at 12 pages."""
from types import SimpleNamespace

from backend.processors.base_processor import (
    BaseChat,
    _env_positive_int,
    _sample_pages_evenly,
    pdf_image_page_scan_limit,
    pdf_max_full_text_chars,
    pdf_native_max_bytes,
    should_send_native_pdf,
    wants_full_document_read,
)


class _FakePage:
    def __init__(self, text, images=None):
        self._text = text
        self.images = images or []

    def extract_text(self):
        return self._text


class _FakeReader:
    def __init__(self, pages):
        self.pages = pages


def _patch_pdf(monkeypatch, texts, images_by_index=None):
    pages = []
    for idx, text in enumerate(texts):
        pages.append(_FakePage(text, (images_by_index or {}).get(idx, [])))
    reader = _FakeReader(pages)

    class _Pypdf:
        @staticmethod
        def PdfReader(_buf):
            return reader

    monkeypatch.setattr("backend.processors.base_processor.pypdf", _Pypdf)
    monkeypatch.setattr("backend.processors.base_processor.PyPDF2", None)
    return BaseChat()


def test_wants_full_document_read_spanish_resumen():
    assert wants_full_document_read("Hazme un resumen detallado por capitulo del libro")
    assert wants_full_document_read("Summarize each chapter of this book")
    assert not wants_full_document_read("What is the tax rate on page 4?")


def test_summary_query_returns_all_pages_under_char_cap(monkeypatch):
    monkeypatch.setenv("IGNITE_PDF_MAX_FULL_TEXT_CHARS", "8000")
    chat = _patch_pdf(monkeypatch, [f"Chapter {i} content about management." for i in range(1, 21)])
    text = chat._extract_text_from_pdf(b"%PDF-fake", user_query="Hazme un resumen por capitulo")
    assert "--- Page 1 ---" in text
    assert "--- Page 20 ---" in text
    assert "Chapter 20" in text
    assert "most relevant sections" not in text


def test_summary_query_samples_across_book_when_over_cap(monkeypatch):
    monkeypatch.setenv("IGNITE_PDF_MAX_FULL_TEXT_CHARS", "80")
    monkeypatch.setenv("IGNITE_PDF_SUMMARY_SAMPLE_PAGES", "6")
    pages = [f"Page {i:03d} " + ("x" * 40) for i in range(1, 41)]
    chat = _patch_pdf(monkeypatch, pages)
    text = chat._extract_text_from_pdf(b"%PDF-fake", user_query="Summarize this book by chapter")
    assert "sampled pages across the whole book" in text
    assert "--- Page 1 ---" in text
    assert "--- Page 40 ---" in text
    selected = [line for line in text.splitlines() if line.startswith("--- Page ")]
    assert 4 <= len(selected) <= 6


def test_non_summary_query_caps_retrieved_pages(monkeypatch):
    monkeypatch.setenv("IGNITE_PDF_MAX_FULL_TEXT_CHARS", "80")
    monkeypatch.setenv("IGNITE_PDF_MAX_RETRIEVED_PAGES", "4")
    pages = [f"Page {i:03d} " + ("tax refund " if i == 30 else "lorem ipsum ") + ("x" * 40) for i in range(1, 41)]
    chat = _patch_pdf(monkeypatch, pages)
    text = chat._extract_text_from_pdf(b"%PDF-fake", user_query="What is the tax refund policy?")
    assert "most relevant sections" in text
    selected = [line for line in text.splitlines() if line.startswith("--- Page ")]
    assert len(selected) <= 4
    assert "--- Page 30 ---" in text


def test_invalid_pdf_env_falls_back(monkeypatch):
    monkeypatch.setenv("IGNITE_PDF_MAX_FULL_TEXT_CHARS", "not-a-number")
    monkeypatch.setenv("IGNITE_PDF_IMAGE_PAGE_SCAN_LIMIT", "")
    monkeypatch.setenv("IGNITE_PDF_NATIVE_MAX_BYTES", "abc")
    assert pdf_max_full_text_chars() == 400000
    assert pdf_image_page_scan_limit() == 8
    assert pdf_native_max_bytes() == 20 * 1024 * 1024
    assert _env_positive_int("IGNITE_PDF_MAX_RETRIEVED_PAGES", 12, 1) >= 1


def test_should_send_native_pdf_respects_byte_cap(monkeypatch):
    monkeypatch.setenv("IGNITE_PDF_NATIVE_MAX_BYTES", "4096")
    assert should_send_native_pdf(b"a" * 50)
    assert not should_send_native_pdf(b"a" * 5000)
    assert not should_send_native_pdf(b"")


def test_image_scan_stops_at_env_page_limit(monkeypatch):
    monkeypatch.setenv("IGNITE_PDF_IMAGE_PAGE_SCAN_LIMIT", "2")
    fake_img = SimpleNamespace(data=b"not-an-image", name="fig.jpg")
    images_by_index = {i: [fake_img] for i in range(10)}
    chat = _patch_pdf(monkeypatch, ["p"] * 10, images_by_index=images_by_index)
    extracted = chat._extract_images_from_pdf(b"%PDF-fake")
    assert len(extracted) <= 2


def test_even_sample_keeps_cover_and_last():
    pages = [(i, f"t{i}") for i in range(1, 21)]
    sampled = _sample_pages_evenly(pages, 6)
    assert 1 in sampled
    assert 2 in sampled
    assert 20 in sampled
    assert len(sampled) <= 6


def test_timeout_stack_ui_poll_outlives_llm_http():
    from backend.processors.base_processor import gemini_http_timeout_ms, llm_http_timeout_seconds
    from main.api import _document_poll_timeout_ms, _generation_poll_timeout_ms

    assert _document_poll_timeout_ms() >= gemini_http_timeout_ms()
    assert _document_poll_timeout_ms() >= llm_http_timeout_seconds() * 1000
    assert _generation_poll_timeout_ms() >= 60000


def test_processors_do_not_hardcode_five_minute_sdk_timeouts():
    import inspect
    import backend.processors.openai_processor as op
    import backend.processors.anthropic_processor as ap
    import backend.processors.grok_processor as grp
    import backend.processors.deepseek_processor as dp
    import backend.processors.perplexity_processor as pp
    import backend.processors.alibabacloud_processor as alp

    for mod in (op, ap, grp, dp, pp, alp):
        source = open(inspect.getfile(mod), encoding="utf-8").read()
        assert "timeout=300.0" not in source, f"{mod.__name__} MUST use llm_http_timeout_seconds()"
        assert "timeout': 120000" not in source and 'timeout": 120000' not in source, (
            f"{mod.__name__} MUST use gemini_http_timeout_ms()"
        )
