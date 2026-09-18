"""Foundry-as-brain: orchestrator Plan JSON drives every downstream step.

Offline path (CI / no Azure): heuristic_plan() + execute_plan().
Live path: ask Foundry ignite-orchestrator-agent for Plan JSON, then execute.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from media_tools import describe_media, load_media
from plan_schema import PLAN_JSON_SCHEMA_HINT, empty_plan, parse_plan, validate_plan
from tools import inspect_document, load_documents

FOUNDRY_DIR = Path(__file__).resolve().parent
load_dotenv(FOUNDRY_DIR / ".env")

PROJECT_CONNECTION_STRING = (os.getenv("PROJECT_CONNECTION_STRING") or "").strip()
ORCHESTRATOR_AGENT = os.getenv("IGNITE_ORCHESTRATOR_AGENT", "ignite-orchestrator-agent").strip()
DOCUMENT_AGENT = os.getenv("IGNITE_DOCUMENT_AGENT", "ignite-document-agent").strip()
MEDIA_AGENT = os.getenv("IGNITE_MEDIA_AGENT", "ignite-image-agent").strip()

_DOC_ID_RE = re.compile(r"\bDOC-\d{3}\b", re.IGNORECASE)
_MEDIA_ID_RE = re.compile(r"\bMED-(?:IMG|AUD|VID)-\d{3}\b", re.IGNORECASE)


def detect_modality(user_text: str) -> str:
    t = (user_text or "").lower()
    if _MEDIA_ID_RE.search(user_text or "") or any(
        w in t for w in ("video", "screen recording", "grabación", "mp4")
    ):
        if "audio" in t or "voz" in t or "voice" in t or "med-aud" in t:
            return "audio"
        if "image" in t or "foto" in t or "imagen" in t or "photo" in t or "med-img" in t:
            return "image"
        if "video" in t or "med-vid" in t or "grabación" in t:
            return "video"
    if _DOC_ID_RE.search(user_text or "") or any(
        w in t for w in ("pdf", "receta", "invoice", "factura", "documento", "extract", "extrae", "analiza")
    ):
        return "document"
    if any(w in t for w in ("audio", "voz", "voice note", "nota de voz")):
        return "audio"
    if any(w in t for w in ("imagen", "foto", "photo", "image", "screenshot")):
        return "image"
    if any(w in t for w in ("video", "mp4", "grabación")):
        return "video"
    return "text"


def heuristic_plan(user_text: str) -> dict[str, Any]:
    """Deterministic brain used offline and as fallback when Foundry JSON is invalid."""
    text = user_text or ""
    lower = text.lower()
    modality = detect_modality(text)
    doc_match = _DOC_ID_RE.search(text)
    media_match = _MEDIA_ID_RE.search(text)
    doc_id = doc_match.group(0).upper() if doc_match else None
    media_id = media_match.group(0).upper() if media_match else None

    if modality in ("image", "audio", "video") or media_id:
        if not media_id:
            defaults = {"image": "MED-IMG-001", "audio": "MED-AUD-001", "video": "MED-VID-001"}
            media_id = defaults.get(modality, "MED-IMG-001")
            modality = next(
                (m["modality"] for m in load_media() if m["media_id"] == media_id),
                modality,
            )
        return validate_plan(
            empty_plan(
                modality=modality if modality in ("image", "audio", "video") else "image",
                intent="MEDIA_DESCRIBE",
                media_id=media_id,
                doc_id=None,
                steps=[
                    {
                        "action": "describe_media",
                        "agent": MEDIA_AGENT,
                        "args": {"media_id": media_id},
                    },
                    {"action": "synthesize", "agent": ORCHESTRATOR_AGENT, "args": {}},
                ],
                trace_tags=[f"modality:{modality}", "intent:MEDIA_DESCRIBE"],
            )
        )

    if any(w in lower for w in ("word", "excel", "powerpoint", "office", "exporta", "export")):
        return validate_plan(
            empty_plan(
                modality="document" if doc_id else "text",
                intent="EXPORT",
                doc_id=doc_id,
                steps=[{"action": "export_office", "agent": ORCHESTRATOR_AGENT, "args": {"doc_id": doc_id}}],
                user_message_es=(
                    f"Prepararía un Office a partir de {doc_id or 'los hechos extraídos'} "
                    "(en el producto Ignite Chat genera el archivo; aquí solo planificamos)."
                ),
                user_message_en=(
                    f"Would prepare an Office file from {doc_id or 'extracted facts'} "
                    "(Ignite Chat generates bytes; Foundry only plans)."
                ),
                trace_tags=["modality:document", "intent:EXPORT"],
            )
        )

    if doc_id or any(w in lower for w in ("extrae", "extract", "analiza", "analyze", "receta", "invoice", "factura")):
        if not doc_id:
            doc_id = "DOC-001"
        return validate_plan(
            empty_plan(
                modality="document",
                intent="EXTRACT",
                doc_id=doc_id,
                steps=[
                    {
                        "action": "inspect_document",
                        "agent": DOCUMENT_AGENT,
                        "args": {"doc_id": doc_id},
                    },
                    {"action": "synthesize", "agent": ORCHESTRATOR_AGENT, "args": {}},
                ],
                trace_tags=["modality:document", "intent:EXTRACT"],
            )
        )

    if doc_id and any(w in lower for w in ("cuánto", "cuanto", "what", "quién", "quien", "diagnóstico", "diagnostico")):
        return validate_plan(
            empty_plan(
                modality="document",
                intent="ANSWER",
                doc_id=doc_id,
                steps=[
                    {
                        "action": "inspect_document",
                        "agent": DOCUMENT_AGENT,
                        "args": {"doc_id": doc_id},
                    },
                    {"action": "synthesize", "agent": ORCHESTRATOR_AGENT, "args": {}},
                ],
                trace_tags=["modality:document", "intent:ANSWER"],
            )
        )

    return validate_plan(
        empty_plan(
            user_message_es=(
                "¿Qué documento o media quieres procesar? "
                f"IDs documento: {[d['doc_id'] for d in load_documents()]}. "
                f"IDs media: {[m['media_id'] for m in load_media()]}."
            ),
            user_message_en=(
                "Which document or media should I process? "
                f"Doc ids: {[d['doc_id'] for d in load_documents()]}. "
                f"Media ids: {[m['media_id'] for m in load_media()]}."
            ),
        )
    )


def execute_plan(plan: dict[str, Any], *, lang: str = "es") -> dict[str, Any]:
    """Run plan steps with local tools. Returns business result for the user."""
    plan = validate_plan(plan)
    tool_results: list[dict[str, Any]] = []
    final_es = plan.get("user_message_es") or ""
    final_en = plan.get("user_message_en") or ""

    for step in plan["steps"]:
        action = step["action"]
        args = step.get("args") or {}
        if action == "inspect_document":
            doc_id = args.get("doc_id") or plan.get("doc_id") or "DOC-001"
            raw = inspect_document(str(doc_id))
            payload = json.loads(raw)
            tool_results.append({"action": action, "doc_id": doc_id, "result": payload})
            if "error" not in payload:
                fields = payload.get("fields") or {}
                final_es = (
                    f"Extraje **{doc_id}** ({payload.get('kind', 'document')}). "
                    f"Campos: {json.dumps(fields, ensure_ascii=False)}."
                )
                final_en = (
                    f"Extracted **{doc_id}** ({payload.get('kind', 'document')}). "
                    f"Fields: {json.dumps(fields, ensure_ascii=False)}."
                )
            else:
                final_es = f"No pude extraer {doc_id}: {payload.get('error')}"
                final_en = f"Could not extract {doc_id}: {payload.get('error')}"

        elif action == "describe_media":
            media_id = args.get("media_id") or plan.get("media_id") or "MED-IMG-001"
            raw = describe_media(str(media_id))
            payload = json.loads(raw)
            tool_results.append({"action": action, "media_id": media_id, "result": payload})
            if "error" not in payload:
                final_es = (
                    f"Media **{media_id}** ({payload.get('modality')}): {payload.get('caption')}"
                )
                final_en = final_es
                suggested = (payload.get("fields") or {}).get("suggested_doc_id")
                if suggested:
                    final_es += f" Sugerido enlazar con {suggested}."
                    final_en += f" Suggested link: {suggested}."
            else:
                final_es = f"Media desconocida: {payload.get('error')}"
                final_en = final_es

        elif action == "export_office":
            doc_id = args.get("doc_id") or plan.get("doc_id")
            final_es = (
                f"Plan EXPORT listo para {doc_id or 'hechos en sesión'}. "
                "Ignite Chat generaría .docx/.xlsx/.pptx; Foundry no emite bytes."
            )
            final_en = (
                f"EXPORT plan ready for {doc_id or 'session facts'}. "
                "Ignite Chat would emit Office bytes; Foundry only plans."
            )
            tool_results.append({"action": action, "status": "planned"})

        elif action == "clarify":
            if not final_es:
                final_es = plan.get("user_message_es") or "¿Qué archivo o media procesamos?"
            if not final_en:
                final_en = plan.get("user_message_en") or "Which file or media should we process?"
            tool_results.append({"action": action, "status": "asked"})

        elif action == "synthesize":
            tool_results.append({"action": action, "status": "done"})

    reply = final_es if lang.startswith("es") else final_en
    return {
        "plan": plan,
        "tool_results": tool_results,
        "final_user_message": reply,
        "final_user_message_es": final_es,
        "final_user_message_en": final_en,
        "trace_tags": plan.get("trace_tags") or [],
    }


def ask_foundry_plan(user_text: str) -> dict[str, Any]:
    """Call Foundry orchestrator agent; fall back to heuristic_plan on any failure."""
    if not PROJECT_CONNECTION_STRING:
        return heuristic_plan(user_text)

    try:
        from azure.ai.projects import AIProjectClient
        from azure.identity import DefaultAzureCredential
    except ImportError:
        return heuristic_plan(user_text)

    prompt = (
        "You are the Ignite orchestration brain inside Microsoft Foundry.\n"
        f"{PLAN_JSON_SCHEMA_HINT}\n\n"
        f"Known documents: {[d['doc_id'] for d in load_documents()]}\n"
        f"Known media: {[m['media_id'] for m in load_media()]}\n\n"
        f"User turn:\n{user_text}\n"
    )
    client = AIProjectClient(
        endpoint=PROJECT_CONNECTION_STRING,
        credential=DefaultAzureCredential(),
    )
    try:
        openai_client = client.get_openai_client()
        agent_ref = {"agent_reference": {"name": ORCHESTRATOR_AGENT, "type": "agent_reference"}}
        conversation = openai_client.conversations.create()
        response = openai_client.responses.create(
            input=prompt,
            conversation=conversation.id,
            extra_body=agent_ref,
        )
        text = response.output_text or ""
        openai_client.conversations.delete(conversation_id=conversation.id)
        try:
            return parse_plan(text)
        except ValueError:
            print("Orchestrator JSON invalid — using heuristic_plan.", file=sys.stderr)
            return heuristic_plan(user_text)
    except Exception as exc:
        print(f"Foundry plan call failed ({exc}) — heuristic_plan.", file=sys.stderr)
        return heuristic_plan(user_text)
    finally:
        client.close()


def run_turn(user_text: str, *, lang: str = "es", use_foundry: bool | None = None) -> dict[str, Any]:
    """One end-to-end turn: Plan (brain) → tools → business reply."""
    if use_foundry is None:
        use_foundry = bool(PROJECT_CONNECTION_STRING) and (
            (os.getenv("FOUNDRY_BRAIN_LIVE") or "").strip().lower() in ("1", "true", "yes", "on")
        )
    plan = ask_foundry_plan(user_text) if use_foundry else heuristic_plan(user_text)
    return execute_plan(plan, lang=lang)


def main() -> int:
    samples = [
        "Extrae la receta DOC-001 y respóndeme en español.",
        "Describe la foto MED-IMG-001.",
        "Resume el audio MED-AUD-001.",
        "Exporta DOC-002 a Excel.",
        "Hola",
    ]
    print("=== Foundry brain (offline heuristic) ===\n")
    for sample in samples:
        result = run_turn(sample, lang="es", use_foundry=False)
        print(f"USER: {sample}")
        print(f"PLAN: {json.dumps(result['plan'], ensure_ascii=False)}")
        print(f"REPLY: {result['final_user_message']}")
        print(f"TAGS: {result['trace_tags']}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
