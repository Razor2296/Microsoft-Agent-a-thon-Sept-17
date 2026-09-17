"""
Voice Processor Class - Handles all interactions with TTS services.
"""
import re
import os
import sys
import tempfile
import threading
import json
import base64
import requests

from backend.core.libraries import get_assistant_logger

# Logger for Voice Processor
logger = get_assistant_logger("voice_processor")

# Voice Processor Class
class VoiceProcessor:
    # Initialization
    def __init__(self):
        self.api_key = os.getenv("CARTESIA_API_KEY", "")
        self.url = "https://api.cartesia.ai/tts/bytes"
        self.version = "2024-06-10"
        # Model and audio quality — configurable via .env to allow switching to cheaper tiers
        # sonic-2 is cheaper than sonic-3.5 and delivers identical quality for conversational TTS
        self.model_id = os.getenv("CARTESIA_MODEL_ID", "sonic-2")
        # 22050 Hz is perceptually identical to 44100 Hz for voice TTS, at half the data size/cost
        self.sample_rate = int(os.getenv("CARTESIA_SAMPLE_RATE", "22050"))

        # Pre-configured multilingual voice IDs for EN and ES (with support for .env overrides)
        self.VOICE_MAPPING_EN = {
            "child_male": os.getenv("CARTESIA_VOICE_CHILD_MALE_EN", "87286a8d-7ea7-4235-a41a-dd9fa6630feb"),
            "child_female": os.getenv("CARTESIA_VOICE_CHILD_FEMALE_EN", "32b3f3c5-7171-46aa-abe7-b598964aa793"),
            "young_male": os.getenv("CARTESIA_VOICE_YOUNG_MALE_EN", "630ed21c-2c5c-41cf-9d82-10a7fd668370"),
            "young_female": os.getenv("CARTESIA_VOICE_YOUNG_FEMALE_EN", "62305e79-9d39-4643-b003-5e0b096fe4f4"),
            "adult_male": os.getenv("CARTESIA_VOICE_ADULT_MALE_EN", "820a3788-2b37-4d21-847a-b65d8a68c99a"),
            "adult_female": os.getenv("CARTESIA_VOICE_ADULT_FEMALE_EN", "e07c00bc-4134-4eae-9ea4-1a55fb45746b"),
            "senior_male": os.getenv("CARTESIA_VOICE_SENIOR_MALE_EN", "c99d36f3-5ffd-4253-803a-535c1bc9c306"),
            "senior_female": os.getenv("CARTESIA_VOICE_SENIOR_FEMALE_EN", "c8605446-247c-4d39-acd4-8f4c28aa363c")
        }

        self.VOICE_MAPPING_ES = {
            "child_male": os.getenv("CARTESIA_VOICE_CHILD_MALE_ES", "7b001dff-b8b2-4da7-92e4-5c794798effa"),
            "child_female": os.getenv("CARTESIA_VOICE_CHILD_FEMALE_ES", "3597a26f-80ef-4bd5-8101-9699bc764917"),
            "young_male": os.getenv("CARTESIA_VOICE_YOUNG_MALE_ES", "5ee9feff-1265-424a-9d7f-8e4d431a12c7"),
            "young_female": os.getenv("CARTESIA_VOICE_YOUNG_FEMALE_ES", "c68a8bd0-f99e-4e7f-915d-a097da6d024c"),
            "adult_male": os.getenv("CARTESIA_VOICE_ADULT_MALE_ES", "15d0c2e2-8d29-44c3-be23-d585d5f154a1"),
            "adult_female": os.getenv("CARTESIA_VOICE_ADULT_FEMALE_ES", "e361b786-2768-4308-9369-a09793d4dd73"),
            "senior_male": os.getenv("CARTESIA_VOICE_SENIOR_MALE_ES", "948196a7-fe02-417b-9b6d-c45ee0803565"),
            "senior_female": os.getenv("CARTESIA_VOICE_SENIOR_FEMALE_ES", "b503f001-80b8-49d3-8666-8d7700fc5ca2")
        }

        # Legacy fallback
        self.VOICE_MAPPING = self.VOICE_MAPPING_ES

    # Function to check if api key and service is configured and enabled
    def is_configured(self) -> bool:
        try:
            enabled = os.getenv("CARTESIA_ENABLED", "true").strip().lower()
            if enabled in ("false", "0", "no", "off", "disabled"):
                logger.info("Cartesia TTS is disabled via CARTESIA_ENABLED environment flag.")
                return False
            return bool(self.api_key)
        except Exception as e:
            logger.error(f"Error checking if Cartesia API is configured: {e}")
            return False

    def detect_language(self, text: str) -> str:
        """Detect language (es or en) based on common stopwords."""
        try:
            es_words = {"el", "la", "los", "las", "un", "una", "y", "en", "que", "es", "de", "con", "para", "por", "como", "esta", "bien", "hola", "amanecido"}
            en_words = {"the", "a", "an", "and", "in", "is", "of", "with", "for", "by", "as", "this", "good", "hello", "you", "are", "i"}

            words = re.findall(r'\b\w+\b', text.lower())
            es_count = sum(1 for w in words if w in es_words)
            en_count = sum(1 for w in words if w in en_words)

            return "es" if es_count >= en_count else "en"
        except Exception:
            return "es"

    # Function to determine voice category based on prompt keywords and thematic topics
    def determine_voice_category(self, prompt: str) -> str:
        """ Determines the voice category based on the prompt keywords or thematic content. """
        try:
            logger.info("Determining voice category based on prompt/text keywords...")

            # 1. Check for explicit directive from the LLM, e.g. [voice: adult_male]
            match = re.match(r'^\[voice:\s*([a-z_]+)\]', prompt, re.IGNORECASE)
            if match:
                category = match.group(1).lower()
                valid_categories = {"child_male", "child_female", "young_male", "young_female", "adult_male", "adult_female", "senior_male", "senior_female"}
                if category in valid_categories:
                    return category

            lower_prompt = prompt.lower()

            # 2. Gender indicator keywords
            female_keywords = ["mujer", "abuela", "anciana", "niña", "chica", "madre", "esposa", "dama", "señora", "ella", "femenina", "femenino",
                               "woman", "female", "girl", "lady", "wife", "mother", "daughter", "she", "her", "hers", "grandma", "grandmother"]
            male_keywords = ["hombre", "abuelo", "anciano", "niño", "chico", "padre", "esposo", "caballero", "señor", "él", "masculino",
                             "man", "male", "guy", "boy", "gentleman", "father", "husband", "son", "he", "him", "his", "grandpa", "grandfather"]

            # Count matches
            female_count = sum(1 for kw in female_keywords if kw in lower_prompt)
            male_count = sum(1 for kw in male_keywords if kw in lower_prompt)
            is_female = female_count > male_count

            # 3. Thematic keywords
            senior_keywords = ["abuelo", "abuela", "anciano", "anciana", "viejo", "vieja", "historia", "pasado", "tradición", "sabiduría", "antiguo", "relato", "cuento", "época", "edad",
                               "senior", "elderly", "old", "adulto mayor", "history", "past", "traditional", "grandparents", "wisdom", "tale", "ancient", "legacy", "experience"]

            child_keywords = ["niño", "niña", "juguete", "juego", "jugar", "dulce", "caricatura", "dibujo animado", "escuela", "infantil", "bebé", "osito", "parque",
                              "kid", "child", "children", "baby", "toy", "playground", "candy", "cartoon", "primary school", "play", "teddy"]

            young_keywords = ["joven", "chico", "chica", "tecnología", "programar", "código", "videojuego", "gamer", "música", "universidad", "fiesta", "celular", "aplicación", "redes", "chat",
                              "young", "youth", "teen", "teenager", "gaming", "technology", "software", "code", "pop", "band", "college", "club", "smartphone", "app", "cool", "chat"]

            # Count theme matches
            senior_count = sum(1 for kw in senior_keywords if kw in lower_prompt)
            child_count = sum(1 for kw in child_keywords if kw in lower_prompt)
            young_count = sum(1 for kw in young_keywords if kw in lower_prompt)

            # Find the strongest theme
            max_theme_count = max(senior_count, child_count, young_count)

            if max_theme_count > 0:
                if max_theme_count == senior_count:
                    return "senior_female" if is_female else "senior_male"
                elif max_theme_count == child_count:
                    return "child_female" if is_female else "child_male"
                elif max_theme_count == young_count:
                    return "young_female" if is_female else "young_male"

            # Default fallback based on gender count
            return "adult_female" if is_female else "adult_male"

        except Exception as e:
            logger.error(f"Error determining voice category: {e}")
            return "adult_male"

    def _clean_text_for_speech(self, text: str) -> str:
        """Cleans text before TTS synthesis so the voice model reads clean, natural sentences.
        Strips markdown formatting, URLs, code blocks, and media generation tags.
        """
        if not text:
            return ""
        # Strip media generation directives like [GENERATE_IMAGE: ...] or [voice: ...]
        cleaned = re.sub(r'\[GENERATE_[A-Z_]+:[^\]]*\]', '', text, flags=re.IGNORECASE)
        cleaned = re.sub(r'\[voice:[^\]]*\]', '', cleaned, flags=re.IGNORECASE)
        # Strip URLs
        cleaned = re.sub(r'https?://\S+', '', cleaned)
        # Strip code blocks ``` ... ``` and inline code ` ... `
        cleaned = re.sub(r'```[\s\S]*?```', '', cleaned)
        cleaned = re.sub(r'`[^`]+`', '', cleaned)
        # Strip markdown headers, bold, italics, bullet points
        cleaned = re.sub(r'^\s*#+\s*', '', cleaned, flags=re.MULTILINE)
        cleaned = re.sub(r'[*_]{1,3}([^*_]+)[*_]{1,3}', r'\1', cleaned)
        cleaned = re.sub(r'^\s*[-*+]\s+', '', cleaned, flags=re.MULTILINE)
        # Replace common symbols with spoken words
        cleaned = cleaned.replace('&', ' y ').replace('%', ' por ciento ').replace('@', ' arroba ')
        # Normalize whitespace
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()
        return cleaned

    # Function to generate TTS raw audio bytes
    def generate_tts(self, text: str, voice_category: str = "adult_female") -> bytes:
        try:
            if not self.is_configured():
                raise ValueError("Cartesia API key is not configured")

            # Check if text contains an explicit voice directive, e.g. [voice: adult_male]
            match = re.match(r'^\[voice:\s*([a-z_]+)\]\s*', text, re.IGNORECASE)
            if match:
                voice_category = match.group(1).lower()
                text = text[match.end():]  # Strip the directive from the spoken text

            # Clean text for speech synthesis (strip markdown, URLs, tags)
            clean_transcript = self._clean_text_for_speech(text)
            if not clean_transcript:
                clean_transcript = text.strip()

            # Detect language of the spoken text
            lang = self.detect_language(clean_transcript)
            mapping = self.VOICE_MAPPING_ES if lang == "es" else self.VOICE_MAPPING_EN

            voice_id = mapping.get(voice_category, mapping.get("adult_female"))
            logger.info(f"Generating Cartesia TTS via voice category '{voice_category}' ({lang}) (ID: {voice_id}) [Model: {self.model_id}]")

            headers = {
                "X-API-Key": self.api_key,
                "Content-Type": "application/json",
                "Cartesia-Version": self.version
            }

            body = {
                "model_id": self.model_id,
                "transcript": clean_transcript,
                "voice": {
                    "mode": "id",
                    "id": voice_id
                },
                "output_format": {
                    "container": "mp3",
                    "sample_rate": self.sample_rate,
                    "bit_rate": 128000
                }
            }

            resp = requests.post(self.url, headers=headers, json=body, timeout=15)
            if resp.status_code == 200:
                return resp.content
            else:
                try:
                    err_msg = resp.json().get("error", {}).get("message", resp.text)
                except Exception:
                    err_msg = resp.text
                raise RuntimeError(f"Cartesia API failed: {err_msg}")
        except Exception as e:
            logger.error(f"Error generating TTS: {e}")
            raise e
