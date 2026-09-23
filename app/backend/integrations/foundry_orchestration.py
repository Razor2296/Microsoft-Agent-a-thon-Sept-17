"""Ignite Chat → Foundry Traces → workflow orchestration (Gemini).

When enabled (FOUNDRY_ORCHESTRATION_ENABLED=true OR PROJECT_CONNECTION_STRING set):
  1. Arm GenAI Tracing (Foundry / App Insights)
  2. Ensure agents + workflow exist (MODEL_DEPLOYMENT_NAME, default gemini-2.5-flash)
  3. Invoke the Foundry WORKFLOW under those traces (primary path)
  4. Fallback per-agent pipeline if workflow returns empty
  5. Mirror Plan JSON locally for the chat bubble / offline fallback

Hooks:
  - Every enabled Chat turn → maybe_run_foundry_turn (Traces + workflow)
  - Mic / Voice_Message → trigger chat_mic (keep provider reply unless extract)
  - Generate image/audio → trigger chat_generate_image|audio (Chat emits bytes; Foundry plans)
  - Chat → Ignite API extract via notify_foundry_after_extract

Agent-a-thon repo only — does not modify IgniteChat / IgniteAPI remotes.
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
import threading
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
_GEN_IMAGE_RE = re.compile(
    r"(genera|generar|crea|crear|dibuja|dibujar|haz|hacer|generate|create|draw|make|paint)"
    r".{0,48}(imagen|image|foto|picture|drawing|photo|ilustraci|illustration|pintura|painting)",
    re.IGNORECASE,
)
_GEN_AUDIO_RE = re.compile(
    r"(genera|generar|crea|crear|generate|create|make)"
    r".{0,48}(audio|sonido|sound|m[uú]sica|music|efecto de sonido|sound effect)",
    re.IGNORECASE,
)
_STATUS_LOGGED = False


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _foundry_dir() -> Path:
    return _repo_root() / "foundry"


def _load_foundry_env() -> None:
    """Load foundry/.env then app/.env. Foundry file wins for FOUNDRY_/PROJECT_/MODEL_ keys."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    foundry_env = _foundry_dir() / ".env"
    app_env = _repo_root() / "app" / ".env"
    if app_env.is_file():
        load_dotenv(app_env, override=False)
    if foundry_env.is_file():
        # Contest secrets live here — override empty/stale app values.
        load_dotenv(foundry_env, override=True)


def _truthy(name: str, default: str = "false") -> bool:
    return (os.getenv(name) or default).strip().lower() in ("1", "true", "yes", "on")


def _project_endpoint() -> str:
    return (os.getenv("PROJECT_CONNECTION_STRING") or "").strip()


def foundry_orchestration_enabled() -> bool:
    """On when flag is true OR project endpoint is configured (contest default)."""
    global _STATUS_LOGGED
    _load_foundry_env()
    flagged = _truthy("FOUNDRY_ORCHESTRATION_ENABLED")
    has_project = bool(_project_endpoint())
    enabled = flagged or has_project
    if not _STATUS_LOGGED:
        _STATUS_LOGGED = True
        logger.info(
            "FOUNDRY orchestration status: enabled=%s flag=%s project=%s model=%s "
            "media_agent=%s appinsights=%s",
            enabled,
            flagged,
            "set" if has_project else "MISSING",
            (os.getenv("MODEL_DEPLOYMENT_NAME") or "gemini-2.5-flash").strip(),
            (os.getenv("IGNITE_MEDIA_AGENT") or "ignite-image-agent").strip(),
            "set" if (os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING") or "").strip() else "MISSING",
        )
        if not enabled:
            logger.warning(
                "FOUNDRY orchestration OFF — set FOUNDRY_ORCHESTRATION_ENABLED=true "
                "and/or PROJECT_CONNECTION_STRING in foundry/.env + app/.env. "
                "Without this, Chat uses normal Gemini→Ignite API and Traces stay empty."
            )
    return enabled


def detect_generate_kind(text: str) -> str | None:
    """'image' | 'audio' when the user asks Chat to create media (not describe)."""
    body = (text or "").split("[channel=")[0]
    if _GEN_IMAGE_RE.search(body):
        return "image"
    if _GEN_AUDIO_RE.search(body):
        return "audio"
    return None


def _has_voice_attachment(files: list | None) -> bool:
    for f in files or []:
        if not isinstance(f, dict):
            continue
        name = str(f.get("name") or f.get("filename") or "")
        mime = str(f.get("mime_type") or "").lower()
        if name.startswith("Voice_Message_") or mime.startswith("audio/"):
            return True
    return False


def _is_extract_or_doc_turn(text: str, files: list | None = None) -> bool:
    """True for document/media *analyze* intents (not generate / plain chat / casual mic)."""
    if detect_generate_kind(text or ""):
        return False
    for f in files or []:
        if not isinstance(f, dict):
            continue
        name = str(f.get("name") or f.get("filename") or "")
        mime = str(f.get("mime_type") or "").lower()
        if name.startswith("Voice_Message_") or mime.startswith("audio/"):
            continue
        return True  # image / pdf / office / etc.
    blob = text or ""
    lower = blob.lower()
    if _DOC_ID_RE.search(blob) or _MEDIA_ID_RE.search(blob):
        return True
    return any(h in lower for h in _EXTRACT_HINTS)


def should_handle_turn(
    text: str,
    files: list | None = None,
    *,
    from_mic: bool = False,
) -> bool:
    """Every enabled Chat turn hits Foundry (Traces + workflow).

    Callers must gate on foundry_orchestration_enabled(). Generate image/audio,
    mic, attachments, extract, and plain chat are all in scope (STD-014).
    """
    if _truthy("FOUNDRY_ORCHESTRATION_ALWAYS", "true"):
        return True
    # FOUNDRY_ORCHESTRATION_ALWAYS=false → legacy narrow filter
    if from_mic or _has_voice_attachment(files):
        return True
    if detect_generate_kind(text or ""):
        return True
    if files:
        return True
    return _is_extract_or_doc_turn(text or "", files)


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
    logger.info(
        "FOUNDRY run_foundry_turn trigger=%s lang=%s chars=%d files=%d",
        trigger,
        lang,
        len(prompt),
        len(files or []),
    )
    return run_traced_orchestration(prompt, lang=lang, trigger=trigger)


def _trace_async_enabled() -> bool:
    """Non-intercept turns trace in a daemon thread so Chat UX never freezes (video-safe)."""
    return _truthy("FOUNDRY_TRACE_ASYNC", "true")


def _spawn_foundry_trace(
    text: str,
    files: list | None = None,
    *,
    language: str | None = None,
    trigger: str = "chat",
) -> None:
    def _worker() -> None:
        try:
            run_foundry_turn(text, files, language=language, trigger=trigger)
        except Exception as exc:
            logger.warning(
                "FOUNDRY async trace failed trigger=%s err=%s", trigger, exc
            )

    threading.Thread(
        target=_worker,
        name=f"foundry-trace-{trigger}",
        daemon=True,
    ).start()
    logger.info("FOUNDRY async trace spawned trigger=%s", trigger)


def maybe_run_foundry_turn(
    text: str,
    files: list | None = None,
    *,
    language: str | None = None,
    from_mic: bool = False,
) -> dict[str, Any] | None:
    """Chat hook: return chat-shaped dict or None to keep normal LLM / generation path.

    When orchestration is on, every turn arms Traces + workflow. Only extract /
    document-analyze turns intercept the bubble (sync). Mic, generate image/audio,
    and plain chat keep Ignite Chat as executor and trace **async** by default
    (FOUNDRY_TRACE_ASYNC=true) so the video demo never freezes on Azure.
    """
    if not foundry_orchestration_enabled():
        logger.info("FOUNDRY maybe_run_foundry_turn: skipped (orchestration disabled)")
        return None
    voice_turn = bool(from_mic) or _has_voice_attachment(files)
    gen_kind = detect_generate_kind(text or "")
    if not should_handle_turn(text or "", files, from_mic=from_mic):
        logger.info("FOUNDRY maybe_run_foundry_turn: skipped (filtered)")
        return None

    files_for_prompt = list(files or [])
    if voice_turn and not _has_voice_attachment(files_for_prompt):
        files_for_prompt.append(
            {
                "name": "Voice_Message_mic.webm",
                "mime_type": "audio/webm",
            }
        )

    if voice_turn:
        trigger = "chat_mic"
    elif gen_kind == "image":
        trigger = "chat_generate_image"
    elif gen_kind == "audio":
        trigger = "chat_generate_audio"
    else:
        trigger = "chat"

    prompt_text = (text or "").strip()
    if voice_turn:
        prompt_text = (
            f"{prompt_text}\n"
            "[channel=audio from_mic=true modality=audio nota de voz Voice_Message]"
        ).strip()
    elif gen_kind == "image":
        prompt_text = (
            f"{prompt_text}\n"
            "[intent=GENERATE_IMAGE modality=image agent=ignite-image-agent]"
        ).strip()
    elif gen_kind == "audio":
        prompt_text = (
            f"{prompt_text}\n"
            "[intent=GENERATE_AUDIO modality=audio agent=ignite-audio-agent]"
        ).strip()

    will_intercept = bool(_is_extract_or_doc_turn(text or "", files) and not gen_kind)

    logger.info(
        "FOUNDRY maybe_run_foundry_turn: RUNNING trigger=%s from_mic=%s gen=%s "
        "intercept=%s async=%s",
        trigger,
        from_mic,
        gen_kind,
        will_intercept,
        (not will_intercept) and _trace_async_enabled(),
    )

    # Video-safe: do not block Imagen / TTS / normal chat on Azure round-trips.
    if not will_intercept and _trace_async_enabled():
        _spawn_foundry_trace(
            prompt_text,
            files_for_prompt,
            language=language,
            trigger=trigger,
        )
        return None

    try:
        raw = run_foundry_turn(
            prompt_text, files_for_prompt, language=language, trigger=trigger
        )
    except Exception as exc:
        logger.exception("foundry_orchestration: chat turn failed")
        if not will_intercept:
            return None
        return {
            "status": "error",
            "message": f"⚠ Foundry orchestration failed: {exc}",
            "foundry": True,
        }
    live = bool(raw.get("live"))
    hard_fail = bool(raw.get("error")) and not live
    logger.info(
        "FOUNDRY maybe_run_foundry_turn: done live=%s source=%s trigger=%s error=%s",
        live,
        raw.get("source"),
        trigger,
        (raw.get("error") or "")[:160] or None,
    )

    if will_intercept:
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

    logger.info(
        "FOUNDRY maybe_run_foundry_turn: traced trigger=%s live=%s; keeping Chat reply",
        trigger,
        live,
    )
    return None


def notify_foundry_generation(
    *,
    kind: str,
    prompt: str,
    language: str | None = None,
) -> dict[str, Any] | None:
    """Standalone generate_image / generate_audio API → Foundry Traces (async by default)."""
    kind_l = (kind or "").strip().lower()
    if kind_l not in ("image", "audio"):
        return None
    if not foundry_orchestration_enabled():
        logger.info("FOUNDRY notify_foundry_generation: skipped (orchestration disabled)")
        return None
    label = "GENERATE_IMAGE" if kind_l == "image" else "GENERATE_AUDIO"
    agent = "ignite-image-agent" if kind_l == "image" else "ignite-audio-agent"
    trigger = f"chat_generate_{kind_l}"
    text = (
        f"{(prompt or '').strip()}\n"
        f"[intent={label} modality={kind_l} agent={agent}]"
    )
    logger.info("FOUNDRY notify_foundry_generation: kind=%s trigger=%s", kind_l, trigger)
    if _trace_async_enabled():
        _spawn_foundry_trace(text, language=language, trigger=trigger)
        return {
            "status": "accepted",
            "foundry": True,
            "foundry_trigger": trigger,
            "foundry_async": True,
        }
    try:
        raw = run_foundry_turn(text, language=language, trigger=trigger)
    except Exception as exc:
        logger.warning("FOUNDRY notify_foundry_generation failed: %s", exc)
        return {"status": "error", "foundry": True, "message": str(exc)}
    return {
        "status": "success" if raw.get("live") or not raw.get("error") else "error",
        "foundry": True,
        "foundry_trigger": trigger,
        "foundry_plan": raw.get("plan"),
        "foundry_trace_tags": raw.get("trace_tags"),
        "foundry_live": bool(raw.get("live")),
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
        logger.warning(
            "FOUNDRY notify_foundry_after_extract: SKIPPED after extract of '%s' "
            "(orchestration disabled — Traces will stay empty)",
            filename,
        )
        return None
    logger.info(
        "FOUNDRY notify_foundry_after_extract: RUNNING for '%s' template=%s",
        filename,
        template_name,
    )
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
    logger.info(
        "FOUNDRY notify_foundry_after_extract: done live=%s source=%s workflow=%s",
        live,
        raw.get("source"),
        raw.get("workflow"),
    )
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
