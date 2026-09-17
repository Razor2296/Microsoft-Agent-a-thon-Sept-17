"""Regression: sendMessage filesForUi must not put full PDF/Office base64 in the bubble DOM.

Mirror of app/frontend/js/api.js buildFilesForUi (inside sendMessage). Keep in sync
when that branch changes — same pattern as test_office_file_kind_js.py.
"""
from __future__ import annotations

from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[3]
API_JS = APP_ROOT / "frontend" / "js" / "api.js"


def build_files_for_ui_mirror(files: list[dict]) -> list[dict]:
    """Python mirror of buildFilesForUi in api.js (no rememberFileForPreview side effects)."""
    out: list[dict] = []
    for f in files:
        mime = (f.get("mime_type") or "").lower()
        name = f.get("name") or ""
        if mime.startswith("image/") or mime.startswith("video/") or name.startswith(
            "Voice_Message_"
        ):
            out.append(dict(f))
            continue
        out.append(
            {
                "name": f.get("name"),
                "mime_type": f.get("mime_type"),
                "size": f.get("size"),
                "path": f.get("path"),
                "preview_id": f.get("preview_id"),
                "preview_base64": f.get("preview_base64"),
                "preview_mime": f.get("preview_mime"),
                "page_count": f.get("page_count"),
            }
        )
    return out


class TestFilesForUiStripRegression:
    def test_pdf_omits_full_base64_keeps_thumbnail_metadata(self):
        huge = "A" * 500_000
        ui = build_files_for_ui_mirror(
            [
                {
                    "name": "book.pdf",
                    "mime_type": "application/pdf",
                    "base64": huge,
                    "size": len(huge),
                    "preview_id": "fp_reg_1",
                    "preview_base64": "THUMB",
                    "preview_mime": "image/jpeg",
                    "page_count": 120,
                }
            ]
        )[0]
        assert "base64" not in ui
        assert ui["preview_base64"] == "THUMB"
        assert ui["preview_id"] == "fp_reg_1"
        assert ui["page_count"] == 120

    def test_office_keeps_path_without_base64(self):
        ui = build_files_for_ui_mirror(
            [
                {
                    "name": "Informe.docx",
                    "mime_type": (
                        "application/vnd.openxmlformats-officedocument."
                        "wordprocessingml.document"
                    ),
                    "path": r"C:\Ignite\generated\Informe.docx",
                    "size": 4096,
                    "preview_id": "fp_gen",
                }
            ]
        )[0]
        assert "base64" not in ui
        assert ui["path"].endswith("Informe.docx")

    def test_image_and_voice_keep_full_payload(self):
        img = build_files_for_ui_mirror(
            [
                {
                    "name": "photo.png",
                    "mime_type": "image/png",
                    "base64": "abc",
                }
            ]
        )[0]
        assert img["base64"] == "abc"

        voice = build_files_for_ui_mirror(
            [
                {
                    "name": "Voice_Message_123.webm",
                    "mime_type": "audio/webm",
                    "base64": "voice-bytes",
                }
            ]
        )[0]
        assert voice["base64"] == "voice-bytes"


class TestSendBubbleBeforeBackgroundHydrate:
    """User bubble must render before pdf.js hydrate (send must not feel stuck)."""

    def test_append_message_precedes_hydrate_loop_in_send_message(self):
        code = API_JS.read_text(encoding="utf-8")
        start = code.find("async function sendMessage")
        assert start != -1
        block = code[start : start + 12000]
        append_pos = block.find("appendMessage('user'")
        hydrate_pos = block.find("hydrateFilePreview(hydrated[i])")
        assert append_pos != -1, "appendMessage('user') missing from sendMessage"
        assert hydrate_pos != -1, "background hydrate loop missing from sendMessage"
        assert append_pos < hydrate_pos
