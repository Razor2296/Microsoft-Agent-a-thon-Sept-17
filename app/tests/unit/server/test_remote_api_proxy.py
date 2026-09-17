"""Unit tests for the thin desktop remote proxy."""

from main.remote_api_proxy import RemotePyWebViewApi


def test_remote_proxy_builds_headers_with_api_key_and_session(monkeypatch, tmp_path):
    monkeypatch.setenv("IGNITE_SESSION_ID", "sess_desktop_client_01")
    monkeypatch.setenv("IGNITE_SESSION_FILE", str(tmp_path / "sid.txt"))
    api = RemotePyWebViewApi(base_url="http://example.test", api_key="secret")
    headers = api._headers()
    assert headers["X-API-Key"] == "secret"
    assert headers["Content-Type"] == "application/json"
    assert headers["X-Ignite-Session-Id"] == "sess_desktop_client_01"


def test_open_file_path_rejects_local_server_paths(monkeypatch, tmp_path):
    monkeypatch.setenv("IGNITE_SESSION_FILE", str(tmp_path / "sid.txt"))
    api = RemotePyWebViewApi(base_url="http://example.test", api_key="")
    result = api.open_file_path(r"C:\server\log\file.txt")
    assert result["status"] == "error"
