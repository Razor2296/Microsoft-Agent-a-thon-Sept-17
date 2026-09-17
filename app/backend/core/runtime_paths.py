"""
Writable data paths for desktop (Program Files / local install) and ACA.

Frozen desktop builds MUST NOT write logs/sessions next to the exe when the
install tree is read-only (Program Files) or when uninstall would wipe chats.
Default user data: %LOCALAPPDATA%\\Ignite Chat
Opt-in portable: place an empty file named `.portable` next to the exe.
"""
from __future__ import annotations

import os
import sys
from typing import Optional


_APP_DATA_NAME = "Ignite Chat"


def _can_write_dir(path: str) -> bool:
    try:
        os.makedirs(path, exist_ok=True)
        probe = os.path.join(path, ".ignite_write_probe")
        with open(probe, "w", encoding="utf-8") as fh:
            fh.write("ok")
        os.remove(probe)
        return True
    except OSError:
        return False


def get_writable_data_dir(install_or_app_dir: Optional[str] = None) -> str:
    """
    Directory for logs, sessions, RAG DB, crash dumps, generated media.

    Priority:
    1. IGNITE_DATA_DIR (ACA Azure Files / explicit override)
    2. Frozen + `.portable` marker beside the exe → install dir (if writable)
    3. Frozen → %LOCALAPPDATA%\\Ignite Chat (survives reinstall/uninstall of Programs\\)
    4. Dev → install_or_app_dir / app root
    """
    existing = (os.getenv("IGNITE_DATA_DIR") or "").strip()
    if existing:
        os.makedirs(existing, exist_ok=True)
        return existing

    if getattr(sys, "frozen", False):
        install = install_or_app_dir or os.path.dirname(sys.executable)
        portable_marker = os.path.join(install, ".portable")
        if os.path.isfile(portable_marker) and _can_write_dir(os.path.join(install, "log")):
            return install

        local_root = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        data = os.path.join(local_root, _APP_DATA_NAME)
        os.makedirs(os.path.join(data, "log"), exist_ok=True)
        os.environ.setdefault("IGNITE_DATA_DIR", data)
        return data

    if install_or_app_dir:
        os.makedirs(os.path.join(install_or_app_dir, "log"), exist_ok=True)
        return install_or_app_dir

    here = os.path.dirname(os.path.abspath(__file__))
    app_root = os.path.dirname(os.path.dirname(here))
    os.makedirs(os.path.join(app_root, "log"), exist_ok=True)
    return app_root


def get_log_dir(install_or_app_dir: Optional[str] = None) -> str:
    log_dir = os.path.join(get_writable_data_dir(install_or_app_dir), "log")
    os.makedirs(log_dir, exist_ok=True)
    return log_dir
