"""Bridge: Ignite Chat (contest snapshot) → Foundry Traces + Plan/Workflow brain.

When FOUNDRY_ORCHESTRATION_ENABLED=true, document/media turns start a GenAI-traced
Foundry flow (orchestrator Plan JSON → specialists) instead of only local LLM chat.

This module lives in the Agent-a-thon repo only. It does not modify IgniteChat or
IgniteAPI product repositories.
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DOC_ID_RE = re.compile(r"\bDOC-\d{3}\b", re.IGNORECASE)
_MEDIA_ID_RE = re.compile(r"\bMED-(?:IMG|AUD|VID)-\d{3}\b", re.IGNORECASE)
_EXTRACT_HINTS = (
    "extrae",
    "extract",
    "analiza",
    "analyze",
    "receta",
    "invoice",
    "factura",
    "pdf",
    "documento",
    "document",
)


def _repo_root() -> Path:
    # app/backend/integrations/this_file.py → repo root
    return Path(__file__).resolve().parents[3]


def _foundry_dir() -> Path:
    return _repo_root() / "foundry"


def _load_foundry_env() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    foundry_env = _foundry_dir() / ".env"
    app_env = _repo_root() / "app" / ".env"
    if foundry_env.is_file():
        load_dotenv(foundry_env, override=False)
    if app_env.is_file():
        load_dotenv(app_env, override=False)


def foundry_orchestration_enabled() -> bool:
    _load_foundry_env()
    flag = (os.getenv("FOUNDRY_ORCHESTRATION_ENABLED") or "").strip().lower()
    return flag in ("1", "true", "yes", "on")


def _truthy(name: str, default: str = "false") -> bool:
    return (os.getenv(name) or default).strip().lower() in ("1", "true", "yes", "on")


def should_handle_turn(text: str, files: list | None = None) -> bool:
    """Route document/media / extract intents to Foundry brain."""
    if _truthy("FOUNDRY_ORCHESTRATION_ALWAYS"):
        return True
    if files:
        return True
    blob = text or ""
    lower = blob.lower()
    if _DOC_ID_RE.search(blob) or _MEDIA_ID_RE.search(blob):
        return True
    return any(h in lower for h in _EXTRACT_HINTS)


def _ensure_foundry_on_path() -> Path:
    root = _foundry_dir()
    root_s = str(root)
    if root_s not in sys.path:
        sys.path.insert(0, root_s)
    return root


def _setup_genai_tracing() -> bool:
    """Enable Foundry / App Insights GenAI tracing. Safe no-op if deps/env missing."""
    if not _truthy("AZURE_EXPERIMENTAL_ENABLE_GENAI_TRACING", "true"):
        os.environ["AZURE_EXPERIMENTAL_ENABLE_GENAI_TRACING"] = "true"
    project = (os.getenv("PROJECT_CONNECTION_STRING") or "").strip()
    if not project:
        logger.info("foundry_orchestration: no PROJECT_CONNECTION_STRING — offline brain, no live traces")
        return False
    try:
        from azure.ai.projects.telemetry import AIProjectInstrumentor
        from azure.monitor.opentelemetry import configure_azure_monitor
    except ImportError as exc:
        logger.warning("foundry_orchestration: tracing packages missing (%s)", exc)
        return False
    try:
        AIProjectInstrumentor().instrument()
        conn = (os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING") or "").strip()
        if conn:
            configure_azure_monitor(connection_string=conn, enable_live_metrics=True)
            logger.info("foundry_orchestration: Azure Monitor exporter connected")
        else:
            logger.info("foundry_orchestration: GenAI instrumented (project-linked App Insights if configured)")
        return True
    except Exception as exc:
        logger.warning("foundry_orchestration: tracing setup failed (%s)", exc)
        return False


def _file_labels(files: list | None) -> str:
    if not files:
        return ""
    names = []
    for f in files:
        if not isinstance(f, dict):
            continue
        name = f.get("name") or f.get("filename") or ""
        if name:
            names.append(str(name))
    if not names:
        return ""
    return " Attachments: " + ", ".join(names[:8]) + "."


def _invoke_foundry_workflow_agent(user_text: str) -> dict[str, Any] | None:
    """Live path: call workflow agent so Traces show a multi-agent run in Foundry."""
    project = (os.getenv("PROJECT_CONNECTION_STRING") or "").strip()
    if not project:
        return None
    workflow_name = (os.getenv("IGNITE_WORKFLOW_AGENT") or "ignite-document-workflow").strip()
    try:
        from azure.ai.projects import AIProjectClient
        from azure.identity import DefaultAzureCredential
    except ImportError:
        return None
    client = AIProjectClient(endpoint=project, credential=DefaultAzureCredential())
    try:
        openai_client = client.get_openai_client(allow_preview=True)
        conversation = openai_client.conversations.create()
        resp = openai_client.responses.create(
            conversation=conversation.id,
            extra_body={"agent_reference": {"name": workflow_name, "type": "agent_reference"}},
            input=user_text,
            background=False,
        )
        text = (resp.output_text or "").strip()
        openai_client.conversations.delete(conversation_id=conversation.id)
        if not text:
            return None
        return {
            "source": "foundry_workflow",
            "workflow": workflow_name,
            "message": text,
            "plan": None,
            "trace_tags": ["source:foundry_workflow", f"workflow:{workflow_name}"],
        }
    except Exception as exc:
        logger.warning("foundry_orchestration: workflow invoke failed (%s) — falling back to brain", exc)
        return None
    finally:
        client.close()


def _run_brain(user_text: str, *, lang: str) -> dict[str, Any]:
    _ensure_foundry_on_path()
    from brain import run_turn  # type: ignore  # noqa: WPS433 — foundry/ on sys.path

    live = _truthy("FOUNDRY_BRAIN_LIVE")
    result = run_turn(user_text, lang=lang, use_foundry=live)
    return {
        "source": "foundry_brain_live" if live else "foundry_brain_offline",
        "workflow": None,
        "message": result.get("final_user_message") or "",
        "plan": result.get("plan"),
        "trace_tags": list(result.get("trace_tags") or []),
        "tool_results": result.get("tool_results"),
    }


def run_foundry_turn(
    text: str,
    files: list | None = None,
    *,
    language: str | None = None,
) -> dict[str, Any]:
    """Start tracing (if configured) and run Foundry workflow or Plan brain."""
    _load_foundry_env()
    lang = "es" if (language or "es").lower().startswith("es") else "en"
    prompt = (text or "").strip() + _file_labels(files)
    tracing_on = _setup_genai_tracing()

    prefer_workflow = _truthy("FOUNDRY_WORKFLOW_LIVE")
    payload: dict[str, Any] | None = None
    if prefer_workflow:
        payload = _invoke_foundry_workflow_agent(prompt)

    if payload is None:
        payload = _run_brain(prompt, lang=lang)

    tags = list(payload.get("trace_tags") or [])
    if tracing_on and "trace:genai" not in tags:
        tags.append("trace:genai")
    payload["trace_tags"] = tags
    payload["tracing_enabled"] = tracing_on
    return payload


def maybe_run_foundry_turn(
    text: str,
    files: list | None = None,
    *,
    language: str | None = None,
) -> dict[str, Any] | None:
    """Return a chat-shaped result dict, or None to continue normal Ignite LLM path."""
    if not foundry_orchestration_enabled():
        return None
    if not should_handle_turn(text or "", files):
        return None
    try:
        raw = run_foundry_turn(text, files, language=language)
    except Exception as exc:
        logger.exception("foundry_orchestration: turn failed")
        return {
            "status": "error",
            "message": f"Foundry orchestration failed: {exc}",
            "foundry": True,
        }

    message = (raw.get("message") or "").strip()
    plan = raw.get("plan")
    if plan and not message:
        message = json.dumps(plan, ensure_ascii=False)
    if plan:
        # Compact footer for demo / judges (no secrets)
        footer = (
            f"\n\n— Foundry Plan: intent={plan.get('intent')} "
            f"modality={plan.get('modality')} tags={','.join(raw.get('trace_tags') or [])}"
        )
        if footer not in message:
            message = message + footer

    return {
        "status": "success",
        "message": message,
        "foundry": True,
        "foundry_source": raw.get("source"),
        "foundry_plan": plan,
        "foundry_trace_tags": raw.get("trace_tags"),
        "foundry_tracing_enabled": raw.get("tracing_enabled"),
    }
