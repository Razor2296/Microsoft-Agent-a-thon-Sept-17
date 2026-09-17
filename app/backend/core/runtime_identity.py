"""Per-request desktop identity for multi-user ACA (ContextVar-isolated)."""

from __future__ import annotations

import contextvars
import os

try:
    from backend.user.windows_user import get_user_display_name
except Exception:  # pragma: no cover - optional on Linux/ACA
    def get_user_display_name() -> str:  # type: ignore[misc]
        return "User"


_RUNTIME_USER_NAME: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "ignite_runtime_user_name",
    default=None,
)


def set_runtime_user_name(name: str | None) -> None:
    """Override the display name used in model system prompts (remote desktop identity)."""
    cleaned = (name or "").strip()
    _RUNTIME_USER_NAME.set(cleaned or None)


def get_runtime_user_name() -> str:
    """Resolve the active user display name (request override → env → OS)."""
    override = _RUNTIME_USER_NAME.get()
    if override:
        return override
    env_name = (os.getenv("IGNITE_USER_NAME") or "").strip()
    if env_name:
        return env_name
    try:
        return str(get_user_display_name() or "User")
    except Exception:
        return "User"
