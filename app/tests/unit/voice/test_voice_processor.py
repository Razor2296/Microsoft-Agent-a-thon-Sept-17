"""
app/tests/unit/test_voice_processor.py
Unit tests for backend/voice_processor.py (Cartesia TTS & voice mapping).
"""
from unittest.mock import MagicMock, patch

import pytest
from backend.voice.voice_processor import VoiceProcessor

# Class test for init
class TestVoiceProcessorInit:
    # Test default initialization
    def test_default_initialization(self, monkeypatch):
        monkeypatch.setenv("CARTESIA_API_KEY", "test_key_123")
        monkeypatch.setenv("CARTESIA_MODEL_ID", "sonic-2")
        monkeypatch.setenv("CARTESIA_SAMPLE_RATE", "22050")

        vp = VoiceProcessor()
        assert vp.api_key == "test_key_123"
        assert vp.model_id == "sonic-2"
        assert vp.sample_rate == 22050
        assert "cartesia.ai" in vp.url

    # Test custom sample rate
    def test_custom_sample_rate(self, monkeypatch):
        monkeypatch.setenv("CARTESIA_SAMPLE_RATE", "44100")
        vp = VoiceProcessor()
        assert vp.sample_rate == 44100

# Class test for voice category determination
class TestVoiceCategoryDetermination:
    # Test female keywords
    def test_female_keywords(self):
        vp = VoiceProcessor()
        assert vp.determine_voice_category("Hola soy Maria y soy una mujer investigadora") == "adult_female"

    # Test male keywords
    def test_male_keywords(self):
        vp = VoiceProcessor()
        assert vp.determine_voice_category("El señor director y profesor asistente") == "adult_male"

    # Test child keywords
    def test_child_keywords(self):
        vp = VoiceProcessor()
        assert vp.determine_voice_category("El pequeño niño estaba jugando con su juguete") == "child_male"

    # Test senior keywords
    def test_senior_keywords(self):
        vp = VoiceProcessor()
        assert vp.determine_voice_category("El anciano abuelo contaba historias antiguas") == "senior_male"

    # Test default fallback category
    def test_default_fallback_category(self):
        vp = VoiceProcessor()
        # General neutral text defaults to adult_female or adult_male
        cat = vp.determine_voice_category("El reporte meteorológico de hoy indica lluvia.")
        assert cat in ("adult_female", "adult_male")

# Class test for TTS generation
class TestVoiceProcessorTTS:
    # Test successful TTS generation
    @patch("backend.voice.voice_processor.requests.post")
    def test_generate_tts_success(self, mock_post, monkeypatch):
        monkeypatch.setenv("CARTESIA_ENABLED", "true")
        monkeypatch.setenv("CARTESIA_API_KEY", "valid_api_key")
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b"fake_audio_bytes_12345"
        mock_post.return_value = mock_response

        vp = VoiceProcessor()
        audio_bytes = vp.generate_tts("Hola mundo", voice_category="adult_male")

        assert audio_bytes == b"fake_audio_bytes_12345"
        mock_post.assert_called_once()

    # Test missing key
    def test_generate_tts_missing_key(self, monkeypatch):
        monkeypatch.setenv("CARTESIA_ENABLED", "true")
        monkeypatch.setenv("CARTESIA_API_KEY", "")
        vp = VoiceProcessor()
        with pytest.raises(ValueError, match="not configured"):
            vp.generate_tts("Hola sin key")

    # Test API error
    @patch("backend.voice.voice_processor.requests.post")
    def test_generate_tts_api_error(self, mock_post, monkeypatch):
        monkeypatch.setenv("CARTESIA_ENABLED", "true")
        monkeypatch.setenv("CARTESIA_API_KEY", "valid_key")
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.text = "Unauthorized key"
        mock_post.return_value = mock_response

        vp = VoiceProcessor()
        with pytest.raises(RuntimeError, match="Cartesia API failed"):
            vp.generate_tts("Test error")
