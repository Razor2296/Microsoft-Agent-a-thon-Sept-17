"""Local document-inspect tool used by Foundry FunctionTool (no real PHI)."""
from __future__ import annotations

import json
from pathlib import Path

DATA_PATH = Path(__file__).resolve().parent / "data" / "documents.json"


def load_documents() -> list[dict]:
    with DATA_PATH.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    return list(payload.get("documents") or [])


def inspect_document(doc_id: str) -> str:
    """Return JSON for one sample document. Unknown ids return an error object."""
    wanted = (doc_id or "").strip().upper()
    for doc in load_documents():
        if str(doc.get("doc_id", "")).upper() == wanted:
            return json.dumps(doc, indent=2)
    return json.dumps({"error": f"Document '{doc_id}' not found", "known_ids": [d["doc_id"] for d in load_documents()]})


INSPECT_DOCUMENT_TOOL = {
    "name": "inspect_document",
    "description": (
        "Look up a sample Ignite document by id (DOC-001 medical order, "
        "DOC-002 invoice, DOC-003 research PDF). Returns structured fields. "
        "Does not call Ignite API; this is the Foundry-visible specialist tool."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "doc_id": {
                "type": "string",
                "description": "Document id such as DOC-001",
            }
        },
        "required": ["doc_id"],
        "additionalProperties": False,
    },
}
