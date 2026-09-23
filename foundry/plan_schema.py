"""Structured orchestration plan emitted by the Foundry orchestrator (brain).

Ignite Chat mirrors these intents operationally; Foundry is the Architect-visible
source of truth for routing, modality tags (Traces), and step sequence.
"""
from __future__ import annotations

import json
import re
from typing import Any

VALID_MODALITIES = frozenset({"text", "document", "image", "audio", "video"})
VALID_INTENTS = frozenset(
    {
        "EXTRACT",
        "ANSWER",
        "EXPORT",
        "CLARIFY",
        "MEDIA_DESCRIBE",
        "GENERATE_IMAGE",
        "GENERATE_AUDIO",
    }
)
VALID_ACTIONS = frozenset(
    {
        "inspect_document",
        "describe_media",
        "synthesize",
        "clarify",
        "export_office",
        "generate_image",
        "generate_audio",
    }
)

PLAN_JSON_SCHEMA_HINT = """
Return ONLY one JSON object (no markdown fences) with this shape:
{
  "modality": "text|document|image|audio|video",
  "intent": "EXTRACT|ANSWER|EXPORT|CLARIFY|MEDIA_DESCRIBE|GENERATE_IMAGE|GENERATE_AUDIO",
  "doc_id": "DOC-001 or null",
  "media_id": "MED-001 or null",
  "steps": [
    {"action": "inspect_document|describe_media|synthesize|clarify|export_office|generate_image|generate_audio",
     "agent": "ignite-document-agent|ignite-image-agent|ignite-audio-agent|ignite-video-agent|ignite-orchestrator-agent",
     "args": {}}
  ],
  "user_message_es": "short Spanish reply or empty if a later step will fill it",
  "user_message_en": "short English reply or empty",
  "trace_tags": ["modality:document", "intent:EXTRACT"]
}
""".strip()


def empty_plan(**overrides: Any) -> dict[str, Any]:
    plan: dict[str, Any] = {
        "modality": "text",
        "intent": "CLARIFY",
        "doc_id": None,
        "media_id": None,
        "steps": [{"action": "clarify", "agent": "ignite-orchestrator-agent", "args": {}}],
        "user_message_es": "",
        "user_message_en": "",
        "trace_tags": ["modality:text", "intent:CLARIFY"],
    }
    plan.update(overrides)
    return plan


def extract_json_object(text: str) -> dict[str, Any] | None:
    """Pull the first JSON object from model output (tolerates fences / prose)."""
    if not text or not str(text).strip():
        return None
    raw = str(text).strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL | re.IGNORECASE)
    if fence:
        raw = fence.group(1)
    else:
        start = raw.find("{")
        end = raw.rfind("}")
        if start < 0 or end <= start:
            return None
        raw = raw[start : end + 1]
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def validate_plan(plan: dict[str, Any]) -> dict[str, Any]:
    """Normalize and validate a plan dict; raise ValueError if unusable."""
    if not isinstance(plan, dict):
        raise ValueError("plan must be an object")

    modality = str(plan.get("modality") or "text").strip().lower()
    if modality not in VALID_MODALITIES:
        modality = "text"

    intent = str(plan.get("intent") or "CLARIFY").strip().upper()
    if intent not in VALID_INTENTS:
        intent = "CLARIFY"

    doc_id = plan.get("doc_id")
    if doc_id is not None:
        doc_id = str(doc_id).strip().upper() or None

    media_id = plan.get("media_id")
    if media_id is not None:
        media_id = str(media_id).strip().upper() or None

    steps_in = plan.get("steps")
    steps: list[dict[str, Any]] = []
    if isinstance(steps_in, list):
        for item in steps_in:
            if not isinstance(item, dict):
                continue
            action = str(item.get("action") or "").strip().lower()
            if action not in VALID_ACTIONS:
                continue
            agent = str(item.get("agent") or "ignite-orchestrator-agent").strip()
            args = item.get("args") if isinstance(item.get("args"), dict) else {}
            steps.append({"action": action, "agent": agent, "args": args})

    if not steps:
        if intent == "EXTRACT" and doc_id:
            steps = [
                {
                    "action": "inspect_document",
                    "agent": "ignite-document-agent",
                    "args": {"doc_id": doc_id},
                },
                {"action": "synthesize", "agent": "ignite-orchestrator-agent", "args": {}},
            ]
        elif intent == "MEDIA_DESCRIBE" and media_id:
            from agent_names import specialist_for_media_id

            steps = [
                {
                    "action": "describe_media",
                    "agent": specialist_for_media_id(media_id),
                    "args": {"media_id": media_id},
                },
                {"action": "synthesize", "agent": "ignite-orchestrator-agent", "args": {}},
            ]
        elif intent == "EXPORT":
            steps = [{"action": "export_office", "agent": "ignite-orchestrator-agent", "args": {}}]
        elif intent == "GENERATE_IMAGE":
            steps = [
                {
                    "action": "generate_image",
                    "agent": "ignite-image-agent",
                    "args": {},
                },
                {"action": "synthesize", "agent": "ignite-orchestrator-agent", "args": {}},
            ]
        elif intent == "GENERATE_AUDIO":
            steps = [
                {
                    "action": "generate_audio",
                    "agent": "ignite-audio-agent",
                    "args": {},
                },
                {"action": "synthesize", "agent": "ignite-orchestrator-agent", "args": {}},
            ]
        else:
            steps = [{"action": "clarify", "agent": "ignite-orchestrator-agent", "args": {}}]

    tags = plan.get("trace_tags")
    if not isinstance(tags, list) or not tags:
        tags = [f"modality:{modality}", f"intent:{intent}"]
    else:
        tags = [str(t) for t in tags]

    return {
        "modality": modality,
        "intent": intent,
        "doc_id": doc_id,
        "media_id": media_id,
        "steps": steps,
        "user_message_es": str(plan.get("user_message_es") or ""),
        "user_message_en": str(plan.get("user_message_en") or ""),
        "trace_tags": tags,
    }


def parse_plan(text: str) -> dict[str, Any]:
    obj = extract_json_object(text)
    if obj is None:
        raise ValueError("no JSON plan found in orchestrator output")
    return validate_plan(obj)
