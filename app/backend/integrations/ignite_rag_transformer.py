"""
app/backend/ignite_rag_transformer.py
Skill 3.2 — Transforms Ignite API JSON Extraction Responses into Semantic RAG Memory Text.

Blends extracted property values with the model's reasoning (reasoning),
confidence scores, mandatory flags, and provider/model metadata so that vector
embeddings and recalled memories store complete contextual justifications.
"""
from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Tuple

# Function to transform extraction response to rag text
def extraction_to_rag_text(response: Dict[str, Any], filename: str) -> str:
    """
    Transform an ExtractionResponse dictionary into a rich Markdown string
    combining property values, model reasoning, confidence scores, and provider metadata.

    Args:
        response: ExtractionResponse dictionary returned by Ignite API.
        filename: Original file name.

    Returns:
        Structured Markdown text suitable for vector embedding & human reading.
    """
    if not response or not isinstance(response, dict):
        return f"📄 EXTRACCIÓN VACÍA: {filename}"

    template_used = response.get("template_used", "Desconocido")
    is_multi_row = response.get("is_multi_row", False)
    extracted_info = response.get("extracted_info", {})
    metadata = response.get("metadata", {}) or {}

    provider = metadata.get("llm_provider", "N/A")
    model = metadata.get("model_used", "N/A")
    duration = metadata.get("duration_seconds", 0.0)
    tokens = metadata.get("tokens_consumed", {}) or {}
    total_tokens = tokens.get("total_tokens", 0)

    lines = [
        f"📄 EXTRACCIÓN ESTRUCTURADA: {filename}",
        f"• Plantilla: {template_used}",
        f"• Proveedor / Modelo IA: {provider} ({model})",
        f"• Tiempo de Inferencia: {duration:.2f}s | Tokens: {total_tokens}",
        "",
        "DATOS EXTRAÍDOS Y RAZONAMIENTO DEL MODELO:",
    ]

    if not extracted_info:
        lines.append("- (No se encontraron propiedades extraídas)")
        return "\n".join(lines)

    missing_mandatory = []

    for row_key, row_data in extracted_info.items():
        if not isinstance(row_data, dict):
            continue

        if is_multi_row:
            lines.append(f"\n--- {row_key.upper()} ---")

        for prop_name, prop_data in row_data.items():
            if not isinstance(prop_data, dict):
                continue

            val = prop_data.get("value", "N/A")
            confidence = prop_data.get("confidence", 0)
            reasoning = prop_data.get("reasoning", "")
            mandatory = prop_data.get("mandatory", False)
            code = prop_data.get("code", "")

            # Format status
            if val == "NO_ENCONTRADO" or confidence == 0:
                if mandatory:
                    missing_mandatory.append(f"{prop_name} (Código: {code})")
                    lines.append(f"- ⚠️ {prop_name}: NO ENCONTRADO [Mandatorio | Confianza: 0%]")
                else:
                    lines.append(f"- ⚪ {prop_name}: No especificado [Opcional]")
                if reasoning:
                    lines.append(f"  ↳ Razonamiento ({model}): {reasoning}")
            else:
                req_str = "Requerido" if mandatory else "Opcional"
                lines.append(f"- ✅ {prop_name}: \"{val}\" [Confianza: {confidence}% | {req_str}]")
                if reasoning:
                    lines.append(f"  ↳ Razonamiento ({model}): {reasoning}")

    if missing_mandatory:
        lines.append("\n⚠️ CAMPOS REQUERIDOS FALTANTES:")
        for item in missing_mandatory:
            lines.append(f"  • {item}")

    return "\n".join(lines)

# Function to transform extraction response to rag chunks
def extraction_to_rag_chunks(
    response: Dict[str, Any],
    filename: str,
    session_id: str = "default",
) -> List[Tuple[str, str, Dict[str, Any]]]:
    """
    Decompose an ExtractionResponse into indexable RAG tuples:
    [(doc_id, text_content, metadata_dict), ...]

    For multi-row tables (e.g. Invoice_Standard), produces one chunk per row
    so each item/row is independently searchable in vector memory.
    """
    if not response or not isinstance(response, dict):
        return []

    template_used = response.get("template_used", "Desconocido")
    is_multi_row = response.get("is_multi_row", False)
    extracted_info = response.get("extracted_info", {})
    metadata = response.get("metadata", {}) or {}

    provider = metadata.get("llm_provider", "N/A")
    model = metadata.get("model_used", "N/A")
    timestamp_ms = int(time.time() * 1000)

    base_metadata = {
        "source": "ignite_api",
        "filename": filename,
        "template_used": template_used,
        "llm_provider": provider,
        "model_used": model,
        "session_id": session_id,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }

    if not is_multi_row or len(extracted_info) <= 1:
        # Single chunk for standard single-row extractions
        doc_id = f"ignite_extract_{filename}_{timestamp_ms}"
        full_text = extraction_to_rag_text(response, filename)
        return [(doc_id, full_text, base_metadata)]

    # Multi-row chunking: 1 document chunk per table row for fine-grained semantic search
    chunks = []
    for row_key, row_data in extracted_info.items():
        if not isinstance(row_data, dict):
            continue

        doc_id = f"ignite_extract_{filename}_{row_key}_{timestamp_ms}"
        row_lines = [
            f"📄 EXTRACCIÓN [{row_key.upper()}]: {filename}",
            f"• Plantilla: {template_used} | Modelo: {provider} ({model})",
            "",
            f"CAMPOS DE {row_key.upper()} CON RAZONAMIENTO DEL MODELO:",
        ]

        for prop_name, prop_data in row_data.items():
            if not isinstance(prop_data, dict):
                continue

            val = prop_data.get("value", "N/A")
            confidence = prop_data.get("confidence", 0)
            reasoning = prop_data.get("reasoning", "")
            mandatory = prop_data.get("mandatory", False)

            if val == "NO_ENCONTRADO" or confidence == 0:
                req_icon = "⚠️" if mandatory else "⚪"
                row_lines.append(f"- {req_icon} {prop_name}: NO ENCONTRADO [Confianza: 0%]")
            else:
                row_lines.append(f"- ✅ {prop_name}: \"{val}\" [Confianza: {confidence}%]")

            if reasoning:
                row_lines.append(f"  ↳ Razonamiento ({model}): {reasoning}")

        chunk_text = "\n".join(row_lines)
        row_meta = dict(base_metadata)
        row_meta["row_key"] = row_key
        chunks.append((doc_id, chunk_text, row_meta))

    return chunks
