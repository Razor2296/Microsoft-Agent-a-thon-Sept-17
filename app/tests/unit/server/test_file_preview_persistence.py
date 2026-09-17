"""Server layer: attachment preview fields survive preprocess and session save."""
from __future__ import annotations

import base64
from pathlib import Path

from main.api import PyWebViewApi, _clean_history_for_frontend, _clean_history_for_saving


class TestPreprocessForwardsPreviewFields:
    def test_pdf_preview_metadata_copied_onto_processed_file(self):
        api = PyWebViewApi()
        result = api._preprocess_input(
            text="analiza esto",
            files=[
                {
                    "name": "form.pdf",
                    "mime_type": "application/pdf",
                    "base64": "JVBERi0xLjQ=",
                    "size": 2048,
                    "preview_id": "fp_1",
                    "preview_base64": "thumb",
                    "preview_mime": "image/jpeg",
                    "page_count": 2,
                }
            ],
            from_mic=False,
            language="es-MX",
            chat=None,
            provider_for_fallback="Gemini",
            history=[],
        )
        saved = result["files"][0]
        assert saved["name"] == "form.pdf"
        assert saved["preview_base64"] == "thumb"
        assert saved["page_count"] == 2
        assert saved["preview_id"] == "fp_1"
        assert saved["size"] == 2048
        assert saved["bytes"]

    def test_missing_page_count_does_not_break_preprocess(self):
        api = PyWebViewApi()
        result = api._preprocess_input(
            text="doc",
            files=[
                {
                    "name": "notes.pdf",
                    "mime_type": "application/pdf",
                    "base64": base64.b64encode(b"%PDF-1.4").decode(),
                }
            ],
            from_mic=False,
            language="en-US",
            chat=None,
            provider_for_fallback="Gemini",
            history=[],
        )
        saved = result["files"][0]
        assert saved["page_count"] is None
        assert saved["bytes"]
        assert result["error"] is None


class TestLocalMediaUrlForPreview:
    def test_get_local_file_media_url_returns_file_uri(self, tmp_path: Path):
        audio = tmp_path / "sample.m4a"
        audio.write_bytes(b"fake-audio")
        api = PyWebViewApi()
        res = api.get_local_file_media_url(str(audio))
        assert res["status"] == "success"
        assert res["url"].startswith("file:")
        assert "sample.m4a" in res["url"].replace("%20", " ")


class TestGeneratedOfficePathSurvivesPipeline:
    def test_path_forwarded_and_bytes_loaded_from_disk(self, tmp_path: Path):
        doc_path = tmp_path / "Informe_Gemini_20260101.docx"
        payload = b"PK\x03\x04fake-docx-bytes"
        doc_path.write_bytes(payload)

        api = PyWebViewApi()
        result = api._preprocess_input(
            text="",
            files=[
                {
                    "name": doc_path.name,
                    "mime_type": (
                        "application/vnd.openxmlformats-officedocument."
                        "wordprocessingml.document"
                    ),
                    "size": len(payload),
                    "path": str(doc_path),
                }
            ],
            from_mic=False,
            language="es-MX",
            chat=None,
            provider_for_fallback="Gemini",
            history=[],
        )
        saved = result["files"][0]
        assert saved["path"] == str(doc_path)
        assert saved["bytes"] == payload

        history = [
            {
                "role": "assistant",
                "content": "Listo.",
                "files": [
                    {
                        "name": doc_path.name,
                        "mime_type": saved["mime_type"],
                        "path": str(doc_path),
                        "size": len(payload),
                        "preview_id": "fp_gen_1",
                        "preview_base64": "THUMB",
                        "preview_mime": "image/jpeg",
                    }
                ],
            }
        ]
        persisted = _clean_history_for_saving(history)
        front = _clean_history_for_frontend(persisted)
        reloaded = front[0]["files"][0]
        assert reloaded["path"] == str(doc_path)
        assert reloaded["preview_base64"] == "THUMB"
        assert "base64" not in reloaded
        assert "bytes" not in reloaded

    def test_resolve_attachment_bytes_reads_path_when_no_base64(self, tmp_path: Path):
        doc_path = tmp_path / "sheet.xlsx"
        raw = b"PK\x03\x04excel"
        doc_path.write_bytes(raw)
        api = PyWebViewApi()
        data = api._resolve_attachment_bytes({"path": str(doc_path), "name": "sheet.xlsx"})
        assert data == raw


class TestHistoryReloadKeepsThumbnail:
    def test_save_and_frontend_clean_drop_full_bytes_keep_first_page(self):
        api = PyWebViewApi()
        preprocess = api._preprocess_input(
            text="analiza este formulario",
            files=[
                {
                    "name": "REGISTRATION_FORM_FALL_2026.pdf",
                    "mime_type": "application/pdf",
                    "base64": "JVBERi0xLjQ=",
                    "size": 245760,
                    "preview_id": "fp_reload_1",
                    "preview_base64": "FIRST_PAGE_JPEG",
                    "preview_mime": "image/jpeg",
                    "page_count": 2,
                }
            ],
            from_mic=False,
            language="es-MX",
            chat=None,
            provider_for_fallback="Gemini",
            history=[],
        )
        live = preprocess["files"][0]
        history = [
            {
                "role": "user",
                "content": "analiza este formulario",
                "files": [
                    {
                        "name": live["name"],
                        "mime_type": live["mime_type"],
                        "base64": "FULL_PDF_NOT_FOR_DOM",
                        "bytes": live["bytes"],
                        "preview_id": live["preview_id"],
                        "preview_base64": live["preview_base64"],
                        "preview_mime": live["preview_mime"],
                        "page_count": live["page_count"],
                        "size": live["size"],
                    }
                ],
            }
        ]
        saved = _clean_history_for_saving(history)
        front = _clean_history_for_frontend(saved)
        reloaded = front[0]["files"][0]
        assert "base64" not in reloaded
        assert "bytes" not in reloaded
        assert reloaded["preview_base64"] == "FIRST_PAGE_JPEG"
        assert reloaded["page_count"] == 2
        assert reloaded["name"] == "REGISTRATION_FORM_FALL_2026.pdf"
