"""Regression: sent-file preview ships as one vertical slice (no follow-up-only assets).

If files.js references wa-file-card / vendor pdf.js, the rest of the feature MUST exist
in the same tree — avoids installing a half-feature build (UI without pdf.js, etc.).
"""
from __future__ import annotations

from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[3]
FRONTEND = APP_ROOT / "frontend"
API_PY = APP_ROOT / "main" / "api.py"


def _read(*parts: str) -> str:
    return FRONTEND.joinpath(*parts).read_text(encoding="utf-8")


class TestFilePreviewVerticalSlice:
    REQUIRED_OVERLAY_IDS = (
        "file-preview-overlay",
        "file-preview-stage",
        "file-preview-thumbs",
    )

    def test_preview_ui_assets_and_scripts_present(self):
        html = _read("index.html")
        files_js = _read("js", "files.js")
        chat_js = _read("js", "chat.js")
        api_js = _read("js", "api.js")
        css = _read("css", "chat.css")

        assert "buildWhatsAppAttachmentCardHTML" in files_js
        assert "wa-file-card" in css
        for elem_id in self.REQUIRED_OVERLAY_IDS:
            assert f'id="{elem_id}"' in html
        assert "buildWhatsAppAttachmentCardHTML" in chat_js
        assert "refreshMessageAttachments" in chat_js
        assert "buildFilesForUi" in api_js or "preview_base64" in api_js
        assert "save_file_to_downloads" in files_js
        assert "renderPdfPagesInto" in files_js

    def test_bundled_pdfjs_when_hydrate_enabled(self):
        files_js = _read("js", "files.js")
        assert "hydrateFilePreview" in files_js
        assert "vendor/pdfjs/pdf.min.js" in files_js
        vendor = FRONTEND / "vendor" / "pdfjs"
        assert (vendor / "pdf.min.js").stat().st_size > 10_000
        assert (vendor / "pdf.worker.min.js").stat().st_size > 10_000

    def test_server_forwards_preview_and_path(self):
        api_src = API_PY.read_text(encoding="utf-8")
        assert "preview_base64" in api_src
        assert '"path"' in api_src or "'path'" in api_src
