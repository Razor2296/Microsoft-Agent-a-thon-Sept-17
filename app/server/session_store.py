"""Per-client PyWebViewApi session registry for multi-user ACA isolation."""

from __future__ import annotations

import logging
import os
import re
import threading
import time
import uuid
from collections.abc import Callable
from typing import Any

logger = logging.getLogger("ignite.session_store")

_SAFE_SESSION_RE = re.compile(r"[^a-zA-Z0-9_-]+")


def normalize_session_id(raw: str | None) -> str:
    """Return a filesystem-safe session id, minting one when missing/invalid."""
    value = (raw or "").strip()
    if not value:
        return f"sess_{uuid.uuid4().hex}"
    cleaned = _SAFE_SESSION_RE.sub("_", value)[:80]
    if len(cleaned) < 8:
        return f"sess_{uuid.uuid4().hex}"
    return cleaned


class SessionApiStore:
    """Lazy per-session API instances with idle TTL eviction."""

    def __init__(
        self,
        factory: Callable[[str], Any],
        *,
        ttl_seconds: float | None = None,
        max_sessions: int | None = None,
    ):
        self._factory = factory
        self._ttl_seconds = float(
            ttl_seconds
            if ttl_seconds is not None
            else os.getenv("IGNITE_SESSION_TTL_SECONDS", "7200")
        )
        self._max_sessions = int(
            max_sessions
            if max_sessions is not None
            else os.getenv("IGNITE_MAX_SESSIONS", "50")
        )
        self._lock = threading.RLock()
        self._entries: dict[str, dict[str, Any]] = {}

    def get_or_create(self, session_id: str | None) -> tuple[str, Any]:
        sid = normalize_session_id(session_id)
        now = time.time()
        with self._lock:
            self._evict_locked(now)
            entry = self._entries.get(sid)
            if entry is not None:
                entry["last_used"] = now
                return sid, entry["api"]

            if len(self._entries) >= max(1, self._max_sessions):
                oldest_sid = min(
                    self._entries.items(),
                    key=lambda item: item[1]["last_used"],
                )[0]
                logger.warning(
                    "Session capacity reached (%s); evicting idle session %s",
                    self._max_sessions,
                    oldest_sid,
                )
                self._entries.pop(oldest_sid, None)

            # Factory must receive sid so tenant disk paths load correctly in __init__.
            api = self._factory(sid)
            if getattr(api, "_tenant_key", None) != sid:
                api._tenant_key = sid
            self._entries[sid] = {"api": api, "last_used": now, "created": now}
            logger.info(
                "Created isolated API session %s (active=%s)",
                sid,
                len(self._entries),
            )
            return sid, api

    def _evict_locked(self, now: float) -> None:
        if self._ttl_seconds <= 0:
            return
        expired = [
            sid
            for sid, entry in self._entries.items()
            if (now - float(entry["last_used"])) > self._ttl_seconds
        ]
        for sid in expired:
            self._entries.pop(sid, None)
            logger.info("Evicted idle API session %s", sid)

    def active_count(self) -> int:
        with self._lock:
            return len(self._entries)
