"""YouTube URL identity: scrape the video the user sent, not a prior RAG/memory link."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from backend.processors.base_processor import BaseChat
from main.api import PyWebViewApi


def test_extracts_watch_v_id_not_share_junk():
    url = (
        "youtube.com/watch?v=pq8QKxKZX8w&time_continue=17"
        "&source_ve_path=NzY3NTg&embeds_referring_euri=https%3A%2F%2Fdevpost.com%2F"
    )
    assert BaseChat._extract_youtube_video_id("https://" + url) == "pq8QKxKZX8w"
    assert BaseChat._extract_youtube_video_id("https://youtu.be/pq8QKxKZX8w?si=abc") == "pq8QKxKZX8w"
    assert BaseChat._extract_youtube_video_id(
        "https://www.youtube.com/shorts/pq8QKxKZX8w"
    ) == "pq8QKxKZX8w"


def test_does_not_treat_random_slash_run_as_video_id():
    # Old regex (?:v=|/)(.{11}) could pick Easy Love / R5 IDs out of other strings.
    assert BaseChat._extract_youtube_video_id("https://example.com/u74gTjC_yUg") is None
    assert BaseChat._extract_youtube_video_id("https://devpost.com/software/ignite") is None


def test_collects_schemeless_youtube_before_http_urls():
    text = (
        "mira youtube.com/watch?v=pq8QKxKZX8w "
        "y también https://www.researchgate.net/publication/379999788_x"
    )
    urls = BaseChat._collect_scrape_urls(text)
    assert urls[0].startswith("https://")
    assert "pq8QKxKZX8w" in urls[0]
    assert BaseChat._extract_youtube_video_id(urls[0]) == "pq8QKxKZX8w"


def test_process_urls_ignores_youtube_links_inside_rag_prefix():
    class GeminiChat(BaseChat):
        pass

    gem = GeminiChat.__new__(GeminiChat)
    poisoned = (
        "[LOCAL PERSISTENT MEMORY RECALLED] "
        "https://www.youtube.com/watch?v=lVe6SEH9IsM R5 Pass Me By\n\n"
        "[USER QUERY]\n"
        "https://www.youtube.com/watch?v=pq8QKxKZX8w"
    )

    def fake_meta(video_id):
        assert video_id == "pq8QKxKZX8w"
        return ("Correct Video Title", "Right Channel", "desc")

    with patch.object(gem, "_get_youtube_metadata", side_effect=fake_meta):
        with patch.object(gem, "_get_youtube_transcript", return_value="transcript of the right video"):
            out, sources = gem._process_urls_in_input(poisoned, force_language="es-MX")

    assert len(sources) == 1
    assert "pq8QKxKZX8w" in sources[0]
    assert "lVe6SEH9IsM" not in "".join(sources)
    assert "Correct Video Title" in out
    assert "Pass Me By" not in out or "Correct Video Title" in out


def test_rag_prefix_skipped_for_youtube_url(tmp_path, monkeypatch):
    api = PyWebViewApi()
    api.rag_engine = MagicMock()
    api.rag_engine.get_rag_system_prompt_snippet.return_value = (
        "[LOCAL PERSISTENT MEMORY RECALLED] https://www.youtube.com/watch?v=lVe6SEH9IsM"
    )
    out = api._text_for_model_with_rag("https://www.youtube.com/watch?v=pq8QKxKZX8w")
    assert out == "https://www.youtube.com/watch?v=pq8QKxKZX8w"
    api.rag_engine.get_rag_system_prompt_snippet.assert_not_called()
