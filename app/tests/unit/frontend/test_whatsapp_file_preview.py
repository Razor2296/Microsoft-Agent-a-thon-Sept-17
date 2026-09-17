"""Frontend layer: thin chrome locks for WhatsApp-style file preview (§11.5 / §12.8).

These tests assert shipping HTML/CSS/i18n contracts only — not JS execution.
Behavioral coverage lives in unit/server/test_file_preview_persistence.py.
"""
from __future__ import annotations

from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[3]
FRONTEND = APP_ROOT / "frontend"


def _read(*parts: str) -> str:
    return (FRONTEND.joinpath(*parts)).read_text(encoding="utf-8")


class TestPdfJsBundledForDesktop:
    def test_files_js_points_at_vendor_not_cdn(self):
        code = _read("js", "files.js")
        assert "vendor/pdfjs/pdf.min.js" in code
        assert "cdn.jsdelivr.net/npm/pdfjs-dist" not in code

    def test_local_pdfjs_assets_exist(self):
        vendor = FRONTEND / "vendor" / "pdfjs"
        for name in ("pdf.min.js", "pdf.worker.min.js"):
            path = vendor / name
            assert path.is_file(), f"missing bundled {name}"
            assert path.stat().st_size > 10_000, f"{name} looks empty"


class TestFilePreviewOverlayChrome:
    """Overlay shell must exist in index.html and chat.css."""

    OVERLAY_IDS = (
        "file-preview-overlay",
        "file-preview-stage",
        "file-preview-thumbs",
        "file-preview-close",
        "file-preview-download",
    )

    def test_overlay_ids_in_html(self):
        html = _read("index.html")
        for elem_id in self.OVERLAY_IDS:
            assert f'id="{elem_id}"' in html, f"missing #{elem_id} in index.html"

    def test_wa_card_styles_in_chat_css(self):
        css = _read("css", "chat.css")
        assert ".wa-file-card" in css
        assert ".file-preview-overlay" in css


class TestPreviewTranslationsEnEs:
    def test_file_preview_keys_in_en_and_es(self):
        code = _read("js", "translations.js")
        for key in (
            "file_preview_close",
            "file_preview_download",
            "file_preview_page",
            "file_preview_pages",
            "file_preview_unavailable",
            "file_preview_open_native",
        ):
            assert code.count(f'"{key}"') >= 2, f"{key} must exist in en and es"


class TestOverlayDownloadUsesNativeBridge:
    """PyWebView/WebView2 blocks <a download>; overlay must use save_file_to_downloads."""

    def test_download_remembered_file_calls_native_bridge(self):
        files_js = _read("js", "files.js")
        assert "function downloadRememberedFile" in files_js
        download_idx = files_js.find("function downloadRememberedFile")
        block = files_js[download_idx : download_idx + 1800]
        assert "save_file_to_downloads" in block
        assert "triggerBrowserDownload" in files_js

    def test_pdf_overlay_uses_pdfjs_canvas_not_blob_iframe(self):
        files_js = _read("js", "files.js")
        css = _read("css", "chat.css")
        assert "function renderPdfPagesInto" in files_js
        assert "file-preview-pdf-pages" in files_js
        assert "file-preview-pdf-pages" in css
        assert "openPdfDocument" in files_js
        paint_idx = files_js.find("async function paintWhatsAppFileViewer")
        paint = files_js[paint_idx : paint_idx + 3500]
        assert "renderPdfPagesInto" in paint
        assert "frame.src = url" not in paint

    def test_audio_overlay_uses_html5_audio_and_local_path(self):
        files_js = _read("js", "files.js")
        assert "function isAudioFile" in files_js
        assert "resolveMediaPlaybackUrl" in files_js
        assert "get_local_file_media_url" in files_js
        paint_idx = files_js.find("async function paintWhatsAppFileViewer")
        paint = files_js[paint_idx : paint_idx + 3500]
        assert "createElement('audio')" in paint
        assert "file-preview-audio" in paint


class TestGeneratedDocNativeOpenLock:
    """Assistant-generated docs keep path + openAttachmentFile fallback."""

    def test_open_attachment_file_and_path_on_cards(self):
        chat_js = _read("js", "chat.js")
        files_js = _read("js", "files.js")
        assert "window.openAttachmentFile" in chat_js
        assert "open_file_path" in chat_js
        assert "data-path" in files_js
        assert "shouldOpenNativePathOnly" in files_js


class TestVoiceMessageExcludedFromDocCards:
    def test_voice_chip_hidden_from_attachment_cards(self):
        chat_js = _read("js", "chat.js")
        assert "Voice_Message_" in chat_js
        idx = chat_js.find("function buildMessageAttachmentsHTML")
        assert idx != -1
        block = chat_js[idx : idx + 2500]
        assert "Voice_Message_" in block
        assert "buildWhatsAppAttachmentCardHTML" in block
