"""
Tests for inaccessible / bot-walled URL scrape soft-fail (URL_INACCESSIBLE).
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from backend.processors.base_processor import BaseChat


def test_is_unusable_scrape_empty_and_short():
    assert BaseChat.is_unusable_scrape("") is True
    assert BaseChat.is_unusable_scrape("   ") is True
    assert BaseChat.is_unusable_scrape("too short") is True


def test_is_unusable_scrape_soundcloud_fingerprint():
    htmlish = (
        "SoundCloud\n"
        "Your current browser isn't compatible with SoundCloud.\n"
        "Please download one of our supported browsers.\n"
        "Sorry! Something went wrong\n"
        "Is your network connection unstable or browser outdated?\n"
    )
    assert BaseChat.is_unusable_scrape(htmlish) is True


def test_is_unusable_scrape_accepts_real_article():
    body = (
        "Título: Informe trimestral de ingresos\n"
        "Descripción: Resumen ejecutivo del Q3 con métricas de crecimiento.\n"
        "[Texto Completo Extraído]:\n"
        "En el tercer trimestre la compañía reportó un incremento de ingresos "
        "del doce por ciento impulsado por nuevos contratos enterprise y "
        "expansión en Latinoamérica. El margen operativo mejoró tras "
        "optimizaciones de infraestructura en la nube."
    )
    assert BaseChat.is_unusable_scrape(body) is False


def test_format_url_inaccessible_marker():
    url = "https://on.soundcloud.com/U0b8hZkMDAwz01Kgz3"
    marker = BaseChat.format_url_inaccessible(url, force_language="es-ES")
    assert marker.startswith("[URL_INACCESSIBLE:")
    assert url in marker
    assert "No inventes" in marker
    assert BaseChat.is_unusable_scrape(marker) is True


def test_format_url_inaccessible_french_not_spanish():
    marker = BaseChat.format_url_inaccessible("https://example.com/x", force_language="fr-FR")
    assert "Impossible d'extraire" in marker or "Impossible" in marker
    assert "No inventes" not in marker
    assert "No se pudo" not in marker


def test_should_enable_search_after_short_or_inaccessible_scrape():
    assert BaseChat.should_enable_search_after_scrape([], "") is True
    short = BaseChat.format_url_inaccessible("https://on.soundcloud.com/x")
    assert BaseChat.should_enable_search_after_scrape(["https://on.soundcloud.com/x"], short) is True
    long_body = "palabra " * 200
    assert len(long_body) >= 800
    assert BaseChat.should_enable_search_after_scrape(["https://example.com/a"], long_body) is False


def test_scrape_web_page_soundcloud_wall_returns_inaccessible():
    chat = BaseChat.__new__(BaseChat)
    fake_html = """
    <html><head><title>SoundCloud</title></head>
    <body>
      <h1>Your current browser isn't compatible with SoundCloud.</h1>
      <p>Please download one of our supported browsers.</p>
      <p>Sorry! Something went wrong</p>
    </body></html>
    """
    mock_resp = MagicMock()
    mock_resp.text = fake_html
    mock_resp.raise_for_status = MagicMock()

    with patch("backend.processors.base_processor.requests.get", return_value=mock_resp):
        with patch.object(chat, "_extract_media_metadata_ytdlp", return_value=None):
            result = chat._scrape_web_page(
                "https://on.soundcloud.com/U0b8hZkMDAwz01Kgz3", force_language="es-ES"
            )

    assert result.startswith("[URL_INACCESSIBLE:")
    assert "on.soundcloud.com" in result


def test_scrape_web_page_request_error_returns_inaccessible():
    chat = BaseChat.__new__(BaseChat)
    with patch(
        "backend.processors.base_processor.requests.get",
        side_effect=TimeoutError("timed out"),
    ):
        with patch.object(chat, "_extract_media_metadata_ytdlp", return_value=None):
            result = chat._scrape_web_page("https://example.com/blocked")

    assert result.startswith("[URL_INACCESSIBLE: https://example.com/blocked]")


def test_process_urls_appends_inaccessible_marker():
    class GeminiChat(BaseChat):
        pass

    gem = GeminiChat.__new__(GeminiChat)
    with patch.object(
        gem,
        "_scrape_web_page",
        return_value=BaseChat.format_url_inaccessible(
            "https://on.soundcloud.com/x", force_language="fr-FR"
        ),
    ):
        out, sources = gem._process_urls_in_input(
            "regarde https://on.soundcloud.com/x", force_language="fr-FR"
        )

    assert sources == ["https://on.soundcloud.com/x"]
    assert "[URL_INACCESSIBLE: https://on.soundcloud.com/x]" in out
    assert "CONTENIDO DE PÁGINA WEB DETECTADO" not in out
    assert "CRITICAL LANGUAGE" in out
    assert "FINAL LANGUAGE REMINDER" in out
    assert "(Español)" not in out
    assert "French" in out


def test_scrape_language_guards_spanish_still_spanish():
    header, footer = BaseChat._scrape_language_guards("es-ES", "Spanish")
    assert "Español" in header
    assert "Español" in footer
