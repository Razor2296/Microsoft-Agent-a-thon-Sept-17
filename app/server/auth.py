"""Simple API-key authentication for the Ignite Chat HTTP backend."""

from __future__ import annotations

import os
from typing import Optional

from fastapi import Header, HTTPException, status


def get_expected_api_key() -> str:
    return (os.getenv("IGNITE_API_KEY") or os.getenv("API_KEY") or "").strip()


def require_api_key(x_api_key: Optional[str] = Header(default=None, alias="X-API-Key")) -> None:
    """Reject requests when an API key is configured and the header does not match."""
    expected = get_expected_api_key()
    if not expected:
        # Local/dev convenience: auth disabled when no key is configured.
        return
    provided = (x_api_key or "").strip()
    if not provided or provided != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
        )
