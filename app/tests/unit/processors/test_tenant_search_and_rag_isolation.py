"""
Critical isolation: SEARCH_DISABLED and RAG DB must be tenant-scoped (ACA).
"""
from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

import backend.processors.base_processor as bp
from backend.processors.base_processor import BaseChat
from backend.tools.rag_engine import LocalRAGEngine


def test_search_disabled_is_tenant_scoped():
    bp._SEARCH_DISABLED_BY_TENANT.clear()
    a = BaseChat.__new__(BaseChat)
    b = BaseChat.__new__(BaseChat)
    a._tenant_key = "tenant-A"
    b._tenant_key = "tenant-B"

    mock_403 = MagicMock()
    mock_403.status_code = 403
    mock_403.text = "forbidden"

    with patch.object(bp, "GOOGLE_KEY", "fake-key"), patch.object(bp, "GOOGLE_CSE_CX", "fake-cx"):
        with patch("backend.processors.base_processor.requests.get", return_value=mock_403):
            assert a._google_custom_search_urls("query") == []
        assert bp._SEARCH_DISABLED_BY_TENANT.get("tenant-A") is True
        assert bp._SEARCH_DISABLED_BY_TENANT.get("tenant-B") is None

        mock_200 = MagicMock()
        mock_200.status_code = 200
        mock_200.json.return_value = {"items": [{"link": "https://example.com"}]}
        with patch("backend.processors.base_processor.requests.get", return_value=mock_200):
            urls = b._google_custom_search_urls("query")
        assert urls == ["https://example.com"]

    bp._SEARCH_DISABLED_BY_TENANT.clear()


def test_rag_default_db_path_isolated_by_tenant(tmp_path, monkeypatch):
    # Point Databases under tools package via default_db_path structure — call method directly
    path_a = LocalRAGEngine.default_db_path("session-AAA")
    path_b = LocalRAGEngine.default_db_path("session-BBB")
    path_local = LocalRAGEngine.default_db_path(None)
    assert path_a != path_b
    assert "local_rag__session-AAA.db" in path_a
    assert "local_rag__session-BBB.db" in path_b
    assert path_local.endswith("local_rag.db")
    assert "__" not in os.path.basename(path_local)


def test_rag_db_follows_ignite_data_dir(tmp_path, monkeypatch):
    """ACA: RAG must live on the /data mount, not the ephemeral container layer."""
    monkeypatch.setenv("IGNITE_DATA_DIR", str(tmp_path))
    path = LocalRAGEngine.default_db_path("session-CCC")
    assert path == str(tmp_path / "Databases" / "vector_store" / "local_rag__session-CCC.db")


def test_rag_db_frozen_desktop_uses_localappdata(tmp_path, monkeypatch):
    """Frozen desktop must not put RAG next to the exe (Program Files is wiped on reinstall)."""
    monkeypatch.delenv("IGNITE_DATA_DIR", raising=False)
    local = tmp_path / "LocalAppData"
    local.mkdir()
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "Programs" / "Ignite Chat" / "Ignite Chat.exe"))
    path = LocalRAGEngine.default_db_path(None)
    assert path == str(local / "Ignite Chat" / "Databases" / "vector_store" / "local_rag.db")


def test_rag_db_defaults_next_to_other_databases(monkeypatch):
    """Desktop: keep app/Databases so .dockerignore and the module docstring stay true."""
    monkeypatch.delenv("IGNITE_DATA_DIR", raising=False)
    path = LocalRAGEngine.default_db_path(None)
    parent = os.path.dirname(os.path.dirname(path))
    assert os.path.basename(parent) == "Databases"
    assert os.path.basename(os.path.dirname(parent)) == "app"


def test_rag_engines_do_not_share_indexed_docs(tmp_path):
    db_a = tmp_path / "rag_a.db"
    db_b = tmp_path / "rag_b.db"
    eng_a = LocalRAGEngine(db_path=str(db_a), tenant_key="A")
    eng_b = LocalRAGEngine(db_path=str(db_b), tenant_key="B")
    assert eng_a.index_document("secret-a", "tenant A confidential payroll data")
    results_b = eng_b.search_relevant_context("payroll confidential", top_k=3)
    assert results_b == []
    results_a = eng_a.search_relevant_context("payroll confidential", top_k=3)
    assert len(results_a) >= 1
