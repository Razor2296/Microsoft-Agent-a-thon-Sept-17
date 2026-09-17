"""
app/tests/unit/test_ignite_extraction_integration.py
Unit tests for End-to-End Ignite API extraction integration:
- System prompt instruction injection
- IGNITE_EXTRACT tag parsing
- RAG vector indexing with model reasoning blending
"""
import base64
import os
import re
import pytest

from backend.processors.base_processor import BaseChat
from backend.tools.rag_engine import LocalRAGEngine
from backend.integrations.ignite_api_client import IgniteAPIClient
from backend.integrations.ignite_rag_transformer import extraction_to_rag_text, extraction_to_rag_chunks


def test_base_processor_injects_extraction_guidelines():
    processor = BaseChat()
    processor.inject_media_guidelines()

    for attr in ['system_instruction', 'system_instruction_gemini', 'system_instruction_openai']:
        if hasattr(processor, attr):
            instr = getattr(processor, attr) or ""
            assert "## Special Structured Extraction Commands" in instr
            assert "[IGNITE_EXTRACT:" in instr
            assert "Medical_Prescription" in instr
            assert "Invoice_Standard" in instr


def test_ignite_extract_rag_ingestion_with_reasoning(tmp_path):
    db_file = str(tmp_path / "test_rag.db")
    rag = LocalRAGEngine(db_path=db_file)

    sample_extraction = {
        "template_used": "Medical_Prescription",
        "is_multi_row": False,
        "extracted_info": {
            "row_1": {
                "Nombre_Paciente": {
                    "code": "001",
                    "value": "Juan Escutia",
                    "confidence": 95,
                    "reasoning": "Nombre claro indicado en texto junto a 'paciente'.",
                    "mandatory": True
                },
                "Medicamentos": {
                    "code": "006",
                    "value": "Paracetamol 500 mg, Claritromicina 500 mg",
                    "confidence": 90,
                    "reasoning": "Medicamentos completos prescritos en la receta.",
                    "mandatory": True
                }
            }
        },
        "metadata": {
            "file_name": "receta.mp3",
            "llm_provider": "azure_openai",
            "model_used": "gpt-4.1-mini",
            "duration_seconds": 9.67,
            "tokens_consumed": {"total_tokens": 2198}
        }
    }

    chunks = extraction_to_rag_chunks(sample_extraction, "receta.mp3", session_id="test_session")
    assert len(chunks) == 1
    doc_id, text_chunk, meta = chunks[0]

    # Index into RAG
    success = rag.index_document(doc_id, text_chunk, meta)
    assert success is True

    # Search RAG
    results = rag.search_relevant_context("¿Qué medicamentos tiene la receta de Juan Escutia?", top_k=1)
    assert len(results) >= 1
    matched = results[0]
    assert "Juan Escutia" in matched.text
    assert "Paracetamol 500 mg" in matched.text
    assert "Razonamiento (gpt-4.1-mini):" in matched.text


def test_tag_regex_parsing():
    reply = "Voy a procesar la receta adjunta.\n\n[IGNITE_EXTRACT: receta.mp3|Medical_Prescription]"
    extract_match = re.search(r'\[IGNITE_EXTRACT:\s*(.*?)\|(.*?)\]', reply, re.IGNORECASE | re.DOTALL)

    assert extract_match is not None
    assert extract_match.group(1).strip() == "receta.mp3"
    assert extract_match.group(2).strip() == "Medical_Prescription"

    cleaned = re.sub(r'\[IGNITE_EXTRACT:\s*.*?\]', '', reply, flags=re.IGNORECASE | re.DOTALL).strip()
    assert "[IGNITE_EXTRACT:" not in cleaned
    assert "Voy a procesar la receta adjunta." in cleaned


def test_attachment_filename_matching():
    processed_files = [
        {"name": "receta_medica_2026.mp3", "base64": "SGVsbG8="},
        {"name": "contrato_final.pdf", "base64": "V29ybGQ="}
    ]
    target_file = "receta_medica_2026.mp3"

    matched = None
    for f in processed_files:
        fname = f.get("name") or ""
        if fname.lower() == target_file.lower() or target_file.lower() in fname.lower():
            matched = f
            break

    assert matched is not None
    assert matched["name"] == "receta_medica_2026.mp3"
    assert base64.b64decode(matched["base64"]) == b"Hello"

