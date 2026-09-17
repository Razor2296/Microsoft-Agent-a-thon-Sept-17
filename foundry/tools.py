"""Document tool for Foundry agents — same extract contract as Ignite Chat → Ignite API.

When FOUNDRY_USE_IGNITE_API=true (and URL + key are set), inspect_document uploads a
local fixture file via POST /api/v1/extract?mode=auto (same as Chat's IgniteAPIClient).

When the API is off or unreachable, falls back to data/documents.json so offline CI
(python test_tools.py) stays green without secrets or network.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

FOUNDRY_DIR = Path(__file__).resolve().parent
DATA_PATH = FOUNDRY_DIR / "data" / "documents.json"
FIXTURES_DIR = FOUNDRY_DIR / "data" / "fixtures"

# Template hints aligned with Ignite Chat _guess_extract_template
_DOC_TEMPLATES = {
    "DOC-001": "Medical_Prescription",
    "DOC-002": "Invoice_Standard",
    "DOC-003": "Invoice_Standard",
}


def load_documents() -> list[dict]:
    with DATA_PATH.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    return list(payload.get("documents") or [])


def _catalog_entry(doc_id: str) -> dict | None:
    wanted = (doc_id or "").strip().upper()
    for doc in load_documents():
        if str(doc.get("doc_id", "")).upper() == wanted:
            return doc
    return None


def _use_ignite_api() -> bool:
    flag = (os.getenv("FOUNDRY_USE_IGNITE_API") or "").strip().lower()
    if flag in ("0", "false", "no", "off"):
        return False
    if flag in ("1", "true", "yes", "on"):
        return True
    # Auto: enable when Chat-compatible env is present
    url = (
        os.getenv("IGNITE_EXTRACTION_API_URL")
        or os.getenv("IGNITE_API_URL")
        or ""
    ).strip()
    key = (
        os.getenv("IGNITE_EXTRACTION_API_KEY")
        or os.getenv("IGNITE_MASTER_API_KEY")
        or ""
    ).strip()
    return bool(url and key)


def _api_base() -> str:
    return (
        os.getenv("IGNITE_EXTRACTION_API_URL")
        or os.getenv("IGNITE_API_URL")
        or "https://ignite-api.azurecontainerapps.io"
    ).rstrip("/")


def _api_key() -> str:
    return (
        os.getenv("IGNITE_EXTRACTION_API_KEY")
        or os.getenv("IGNITE_MASTER_API_KEY")
        or ""
    ).strip()


def _fixture_path(doc_id: str) -> Path | None:
    wanted = (doc_id or "").strip().upper()
    if not wanted:
        return None
    for ext in (".txt", ".pdf", ".json"):
        candidate = FIXTURES_DIR / f"{wanted}{ext}"
        if candidate.is_file():
            return candidate
    return None


def _normalize_extraction(doc_id: str, api_payload: Any, fixture_name: str, template: str) -> dict:
    """Shape API JSON into the compact fields agents already expect."""
    if not isinstance(api_payload, dict):
        return {
            "doc_id": doc_id,
            "source": "ignite_api",
            "mode": "auto",
            "template": template,
            "fixture": fixture_name,
            "raw": str(api_payload)[:2000],
        }
    fields = api_payload.get("fields") or api_payload.get("data") or api_payload.get("result")
    if not isinstance(fields, dict):
        fields = {k: v for k, v in api_payload.items() if k not in ("job_id", "status", "error")}
    return {
        "doc_id": doc_id,
        "source": "ignite_api",
        "mode": "auto",
        "template": template,
        "fixture": fixture_name,
        "kind": api_payload.get("kind") or api_payload.get("channel") or "extract",
        "title": api_payload.get("title") or fixture_name,
        "fields": fields,
        "job_id": api_payload.get("job_id"),
        "status": api_payload.get("status") or "ok",
    }


def _extract_via_ignite_api(doc_id: str) -> str:
    import httpx

    wanted = (doc_id or "").strip().upper()
    fixture = _fixture_path(wanted)
    if fixture is None:
        return json.dumps(
            {
                "error": f"No fixture file for '{doc_id}' under data/fixtures/",
                "known_ids": [d["doc_id"] for d in load_documents()],
                "hint": "Add DOC-001.txt (etc.) or set FOUNDRY_USE_IGNITE_API=false for catalog fallback",
            }
        )

    template = _DOC_TEMPLATES.get(wanted, "Invoice_Standard")
    url = f"{_api_base()}/api/v1/extract"
    headers = {"X-API-Key": _api_key()} if _api_key() else {}
    timeout = float(os.getenv("IGNITE_API_TIMEOUT", "300"))
    max_wait = float(os.getenv("IGNITE_EXTRACTION_MAX_WAIT", "300"))
    poll_interval = float(os.getenv("IGNITE_EXTRACTION_POLL_INTERVAL", "3"))

    with fixture.open("rb") as handle:
        files = {"file": (fixture.name, handle, "application/octet-stream")}
        data = {"template_name": template}
        with httpx.Client(timeout=timeout) as client:
            response = client.post(
                url,
                params={"mode": "auto"},
                headers=headers,
                files=files,
                data=data,
            )

            if response.status_code == 202:
                body = response.json() if response.content else {}
                job_id = body.get("job_id") or body.get("id")
                if not job_id:
                    return json.dumps(
                        {
                            "error": "202 without job_id",
                            "body": body,
                            "doc_id": wanted,
                            "source": "ignite_api",
                        }
                    )
                deadline = __import__("time").time() + max_wait
                while __import__("time").time() < deadline:
                    job = client.get(
                        f"{_api_base()}/api/v1/jobs/{job_id}",
                        headers=headers,
                    )
                    job.raise_for_status()
                    payload = job.json()
                    status = str(payload.get("status") or "").lower()
                    if status in ("succeeded", "completed", "success", "done"):
                        result = payload.get("result") or payload.get("data") or payload
                        return json.dumps(
                            _normalize_extraction(wanted, result, fixture.name, template),
                            indent=2,
                        )
                    if status in ("failed", "error", "cancelled"):
                        return json.dumps(
                            {
                                "error": f"Job {job_id} {status}",
                                "doc_id": wanted,
                                "source": "ignite_api",
                                "detail": payload,
                            },
                            indent=2,
                        )
                    __import__("time").sleep(poll_interval)
                return json.dumps(
                    {
                        "error": f"Job {job_id} timed out",
                        "doc_id": wanted,
                        "source": "ignite_api",
                    }
                )

            if response.status_code >= 400:
                return json.dumps(
                    {
                        "error": f"HTTP {response.status_code}",
                        "doc_id": wanted,
                        "source": "ignite_api",
                        "body": (response.text or "")[:1500],
                    },
                    indent=2,
                )

            payload = response.json() if response.content else {}
            return json.dumps(
                _normalize_extraction(wanted, payload, fixture.name, template),
                indent=2,
            )


def inspect_document(doc_id: str) -> str:
    """Return JSON for one document via Ignite API (mode=auto) or catalog fallback."""
    wanted = (doc_id or "").strip().upper()
    if _use_ignite_api():
        try:
            return _extract_via_ignite_api(wanted)
        except Exception as exc:
            # Soft-fail to catalog so seed demos still work if API is down
            catalog = _catalog_entry(wanted)
            if catalog is not None:
                out = dict(catalog)
                out["source"] = "catalog_fallback"
                out["api_error"] = str(exc)[:500]
                return json.dumps(out, indent=2)
            return json.dumps(
                {
                    "error": str(exc),
                    "doc_id": doc_id,
                    "source": "ignite_api",
                    "known_ids": [d["doc_id"] for d in load_documents()],
                }
            )

    catalog = _catalog_entry(wanted)
    if catalog is not None:
        out = dict(catalog)
        out["source"] = "catalog"
        out["mode"] = "offline"
        return json.dumps(out, indent=2)
    return json.dumps(
        {
            "error": f"Document '{doc_id}' not found",
            "known_ids": [d["doc_id"] for d in load_documents()],
        }
    )


INSPECT_DOCUMENT_TOOL = {
    "name": "inspect_document",
    "description": (
        "Extract structured fields for an Ignite document id (DOC-001 medical, "
        "DOC-002 invoice, DOC-003 research). When FOUNDRY_USE_IGNITE_API is on, "
        "calls Ignite API POST /api/v1/extract?mode=auto (same contract as Ignite Chat). "
        "Otherwise returns the offline catalog. Never invent PHI."
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
