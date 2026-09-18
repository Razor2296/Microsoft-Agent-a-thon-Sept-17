"""Modality catalog + describe_media tool (synthetic, no real PHI/PII).

Used when the Foundry brain routes image / audio / video turns. Traces tag
modality:* so Foundry Tracing can filter spans by channel.
"""
from __future__ import annotations

import json
from pathlib import Path

FOUNDRY_DIR = Path(__file__).resolve().parent
MEDIA_PATH = FOUNDRY_DIR / "data" / "modalities.json"


def load_media() -> list[dict]:
    with MEDIA_PATH.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    return list(payload.get("media") or [])


def describe_media(media_id: str) -> str:
    """Return JSON facts for a sample media asset (image / audio / video)."""
    wanted = (media_id or "").strip().upper()
    for item in load_media():
        if str(item.get("media_id", "")).upper() == wanted:
            out = dict(item)
            out["source"] = "modality_catalog"
            return json.dumps(out, indent=2)
    return json.dumps(
        {
            "error": f"Media '{media_id}' not found",
            "known_ids": [m["media_id"] for m in load_media()],
        }
    )


DESCRIBE_MEDIA_TOOL = {
    "name": "describe_media",
    "description": (
        "Look up a sample Ignite media asset by id (MED-IMG-001 image, "
        "MED-AUD-001 audio transcript summary, MED-VID-001 video summary). "
        "Returns modality tags and safe synthetic captions — no real PHI."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "media_id": {
                "type": "string",
                "description": "Media id such as MED-IMG-001",
            }
        },
        "required": ["media_id"],
        "additionalProperties": False,
    },
}
