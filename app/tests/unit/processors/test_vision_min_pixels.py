"""Skip tiny PDF/DOCX logos before Grok multimodal (invalid_image when pixels < 512)."""
import io

from PIL import Image

from backend.processors.base_processor import BaseChat, vision_min_image_pixels


def _png_bytes(width: int, height: int) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), color=(200, 40, 40)).save(buf, format="PNG")
    return buf.getvalue()


def test_vision_min_image_pixels_default():
    assert vision_min_image_pixels() == 512


def test_tiny_logo_not_viable(monkeypatch):
    monkeypatch.delenv("IGNITE_VISION_MIN_IMAGE_PIXELS", raising=False)
    chat = BaseChat()
    tiny = _png_bytes(24, 20)  # 480 px — Grok rejects
    assert chat._image_pixel_count(tiny) == 480
    assert chat._is_vision_api_image_viable(tiny, name="usil_logo.png") is False
    assert chat._prepare_image_for_vision_api(tiny, name="usil_logo.png") is None


def test_viable_image_passes_prepare(monkeypatch):
    monkeypatch.delenv("IGNITE_VISION_MIN_IMAGE_PIXELS", raising=False)
    chat = BaseChat()
    ok = _png_bytes(32, 32)  # 1024 px
    prepared = chat._prepare_image_for_vision_api(ok, mime_type="image/png", name="shot.png")
    assert prepared is not None
    payload, mime = prepared
    assert mime.startswith("image/")
    assert chat._image_pixel_count(payload) >= 512


def test_docx_extract_skips_tiny_keeps_large(monkeypatch):
    monkeypatch.delenv("IGNITE_VISION_MIN_IMAGE_PIXELS", raising=False)
    import zipfile

    chat = BaseChat()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("word/document.xml", "<w:document/>")
        zf.writestr("word/media/tiny.png", _png_bytes(24, 20))
        zf.writestr("word/media/ok.png", _png_bytes(64, 64))
    images = chat._extract_images_from_docx(buf.getvalue())
    names = {img["name"] for img in images}
    assert "tiny.png" not in names
    assert "ok.png" in names
