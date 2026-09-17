"""Unit tests for document analysis vs generation intent detection."""

from backend.integrations.document_request import (
    CRITICAL_DOCUMENT_ANALYSIS_RULE,
    DOC_GUIDELINES_MARKER,
    DOCUMENT_GENERATION_GUIDELINES,
    detect_document_request,
)


def test_analiza_este_ppt_with_attachment_is_not_generation():
    assert detect_document_request("Analiza este ppt", has_attachments=True) is None


def test_analiza_este_pptx_without_attachment_is_not_generation():
    assert detect_document_request("Analiza este pptx", has_attachments=False) is None


def test_resume_excel_attachment_is_not_generation():
    assert detect_document_request("Resume este excel", has_attachments=True) is None


def test_explain_word_doc_is_not_generation():
    assert detect_document_request("Explain this word document", has_attachments=True) is None


def test_bare_ppt_mention_with_attachment_is_not_generation():
    assert detect_document_request("este ppt", has_attachments=True) is None


def test_create_ppt_without_attachment_is_generation():
    assert detect_document_request("genera un ppt sobre IA", has_attachments=False) == "pptx"


def test_create_excel_is_generation():
    assert detect_document_request("crea un excel con estos datos", has_attachments=False) == "xlsx"


def test_create_word_is_generation():
    assert detect_document_request("hazme un documento word", has_attachments=False) == "docx"


def test_create_ppt_summary_from_attachment_is_generation():
    assert (
        detect_document_request(
            "genera un resumen en ppt de este archivo",
            has_attachments=True,
        )
        == "pptx"
    )


def test_empty_text_returns_none():
    assert detect_document_request("", has_attachments=True) is None
    assert detect_document_request(None, has_attachments=False) is None


def test_guidelines_distinguish_analysis_from_generation():
    assert DOC_GUIDELINES_MARKER in DOCUMENT_GENERATION_GUIDELINES
    assert "Analysis vs Generation" in DOCUMENT_GENERATION_GUIDELINES
    assert "Analiza este ppt" in DOCUMENT_GENERATION_GUIDELINES


def test_critical_document_rule_blocks_auto_export_bias():
    assert "CRITICAL DOCUMENT RULE" in CRITICAL_DOCUMENT_ANALYSIS_RULE
    assert "DO NOT create or export a new" in CRITICAL_DOCUMENT_ANALYSIS_RULE
    assert "analyze" in CRITICAL_DOCUMENT_ANALYSIS_RULE.lower()
