"""External integrations, S2S client, and document extractors."""

# Import document request functions
from backend.integrations.document_request import (
    CRITICAL_DOCUMENT_ANALYSIS_RULE,
    DOC_GUIDELINES_MARKER,
    DOCUMENT_GENERATION_GUIDELINES,
    detect_document_request,
    is_document_analysis_request,
    is_document_generation_request,
)

# Import Ignite API client
from backend.integrations.ignite_api_client import IgniteAPIClient

# Import Ignite RAG transformer
from backend.integrations.ignite_rag_transformer import (
    extraction_to_rag_chunks,
    extraction_to_rag_text,
)

# Import office extract functions
from backend.integrations.office_extract import (
    extract_all_office_files,
    extract_docx_text,
    extract_pptx_text,
    extract_text_from_docx,
    extract_text_from_pptx,
    extract_text_from_xlsx,
    extract_xlsx_text,
)

__all__ = [
    "IgniteAPIClient",
    "extraction_to_rag_chunks",
    "extraction_to_rag_text",
    "CRITICAL_DOCUMENT_ANALYSIS_RULE",
    "DOCUMENT_GENERATION_GUIDELINES",
    "DOC_GUIDELINES_MARKER",
    "detect_document_request",
    "is_document_analysis_request",
    "is_document_generation_request",
    "extract_all_office_files",
    "extract_docx_text",
    "extract_pptx_text",
    "extract_xlsx_text",
    "extract_text_from_docx",
    "extract_text_from_xlsx",
    "extract_text_from_pptx",
]
