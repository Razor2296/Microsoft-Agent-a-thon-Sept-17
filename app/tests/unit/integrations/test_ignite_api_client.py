"""
app/tests/unit/integrations/test_ignite_api_client.py
Unit tests for IgniteAPIClient & ignite_rag_transformer.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import httpx
import pytest

from backend.integrations.ignite_api_client import IgniteAPIClient
from backend.integrations.ignite_rag_transformer import extraction_to_rag_chunks, extraction_to_rag_text


def test_detect_channel():
    assert IgniteAPIClient.detect_channel("document.pdf") == "doc"
    assert IgniteAPIClient.detect_channel("contract.docx") == "doc"
    assert IgniteAPIClient.detect_channel("audio.mp3") == "audio"
    assert IgniteAPIClient.detect_channel("voice.wav") == "audio"
    assert IgniteAPIClient.detect_channel("photo.png") == "image"
    assert IgniteAPIClient.detect_channel("scan.jpg") == "image"
    assert IgniteAPIClient.detect_channel("recording.mp4") == "video"
    assert IgniteAPIClient.detect_channel("movie.mkv") == "video"
    assert IgniteAPIClient.detect_channel("unknown.xyz") == "doc"


def test_extraction_to_rag_text_blends_model_reasoning():
    sample_response = {
        "template_used": "Medical_Prescription",
        "is_multi_row": False,
        "extracted_info": {
            "row_1": {
                "Nombre_Paciente": {
                    "code": "001",
                    "value": "Juan Escutia",
                    "confidence": 95,
                    "reasoning": "Nombre claro indicado en texto junto a 'paciente'.",
                    "mandatory": True,
                },
                "Nombre_Medico": {
                    "code": "004",
                    "value": "NO_ENCONTRADO",
                    "confidence": 0,
                    "reasoning": "No se especifica nombre ni especialidad del médico.",
                    "mandatory": True,
                },
            }
        },
        "metadata": {
            "file_name": "receta.mp3",
            "llm_provider": "azure_openai",
            "model_used": "gpt-4.1-mini",
            "duration_seconds": 9.67,
            "tokens_consumed": {"total_tokens": 2198},
        },
    }

    text = extraction_to_rag_text(sample_response, "receta.mp3")

    # Verify model and provider metadata presence
    assert "azure_openai (gpt-4.1-mini)" in text
    assert "Medical_Prescription" in text

    # Verify values and mandatory status
    assert "Juan Escutia" in text
    assert "Confianza: 95%" in text

    # Verify explicit reasoning blending per model requirement
    assert "Razonamiento (gpt-4.1-mini): Nombre claro indicado en texto junto a 'paciente'." in text
    assert "Razonamiento (gpt-4.1-mini): No se especifica nombre ni especialidad del médico." in text
    assert "⚠️ CAMPOS REQUERIDOS FALTANTES:" in text


def test_extraction_to_rag_chunks_multi_row():
    sample_multi_row = {
        "template_used": "Invoice_Standard",
        "is_multi_row": True,
        "extracted_info": {
            "row_1": {
                "Item": {"value": "Laptop", "confidence": 90, "reasoning": "Laptop listed in row 1", "mandatory": True}
            },
            "row_2": {
                "Item": {"value": "Mouse", "confidence": 95, "reasoning": "Mouse listed in row 2", "mandatory": True}
            },
        },
        "metadata": {
            "llm_provider": "gemini",
            "model_used": "gemini-2.5-flash",
        },
    }

    chunks = extraction_to_rag_chunks(sample_multi_row, "invoice.pdf")
    assert len(chunks) == 2

    doc_id_1, text_1, meta_1 = chunks[0]
    doc_id_2, text_2, meta_2 = chunks[1]

    assert "row_1" in doc_id_1
    assert "Laptop" in text_1
    assert "Razonamiento (gemini-2.5-flash): Laptop listed in row 1" in text_1
    assert meta_1["template_used"] == "Invoice_Standard"

    assert "row_2" in doc_id_2
    assert "Mouse" in text_2
    assert "Razonamiento (gemini-2.5-flash): Mouse listed in row 2" in text_2


def test_client_disabled_returns_none():
    client = IgniteAPIClient(enabled=False)
    res = asyncio.run(client.extract(b"dummy content", "test.pdf", "Invoice_Standard"))
    assert res is None


def test_client_empty_bytes_returns_none():
    client = IgniteAPIClient(enabled=True, api_key="secret")
    res = asyncio.run(client.extract(b"", "test.pdf", "Invoice_Standard"))
    assert res is None


def test_client_handles_sync_200_success():
    client = IgniteAPIClient(enabled=True, api_url="http://mock-ignite-api", api_key="test-key")
    mock_payload = {
        "template_used": "Invoice_Standard",
        "is_multi_row": False,
        "extracted_info": {"row_1": {"total": {"value": "$100"}}},
        "metadata": {"duration_seconds": 1.5},
    }

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = mock_payload

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp
        res = asyncio.run(client.extract(b"data", "test.pdf", "Invoice_Standard"))

    assert res == mock_payload
    assert client.last_error is None
    mock_post.assert_called_once()
    assert mock_post.call_args.kwargs.get("params") == {"mode": "auto"}


def test_client_handles_403_forbidden():
    client = IgniteAPIClient(enabled=True, api_url="http://mock-ignite-api", api_key="invalid-key")

    mock_resp = MagicMock()
    mock_resp.status_code = 403
    mock_resp.text = "Forbidden: Invalid API Key"

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp
        res = asyncio.run(client.extract(b"data", "test.pdf", "Invoice_Standard"))

    assert res is None
    assert client.last_error == "http"


def test_client_handles_400_bad_request():
    client = IgniteAPIClient(enabled=True, api_url="http://mock-ignite-api", api_key="valid-key")

    mock_resp = MagicMock()
    mock_resp.status_code = 400
    mock_resp.text = "Bad Request: Unsupported format"

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp
        res = asyncio.run(client.extract(b"data", "test.xyz", "Invoice_Standard"))

    assert res is None
    assert client.last_error == "http"


def test_client_handles_network_timeout():
    client = IgniteAPIClient(enabled=True, api_url="http://mock-ignite-api", api_key="valid-key", max_wait=5)

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.side_effect = httpx.TimeoutException("Connection timed out")
        res = asyncio.run(client.extract(b"data", "test.pdf", "Invoice_Standard"))

    assert res is None
    assert client.last_error == "timeout"


def test_client_handles_read_timeout_on_sync_post():
    """Regression: small docs under sync threshold can still exceed old 120s read budget."""
    client = IgniteAPIClient(
        enabled=True,
        api_url="http://mock-ignite-api",
        api_key="valid-key",
        max_wait=300,
        connect_timeout=30,
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.side_effect = httpx.ReadTimeout("The read operation timed out")
        res = asyncio.run(client.extract(b"x" * 12751, "test_bank_statement.xlsx", "Bank_Statement"))

    assert res is None
    assert client.last_error == "timeout"
    hint = IgniteAPIClient.user_failure_hint("test_bank_statement.xlsx", client.last_error)
    assert "timed out" in hint


def test_extraction_enabled_defaults_true_when_env_unset(monkeypatch):
    monkeypatch.delenv("IGNITE_EXTRACTION_ENABLED", raising=False)
    client = IgniteAPIClient(api_key="k")
    assert client.enabled is True


def test_user_failure_hint_french_timeout():
    hint = IgniteAPIClient.user_failure_hint("doc.xlsx", "timeout", "fr-FR")
    assert "expiré" in hint.lower() or "expir" in hint.lower()
    assert "timed out" not in hint.lower()


def test_client_default_max_wait_is_300(monkeypatch):
    monkeypatch.delenv("IGNITE_EXTRACTION_MAX_WAIT", raising=False)
    client = IgniteAPIClient(enabled=True, api_key="k")
    assert client.max_wait == 300.0


def test_client_httpx_timeout_splits_connect_write_read():
    client = IgniteAPIClient(
        enabled=True,
        api_key="k",
        max_wait=300,
        connect_timeout=30,
        write_timeout=60,
    )
    t = client._httpx_timeout()
    assert t.connect == 30
    assert t.write == 60
    assert t.read == 300


def test_client_handles_async_202_completed_job():
    client = IgniteAPIClient(
        enabled=True,
        api_url="http://mock-ignite-api",
        api_key="valid-key",
        poll_interval=0.01,
        max_wait=5,
    )

    accept_resp = MagicMock()
    accept_resp.status_code = 202
    accept_resp.json.return_value = {"job_id": "job_12345", "status": "processing"}

    job_result = {
        "template_used": "Meeting_Minutes",
        "extracted_info": {"row_1": {"summary": {"value": "Action items discussed"}}},
        "metadata": {"duration_seconds": 12.3},
    }
    poll_resp = MagicMock()
    poll_resp.status_code = 200
    poll_resp.json.return_value = {"status": "completed", "result": job_result}

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = accept_resp
        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = poll_resp
            res = asyncio.run(client.extract(b"audio-data", "meeting.mp3", "Meeting_Minutes"))

    assert res == job_result
    assert mock_post.call_args.kwargs.get("params") == {"mode": "auto"}


def test_client_handles_async_202_via_runtime_status():
    client = IgniteAPIClient(
        enabled=True,
        api_url="http://mock-ignite-api",
        api_key="valid-key",
        poll_interval=0.01,
        max_wait=5,
    )

    accept_resp = MagicMock()
    accept_resp.status_code = 202
    accept_resp.json.return_value = {"job_id": "job_rt", "runtimeStatus": "Running"}

    job_result = {"template_used": "Bank_Statement", "extracted_info": {}}
    poll_resp = MagicMock()
    poll_resp.status_code = 200
    poll_resp.json.return_value = {"runtimeStatus": "Completed", "result": job_result}

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = accept_resp
        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = poll_resp
            res = asyncio.run(client.extract(b"sheet", "bank.xlsx", "Bank_Statement"))

    assert res == job_result


def test_client_handles_async_202_failed_job():
    client = IgniteAPIClient(
        enabled=True,
        api_url="http://mock-ignite-api",
        api_key="valid-key",
        poll_interval=0.01,
        max_wait=5,
    )

    accept_resp = MagicMock()
    accept_resp.status_code = 202
    accept_resp.json.return_value = {"job_id": "job_99999", "status": "processing"}

    poll_resp = MagicMock()
    poll_resp.status_code = 200
    poll_resp.json.return_value = {"status": "failed", "error": "Transcription failed"}

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = accept_resp
        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = poll_resp
            res = asyncio.run(client.extract(b"audio-data", "meeting.mp3", "Meeting_Minutes"))

    assert res is None
    assert client.last_error == "poll"


def test_extract_sync_wrapper():
    client = IgniteAPIClient(enabled=True, api_url="http://mock-ignite-api", api_key="valid-key")

    mock_payload = {
        "template_used": "Invoice_Standard",
        "extracted_info": {"row_1": {"total": {"value": "$500"}}},
    }

    with patch.object(client, "extract", new_callable=AsyncMock) as mock_async_extract:
        mock_async_extract.return_value = mock_payload
        result = client.extract_sync(b"test-bytes", "invoice.pdf", "Invoice_Standard")

    assert result == mock_payload

