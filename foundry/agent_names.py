"""Canonical Foundry agent names for juliancuray-7914 (Paso 3).

DO NOT invent alternate defaults. Portal Build → Agents is the source of truth.
See `.agents/skills/foundry-paso3/references/FOUNDRY_AGENTS.md`.
"""
from __future__ import annotations

import os
from typing import Iterable


def _env(name: str, default: str) -> str:
    return (os.getenv(name) or default).strip()


def orchestrator_agent() -> str:
    return _env("IGNITE_ORCHESTRATOR_AGENT", "ignite-orchestrator-agent")


def document_agent() -> str:
    return _env("IGNITE_DOCUMENT_AGENT", "ignite-document-agent")


def image_agent() -> str:
    return _env("IGNITE_IMAGE_AGENT", "ignite-image-agent")


def audio_agent() -> str:
    return _env("IGNITE_AUDIO_AGENT", "ignite-audio-agent")


def video_agent() -> str:
    return _env("IGNITE_VIDEO_AGENT", "ignite-video-agent")


def workflow_agent() -> str:
    return _env("IGNITE_WORKFLOW_AGENT", "ignite-document-workflow")


def specialist_for_modality(modality: str) -> str:
    """Map Ignite API / Plan modality → Foundry specialist agent name."""
    m = (modality or "").strip().lower()
    if m in ("document", "doc", "pdf"):
        return document_agent()
    if m == "image":
        return image_agent()
    if m == "audio":
        return audio_agent()
    if m == "video":
        return video_agent()
    return orchestrator_agent()


def specialist_for_media_id(media_id: str | None) -> str:
    mid = (media_id or "").strip().upper()
    if mid.startswith("MED-AUD"):
        return audio_agent()
    if mid.startswith("MED-VID"):
        return video_agent()
    if mid.startswith("MED-IMG"):
        return image_agent()
    return image_agent()


def specialist_for_ignite_channel(channel: str | None, *, filename: str = "") -> str:
    """Map Ignite API extract channel / filename → specialist."""
    ch = (channel or "").strip().lower()
    if ch in ("document", "doc", "pdf"):
        return document_agent()
    if ch == "image":
        return image_agent()
    if ch == "audio":
        return audio_agent()
    if ch == "video":
        return video_agent()
    name = (filename or "").lower()
    if name.endswith((".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff")):
        return image_agent()
    if name.endswith((".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac")):
        return audio_agent()
    if name.endswith((".mp4", ".mov", ".webm", ".mkv", ".avi")):
        return video_agent()
    if name.endswith((".pdf", ".docx", ".doc", ".xlsx", ".pptx", ".txt")):
        return document_agent()
    return document_agent()


def all_prompt_agents() -> list[str]:
    """Five prompt agents that must exist in Foundry (order: orch + 4 specialists)."""
    return [
        orchestrator_agent(),
        document_agent(),
        image_agent(),
        audio_agent(),
        video_agent(),
    ]


def modality_agents() -> dict[str, str]:
    return {
        "document": document_agent(),
        "image": image_agent(),
        "audio": audio_agent(),
        "video": video_agent(),
    }


def is_canonical_agent(name: str) -> bool:
    return name in set(all_prompt_agents()) | {workflow_agent()}


def iter_modality_labels() -> Iterable[str]:
    return ("document", "image", "audio", "video")
