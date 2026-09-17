"""Writable data dir for frozen desktop vs ACA."""
from __future__ import annotations

import os
import sys

from backend.core.runtime_paths import get_writable_data_dir, get_log_dir


def test_respects_ignite_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("IGNITE_DATA_DIR", str(tmp_path / "mounted"))
    assert get_writable_data_dir() == str(tmp_path / "mounted")


def test_frozen_defaults_to_localappdata(tmp_path, monkeypatch):
    monkeypatch.delenv("IGNITE_DATA_DIR", raising=False)
    install = tmp_path / "Programs" / "Ignite Chat"
    install.mkdir(parents=True)
    local = tmp_path / "LocalAppData"
    local.mkdir()
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(install / "Ignite Chat.exe"))

    path = get_writable_data_dir(str(install))
    assert path == str(local / "Ignite Chat")
    assert (local / "Ignite Chat" / "log").is_dir()
    assert get_log_dir(str(install)) == str(local / "Ignite Chat" / "log")


def test_frozen_portable_marker_uses_install_dir(tmp_path, monkeypatch):
    monkeypatch.delenv("IGNITE_DATA_DIR", raising=False)
    install = tmp_path / "portable" / "Ignite Chat"
    install.mkdir(parents=True)
    (install / ".portable").write_text("", encoding="utf-8")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(install / "Ignite Chat.exe"))

    path = get_writable_data_dir(str(install))
    assert path == str(install)
