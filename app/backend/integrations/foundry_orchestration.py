"""Ignite Chat → Foundry Traces → workflow orchestration (Gemini).

When FOUNDRY_ORCHESTRATION_ENABLED=true:
  1. Arm GenAI Tracing (Foundry / App Insights)
  2. Ensure agents + workflow exist (MODEL_DEPLOYMENT_NAME, default gemini-2.5-flash)
  3. Invoke the Foundry WORKFLOW under those traces (primary path)
  4. Fallback per-agent pipeline if workflow returns empty
  5. Mirror Plan JSON locally for the chat bubble / offline fallback

Hooks:
  - Chat turns (document/media/extract) via maybe_run_foundry_turn
  - Chat → Ignite API extract via notify_foundry_after_extract

Agent-a-thon repo only — does not modify IgniteChat / IgniteAPI remotes.
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
    return Path(__file__).resolve().parents[3]


def _foundry_dir() -> Path:
    return _repo_root() / "foundry"


def _load_foundry_env() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    for path in (_foundry_dir() / ".env", _repo_root() / "app" / ".env"):
        if path.is_file():
            load_dotenv(path, override=False)


def _truthy(name: str, default: str = "false") -> bool:
    return (os.getenv(name) or default).strip().lower() in ("1", "true", "yes", "on")


def foundry_orchestration_enabled() -> bool:
    _load_foundry_env()
    return _truthy("FOUNDRY_ORCHESTRATION_ENABLED")


def should_handle_turn(text: str, files: list | None = None) -> bool:
    if _truthy("FOUNDRY_ORCHESTRATION_ALWAYS"):
        return True
    if files:
        return True
    blob = text or ""
    lower = blob.lower()
    if _DOC_ID_RE.search(blob) or _MEDIA_ID_RE.search(blob):
        return True
    return any(h in lower for h in _EXTRACT_HINTS)


def _ensure_foundry_on_path() -> None:
    root = str(_foundry_dir())
    if root not in sys.path:
        sys.path.insert(0, root)


def _file_labels(files: list | None) -> str:
    if not files:
        return ""
    names = []
    for f in files:
        if isinstance(f, dict):
            name = f.get("name") or f.get("filename") or ""
            if name:
                names.append(str(name))
    return (" Attachments: " + ", ".join(names[:8]) + ".") if names else ""


def _format_chat_message(raw: dict[str, Any]) -> str:
    message = (raw.get("message") or "").strip()
    plan = raw.get("plan") or {}
    tags = raw.get("trace_tags") or []
    parts: list[str] = []
    err = (raw.get("error") or "").strip()
    if err:
        parts.append(f"⚠ {err}")
    if message:
        parts.append(message)
    if plan:
        steps = ", ".join(
            f"{s.get('action')}@{s.get('agent')}" for s in (plan.get("steps") or [])
        )
        parts.append(
            "\n— Foundry orchestration"
            f"\n  model={raw.get('model') or 'gemini'}"
            f"\n  intent={plan.get('intent')} modality={plan.get('modality')}"
            f"\n  steps=[{steps}]"
            f"\n  tags={', '.join(tags)}"
            f"\n  tracing={'on' if raw.get('tracing_enabled') else 'off'}"
            f"  appinsights={'on' if raw.get('app_insights_enabled') else 'off'}"
            f"  agents={'ready' if raw.get('agents_ensured') else 'offline'}"
            f"  live={'yes' if raw.get('live') else 'no'}"
            f"  workflow={raw.get('workflow') or '-'}"
            f"  trigger={raw.get('trigger')}"
        )
    elif err and not message:
        parts.append(
            "\n— Foundry orchestration failed before Plan JSON. "
            "Fix .env / az login, then retry Extrae DOC-001."
        )
    return "\n".join(parts).strip()


def run_foundry_turn(
    text: str,
    files: list | None = None,
    *,
    language: str | None = None,
    trigger: str = "chat",
) -> dict[str, Any]:
    """Traces → ensure agents/workflow (Gemini) → invoke workflow (Chat path)."""
    _load_foundry_env()
    _ensure_foundry_on_path()
    from runtime import run_traced_orchestration  # type: ignore

    lang = "es" if (language or "es").lower().startswith("es") else "en"
    prompt = (text or "").strip() + _file_labels(files)
    return run_traced_orchestration(prompt, lang=lang, trigger=trigger)


def maybe_run_foundry_turn(
    text: str,
    files: list | None = None,
    *,
    language: str | None = None,
) -> dict[str, Any] | None:
    """Chat hook: return chat-shaped dict or None to keep normal LLM path."""
    if not foundry_orchestration_enabled():
        return None
    if not should_handle_turn(text or "", files):
        return None
    try:
        raw = run_foundry_turn(text, files, language=language, trigger="chat")
    except Exception as exc:
        logger.exception("foundry_orchestration: chat turn failed")
        return {
            "status": "error",
            "message": f"⚠ Foundry orchestration failed: {exc}",
            "foundry": True,
        }
    live = bool(raw.get("live"))
    hard_fail = bool(raw.get("error")) and not live
    return {
        "status": "error" if hard_fail else "success",
        "message": _format_chat_message(raw),
        "foundry": True,
        "foundry_source": raw.get("source"),
        "foundry_plan": raw.get("plan"),
        "foundry_trace_tags": raw.get("trace_tags"),
        "foundry_tracing_enabled": raw.get("tracing_enabled"),
        "foundry_agents_ensured": raw.get("agents_ensured"),
        "foundry_workflow": raw.get("workflow"),
        "foundry_live": live,
        "foundry_model": raw.get("model"),
        "foundry_error": raw.get("error"),
        "foundry_app_insights": raw.get("app_insights_enabled"),
    }


def notify_foundry_after_extract(
    *,
    filename: str,
    template_name: str,
    extraction: Any = None,
    language: str | None = None,
    user_text: str | None = None,
) -> dict[str, Any] | None:
    """Chat → Ignite API extract hook: Traces ON → workflow (Gemini)."""
    if not foundry_orchestration_enabled():
        return None
    summary = {
        "event": "ignite_api_extract",
        "filename": filename,
        "template": template_name,
        "keys": list(extraction.keys())[:20] if isinstance(extraction, dict) else [],
    }
    prompt = (
        (user_text or f"Extrae y orquesta el archivo {filename} con plantilla {template_name}.")
        + "\nIgnite API extract completed. Facts:\n"
        + json.dumps(summary, ensure_ascii=False)
    )
    try:
        raw = run_foundry_turn(prompt, language=language, trigger="chat_api_extract")
    except Exception as exc:
        logger.warning("foundry_orchestration: post-extract orchestration failed (%s)", exc)
        return {
            "status": "error",
            "message": f"⚠ Foundry post-extract failed: {exc}",
            "foundry": True,
            "foundry_trigger": "chat_api_extract",
        }
    live = bool(raw.get("live"))
    hard_fail = bool(raw.get("error")) and not live
    return {
        "status": "error" if hard_fail else "success",
        "message": _format_chat_message(raw),
        "foundry": True,
        "foundry_source": raw.get("source"),
        "foundry_plan": raw.get("plan"),
        "foundry_trace_tags": raw.get("trace_tags"),
        "foundry_tracing_enabled": raw.get("tracing_enabled"),
        "foundry_trigger": "chat_api_extract",
        "foundry_live": live,
        "foundry_model": raw.get("model"),
        "foundry_error": raw.get("error"),
        "foundry_workflow": raw.get("workflow"),
    }
