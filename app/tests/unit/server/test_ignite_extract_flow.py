"""Ignite API extract hook: attachment matching + extract_sync invocation from LLM tag."""
from __future__ import annotations

from main.api import PyWebViewApi


class TestMatchAttachmentForExtract:
    def test_exact_filename_match(self):
        api = PyWebViewApi()
        data, name = api._match_attachment_for_extract(
            "Invoice-UJJJRFP7-0002.pdf",
            [{"name": "Invoice-UJJJRFP7-0002.pdf", "bytes": b"%PDF-1.4"}],
        )
        assert data == b"%PDF-1.4"
        assert name == "Invoice-UJJJRFP7-0002.pdf"

    def test_single_attachment_fallback_when_llm_name_wrong(self):
        api = PyWebViewApi()
        data, name = api._match_attachment_for_extract(
            "Receta_Medica_Curay.png",
            [{"name": "scan_factura_001.png", "bytes": b"\x89PNG"}],
        )
        assert data == b"\x89PNG"
        assert name == "scan_factura_001.png"

    def test_base64_payload_from_frontend(self):
        api = PyWebViewApi()
        import base64

        raw = b"hello-pdf"
        data, name = api._match_attachment_for_extract(
            "doc.pdf",
            [{"name": "doc.pdf", "base64": base64.b64encode(raw).decode()}],
        )
        assert data == raw


class TestApplyIgniteExtractFromReply:
    def test_calls_extract_sync_and_returns_success_chrome(self, monkeypatch):
        api = PyWebViewApi()
        calls = []

        class _FakeClient:
            enabled = True
            last_error = None

            def extract_sync(self, file_bytes, filename, template_name, **kwargs):
                calls.append((filename, template_name, len(file_bytes)))
                return {
                    "template_used": template_name,
                    "is_multi_row": False,
                    "extracted_info": {"row_1": {"field": {"value": "x"}}},
                    "metadata": {"file_name": filename},
                }

        monkeypatch.setattr("main.api.IgniteAPIClient", lambda: _FakeClient())

        reply = "Analizo la factura.\n[IGNITE_EXTRACT: Invoice.pdf|Invoice_Standard]"
        out = api._apply_ignite_extract_from_reply(
            reply,
            [{"name": "Invoice.pdf", "bytes": b"%PDF"}],
            "es-MX",
            request_id="req-test-1",
        )
        assert len(calls) == 1
        assert calls[0][0] == "Invoice.pdf"
        assert calls[0][1] == "Invoice_Standard"
        assert calls[0][2] > 0
        assert "Invoice_Standard" in out or "extracción" in out.lower() or "indexed" in out.lower()

    def test_no_nameerror_when_request_id_none(self, monkeypatch):
        api = PyWebViewApi()

        class _FakeClient:
            enabled = True
            last_error = None

            def extract_sync(self, *a, **k):
                return {"template_used": "T", "extracted_info": {}, "metadata": {}}

        monkeypatch.setattr("main.api.IgniteAPIClient", lambda: _FakeClient())
        reply = "[IGNITE_EXTRACT: a.pdf|Invoice_Standard]"
        api._apply_ignite_extract_from_reply(
            reply,
            [{"name": "a.pdf", "bytes": b"x"}],
            "en-US",
            request_id=None,
        )

    def test_multiple_llm_tags_extract_both_pdfs(self, monkeypatch):
        api = PyWebViewApi()
        calls = []

        class _FakeClient:
            enabled = True
            last_error = None

            def extract_sync(self, file_bytes, filename, template_name, **kwargs):
                calls.append((filename, template_name))
                return {
                    "template_used": template_name,
                    "extracted_info": {},
                    "metadata": {"file_name": filename},
                }

        monkeypatch.setattr("main.api.IgniteAPIClient", lambda: _FakeClient())
        reply = (
            "Summary here.\n"
            "[IGNITE_EXTRACT: a.pdf|Invoice_Standard]\n"
            "[IGNITE_EXTRACT: b.pdf|Invoice_Standard]"
        )
        out = api._apply_ignite_extract_from_reply(
            reply,
            [
                {"name": "a.pdf", "bytes": b"%PDF-a"},
                {"name": "b.pdf", "bytes": b"%PDF-b"},
            ],
            "en-US",
            request_id="req-multi",
        )
        assert len(calls) == 2
        assert {c[0] for c in calls} == {"a.pdf", "b.pdf"}
        assert "[IGNITE_EXTRACT:" not in out

    def test_auto_extract_when_user_asks_analyze_two_receipts_no_tag(self, monkeypatch):
        api = PyWebViewApi()
        calls = []

        class _FakeClient:
            enabled = True
            last_error = None

            def extract_sync(self, file_bytes, filename, template_name, **kwargs):
                calls.append((filename, template_name))
                return {
                    "template_used": template_name,
                    "extracted_info": {},
                    "metadata": {},
                }

        monkeypatch.setattr("main.api.IgniteAPIClient", lambda: _FakeClient())
        reply = "Here is a quick summary of both receipts."
        out = api._apply_ignite_extract_from_reply(
            reply,
            [
                {"name": "Receipt-1.pdf", "bytes": b"%PDF-1"},
                {"name": "receipt_2.pdf", "bytes": b"%PDF-2"},
            ],
            "en-US",
            request_id="req-auto",
            user_text="Analyze those invoice receipts please",
        )
        assert len(calls) == 2
        assert all(c[1] == "Invoice_Standard" for c in calls)
        assert "Structured analysis" in out or "summary" in out


class TestIgniteLlmProviderMapping:
    def test_maps_gemini_active_model_to_extract_sync(self, monkeypatch):
        api = PyWebViewApi()
        api._current_model = {"Gemini": "gemini-3.5-flash"}
        calls = []

        class _FakeClient:
            enabled = True
            last_error = None

            def extract_sync(self, file_bytes, filename, template_name, **kwargs):
                calls.append(kwargs)
                return {"template_used": template_name, "extracted_info": {}, "metadata": {}}

        monkeypatch.setattr("main.api.IgniteAPIClient", lambda: _FakeClient())
        api._apply_ignite_extract_from_reply(
            "[IGNITE_EXTRACT: a.pdf|Invoice_Standard]",
            [{"name": "a.pdf", "bytes": b"%PDF"}],
            "es-MX",
            chat_provider="Gemini",
            chat_model="gemini-3.5-flash",
        )
        assert calls[0].get("llm_provider") == "gemini"
        assert calls[0].get("model") == "gemini-3.5-flash"
