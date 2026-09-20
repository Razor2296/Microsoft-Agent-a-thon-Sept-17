"""
Class with configuration parameters for all AI models.
"""
# Force bytecode recompilation

import sys
import os
import threading
import importlib
import logging
import re
import json
import tempfile
import base64
import hashlib
import subprocess
import textwrap
import io
import wave
import zipfile
import shutil
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, Iterable, List, Optional, Tuple, Union, cast
from urllib.parse import urlparse, parse_qs

import requests
try:
    import pytz
except ImportError:
    pytz = None

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None  # type: ignore

try:
    from youtube_transcript_api import YouTubeTranscriptApi
except ImportError:
    YouTubeTranscriptApi = None  # type: ignore

try:
    from google import genai
    from google.genai import types
except ImportError:
    genai = None  # type: ignore
    types = None  # type: ignore

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None  # type: ignore

try:
    from anthropic import Anthropic
except ImportError:
    Anthropic = None  # type: ignore

try:
    from tenacity import Retrying, stop_after_attempt, wait_chain, wait_fixed
except ImportError:
    Retrying = None  # type: ignore
    stop_after_attempt = None  # type: ignore
    wait_chain = None  # type: ignore
    wait_fixed = None  # type: ignore

from dotenv import load_dotenv
from PIL import Image

try:
    from mutagen import File as MutagenFile
except ImportError:
    MutagenFile = None  # type: ignore

try:
    from langdetect import detect
except ImportError:
    detect = None


yt_dlp = None
try:
    import yt_dlp
except ImportError:
    pass

pytesseract = None
try:
    import pytesseract
except ImportError:
    pass

WhisperModel = None
try:
    from faster_whisper import WhisperModel
except ImportError:
    pass

pypdf = None
try:
    import pypdf
except ImportError:
    pass

PyPDF2 = None
try:
    import PyPDF2
except ImportError:
    pass


from backend.core.libraries import get_assistant_logger
from backend.core.schemas import TokenInfo, ChatMessage, APIResponsePayload
from backend.core.conversation_language import (
    detect_language_from_text,
    get_default_conversation_language,
)
from backend.processors.cost_calculator import calculate_cost_usd, calculate_media_cost_usd
from backend.integrations.document_request import (
    DOC_GUIDELINES_MARKER,
    DOCUMENT_GENERATION_GUIDELINES,
    detect_document_request as classify_document_request,
)
from backend.integrations.office_extract import (
    extract_text_from_docx,
    extract_text_from_pptx,
    extract_text_from_xlsx,
)


# Import System User Information class
from backend.user.windows_user import (
    get_user_display_name,
    get_system_language,
    get_system_timezone,
    is_system_dark_mode,
    get_desktop_path,
    get_downloads_path,
    get_documents_path,
    get_pictures_path,
    get_user_profile_picture,
    get_clipboard_text,
    get_user_country_code,
)

# Import Voice Processor class
from backend.voice.voice_processor import VoiceProcessor

# Re-export for existing callers (api.py / server.main).
from backend.core.runtime_identity import get_runtime_user_name, set_runtime_user_name  # noqa: E402

logger = get_assistant_logger("base_processor")

# Set all input parameters as environment variables or defaults
if getattr(sys, 'frozen', False):
    # PyInstaller places the compiled executable inside the dist/ folder by default.
    # Check if .env is in the executable folder or one level up (app root).
    _exe_dir = os.path.dirname(sys.executable)
    if os.path.exists(os.path.join(_exe_dir, '.env')):
        app_root = _exe_dir
    elif os.path.exists(os.path.join(os.path.dirname(_exe_dir), '.env')):
        app_root = os.path.dirname(_exe_dir)
    else:
        app_root = _exe_dir
else:
    app_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

env_path = os.path.join(app_root, '.env')
load_dotenv(dotenv_path=env_path, override=True)

# Per-tenant flag: Google CSE 403 must NOT disable search for all ACA sessions on a replica.
# Keyed by BaseChat._cache_namespace() / "_tenant_key". Legacy module bool removed.
_SEARCH_DISABLED_BY_TENANT: dict = {}

# System User Information
class DynamicClipboardString:
    """A wrapper class that dynamically queries the Windows clipboard when formatted or stringified."""
    def __str__(self):
        try:
            return get_clipboard_text() or ""
        except Exception:
            return ""

    def __repr__(self):
        return repr(self.__str__())

    def __format__(self, format_spec):
        return format(self.__str__(), format_spec)

    def __add__(self, other):
        return self.__str__() + other

    def __radd__(self, other):
        return other + self.__str__()

# Class that dynamically queries the Windows clipboard when formatted or stringified.
class DynamicUserNameString:
    """String-like wrapper so f-strings always see the current runtime user name."""

    def __str__(self):
        return get_runtime_user_name()

    def __repr__(self):
        return repr(self.__str__())

    def __format__(self, format_spec):
        return format(self.__str__(), format_spec)

    def __add__(self, other):
        return self.__str__() + other

    def __radd__(self, other):
        return other + self.__str__()


USER_NAME                           = DynamicUserNameString()
USER_DESKTOP_PATH                   = get_desktop_path()
USER_DOWNLOADS_PATH                 = get_downloads_path()
USER_DOCUMENTS_PATH                 = get_documents_path()
USER_PICTURES_PATH                  = get_pictures_path()
USER_PROFILE_PICTURE_PATH           = get_user_profile_picture()
USER_CLIPBOARD_TEXT                 = DynamicClipboardString()
USER_SYSTEM_LANGUAGE                = get_system_language()
USER_SYSTEM_TIMEZONE                = get_system_timezone()
USER_SYSTEM_DARK_MODE               = is_system_dark_mode()

# Helper to resolve absolute paths for assets
def _resolve_asset_path(env_key: str, default_rel_path: str) -> str:
    path = os.getenv(env_key, default_rel_path)
    if os.path.isabs(path) and os.path.exists(path):
        return path
    candidates = [
        os.path.join(app_root, path),
        os.path.join(app_root, "_internal", path),
        os.path.join(app_root, "frontend", path),
        os.path.join(app_root, "_internal", "frontend", path),
    ]
    if getattr(sys, 'frozen', False):
        _exe = os.path.dirname(sys.executable)
        candidates.extend([
            os.path.join(_exe, path),
            os.path.join(_exe, "_internal", path),
            os.path.join(_exe, "frontend", path),
            os.path.join(_exe, "_internal", "frontend", path),
        ])
        if hasattr(sys, '_MEIPASS'):
            candidates.append(os.path.join(sys._MEIPASS, path))
    for c in candidates:
        if os.path.exists(c):
            return c
    return os.path.join(app_root, path)

# Gemini configuration parameters
GEMINI_API_KEY                      = os.getenv("GEMINI_API_KEY", "<your-key-here>")
GEMINI_MODEL_VERSION                = os.getenv("GEMINI_MODEL_VERSION", "gemini-3.1-flash-lite")
GEMINI_SEARCH_MODEL                 = os.getenv("GEMINI_SEARCH_MODEL", "gemini-2.5-flash-lite")
GEMINI_MAX_TOKENS                   = int(os.getenv("GEMINI_MAX_TOKENS", "4000"))
GEMINI_TEMPERATURE                  = float(os.getenv("GEMINI_TEMPERATURE", "0.7"))
GEMINI_TOP_P                        = float(os.getenv("GEMINI_TOP_P", "0.9"))
GEMINI_RETRY_SEQUENCE               = [int(x.strip()) for x in os.getenv("GEMINI_RETRY_SEQUENCE", "1, 2, 3, 5, 8").split(",")]
GEMINI_PROFILE_PICTURE_PATH         = _resolve_asset_path("GEMINI_PROFILE_PICTURE_PATH", "assets/gemini-color.svg")

# Deepseek configuration parameters
DEEPSEEK_API_KEY                    = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL                   = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL_VERSION              = os.getenv("DEEPSEEK_MODEL_VERSION", "deepseek-v4-pro")
DEEPSEEK_MAX_TOKENS                 = int(os.getenv("DEEPSEEK_MAX_TOKENS", "6000"))
DEEPSEEK_TEMPERATURE                = float(os.getenv("DEEPSEEK_TEMPERATURE", "0.1"))
DEEPSEEK_TOP_P                      = float(os.getenv("DEEPSEEK_TOP_P", "0.9"))
DEEPSEEK_REASONING_EFFORT           = os.getenv("DEEPSEEK_REASONING_EFFORT", "High").strip()
DEEPSEEK_RETRY_SEQUENCE             = [int(x.strip()) for x in os.getenv("DEEPSEEK_RETRY_SEQUENCE", "1, 2, 3, 5, 8").split(",")]
DEEPSEEK_PROFILE_PICTURE_PATH       = _resolve_asset_path("DEEPSEEK_PROFILE_PICTURE_PATH", "assets/deepseek-color.svg")

# OpenAI / Azure OpenAI (Foundry) configuration parameters
AZURE_OPENAI_API_KEY = os.getenv("AZURE_OPENAI_API_KEY", "").strip() or os.getenv("AZURE_OPENAI_KEY", "").strip() or os.getenv("Azure_OPENAI_KEY", "").strip()
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT", "").strip() or os.getenv("Azure_OPENAI_ENDPOINT", "").strip() or os.getenv("AZURE_OPENAI_URL", "").strip()
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "").strip() or AZURE_OPENAI_ENDPOINT or None
_OPENAI_USES_AZURE = bool(
    OPENAI_BASE_URL
    and (
        "openai.azure.com" in OPENAI_BASE_URL.lower()
        or "cognitiveservices.azure.com" in OPENAI_BASE_URL.lower()
        or "services.ai.azure.com" in OPENAI_BASE_URL.lower()
    )
)
OPENAI_API_KEY                      = AZURE_OPENAI_API_KEY if (_OPENAI_USES_AZURE and AZURE_OPENAI_API_KEY) else (os.getenv("OPENAI_API_KEY", "").strip() or AZURE_OPENAI_API_KEY)
_OPENAI_DEFAULT_MODEL               = "gpt-4.1-mini" if _OPENAI_USES_AZURE else "gpt-4o"
OPENAI_MODEL_VERSION                = os.getenv("OPENAI_MODEL_VERSION", _OPENAI_DEFAULT_MODEL)
OPENAI_AVAILABLE_MODELS_DEFAULT     = os.getenv(
    "OPENAI_AVAILABLE_MODELS",
    "gpt-4.1-mini,gpt-5.6-sol,gpt-5.6-luna,gpt-5.6-terra,o3"
    if _OPENAI_USES_AZURE
    else "gpt-4o,gpt-4o-mini,o1,o3-mini",
)
OPENAI_MAX_TOKENS                   = int(os.getenv("OPENAI_MAX_TOKENS", "6000"))
OPENAI_TEMPERATURE                  = float(os.getenv("OPENAI_TEMPERATURE", "0.1"))
OPENAI_TOP_P                        = float(os.getenv("OPENAI_TOP_P", "0.9"))
OPENAI_RETRY_SEQUENCE               = [int(x.strip()) for x in os.getenv("OPENAI_RETRY_SEQUENCE", "1, 2, 3, 5, 8").split(",")]
OPENAI_PROFILE_PICTURE_PATH         = _resolve_asset_path("OPENAI_PROFILE_PICTURE_PATH", "assets/openai-color.svg")
OPENAI_AUDIO_MODEL_VERSION          = os.getenv("OPENAI_AUDIO_MODEL_VERSION", "tts-1-hd").strip()
OPENAI_FALLBACK_AUDIO_MODEL_VERSION = os.getenv("OPENAI_FALLBACK_AUDIO_MODEL_VERSION", "tts-1").strip()
OPENAI_TTS_VOICE                    = os.getenv("OPENAI_TTS_VOICE", "onyx").strip()
OPENAI_IMAGE_MODEL_VERSION          = os.getenv("OPENAI_IMAGE_MODEL_VERSION", "gpt-image-2").strip()
OPENAI_FALLBACK_IMAGE_MODEL         = os.getenv("OPENAI_FALLBACK_IMAGE_MODEL", "gpt-image-1").strip()


def build_openai_client(api_key=None, timeout: float | None = None):
    """Create an OpenAI SDK client, routing to Azure Foundry when OPENAI_BASE_URL is set."""
    key = (api_key or OPENAI_API_KEY or "").strip()
    if timeout is None:
        timeout = float(llm_http_timeout_seconds())
    kwargs = {"api_key": key, "timeout": timeout}
    if OPENAI_BASE_URL:
        kwargs["base_url"] = OPENAI_BASE_URL
    return OpenAI(**kwargs)

# Anthropic configuration parameters
ANTHROPIC_API_KEY                   = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL_VERSION             = os.getenv("ANTHROPIC_MODEL_VERSION", "claude-fable-5")
ANTHROPIC_MAX_TOKENS                = int(os.getenv("ANTHROPIC_MAX_TOKENS", "6000"))
ANTHROPIC_TEMPERATURE               = float(os.getenv("ANTHROPIC_TEMPERATURE", "0.1"))
ANTHROPIC_TOP_P                     = float(os.getenv("ANTHROPIC_TOP_P", "0.9"))
ANTHROPIC_RETRY_SEQUENCE            = [int(x.strip()) for x in os.getenv("ANTHROPIC_RETRY_SEQUENCE", "1, 2, 3, 5, 8").split(",")]
ANTHROPIC_PROFILE_PICTURE_PATH      = _resolve_asset_path("ANTHROPIC_PROFILE_PICTURE_PATH", "assets/anthropic-color.svg")

# Google AI Studio configuration parameters
GEMINI_IMAGE_MODEL_VERSION          = os.getenv("GEMINI_IMAGE_MODEL_VERSION", "gemini-3.1-flash-image").strip()
GEMINI_FALLBACK_IMAGE_MODEL         = os.getenv("GEMINI_FALLBACK_IMAGE_MODEL", "gemini-3-pro-image").strip()
GEMINI_AUDIO_MODEL_VERSION          = os.getenv("GEMINI_AUDIO_MODEL_VERSION", "gemini-2.5-flash-native-audio-preview-12-2025").strip()
GEMINI_FALLBACK_AUDIO_MODEL_VERSION = os.getenv("GEMINI_FALLBACK_AUDIO_MODEL_VERSION", "gemini-2.5-flash-native-audio-preview-09-2025").strip()
GEMINI_TTS_VOICE                    = os.getenv("GEMINI_TTS_VOICE", "Charon").strip()

# Perplexity configuration parameters
PERPLEXITY_API_KEY                  = os.getenv("PERPLEXITY_API_KEY", "")
PERPLEXITY_BASE_URL                 = os.getenv("PERPLEXITY_BASE_URL", "https://api.perplexity.ai")
PERPLEXITY_MODEL_VERSION            = os.getenv("PERPLEXITY_MODEL_VERSION", "sonar")
PERPLEXITY_MAX_TOKENS               = int(os.getenv("PERPLEXITY_MAX_TOKENS", "4096"))
PERPLEXITY_TEMPERATURE              = float(os.getenv("PERPLEXITY_TEMPERATURE", "0.2"))
PERPLEXITY_TOP_P                    = float(os.getenv("PERPLEXITY_TOP_P", "0.9"))
PERPLEXITY_RETRY_SEQUENCE           = [int(x.strip()) for x in os.getenv("PERPLEXITY_RETRY_SEQUENCE", "1, 2, 3, 5, 8").split(",")]
PERPLEXITY_PROFILE_PICTURE_PATH     = _resolve_asset_path("PERPLEXITY_PROFILE_PICTURE_PATH", "assets/perplexity-color.svg")
# Sonar context is smaller than Gemini/OpenAI; large PDF + image descriptions blow the prompt.
try:
    PERPLEXITY_MAX_PROMPT_CHARS = int(os.getenv("IGNITE_PERPLEXITY_MAX_PROMPT_CHARS", "100000"))
except (TypeError, ValueError):
    PERPLEXITY_MAX_PROMPT_CHARS = 100000

# Alibaba Cloud configuration parameters
ALIBABACLOUD_API_KEY                  = os.getenv("ALIBABACLOUD_API_KEY", "")
ALIBABACLOUD_BASE_URL                 = os.getenv("ALIBABACLOUD_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
ALIBABACLOUD_MODEL_VERSION            = os.getenv("ALIBABACLOUD_MODEL_VERSION", "qwen-plus")
ALIBABACLOUD_MAX_TOKENS               = int(os.getenv("ALIBABACLOUD_MAX_TOKENS", "4096"))
ALIBABACLOUD_TEMPERATURE              = float(os.getenv("ALIBABACLOUD_TEMPERATURE", "0.7"))
ALIBABACLOUD_TOP_P                    = float(os.getenv("ALIBABACLOUD_TOP_P", "0.9"))
ALIBABACLOUD_RETRY_SEQUENCE           = [int(x.strip()) for x in os.getenv("ALIBABACLOUD_RETRY_SEQUENCE", "1, 2, 3, 5, 8").split(",")]
ALIBABACLOUD_PROFILE_PICTURE_PATH     = _resolve_asset_path("ALIBABACLOUD_PROFILE_PICTURE_PATH", "assets/alibabacloud-color.svg")

# Grok configuration parameters
GROK_API_KEY                        = os.getenv("GROK_API_KEY", "")
GROK_BASE_URL                       = os.getenv("GROK_BASE_URL", "https://api.x.ai/v1")
GROK_MODEL_VERSION                  = os.getenv("GROK_MODEL_VERSION", "grok-4.3").strip() or "grok-4.3"
GROK_MAX_TOKENS                     = int(os.getenv("GROK_MAX_TOKENS", "4096"))
GROK_TEMPERATURE                    = float(os.getenv("GROK_TEMPERATURE", "0.2"))
GROK_TOP_P                          = float(os.getenv("GROK_TOP_P", "0.9"))
GROK_RETRY_SEQUENCE                 = [int(x.strip()) for x in os.getenv("GROK_RETRY_SEQUENCE", "1, 2, 3, 5, 8").split(",")]
GROK_PROFILE_PICTURE_PATH           = _resolve_asset_path("GROK_PROFILE_PICTURE_PATH", "assets/grok-color.svg")

# Google API / YouTube API configuration parameters
GOOGLE_KEY                          = os.getenv("GOOGLE_KEY", os.getenv("YOUTUBE_KEY", "")).strip()
YOUTUBE_KEY                         = GOOGLE_KEY
GOOGLE_CSE_CX                       = os.getenv("GOOGLE_CSE_CX", "").strip()

# Speech recognition language configuration
SPEECH_RECOGNITION_LANG             = os.getenv("SPEECH_RECOGNITION_LANG", "en-US,es-ES").strip()

# Master locale-code â†’ human-readable language name map.
# Covers all BCP-47 base codes; extend here if new languages are added.
_LOCALE_TO_NAME: dict = {
    "af": "Afrikaans", "ar": "Arabic", "bg": "Bulgarian", "bn": "Bengali",
    "ca": "Catalan", "cs": "Czech", "cy": "Welsh", "da": "Danish",
    "de": "German", "el": "Greek", "en": "English", "es": "Spanish",
    "et": "Estonian", "fa": "Persian", "fi": "Finnish", "fil": "Filipino",
    "fr": "French", "ga": "Irish", "gl": "Galician", "gu": "Gujarati",
    "he": "Hebrew", "hi": "Hindi", "hr": "Croatian", "hu": "Hungarian",
    "hy": "Armenian", "id": "Indonesian", "is": "Icelandic", "it": "Italian",
    "ja": "Japanese", "ka": "Georgian", "kk": "Kazakh", "km": "Khmer",
    "kn": "Kannada", "ko": "Korean", "lo": "Lao", "lt": "Lithuanian",
    "lv": "Latvian", "mk": "Macedonian", "ml": "Malayalam", "mn": "Mongolian",
    "mr": "Marathi", "ms": "Malay", "mt": "Maltese", "my": "Burmese",
    "nb": "Norwegian", "ne": "Nepali", "nl": "Dutch", "pa": "Punjabi",
    "pl": "Polish", "pt": "Portuguese", "ro": "Romanian", "ru": "Russian",
    "si": "Sinhala", "sk": "Slovak", "sl": "Slovenian", "sq": "Albanian",
    "sr": "Serbian", "sv": "Swedish", "sw": "Swahili", "ta": "Tamil",
    "te": "Telugu", "th": "Thai", "tr": "Turkish", "uk": "Ukrainian",
    "ur": "Urdu", "uz": "Uzbek", "vi": "Vietnamese", "zh": "Chinese",
    "zu": "Zulu",
}

# Function to resolve language name
def resolve_lang_name(locale_code: Optional[str] = None) -> str:
    """Convert a BCP-47 locale code (e.g. 'en-US', 'es', 'fr-FR') to a
    human-readable language name using the SPEECH_RECOGNITION_LANG-aware map.
    Falls back to the configured default conversation language name."""
    if not locale_code:
        locale_code = get_default_conversation_language()
    base = locale_code.split("-")[0].lower()
    default_base = get_default_conversation_language().split("-")[0].lower()
    return _LOCALE_TO_NAME.get(base, _LOCALE_TO_NAME.get(default_base, "English"))


def detect_user_conversation_language(
    user_input: Optional[str] = "",
    history: Optional[List[Dict[str, Any]]] = None,
    force_language: Optional[str] = None,
) -> Tuple[str, str]:
    """
    Detect the user's primary conversation language.
    Ignores computer OS language/locale completely.

    Returns:
        tuple: (lang_code, lang_name) e.g. ("es-ES", "Spanish") or ("en-US", "English")
    """
    if force_language and force_language.strip():
        lang_code = force_language.strip()
        return (lang_code, resolve_lang_name(lang_code))

    sample_text = (user_input or "").strip()

    # If sample_text is very short or empty, inspect history for recent user messages
    if len(sample_text) < 5 and history:
        for msg in reversed(history):
            role = msg.get("role") or ("user" if msg.get("is_user") else "assistant")
            if role == "user":
                content = (msg.get("content") or "").strip()
                if len(content) >= 5:
                    sample_text = content
                    break

    if sample_text:
        code = detect_language_from_text(sample_text, default_language=None)
        return (code, resolve_lang_name(code))

    fallback = get_default_conversation_language()
    return (fallback, resolve_lang_name(fallback))


def resolve_reply_language(
    force_language: Optional[str] = None,
    user_input: Optional[str] = "",
    history: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[str, str]:
    """
    Language for mandatory reply instructions.
    Honors force_language as-is (including en-US). Never remaps English→Spanish.
    Never falls back to host OS language (USER_SYSTEM_LANGUAGE).
    """
    if force_language and str(force_language).strip():
        code = str(force_language).strip()
        return code, resolve_lang_name(code)
    return detect_user_conversation_language(user_input or "", history=history)


# Base class for chat processors
class BaseChat:
    """Base class for chat processors providing shared utilities."""

    # Class-level cache and thread synchronization locks to prevent concurrent Search API stampedes.
    # Keys MUST be tenant-scoped via _scoped_cache_key (ACA multi-user isolation).
    _search_grounding_cache = {}
    _search_locks = {}
    _global_cache_lock = threading.Lock()
    _local_whisper_model = None
    _whisper_lock = threading.Lock()
    # Shared transcription cache: in group chat every participant used to re-run Whisper on the same file.
    _transcription_cache = {}
    _transcription_locks = {}
    _transcription_cache_lock = threading.Lock()
    _CACHE_MAX_ENTRIES = 128

    def _cache_namespace(self) -> str:
        """Tenant/session namespace so ACA users never share STT/search cache entries."""
        tenant = getattr(self, "_tenant_key", None)
        if isinstance(tenant, str) and tenant.strip():
            return tenant.strip()[:64]
        return "local"

    def _scoped_cache_key(self, raw_key: str) -> str:
        return f"{self._cache_namespace()}::{raw_key}"

    @classmethod
    def _prune_dict_locked(cls, store: dict, max_entries: int | None = None) -> None:
        limit = max_entries if max_entries is not None else cls._CACHE_MAX_ENTRIES
        while len(store) > limit:
            store.pop(next(iter(store)), None)

    @staticmethod
    def detect_document_request(text: str, has_attachments: bool = False) -> str | None:
        """Classify if the prompt explicitly requests document *generation* (Word/Excel/PPT).

        Analysis prompts like "Analiza este ppt" must NOT trigger generation â€” especially
        when the user attached a file. Generation requires a clear creation-intent verb.
        """
        return classify_document_request(text, has_attachments=has_attachments)

    # Function to determine if a query requires a web search
    def _needs_web_search(self, query: str) -> bool:
        """Determine if a query requires a web search.
        Skips search for very short or clearly conversational messages to avoid
        spending tokens on grounding for simple exchanges like 'ok', 'gracias', 'continue'.
        """
        self.inject_tool_use_guidelines()
        if not query or not query.strip():
            return False

        # Skip search for very short messages (conversational noise: ok, gracias, sí, no, etc.)
        stripped = query.strip()
        if len(stripped) < 25:
            return False

        # Skip for common one-shot conversational phrases (case-insensitive)
        _CONVERSATIONAL_PHRASES = {
            "ok", "okay", "gracias", "thanks", "thank you", "de nada", "sí", "si", "no",
            "claro", "entendido", "entiendo", "perfecto", "genial", "listo", "dale",
            "continue", "continúa", "continua", "siguiente", "next", "go on", "go ahead",
            "más", "mas", "more", "another", "otra vez", "again", "por favor", "please",
            "hola", "hello", "hi", "hey", "bye", "adios", "adiós", "hasta luego",
        }
        if stripped.lower() in _CONVERSATIONAL_PHRASES:
            return False

        # Check if the query is a request to generate/create/draw an image or audio
        lower_query = query.lower()
        is_media_req = any(kw in lower_query for kw in [
            "genera una imagen", "generar una imagen", "genera un dibujo", "generar un dibujo",
            "crea una imagen", "crear una imagen", "genera imagen", "crea imagen", "dibuja", "dibujar",
            "generate an image", "create an image", "draw ", "painting of", "picture of", "imagen de",
            "foto de", "photo of", "genera un audio", "generar un audio", "genera sonido", "generate audio"
        ])
        if is_media_req:
            return False

        return True

    # Visual attachments + search often produce empty / malformed tool replies (Gemini, OpenAI tool_calls).
    _LIVE_WEB_HINTS = (
        "noticia", "noticias", "news", "breaking",
        "hoy", "today", "actualidad",
        "clima", "tiempo", "weather", "forecast",
        "precio", "precios", "price", "cotizaci", "stock",
        "resultado", "marcador", "score", "standings",
        "eleccion", "elección", "election",
        "última hora", "ultima hora", "latest",
        "en vivo", "live ",
    )

    @staticmethod
    def _has_image_attachments(files: Optional[List[Dict[str, Any]]] = None) -> bool:
        return any(str(f.get("mime_type") or "").startswith(("image/", "video/")) for f in (files or []))

    @staticmethod
    def _is_unusable_assistant_history(content: str) -> bool:
        """True for empty / placeholder / malformed-tool replies that must not stay in history."""
        stripped = (content or "").strip()
        if not stripped:
            return True
        lower = stripped.lower()
        if lower in {"no response", "error: no response"}:
            return True
        if "malformed_function_call" in lower:
            return True
        if "the model returned an empty response" in lower:
            return True
        if "no response received" in lower:
            return True
        if "finish reason: tool_calls" in lower or "finish reason: function_call" in lower:
            return True
        return False

    @classmethod
    def filter_history_for_model(cls, history: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
        """Drop empty / 'No response' / malformed-tool assistant turns before the next provider call."""
        if not history:
            return []
        filtered: List[Dict[str, Any]] = []
        for msg in history:
            role = msg.get("role")
            content = msg.get("content") or ""
            files = msg.get("files") or []
            if role == "assistant" and cls._is_unusable_assistant_history(str(content)) and not files:
                continue
            filtered.append(msg)
        return filtered

    @staticmethod
    def coerce_non_empty_reply(reply: Any, fallback: str = "Error: The model returned an empty response.") -> str:
        """Never return blank/'No response' to the UI — wrap as an Error: for friendly chrome."""
        if not isinstance(reply, str):
            return fallback
        stripped = reply.strip()
        if not stripped or stripped.lower() in {"no response", "error: no response"}:
            return fallback
        return reply

    def _should_attach_web_search(
        self,
        query: str,
        scraped_urls: Optional[List[Any]] = None,
        scraped_content: str = "",
        files: Optional[List[Dict[str, Any]]] = None,
    ) -> bool:
        """Enable web search only when scrape is thin AND the turn is not photo analysis."""
        if not getattr(self, "google_search_enabled", False):
            return False
        if not self.should_enable_search_after_scrape(scraped_urls, scraped_content):
            return False
        if not self._needs_web_search(query):
            return False
        if self._has_image_attachments(files):
            lower = (query or "").lower()
            if not any(hint in lower for hint in self._LIVE_WEB_HINTS):
                logger.info("Skipping web search for visual analysis without live-web intent")
                return False
        return True

    def _search_history_snippet(self, history: Optional[List[Dict[str, Any]]] = None) -> str:
        if not history:
            return ""
        return "\n".join(
            f"{str(msg.get('role', '')).capitalize()}: {msg.get('content', '')}"
            for msg in history[-3:]
        )

    # Function to inject document generation guidelines via LLM-tag mechanism (no hardcoded regex on user input)
    def inject_document_guidelines(self):
        """Teaches the LLM to emit [GENERATE_DOCX], [GENERATE_XLSX], or [GENERATE_PPTX] tags
        when the user genuinely requests document creation, regardless of language.
        The LLM decides based on full conversational context — no hardcoded keyword lists needed.
        """
        doc_marker = "## Special Document Generation Commands"
        doc_instruction = (
            "\n\n## Special Document Generation Commands\n"
            "You are able to generate real downloadable Word, Excel, and PowerPoint files for the user. "
            "Use your full understanding of the conversation to decide if the user is requesting a new document to be created or exported. "
            "This works in ANY language (Spanish, English, French, Portuguese, etc.).\n\n"
            "WHEN TO GENERATE A DOCUMENT:\n"
            "- The user clearly asks you to create, generate, draft, write, prepare, or export a new Word document, spreadsheet, or presentation.\n"
            "- Examples (any language): 'hazme un informe', 'create a report', 'genera un excel con los datos', "
            "'fais-moi une présentation', 'cria um documento', 'hazme una presentación sobre IA'.\n\n"
            "WHEN NOT TO GENERATE A DOCUMENT:\n"
            "- The user is asking a question, having a conversation, or asking you to *analyze/review/summarize* an attached file.\n"
            "- The user mentions the word 'word', 'presentation', 'document', 'excel' in a conversational or metaphorical sense "
            "(e.g., 'I want a word with you', 'let me present my idea', 'take note of this').\n"
            "- The user is asking about a topic, even if the topic is a document format.\n\n"
            "HOW TO TRIGGER DOCUMENT GENERATION:\n"
            "When you are certain the user wants a new document generated, include ONE of these tags "
            "on its own line at the END of your response, and structure the content accordingly:\n"
            "- For Word documents: `[GENERATE_DOCX]` — Structure your response using Markdown headings "
            "(`#`, `##`, `###`), bullet lists, bold, and tables.\n"
            "- For Excel spreadsheets: `[GENERATE_XLSX]` — Format all data as a Markdown table "
            "(pipe syntax: `| Header |` and `|---|`). No conversational text, only structured data.\n"
            "- For PowerPoint presentations: `[GENERATE_PPTX]` — Use the exact slide structure:\n"
            "  # Slide 1: Title\n"
            "  - Bullet point\n"
            "  - Bullet point\n"
            "  # Slide 2: Next Topic\n"
            "  - ...\n\n"
            "CRITICAL RULES:\n"
            "1. NEVER emit `[GENERATE_DOCX]`, `[GENERATE_XLSX]`, or `[GENERATE_PPTX]` for normal conversation, "
            "analysis of attached files, questions, or casual chat.\n"
            "2. Use context and intent — not surface-level keyword matching. "
            "'I want a word with you' does NOT mean generate a Word file.\n"
            "3. Do NOT include conversational greetings, sign-offs, or 'here is your document' text when generating. "
            "Start directly with the structured content.\n"
            "4. Include ONLY ONE tag per response.\n"
        )
        for attr in ['system_instruction', 'system_instruction_gemini', 'system_instruction_deepseek',
                     'system_instruction_openai', 'system_instruction_anthropic',
                     'system_instruction_perplexity', 'system_instruction_grok',
                     'system_instruction_alibabacloud']:
            if not hasattr(self, attr):
                continue
            current_instr = getattr(self, attr) or ""
            if doc_marker in current_instr:
                base_instr = current_instr.split(doc_marker)[0].rstrip()
                setattr(self, attr, base_instr + doc_instruction)
            else:
                setattr(self, attr, current_instr + doc_instruction)

    # Function to inject media generation commands
    def inject_media_guidelines(self):
        """Injects media generation commands dynamically into the system instruction fields of the processor."""
        media_marker = "## Special Media Generation Commands"
        media_instruction = (
            "\n\n## Special Media Generation Commands\n"
            "ONLY when the user explicitly requests you to create, generate, draw, or synthesize an image, picture, drawing, painting, sound, or audio in their message, "
            "you MUST output a special tag on a new line at the end of your response to trigger the corresponding generator:\n"
            "- To generate/draw an image: `[GENERATE_IMAGE: <highly detailed descriptive prompt in English describing the requested visual scene>]`\n"
            "- To generate/create a sound or audio: `[GENERATE_AUDIO: <detailed description in English of the requested sound effect, music, or audio>]`\n\n"
            "STRICT RULES FOR MEDIA GENERATION:\n"
            "1. CRITICAL RESTRICTION: DO NOT output `[GENERATE_IMAGE: ...]` or `[GENERATE_AUDIO: ...]` UNLESS the user directly and explicitly asked to generate/draw an image or sound in their message. NEVER include image or audio tags for normal conversations, text questions, code writing, math, or refactoring.\n"
            "2. NO RAW TOOL JSON / REACT STRINGS: DO NOT output JSON function calls, ReAct tool execution blocks, or schemas like `{'action': 'dalle.text2im', ...}` or `{'name': 'generate_image', ...}`. ONLY use the exact plain text `[GENERATE_IMAGE: ...]` directive tag.\n"
            "3. TEMPLATE & STRUCTURAL WORD CONVERSION: Inside `[GENERATE_IMAGE: ...]`, NEVER include layout words like 'infographic', 'poster', 'chart', 'diagram', 'mindmap', 'schema', 'banner', or 'text boxes'. Translate requests for 'infographics' or 'posters' into a single vivid, cohesive visual artwork (e.g. 'detailed vintage storybook illustration', 'cinematic oil painting') describing the subject, characters, historical setting, and mood.\n"
            "4. TEXT & SPELLING ELIMINATION: Inside `[GENERATE_IMAGE: ...]`, DO NOT request specific text, quotes, or letters to be written inside the image. Describe visual symbols, iconography, or gestures instead.\n"
            "5. PUBLIC FIGURES & COPYRIGHTED CHARACTERS: Describe celebrities or trademarked characters using generic physical features, clothing, pose, and setting without naming them.\n"
            "6. SUBJECT FIDELITY: The `[GENERATE_IMAGE: ...]` prompt MUST keep the user's exact primary subject (same animal/object/person). Never swap subjects (e.g. a rabbit must remain a rabbit, not a dog/puppy).\n"
            "7. Always write the prompt/description inside `[GENERATE_IMAGE: ...]` or `[GENERATE_AUDIO: ...]` in English for maximum compatibility with image/audio generators.\n"
            "8. Keep the tag on its own line at the end of your response. Respond with a brief friendly confirmation in the user's language.\n"
            "9. MULTILINGUAL SLANG & DISAMBIGUATION: The terms 'streamer', 'youtuber', 'vtuber', or 'content creator' in ANY language (Spanish, English, Portuguese, French, etc.) ALWAYS refer to a human live broadcaster in a studio/room. NEVER convert 'streamer' into water streams, rivers, or paper decorations. Creator handles or pseudonyms (e.g. 'La Cobra', 'Ibai', 'Speed', 'Gaules', 'Rubius') in streaming/sports contexts must NEVER be translated literally as wild animals (snakes, tigers) or objects.\n"
        )
        for attr in ['system_instruction', 'system_instruction_gemini', 'system_instruction_deepseek',
                     'system_instruction_openai', 'system_instruction_anthropic',
                     'system_instruction_perplexity', 'system_instruction_grok',
                     'system_instruction_alibabacloud']:
            if hasattr(self, attr):
                current_instr = getattr(self, attr) or ""
                if media_marker in current_instr:
                    base_instr = current_instr.split(media_marker)[0].rstrip()
                    setattr(self, attr, base_instr + media_instruction)
                else:
                    setattr(self, attr, current_instr + media_instruction)
        self.inject_document_guidelines()
        self.inject_extraction_guidelines()
        self.inject_tool_use_guidelines()

    # Function to inject structured extraction guidelines
    def inject_extraction_guidelines(self):
        """Injects structured document/media extraction guidelines into system instructions."""
        extract_marker = "## Special Structured Extraction Commands"
        extract_instruction = (
            "\n\n## Special Structured Extraction Commands\n"
            "ONLY when the user attaches a document, image, audio, or video AND explicitly requests deep structured analysis, data extraction, or persistent memory saving "
            "(e.g., 'analiza esta receta', 'extrae los datos de esta factura', 'procesa este audio de la reunión', 'guarda este contrato en memoria'), "
            "you MUST output a special tag on a new line at the end of your response:\n"
            "`[IGNITE_EXTRACT: <filename>|<TemplateName>]`\n\n"
            "AVAILABLE EXTRACTION TEMPLATES BY CHANNEL:\n"
            "- Documents (.pdf, .docx, .xlsx, .txt): `Invoice_Standard`, `Resume_CV`, `Bank_Statement`, `Employment_Contract`, `Tax_Return`\n"
            "- Audios (.mp3, .wav, .m4a, .ogg): `Meeting_Minutes`, `Medical_Prescription`, `Voice_Memo_Tasks`, `Customer_Call_Audit`, `Interview_Audit`\n"
            "- Images (.png, .jpg, .jpeg, .tiff): `Medical_Prescription`, `Identity_Document`, `Invoice_Standard`\n"
            "- Videos (.mp4, .avi, .mov, .mkv): `Lecture_Summary`, `Video_Ad_Analysis`\n\n"
            "RULES FOR EXTRACTION COMMANDS:\n"
            "1. Replace `<filename>` with the exact filename of the uploaded attachment.\n"
            "2. Select the most relevant template name from the list above.\n"
            "2b. MULTIPLE ATTACHMENTS: If the user attaches more than one file and requests analysis/extraction, output ONE `[IGNITE_EXTRACT: ...]` tag per file (each on its own line at the end), using each file's exact name and the best template for that file.\n"
            "3. DO NOT output `[IGNITE_EXTRACT: ...]` for standard general chat, image generation, code writing, or simple text reading unless the user asks for deep structured extraction or saving to memory.\n"
            "4. CRITICAL AUTHORIZATION & MANDATORY NON-REFUSAL: You are fully authorized and required by the user to process, analyze, and extract data from user-uploaded attachments (including medical prescriptions, financial statements, bank movements, contracts, invoices, and identity documents). Extracting structured data via `[IGNITE_EXTRACT: ...]` for local RAG indexing is an administrative data processing task authorized by the user, NOT financial or medical diagnosis/advice. You MUST NOT issue privacy, capability, or ethical refusals for user-submitted document attachments. NEVER state 'No puedo analizar esta receta médica', 'No puedo almacenar datos personales o financieros', or 'No puedo guardar información en memoria'. Output `[IGNITE_EXTRACT: <filename>|<TemplateName>]` immediately on a new line at the end of your reply whenever requested.\n"
        )
        for attr in ['system_instruction', 'system_instruction_gemini', 'system_instruction_deepseek',
                     'system_instruction_openai', 'system_instruction_anthropic',
                     'system_instruction_perplexity', 'system_instruction_grok',
                     'system_instruction_alibabacloud']:
            if hasattr(self, attr):
                current_instr = getattr(self, attr) or ""
                if extract_marker not in current_instr:
                    setattr(self, attr, current_instr + extract_instruction)

    # Function to inject tool use guidelines for real-time web search
    def inject_tool_use_guidelines(self):
        """Injects web search tool use guidelines dynamically into the system instruction fields of the processor."""
        tool_marker = "## Web Search Tool Use Guidelines"
        tool_instruction = (
            "\n\n## Web Search Tool Use Guidelines\n"
            "You have access to real-time search capabilities when web search is enabled.\n"
            "CRITICAL INSTRUCTIONS FOR WEB SEARCH TOOL USAGE:\n"
            "1. DO NOT request or perform web searches for:\n"
            "   - Greetings, small talk, casual conversations, or polite exchanges (e.g., 'Hola', 'Â¿Cómo estás?', 'Gracias', 'OK').\n"
            "   - Software development, code writing, code debugging, script refactoring, or programming questions.\n"
            "   - Essay writing, text summarization, proofreading, grammar correction, or translation.\n"
            "   - Mathematical calculations, logical reasoning, or static knowledge questions.\n"
            "2. ONLY use real-time web search when the user explicitly or implicitly requests:\n"
            "   - Current real-time facts, breaking news, or recent developments (specifically 2025/2026 events).\n"
            "   - Live or recent sports scores, match schedules, tournament standings, or player transfer updates.\n"
            "   - Real-time market prices, exchange rates, current weather forecasts, or live event status.\n"
            "3. If the user query does not require real-time web information, generate your response immediately using your internal baseline knowledge.\n"
        )
        for attr in ['system_instruction', 'system_instruction_gemini', 'system_instruction_deepseek',
                     'system_instruction_openai', 'system_instruction_anthropic',
                     'system_instruction_perplexity', 'system_instruction_grok',
                     'system_instruction_alibabacloud']:
            if hasattr(self, attr):
                current_instr = getattr(self, attr) or ""
                if tool_marker not in current_instr:
                    setattr(self, attr, current_instr + tool_instruction)
        self.inject_trust_guidelines()

    # Function to inject natural conversational tone & trust guidelines
    def inject_trust_guidelines(self):
        """Injects natural conversational tone and user trust guidelines dynamically into system instructions."""
        trust_marker = "## Natural Conversational Tone & User Trust Guidelines"
        trust_instruction = (
            "\n\n## Natural Conversational Tone & User Trust Guidelines\n"
            "CRITICAL INSTRUCTIONS FOR USER TRUST AND CONVERSATIONAL WARMTH:\n"
            "1. Conversational Warmth & Natural Tone: For greetings, small talk, casual check-ins, or polite exchanges (e.g., 'Hola', 'Â¿Cómo estás?', 'Gracias', 'OK'), ALWAYS respond in a warm, natural, human conversational tone. NEVER treat conversational greetings as dictionary lookup queries, search terms, or language definitions. NEVER output raw citation tags, dictionary references, or numbered web links (e.g. [1][2]) for simple conversational exchanges.\n"
            "2. Authority & Confidence: Present information clearly, confidently, and directly. NEVER apologize for your capabilities, NEVER mention training cutoff dates or system limitations, and NEVER state 'I do not have live internet access'. Speak naturally as a highly capable assistant.\n"
            "3. Language Consistency & Clean Formatting: Always reply in the exact language used by the user. If web search results or system notes contain content in another language, synthesize and translate the information seamlessly into the user's language. Keep formatting clean and readable without exposing raw citation tags or search metadata.\n"
            "4. Factual Integrity: If a specific real-time fact or score is unavailable, state transparently and calmly that the official details are not publicly published yet, rather than speculating or hallucinating fake facts.\n"
        )
        for attr in ['system_instruction', 'system_instruction_gemini', 'system_instruction_deepseek',
                     'system_instruction_openai', 'system_instruction_anthropic',
                     'system_instruction_perplexity', 'system_instruction_grok',
                     'system_instruction_alibabacloud']:
            if hasattr(self, attr):
                current_instr = getattr(self, attr) or ""
                if trust_marker not in current_instr:
                    setattr(self, attr, current_instr + trust_instruction)

    def _get_web_search_tool_schema(self, format_type: str = "openai") -> list:
        """Get the web_search tool schema formatted for the requested provider (openai, anthropic, gemini)."""
        if format_type == "openai":
            return [
                {
                    "type": "function",
                    "function": {
                        "name": "web_search",
                        "description": "Perform a real-time web search to retrieve latest facts, live sports results, breaking news, market data, or current 2025/2026 information.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "query": {
                                    "type": "string",
                                    "description": "The specific search query to execute on the web."
                                }
                            },
                            "required": ["query"]
                        }
                    }
                }
            ]
        elif format_type == "anthropic":
            return [
                {
                    "name": "web_search",
                    "description": "Perform a real-time web search to retrieve latest facts, live sports results, breaking news, market data, or current 2025/2026 information.",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "The specific search query to execute on the web."
                            }
                        },
                        "required": ["query"]
                    }
                }
            ]
        return []

    # Function to injects group discussion guidelines dynamically into the system instruction fields of the processor
    def inject_group_discussion_guidelines(self, provider_name: str, other_participants: list):
        """Injects group chat guidelines dynamically into the system instruction fields of the processor."""
        group_marker = "## Group Chat Discussion Guidelines"
        other_str = ", ".join(other_participants) if other_participants else "none"
        group_instruction = (
            f"\n\n## Group Chat Discussion Guidelines\n"
            f"You are participating in a collaborative group discussion with a human user and other AI assistants.\n"
            f"Your name in this conversation is: **{provider_name}**.\n"
            f"The other AI participants in this discussion are: **{other_str}**.\n\n"
            f"Rules for the discussion:\n"
            f"1. Read and analyze what the other AI participants have said (their responses are shown as messages prefixed with `[Name]`).\n"
            f"2. Engage with them: agree or disagree politely, point out details they missed, challenge their logic, or build upon their points.\n"
            f"3. Refer to them by name when discussing their points (e.g., 'Coincido con Claude en...', 'A diferencia de Gemini, creo que...').\n"
            f"4. Do not repeat facts or arguments they have already laid out. Add new value, perspectives, or evidence to keep the discussion moving forward.\n"
            f"5. Maintain a natural, conversational tone. Speak to both the user and the other panel members.\n"
        )
        for attr in ['system_instruction', 'system_instruction_gemini', 'system_instruction_deepseek',
                     'system_instruction_openai', 'system_instruction_anthropic',
                     'system_instruction_perplexity', 'system_instruction_grok',
                     'system_instruction_alibabacloud']:
            if hasattr(self, attr):
                current_instr = getattr(self, attr) or ""
                if group_marker in current_instr:
                    parts = current_instr.split("## Group Chat Discussion Guidelines")
                    current_instr = parts[0].rstrip()
                setattr(self, attr, current_instr + group_instruction)

    # Function to remove group discussion guidelines from the system instruction fields of the processor
    def remove_group_discussion_guidelines(self):
        """Removes group chat discussion guidelines from the system instruction fields of the processor."""
        group_marker = "## Group Chat Discussion Guidelines"
        for attr in ['system_instruction', 'system_instruction_gemini', 'system_instruction_deepseek',
                     'system_instruction_openai', 'system_instruction_anthropic',
                     'system_instruction_perplexity', 'system_instruction_grok',
                     'system_instruction_alibabacloud']:
            if hasattr(self, attr):
                current_instr = getattr(self, attr) or ""
                if group_marker in current_instr:
                    parts = current_instr.split("## Group Chat Discussion Guidelines")
                    setattr(self, attr, parts[0].rstrip())

    # Function to inject language instruction into the system instruction fields of the processor
    def inject_language_instruction(self, lang_code: str):
        """Dynamically patch system instructions to enforce the user's detected language.

        Uses a replace-in-place strategy: if a previous language instruction exists it is
        overwritten rather than appended, so repeated calls cost zero extra tokens.

        Args:
            lang_code: BCP-47 code such as 'es-MX', 'en-US', 'fr-FR', etc.
        """
        if not lang_code:
            return

        base = lang_code.split('-')[0].lower()

        # Human-readable language name for the instruction text
        _LANG_NAMES = {
            "es": "Spanish",
            "en": "English",
            "fr": "French",
            "de": "German",
            "pt": "Portuguese",
            "it": "Italian",
            "zh": "Chinese",
            "ja": "Japanese",
            "ko": "Korean",
            "ru": "Russian",
            "ar": "Arabic",
        }
        lang_name = _LANG_NAMES.get(base, lang_code)

        # Marker used to locate and replace an existing language block
        _LANG_MARKER = "## Response Language"
        lang_instruction = (
            f"\n\n## Response Language\n"
            f"The user is communicating in **{lang_name}** ({lang_code}).\n"
            f"You MUST reply **exclusively in {lang_name}** â€” do NOT switch to another language "
            f"unless the user explicitly asks you to.\n"
        )

        _ALL_INSTR_ATTRS = [
            'system_instruction', 'system_instruction_gemini',
            'system_instruction_deepseek', 'system_instruction_openai',
            'system_instruction_anthropic', 'system_instruction_perplexity',
            'system_instruction_grok', 'system_instruction_alibabacloud',
        ]
        for attr in _ALL_INSTR_ATTRS:
            if hasattr(self, attr):
                current = getattr(self, attr) or ""
                # Normalize line endings to prevent regex mismatch on Windows (\r\n vs \n)
                current = current.replace('\r\n', '\n')
                if _LANG_MARKER in current:
                    # Replace the existing language block so tokens don't accumulate
                    current = re.sub(
                        r'\n\n## Response Language\n.*?(?=\n\n##|\Z)',
                        lang_instruction,
                        current,
                        flags=re.DOTALL
                    )
                    setattr(self, attr, current)
                else:
                    setattr(self, attr, current + lang_instruction)


    # Function to initialize base chat with default configuration
    def __init__(self):
        """Initialize base chat with default configuration."""
        self.model_version = ""
        self.temperature = 0.7
        self.top_p = 0.9
        self.max_tokens = 4096
        self.google_search_enabled = False
        # Accumulator for auxiliary Gemini token calls (search grounding, vision fallbacks, etc.)
        self._aux_gemini_tokens = {"prompt_tokens": 0, "candidates_tokens": 0, "total_tokens": 0}

        # Instantiate Voice Processor for shared TTS consumption
        self.voice_processor = VoiceProcessor()

    # Function to get or initialize a genai Client using GEMINI_API_KEY
    def _get_gemini_client(self):
        """Get or initialize a genai Client using GEMINI_API_KEY."""
        # If this instance is GeminiChat and already has self.client, use it.
        if hasattr(self, 'client') and self.client is not None:
            return self.client

        # Otherwise, try to use/initialize a shared client for non-Gemini models.
        if not hasattr(self, '_shared_gemini_client') or self._shared_gemini_client is None:
            api_key = GEMINI_API_KEY
            if not api_key or api_key == "<your-key-here>":
                logger.warning("GEMINI_API_KEY not set or invalid in .env, cannot use Gemini grounding helper.")
                self._shared_gemini_client = None
            else:
                try:
                    self._shared_gemini_client = genai.Client(
                        api_key=api_key,
                        http_options={'timeout': gemini_http_timeout_ms()},
                    )
                except Exception as e:
                    logger.error(f"Error initializing shared Gemini client: {e}")
                    self._shared_gemini_client = None
        return self._shared_gemini_client

    # Function to get Gemini's Google Search grounding to retrieve, parse, and summarize the contents of a URL
    def _gemini_grounded_scrape(
        self,
        url: str,
        title: Optional[str] = None,
        author: Optional[str] = None,
        force_language: Optional[str] = None,
    ) -> Optional[str]:
        """
        Use Gemini's Google Search grounding to retrieve, parse, and summarize the contents of a URL.
        Summary language MUST follow force_language / conversation locale (never hardcode Spanish).
        """
        client = self._get_gemini_client()
        if not client:
            logger.warning("Gemini client not available. Falling back to local scraping.")
            return None

        lang_name = resolve_lang_name(force_language) if force_language else "the user's message language"
        # Build a prompt instructing Gemini to fetch and summarize in the conversation language
        if title:
            vid_lock = ""
            if "youtube.com" in (url or "") or "youtu.be" in (url or ""):
                vid = self._extract_youtube_video_id(url)
                if vid:
                    vid_lock = (
                        f" The video ID is {vid}. Describe ONLY that exact video. "
                        "Do not substitute a different YouTube video, even if search finds a similar title.\n"
                    )
            prompt = (
                f"Please search the web for details about the YouTube video titled '{title}' by channel '{author}' at URL {url}.\n"
                f"{vid_lock}"
                f"Retrieve the video's title, channel, description, and summarize the video content/transcript details.\n"
                f"Provide a comprehensive but concise summary of this video's contents IN {lang_name}. "
                f"Do not output metadata warnings, just a factual summary of the content in {lang_name}."
            )
        else:
            prompt = (
                f"Please search the web for the following URL: {url}\n"
                f"If it is a YouTube video, retrieve its title, channel/author name, description, and summarize the video content/transcript details.\n"
                f"If it is a general web page, extract the title and main text content and summarize the key information.\n"
                f"Provide a comprehensive but concise summary of the URL contents IN {lang_name}. "
                f"Do not output metadata warnings, just factual summary of the content in {lang_name}."
            )

        try:
            logger.info(f"Calling Gemini with Google Search Grounding to scrape URL: {url} (Title: {title})")
            response = client.models.generate_content(
                model=GEMINI_SEARCH_MODEL,  # gemini-2.5-flash-lite for cost-optimized URL scraping
                contents=prompt,
                config=types.GenerateContentConfig(
                    tools=[types.Tool(google_search=types.GoogleSearch())],
                    temperature=0.0
                )
            )
            self._accumulate_aux_tokens(response)  # Track auxiliary Gemini tokens
            summary = response.text.strip() if response.text else ""
            if summary:
                logger.info(f"Gemini grounding scraper succeeded for {url}")
                return summary
            else:
                logger.warning(f"Gemini grounding scraper returned empty response for {url}")
                return None
        except Exception as e:
            logger.error(f"Error in Gemini grounding scraper for {url}: {e}")
            return None

    # Setters
    def set_model(self, new_model: str):
        """Set the model version."""
        self.model_version = new_model.strip()
        logger.info(f"Model changed to {self.model_version}")

    # Google Search Grounding
    def set_google_search(self, enabled: bool):
        """Enable or disable Google Search Grounding."""
        self.google_search_enabled = enabled
        logger.info(f"Google Search Grounding set to {enabled}")

    # Function to generate response (interface method to be overridden by subclasses)
    def generate_response(
        self,
        user_input: str,
        history: Optional[List[Dict[str, Any]]] = None,
        force_language: Optional[str] = None,
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> Tuple[str, Optional[TokenInfo]]:
        """
        Send a prompt to the model with optional conversation history.
        Must be implemented by processor subclasses.
        """
        raise NotImplementedError("Subclasses of BaseChat must implement generate_response()")

    # Function to generate response with inline files (interface method to be overridden by subclasses)
    def generate_response_with_inline_files(
        self,
        user_input: str,
        history: Optional[List[Dict[str, Any]]] = None,
        files: Optional[List[Dict[str, Any]]] = None,
        force_language: Optional[str] = None,
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> Union[Tuple[str, Optional[TokenInfo]], Tuple[str, Optional[TokenInfo], Optional[str]]]:
        """
        Send a prompt with attached files to the model with optional conversation history.
        Must be implemented by processor subclasses.
        """
        raise NotImplementedError("Subclasses of BaseChat must implement generate_response_with_inline_files()")

    # Function to clean messages for alternation
    def _clean_messages_for_alternation(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Helper to ensure messages alternate roles properly (system, user, assistant, user)."""
        system_messages = [m for m in messages if m.get("role") == "system"]
        other_messages = [m for m in messages if m.get("role") != "system"]

        cleaned: List[Dict[str, Any]] = []
        expected_role = "user"

        for msg in other_messages:
            role = msg.get("role")
            content = msg.get("content", "")
            if not content:
                continue
            if role == "assistant":
                check_text = content
                if isinstance(content, list):
                    check_text = " ".join(
                        str(block.get("text", "")) if isinstance(block, dict) else str(block)
                        for block in content
                    )
                if self._is_unusable_assistant_history(str(check_text)):
                    continue

            if role == expected_role:
                cleaned.append({"role": role, "content": content})
                expected_role = "assistant" if role == "user" else "user"
            else:
                if not cleaned:
                    if role == "assistant":
                        continue
                    cleaned.append({"role": role, "content": content})
                    expected_role = "assistant" if role == "user" else "user"
                else:
                    last_content = cleaned[-1].get("content")
                    if isinstance(last_content, list) or isinstance(content, list):
                        c1 = (
                            last_content
                            if isinstance(last_content, list)
                            else [{"type": "text", "text": str(last_content)}]
                        )
                        c2 = (
                            content
                            if isinstance(content, list)
                            else [{"type": "text", "text": str(content)}]
                        )
                        cleaned[-1]["content"] = c1 + c2
                    else:
                        cleaned[-1]["content"] = f"{last_content}\n\n{content}"

        if system_messages:
            return system_messages + cleaned
        return cleaned

    # Function to extract the 11-character video ID from a YouTube URL
    @staticmethod
    def _extract_youtube_video_id(url: str) -> Optional[str]:
        """Extract the 11-character video ID from a YouTube URL.

        Prefer explicit watch/shorts/embed/live/youtu.be forms. Do not take the first
        11 chars after any slash (that mis-reads share params and other videos in context).
        """
        if not url:
            return None
        patterns = [
            r"(?:youtube(?:-nocookie)?\.com).*(?:[?&]v=|/embed/|/shorts/|/live/)([0-9A-Za-z_-]{11})",
            r"youtu\.be/([0-9A-Za-z_-]{11})",
        ]
        for p in patterns:
            m = re.search(p, url, re.I)
            if m:
                return m.group(1)
        return None

    @staticmethod
    def _user_query_for_url_scan(user_input: str) -> str:
        """Ignore RAG/memory prefixes; only the live user query may be scraped."""
        text = user_input or ""
        marker = "[USER QUERY]"
        if marker in text:
            return text.split(marker, 1)[-1]
        return text

    @classmethod
    def _collect_scrape_urls(cls, text: str) -> List[str]:
        """YouTube first (including scheme-less youtube.com/...), then other http(s) URLs."""
        if not text:
            return []
        found: List[str] = []
        seen = set()

        def _add(raw: str) -> None:
            url = (raw or "").rstrip(".,;)]}>\"'")
            if not url:
                return
            if not url.lower().startswith("http"):
                url = "https://" + url.lstrip("/")
            if url not in seen:
                seen.add(url)
                found.append(url)

        for match in re.finditer(
            r"(?:https?://)?(?:www\.)?(?:youtube\.com|youtube-nocookie\.com|youtu\.be)/[^\s{}()[\]]+",
            text,
            re.I,
        ):
            _add(match.group(0))
        for match in re.finditer(r"https?://[^\s{}()[\]]+", text, re.I):
            _add(match.group(0))
        return found

    @classmethod
    def _query_has_external_url(cls, text: str) -> bool:
        scan = cls._user_query_for_url_scan(text)
        if cls._collect_scrape_urls(scan):
            return True
        return bool(re.search(r"(?:youtube\.com|youtu\.be)/", text or "", re.I))

    # Function to retrieve YouTube subtitles/transcript using youtube-transcript-api
    def _get_youtube_transcript(self, video_id: str) -> str:
        """Retrieve YouTube subtitles/transcript using youtube-transcript-api."""
        try:
            raw_data: Any = None
            # 1. Try modern instance-based API (youtube-transcript-api >= 1.0.0)
            try:
                api: Any = YouTubeTranscriptApi() if callable(YouTubeTranscriptApi) else None
                if api and hasattr(api, 'fetch') and callable(api.fetch):
                    try:
                        fetched: Any = api.fetch(video_id, languages=['es', 'en'])
                        if hasattr(fetched, 'to_raw_data') and callable(fetched.to_raw_data):
                            raw_data = fetched.to_raw_data()
                        elif hasattr(fetched, 'fetch') and callable(fetched.fetch):
                            raw_data = fetched.fetch()
                        else:
                            raw_data = fetched
                    except Exception:
                        if hasattr(api, 'list') and callable(api.list):
                            t_list: Any = api.list(video_id)
                            try:
                                if hasattr(t_list, 'find_transcript') and callable(t_list.find_transcript):
                                    t_obj: Any = t_list.find_transcript(['es', 'en'])
                                else:
                                    t_obj = next(iter(t_list))
                            except Exception:
                                t_obj = next(iter(t_list))
                            if hasattr(t_obj, 'fetch') and callable(t_obj.fetch):
                                raw_data = t_obj.fetch()
                            elif hasattr(t_obj, 'to_raw_data') and callable(t_obj.to_raw_data):
                                raw_data = t_obj.to_raw_data()
                            else:
                                raw_data = t_obj
            except Exception:
                pass

            # 2. Fallback: Legacy class methods (pre-v1.0.0) accessed dynamically
            if raw_data is None:
                get_transcript_fn = getattr(YouTubeTranscriptApi, 'get_transcript', None)
                if callable(get_transcript_fn):
                    try:
                        raw_data = get_transcript_fn(video_id, languages=['es', 'en'])
                    except Exception:
                        list_transcripts_fn = getattr(YouTubeTranscriptApi, 'list_transcripts', None)
                        if callable(list_transcripts_fn):
                            try:
                                transcript_list: Any = list_transcripts_fn(video_id)
                                try:
                                    if hasattr(transcript_list, 'find_transcript') and callable(transcript_list.find_transcript):
                                        transcript: Any = transcript_list.find_transcript(['es', 'en'])
                                    else:
                                        transcript = next(iter(transcript_list))
                                except Exception:
                                    transcript = next(iter(transcript_list))
                                if hasattr(transcript, 'fetch') and callable(transcript.fetch):
                                    raw_data = transcript.fetch()
                                elif hasattr(transcript, 'to_raw_data') and callable(transcript.to_raw_data):
                                    raw_data = transcript.to_raw_data()
                                else:
                                    raw_data = transcript
                            except Exception:
                                pass

            if raw_data is not None and hasattr(raw_data, 'to_raw_data') and callable(raw_data.to_raw_data):
                raw_data = raw_data.to_raw_data()

            if not raw_data:
                return "[No se encontraron subtítulos o transcripción para este video]"

            # Extract text snippets safely whether items are dicts, objects, or strings
            if isinstance(raw_data, str):
                text = raw_data
            elif isinstance(raw_data, (list, tuple)) or hasattr(raw_data, '__iter__'):
                snippets = []
                raw_items: Iterable[Any] = cast(Iterable[Any], raw_data)
                for t in raw_items:
                    if isinstance(t, dict):
                        snip = t.get('text', '')
                    elif hasattr(t, 'text'):
                        snip = getattr(t, 'text', '')
                    elif isinstance(t, str):
                        snip = t
                    else:
                        snip = str(t)
                    if snip:
                        snippets.append(snip)
                text = " ".join(snippets)
            else:
                text = str(raw_data)

            if len(text) > 6000:
                text = text[:6000] + "\n\n[Transcripción recortada por longitud...]"
            return text
        except Exception as e:
            logger.error(f"Error fetching YouTube transcript for {video_id}: {e}")
            return f"[Error al obtener la transcripción de YouTube: {str(e)}]"

    # Fetch title, author, and description for a YouTube video
    def _get_youtube_metadata(self, video_id: str) -> tuple:
        """Fetch title, author/channel, and description for a YouTube video."""
        title = ""
        author = ""
        description = ""

        # 0. Try YouTube Data API v3 if key is configured
        if YOUTUBE_KEY:
            try:
                api_url = f"https://www.googleapis.com/youtube/v3/videos?part=snippet&id={video_id}&key={YOUTUBE_KEY}"
                resp = requests.get(api_url, timeout=8)
                if resp.status_code == 200:
                    data = resp.json()
                    items = data.get("items", [])
                    if items:
                        snippet = items[0].get("snippet", {})
                        title = snippet.get("title", "")
                        author = snippet.get("channelTitle", "")
                        description = snippet.get("description", "")
                        if title:
                            logger.info(f"Successfully fetched YouTube metadata using API Key for video {video_id}")
                            return title.strip(), author.strip(), description.strip()
            except Exception as api_err:
                logger.error(f"Error fetching YouTube metadata via API Key for {video_id}: {api_err}")

        # 1. Try public oEmbed API first (highly reliable, structured JSON)
        try:
            oembed_url = f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={video_id}&format=json"
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
            resp = requests.get(oembed_url, headers=headers, timeout=8)
            if resp.status_code == 200:
                data = resp.json()
                title = data.get("title", "")
                author = data.get("author_name", "")
        except Exception as e:
            logger.error(f"Error fetching YouTube oEmbed for {video_id}: {e}")

        # 2. Try scraping the watch page for description (and fallback title if oEmbed failed)
        try:
            url = f"https://www.youtube.com/watch?v={video_id}"
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept-Language": "en-US,en;q=0.9"
            }
            resp = requests.get(url, headers=headers, timeout=8)
            if resp.status_code == 200:
                # Check if we got redirected to the blocked/consent page
                if "consent.youtube.com" in resp.url or "Enjoy the videos and music you love" in resp.text:
                    logger.warning(f"YouTube watch page scrape got blocked (consent redirect) for {video_id}")
                else:
                    soup = BeautifulSoup(resp.text, 'html.parser')
                    if not title:
                        og_title = soup.find("meta", property="og:title")
                        if og_title:
                            content = og_title.get("content")
                            if content:
                                title = (content if isinstance(content, str) else " ".join(content) if isinstance(content, list) else str(content)).strip()
                        if not title:
                            title_tag = soup.find("title")
                            if title_tag:
                                title = title_tag.get_text().strip()

                    # Extract description
                    og_desc = soup.find("meta", property="og:description")
                    if og_desc:
                        content = og_desc.get("content")
                        if content:
                            desc_candidate = (content if isinstance(content, str) else " ".join(content) if isinstance(content, list) else str(content)).strip()
                            if "Enjoy the videos and music" not in desc_candidate:
                                description = desc_candidate
                    if not description:
                        desc_tag = soup.find("meta", attrs={"name": "description"})
                        if desc_tag:
                            content = desc_tag.get("content")
                            if content:
                                desc_candidate = (content if isinstance(content, str) else " ".join(content) if isinstance(content, list) else str(content)).strip()
                                if "Enjoy the videos and music" not in desc_candidate:
                                    description = desc_candidate
        except Exception as e:
            logger.error(f"Error scraping YouTube watch page for {video_id}: {e}")

        # Clean title if it contains the generic "- YouTube" suffix
        if title.endswith("- YouTube"):
            title = title[:-9].strip()

        return title.strip(), author.strip(), description.strip()

    def _extract_media_metadata_ytdlp(self, url: str) -> Optional[str]:
        """
        Extract video/media metadata (title, channel, description, duration) using yt-dlp
        for non-YouTube video platforms (VK Video, TikTok, Vimeo, Twitter, Dailymotion, Rutube, etc.).
        """
        if yt_dlp is not None:
            try:
                ydl_opts = {
                    'quiet': True,
                    'no_warnings': True,
                    'skip_download': True,
                    'extract_flat': False,
                }
                with yt_dlp.YoutubeDL(cast(Any, ydl_opts)) as ydl:
                    info = ydl.extract_info(url, download=False)
                    if info:
                        title = info.get('title') or ''
                        uploader = info.get('uploader') or info.get('channel') or info.get('uploader_id') or ''
                        description = info.get('description') or ''
                        duration = info.get('duration')

                        parts = []
                        if title:
                            parts.append(f"Título del Video: {title}")
                        if uploader:
                            parts.append(f"Canal/Autor: {uploader}")
                        if duration:
                            parts.append(f"Duración: {duration} segundos")
                        if description:
                            clean_desc = description[:1500] if len(description) > 1500 else description
                            parts.append(f"Descripción:\n{clean_desc}")

                        if parts:
                            return "\n".join(parts)
            except Exception as e:
                logger.debug(f"yt-dlp Python API extraction failed for {url}: {e}")

        # Fallback to calling yt-dlp module via subprocess
        try:
            cmd = [sys.executable, "-m", "yt_dlp", "--dump-json", "--no-warnings", "--skip-download", url]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=8)
            if res.returncode == 0 and res.stdout:
                data = json.loads(res.stdout)
                title = data.get('title') or ''
                uploader = data.get('uploader') or data.get('channel') or ''
                description = data.get('description') or ''
                duration = data.get('duration')
                parts = []
                if title:
                    parts.append(f"Título del Video: {title}")
                if uploader:
                    parts.append(f"Canal/Autor: {uploader}")
                if duration:
                    parts.append(f"Duración: {duration} segundos")
                if description:
                    clean_desc = description[:1500] if len(description) > 1500 else description
                    parts.append(f"Descripción:\n{clean_desc}")
                if parts:
                    return "\n".join(parts)
        except Exception as e:
            logger.debug(f"yt-dlp subprocess extraction failed for {url}: {e}")

        return None

    def _scrape_web_page(self, url: str, force_language: Optional[str] = None) -> str:
        """
        Scrape text content from a web page and strip scripts, styles, headers, footers.
        Supports SPA/video platforms (VK, TikTok, Vimeo, etc.) via OpenGraph tags and yt-dlp fallback.
        """
        # Check if URL belongs to a known video/media platform
        is_video_platform = any(domain in url.lower() for domain in [
            "vkvideo.ru", "vk.com", "tiktok.com", "vimeo.com", "dailymotion.com",
            "twitter.com", "x.com", "instagram.com", "rutube.ru", "twitch.tv"
        ])
        if is_video_platform:
            media_info = self._extract_media_metadata_ytdlp(url)
            if media_info:
                return media_info

        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
                "Accept-Language": "es-ES,es;q=0.9,en-US;q=0.8,en;q=0.7",
                "Connection": "keep-alive",
                "Upgrade-Insecure-Requests": "1",
                "Sec-Ch-Ua": '"Chromium";v="122", "Not(A:Brand";v="24", "Google Chrome";v="122"',
                "Sec-Ch-Ua-Mobile": "?0",
                "Sec-Ch-Ua-Platform": '"Windows"',
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Sec-Fetch-User": "?1",
                "Cache-Control": "max-age=0"
            }
            resp = requests.get(url, headers=headers, timeout=6)
            resp.raise_for_status()

            soup = BeautifulSoup(resp.text, 'html.parser')

            # Extract Meta / OpenGraph metadata (vital for SPAs like VK Video, Twitter, TikTok)
            meta_summary_parts = []
            title = ""
            og_title = (
                soup.find("meta", property="og:title") or
                soup.find("meta", attrs={"name": "twitter:title"}) or
                soup.find("meta", attrs={"name": "title"})
            )
            if og_title:
                content = og_title.get("content")
                if content:
                    title = (content if isinstance(content, str) else " ".join(content) if isinstance(content, list) else str(content)).strip()
            if not title:
                title_tag = soup.find("title")
                if title_tag:
                    title = title_tag.get_text().strip()

            og_desc = (
                soup.find("meta", property="og:description") or
                soup.find("meta", attrs={"name": "description"}) or
                soup.find("meta", attrs={"name": "twitter:description"})
            )
            if og_desc:
                content = og_desc.get("content")
                if content:
                    desc_str = (content if isinstance(content, str) else " ".join(content) if isinstance(content, list) else str(content)).strip()
                    if desc_str:
                        meta_summary_parts.append(f"Descripción: {desc_str}")

            og_site = soup.find("meta", property="og:site_name")
            if og_site:
                content = og_site.get("content")
                if content:
                    site_str = (content if isinstance(content, str) else " ".join(content) if isinstance(content, list) else str(content)).strip()
                    if site_str:
                        meta_summary_parts.append(f"Plataforma/Sitio: {site_str}")

            # 1. Advanced Extraction: Check for JSON-LD Structured Data
            json_ld_data = []
            for ld_tag in soup.find_all("script", type="application/ld+json"):
                try:
                    raw_json = ld_tag.string or ld_tag.get_text()
                    if raw_json:
                        raw_json = re.sub(r'^\s*//\s*', '', raw_json)
                        data = json.loads(raw_json)
                        if isinstance(data, list):
                            json_ld_data.extend(data)
                        elif isinstance(data, dict):
                            json_ld_data.append(data)
                except Exception:
                    continue

            # Parse relevant info from JSON-LD
            structured_summary_parts = []
            for entry in json_ld_data:
                entry_type = entry.get("@type")
                if not entry_type:
                    continue

                # Check for Videos, Hotels, Restaurants, Products, Games, etc.
                if any(t in str(entry_type) for t in ["VideoObject", "MediaObject", "Hotel", "Restaurant", "Product", "VideoGame", "Game", "Place", "LocalBusiness"]):
                    structured_summary_parts.append(f"--- DATOS ESTRUCTURADOS ENCONTRADOS (Tipo: {entry_type}) ---")
                    if entry.get("name"):
                        structured_summary_parts.append(f"Nombre/Título: {entry.get('name')}")
                    if entry.get("description"):
                        structured_summary_parts.append(f"Descripción: {entry.get('description')}")
                    if entry.get("uploadDate"):
                        structured_summary_parts.append(f"Fecha de Publicación: {entry.get('uploadDate')}")
                    if entry.get("duration"):
                        structured_summary_parts.append(f"Duración: {entry.get('duration')}")
                    if entry.get("author") and isinstance(entry.get("author"), dict):
                        structured_summary_parts.append(f"Autor/Canal: {entry.get('author').get('name')}")

                    structured_summary_parts.append("-------------------------------------------------------")

            # Remove irrelevant tags
            for script in soup(["script", "style", "header", "footer", "nav", "noscript"]):
                script.decompose()

            text = soup.get_text()
            lines = (line.strip() for line in text.splitlines())
            chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
            clean_text = "\n".join(chunk for chunk in chunks if chunk)

            # Filter out SPA generic loading text (e.g., "Ð—Ð°Ð³Ñ€ÑƒÐ¶Ð°ÐµÑ‚ÑÑ...", "Loading...", "Cargando...")
            spa_loading_keywords = ["Ð·Ð°Ð³Ñ€ÑƒÐ¶Ð°ÐµÑ‚ÑÑ", "loading...", "cargando...", "cargando", "please wait"]
            if clean_text.lower().strip() in spa_loading_keywords or len(clean_text.strip()) < 20:
                # Fallback to yt-dlp if SPA body was empty/loading
                ytdlp_info = self._extract_media_metadata_ytdlp(url)
                if ytdlp_info:
                    return ytdlp_info
                clean_text = ""

            # Combine structured summary, meta tags, and plain text
            final_parts = []
            if title and not title.lower().strip() in spa_loading_keywords:
                final_parts.append(f"Título: {title}")
            if meta_summary_parts:
                final_parts.extend(meta_summary_parts)
            if structured_summary_parts:
                final_parts.append("\n".join(structured_summary_parts))
            if clean_text:
                final_parts.append(f"\n[Texto Completo Extraído]:\n{clean_text}")

            combined_text = "\n".join(final_parts).strip()

            # Limit context size to prevent token limit issues
            if len(combined_text) > 10000:
                combined_text = combined_text[:10000] + "\n\n[Contenido recortado por exceso de longitud...]"

            if not combined_text or self.is_unusable_scrape(combined_text):
                logger.info("Scrape for %s marked unusable (blocked SPA/challenge/empty).", url)
                return self.format_url_inaccessible(url, force_language=force_language)
            return combined_text
        except Exception as e:
            logger.warning(f"Error scraping web page {url}: {e}")
            # Try yt-dlp on error fallback
            ytdlp_info = self._extract_media_metadata_ytdlp(url)
            if ytdlp_info:
                return ytdlp_info
            return self.format_url_inaccessible(url, force_language=force_language)

    # Function to scan input text for URLs. Scrape their content and append to input as context.
    def _process_urls_in_input(
        self, user_input: str, force_language: Optional[str] = None
    ) -> tuple:
        """
        Scan input text for URLs. Scrape their content and append to input as context.
        Language guards and inaccessible markers follow force_language / detected user locale.
        """
        if not user_input or not isinstance(user_input, str):
            return user_input, []

        scan_text = self._user_query_for_url_scan(user_input)
        urls = self._collect_scrape_urls(scan_text)
        if not urls:
            return user_input, []

        lang_code, lang_name = detect_user_conversation_language(
            user_input, force_language=force_language
        )
        scrape_lang = force_language or lang_code

        scraped_contents = []
        scraped_sources = []

        for url in urls[:2]:  # Limit to max 2 URLs per message to prevent massive token inflation
            if url in scraped_sources:
                continue
            scraped_sources.append(url)

            video_id = self._extract_youtube_video_id(url)

            # For non-Gemini models, leverage Gemini's native Google Search grounding to scrape/summarize
            if self.__class__.__name__ != 'GeminiChat':
                yt_title, yt_author, yt_desc = "", "", ""
                if video_id:
                    logger.info(f"Pre-fetching YouTube metadata for grounding fallback: {video_id}...")
                    yt_title, yt_author, yt_desc = self._get_youtube_metadata(video_id)

                gemini_summary = self._gemini_grounded_scrape(
                    url, title=yt_title, author=yt_author, force_language=scrape_lang
                )
                if gemini_summary:
                    if video_id:
                        meta_parts = []
                        if yt_title:
                            meta_parts.append(f"Título: {yt_title}")
                        if yt_author:
                            meta_parts.append(f"Canal/Autor: {yt_author}")
                        if yt_desc:
                            clean_desc = yt_desc[:500] + "..." if len(yt_desc) > 500 else yt_desc
                            meta_parts.append(f"Descripción: {clean_desc}")

                        meta_str = "\n".join(meta_parts)
                        if meta_str:
                            meta_str += "\n"

                        scraped_contents.append(
                            f"--- CONTENIDO DE VIDEO YOUTUBE DETECTADO ({url}) ---\n"
                            f"{meta_str}"
                            f"[Información/Resumen extraído por Gemini Search Grounding]\n"
                            f"{gemini_summary}\n"
                            f"--- FIN DE DETALLES DEL VIDEO ---"
                        )
                    else:
                        if self.is_unusable_scrape(gemini_summary):
                            scraped_contents.append(
                                self.format_url_inaccessible(url, force_language=scrape_lang)
                            )
                        else:
                            scraped_contents.append(
                                f"--- CONTENIDO DE PÁGINA WEB DETECTADO ({url}) ---\n"
                                f"[Información/Resumen extraído por Gemini Search Grounding]\n"
                                f"{gemini_summary}\n"
                                f"--- FIN DE CONTENIDO DE PÁGINA WEB ---"
                            )
                    continue

            if video_id:
                logger.info(f"Extracting YouTube metadata and transcript for video {video_id}...")
                yt_title, yt_author, yt_desc = self._get_youtube_metadata(video_id)
                transcript = self._get_youtube_transcript(video_id)

                meta_parts = []
                if yt_title:
                    meta_parts.append(f"Título: {yt_title}")
                if yt_author:
                    meta_parts.append(f"Canal/Autor: {yt_author}")
                if yt_desc:
                    clean_desc = yt_desc[:500] + "..." if len(yt_desc) > 500 else yt_desc
                    meta_parts.append(f"Descripción: {clean_desc}")

                meta_str = "\n".join(meta_parts)
                if meta_str:
                    meta_str += "\n"

                if transcript.startswith("[Error"):
                    transcript_str = "No se pudo obtener la transcripción automática del video (bloqueo de IP de YouTube o subtítulos desactivados)."
                else:
                    transcript_str = f"Transcripción:\n{transcript}"

                scraped_contents.append(
                    f"--- CONTENIDO DE VIDEO YOUTUBE DETECTADO ({url}) ---\n"
                    f"{meta_str}"
                    f"{transcript_str}\n"
                    f"--- FIN DE TRANSCRIPCIÍ“N DEL VIDEO ---"
                )
            else:
                logger.info(f"Scraping web page {url}...")
                web_text = self._scrape_web_page(url, force_language=scrape_lang)
                if self.is_unusable_scrape(web_text) or web_text.startswith("[URL_INACCESSIBLE:"):
                    scraped_contents.append(
                        web_text
                        if web_text.startswith("[URL_INACCESSIBLE:")
                        else self.format_url_inaccessible(url, force_language=scrape_lang)
                    )
                else:
                    scraped_contents.append(
                        f"--- CONTENIDO DE PÁGINA WEB DETECTADO ({url}) ---\n"
                        f"{web_text}\n"
                        f"--- FIN DE CONTENIDO DE PÁGINA WEB ---"
                    )

        if scraped_contents:
            lang_guard_header, lang_guard_footer = self._scrape_language_guards(
                scrape_lang, lang_name
            )
            appended_context = lang_guard_header + "\n\n".join(scraped_contents) + lang_guard_footer
            return user_input + appended_context, scraped_sources

        return user_input, []

    @staticmethod
    def _scrape_language_guards(force_language: Optional[str], lang_name: str) -> tuple:
        """Language guards for scraped context — never hardcode Spanish for non-ES threads."""
        is_spanish = bool(force_language and str(force_language).lower().startswith("es"))
        if is_spanish:
            header = (
                "\n\n========================================================================\n"
                "[INSTRUCCIÓN CRÍTICA DE IDIOMA MANDATORIA PARA EL MODELO DE IA]\n"
                "1. DEBES RESPONDER ÚNICAMENTE EN EL IDIOMA DEL MENSAJE INICIAL DEL USUARIO "
                "(si el usuario escribió en español, responde 100% en ESPAÑOL).\n"
                "2. El siguiente bloque es contenido web/video extraído automáticamente de URLs "
                "externas y PUEDE incluir texto en portugués, inglés u otros idiomas.\n"
                "3. IGNORA POR COMPLETO el idioma de este contenido extraído. JAMÁS respondas en "
                "portugués ni en el idioma del sitio raspado.\n"
                "4. Traduce y sintetiza todo al idioma del usuario (Español).\n"
                "========================================================================\n\n"
            )
            footer = (
                "\n\n========================================================================\n"
                "[RECORDATORIO FINAL DE IDIOMA MANDATORIO]: Responde al usuario ÚNICAMENTE en el "
                "idioma de su pregunta original (Español). NUNCA en portugués ni en el idioma de "
                "la web raspada.\n"
                "========================================================================\n"
            )
            return header, footer
        name = lang_name or "the user's language"
        header = (
            "\n\n========================================================================\n"
            "[CRITICAL LANGUAGE INSTRUCTION FOR THE AI MODEL]\n"
            f"1. You MUST reply ONLY in {name} (the language of the user's original message).\n"
            "2. The following block is auto-extracted web/video content from external URLs and "
            "MAY be in Portuguese, English, or other languages.\n"
            "3. IGNORE the language of this extracted content entirely. NEVER reply in the "
            "scraped page's language.\n"
            f"4. Translate and synthesize everything into {name}.\n"
            "========================================================================\n\n"
        )
        footer = (
            "\n\n========================================================================\n"
            f"[FINAL LANGUAGE REMINDER]: Reply to the user ONLY in {name}. "
            "NEVER in Portuguese or the scraped page language.\n"
            "========================================================================\n"
        )
        return header, footer

    # Fingerprints for blocked/SPA/challenge pages that return HTTP 200 with useless HTML.
    _URL_INACCESSIBLE_FINGERPRINTS = (
        "browser isn't compatible",
        "browser not compatible",
        "please download one of our supported browsers",
        "something went wrong",
        "is your network connection unstable",
        "enable javascript",
        "enable cookies",
        "just a moment",
        "cf-browser-verification",
        "challenge-platform",
        "attention required",
        "access denied",
        "captcha",
        "consent.youtube.com",
        "before you continue to youtube",
    )

    @staticmethod
    def format_url_inaccessible(url: str, force_language: Optional[str] = None) -> str:
        """Explicit soft-fail marker so the LLM does not invent page content (locale-aware)."""
        base = "en"
        if force_language and isinstance(force_language, str) and force_language.strip():
            base = force_language.strip().split("-")[0].lower()
        bodies = {
            "es": (
                f"[URL_INACCESSIBLE: {url}] No se pudo extraer el contenido "
                f"(sitio bloquea scrapers / SPA / challenge). "
                f"No inventes el contenido; pide lista/screenshot al usuario."
            ),
            "fr": (
                f"[URL_INACCESSIBLE: {url}] Impossible d'extraire le contenu "
                f"(site bloque les scrapers / SPA / challenge). "
                f"N'invente pas le contenu ; demande une liste/capture à l'utilisateur."
            ),
            "de": (
                f"[URL_INACCESSIBLE: {url}] Inhalt konnte nicht extrahiert werden "
                f"(Seite blockiert Scraper / SPA / Challenge). "
                f"Erfinde den Inhalt nicht; bitte den Nutzer um Liste/Screenshot."
            ),
            "it": (
                f"[URL_INACCESSIBLE: {url}] Impossibile estrarre il contenuto "
                f"(sito blocca scraper / SPA / challenge). "
                f"Non inventare il contenuto; chiedi lista/screenshot all'utente."
            ),
            "pt": (
                f"[URL_INACCESSIBLE: {url}] Não foi possível extrair o conteúdo "
                f"(site bloqueia scrapers / SPA / challenge). "
                f"Não invente o conteúdo; peça lista/screenshot ao usuário."
            ),
            "en": (
                f"[URL_INACCESSIBLE: {url}] Could not extract the content "
                f"(site blocks scrapers / SPA / challenge). "
                f"Do not invent the content; ask the user for a list/screenshot."
            ),
        }
        return bodies.get(base, bodies["en"])

    @classmethod
    def is_unusable_scrape(cls, text: str, *, min_chars: int = 80) -> bool:
        """
        True when scraped text is empty, an error stub, a bot-wall fingerprint,
        or too short to be informative page content.
        """
        if not text or not str(text).strip():
            return True
        t = str(text).strip()
        if t.startswith("[URL_INACCESSIBLE:"):
            return True
        if t.startswith("[Error al extraer") or t.startswith("[No se pudo extraer"):
            return True
        low = t.lower()
        for fp in cls._URL_INACCESSIBLE_FINGERPRINTS:
            if fp in low:
                return True
        if len(t) < min_chars:
            return True
        return False

    @staticmethod
    def scraped_body_char_count(scraped_content: str) -> int:
        """Informative scrape length excluding language-guard wrappers (skill core grounding)."""
        if not scraped_content:
            return 0
        text = scraped_content
        # Prefer content between FIN/INICIO style blocks by removing ===== banners
        lines = []
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("=====") or "INSTRUCCI" in stripped or "RECORDATORIO FINAL" in stripped:
                continue
            if "CRITICAL LANGUAGE" in stripped or "FINAL LANGUAGE REMINDER" in stripped:
                continue
            lines.append(line)
        body = "\n".join(lines).strip()
        return len(body)

    @classmethod
    def should_enable_search_after_scrape(cls, scraped_urls, scraped_content: str) -> bool:
        """
        True when Google Search may still enrich the turn:
        no URLs scraped, or scrape BODY (guards excluded) is under 800 chars.
        Includes URL_INACCESSIBLE soft-fails. All providers MUST use this rule.
        """
        if not scraped_urls:
            return True
        return bool(scraped_content and cls.scraped_body_char_count(scraped_content) < 800)

    # Function that perform a DuckDuckGo HTML search to get real-time context.
    def _duckduckgo_search(self, query: str, num_results: int = 4) -> str:
        """Perform a simple DuckDuckGo HTML search to get real-time context."""
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5"
            }
            resp = requests.post("https://html.duckduckgo.com/html/", data={"q": query}, headers=headers, timeout=10)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, 'html.parser')
            results = []
            for a in soup.select('.result__snippet')[:num_results]:
                results.append(a.text.strip())

            if not results:
                return ""

            context = "\n".join([f"- {res}" for res in results])
            return context
        except Exception as e:
            logger.warning(f"DuckDuckGo search failed: {e}")
            return ""

    # Function that perform a Google Custom Search to get real-time context.
    def _google_custom_search_urls(self, query: str, num_results: int = 3) -> list:
        """
        Query the Google Custom Search JSON API to retrieve search result URLs.
        CSE 403 disables search only for this tenant/session namespace (not process-global).
        """
        tenant_ns = self._cache_namespace()
        if _SEARCH_DISABLED_BY_TENANT.get(tenant_ns):
            return []
        key = GOOGLE_KEY
        cx = GOOGLE_CSE_CX
        if not key or not cx:
            return []
        try:
            logger.info(f"Querying Google Custom Search API for: {query}")
            api_url = "https://www.googleapis.com/customsearch/v1"
            params = {
                "q": query,
                "key": key,
                "cx": cx,
                "num": num_results
            }
            resp = requests.get(api_url, params=params, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                items = data.get("items", [])
                urls = [item.get("link") for item in items if item.get("link")]
                logger.info(f"Google Custom Search returned {len(urls)} URLs")
                return urls
            elif resp.status_code == 403:
                _SEARCH_DISABLED_BY_TENANT[tenant_ns] = True
                BaseChat._prune_dict_locked(_SEARCH_DISABLED_BY_TENANT, max_entries=256)
                logger.warning(
                    "Google Custom Search API returned status 403. "
                    "Disabling Custom Search for tenant namespace %s only.",
                    tenant_ns,
                )
            else:
                logger.warning(f"Google Custom Search API returned status {resp.status_code}: {resp.text}")
        except Exception as e:
            logger.error(f"Error querying Google Custom Search API: {e}")
        return []

    # Function that perform a Google Knowledge Graph search to get real-time context.
    def _google_knowledge_graph_search(self, query: str) -> str:
        """
        Query the Google Knowledge Graph Search API for entity details.
        """
        key = GOOGLE_KEY
        if not key:
            return ""
        try:
            logger.info(f"Querying Google Knowledge Graph for: {query}")
            api_url = "https://kgsearch.googleapis.com/v1/entities:search"
            params = {
                "query": query,
                "key": key,
                "limit": 1,
                "languages": "es,en"
            }
            resp = requests.get(api_url, params=params, timeout=8)
            if resp.status_code == 200:
                data = resp.json()
                element_list = data.get("itemListElement", [])
                if element_list:
                    result = element_list[0].get("result", {})
                    name = result.get("name", "")
                    detail = result.get("detailedDescription", {})
                    article_body = detail.get("articleBody", "")
                    url = detail.get("url", "")
                    types = ", ".join(result.get("@type", []))

                    info = f"--- INFORMACIÍ“N DE GRAFO DE CONOCIMIENTO (GOOGLE KNOWLEDGE GRAPH) ---\n"
                    info += f"Nombre: {name}\n"
                    if types:
                        info += f"Tipo: {types}\n"
                    if article_body:
                        info += f"Descripción: {article_body}\n"
                    if url:
                        info += f"Fuente/Enlace: {url}\n"
                    info += "--------------------------------------------------------------------\n"
                    return info
        except Exception as e:
            logger.error(f"Error querying Google Knowledge Graph: {e}")
        return ""

    # Function that perform a DuckDuckGo HTML search to get real-time context.
    def _duckduckgo_search_urls(self, query: str, num_results: int = 3) -> list:
        """Perform a DuckDuckGo HTML search and extract top result URLs."""
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5"
            }
            resp = requests.post("https://html.duckduckgo.com/html/", data={"q": query}, headers=headers, timeout=10)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, 'html.parser')
            urls = []
            for a in soup.select('.result__a')[:num_results]:
                href = a.get('href', '')
                if isinstance(href, list):
                    href = href[0] if href else ''
                if isinstance(href, str) and href:
                    if "/l/?uddg=" in href:
                        parsed = urlparse(href)
                        queries = parse_qs(parsed.query)
                        real_url = queries.get("uddg", [""])[0]
                        if real_url:
                            urls.append(real_url)
                    else:
                        urls.append(href)
            return urls
        except Exception as e:
            logger.warning(f"DuckDuckGo search URLs extraction failed: {e}")
            return []

    def _extract_urls_from_grounding_metadata(self, response) -> list:
        """Extract citations/URLs from Gemini grounding metadata."""
        urls = []
        try:
            if hasattr(response, 'candidates') and response.candidates:
                candidate = response.candidates[0]
                if hasattr(candidate, 'grounding_metadata') and candidate.grounding_metadata:
                    gm = candidate.grounding_metadata
                    chunks = getattr(gm, 'grounding_chunks', []) or []
                    for chunk in chunks:
                        web = getattr(chunk, 'web', None)
                        if web:
                            uri = getattr(web, 'uri', None)
                            if uri:
                                urls.append(uri)
        except Exception as e:
            logger.warning(f"Error extracting grounding URLs: {e}")
        return list(dict.fromkeys(urls))

    def _run_amplified_search_grounding(self, query: str, force_language: Optional[str] = None, history_text: str = "", current_date_str: str = "", current_time_str: str = "") -> str:
        """
        Performs a Google Search via Gemini Search Grounding or Google Custom Search,
        extracts related URLs from the search, scrapes the actual page content of the top sources,
        queries Google Knowledge Graph for entity info, and aggregates everything.
        """
        # Normalize query and incorporate the current date to prevent cross-day stale cache hits
        normalized_query = re.sub(r'[^\w\s]', '', query).strip().lower() if query else ""
        raw_key = f"{current_date_str}||{normalized_query}" if normalized_query else ""
        cache_key = self._scoped_cache_key(raw_key) if raw_key else ""

        if not cache_key:
            return "SEARCH_NO_RESULTS"

        event_to_wait = None
        is_owner = False

        # Check cache or register search lock
        with BaseChat._global_cache_lock:
            if cache_key in BaseChat._search_grounding_cache:
                logger.info(f"Reusing cached search grounding for query: '{query}'")
                return BaseChat._search_grounding_cache[cache_key]

            if cache_key in BaseChat._search_locks:
                event_to_wait = BaseChat._search_locks[cache_key]
            else:
                BaseChat._search_locks[cache_key] = threading.Event()
                is_owner = True

        if event_to_wait is not None:
            logger.info(f"Thread waiting for concurrent search grounding of query: '{query}'")
            event_to_wait.wait(timeout=30.0)

            with BaseChat._global_cache_lock:
                if cache_key in BaseChat._search_grounding_cache:
                    result = BaseChat._search_grounding_cache[cache_key]
                    logger.info(f"Thread retrieved cached result for query: '{query}' after waiting")
                    return result
                # Timed out / worker failed: claim ownership before retrying.
                if cache_key in BaseChat._search_locks:
                    event_to_wait = BaseChat._search_locks[cache_key]
                    is_owner = False
                else:
                    BaseChat._search_locks[cache_key] = threading.Event()
                    is_owner = True

            if not is_owner:
                event_to_wait.wait(timeout=30.0)
                with BaseChat._global_cache_lock:
                    return BaseChat._search_grounding_cache.get(cache_key, "SEARCH_NO_RESULTS")

        # We are the worker thread!
        try:
            result = self._execute_search_grounding_worker(query, force_language, history_text, current_date_str, current_time_str)
            with BaseChat._global_cache_lock:
                BaseChat._search_grounding_cache[cache_key] = result
                BaseChat._prune_dict_locked(BaseChat._search_grounding_cache)
            return result
        finally:
            with BaseChat._global_cache_lock:
                if cache_key in BaseChat._search_locks:
                    event = BaseChat._search_locks.pop(cache_key)
                    event.set()

    def _execute_search_grounding_worker(self, query: str, force_language: Optional[str] = None, history_text: str = "", current_date_str: str = "", current_time_str: str = "") -> str:
        is_spanish = force_language and force_language.startswith("es")
        search_model = GEMINI_SEARCH_MODEL

        # Truncate history_text to recent context to prevent token explosion on multi-turn searches
        trimmed_history = history_text[-1200:] if history_text and len(history_text) > 1200 else (history_text or "")
        _, _, current_year_str = get_current_date_and_time_strings()

        # 1. Search Prompts with User Local Timezone & Strict Recency Enforcement
        if is_spanish:
            search_prompt = (
                f"Usa la Búsqueda de Google para encontrar las NOTICIAS Y HECHOS MÁS RECIENTES Y EN VIVO para responder a la consulta del usuario.\n"
                f"FECHA Y HORA ACTUAL DEL USUARIO: {current_date_str}, {current_time_str} (Zona Horaria Local: {USER_SYSTEM_TIMEZONE}).\n\n"
                f"INSTRUCCIONES CLAVE DE FRESCURA Y RECICLAJE:\n"
                f"1. Esta consulta busca información actual del año {current_year_str}. Genera búsquedas en Google enfocado en NOTICIAS RECIENTES y noticias de última hora de {current_year_str}.\n"
                f"2. IGNORA Y DESCARTA hilos históricos antiguos, foros pasados (ej. Quora, Reddit) y recopilaciones de títulos de años pasados (ej. victorias de 1992-2015).\n"
                f"3. Para eventos deportivos o noticias en desarrollo, busca reportes y marcadores en la zona horaria del usuario ({USER_SYSTEM_TIMEZONE}).\n"
                f"4. Proporciona un resumen directo, preciso y fáctico en ESPAÍ‘OL basado ÍšNICAMENTE en noticias recientes. Si no hay información disponible, indica 'SEARCH_NO_RESULTS'.\n\n"
                f"Contexto de la Conversación:\n{trimmed_history}\n\n"
                f"Consulta del Usuario: {query}"
            )
        else:
            search_prompt = (
                f"Use Google Search to find the MOST RECENT LATEST NEWS AND LIVE FACTS to answer the user's query.\n"
                f"USER LOCAL DATE AND TIME: {current_date_str}, {current_time_str} (User Local Timezone: {USER_SYSTEM_TIMEZONE}).\n\n"
                f"KEY FRESHNESS AND RECENCY INSTRUCTIONS:\n"
                f"1. This query seeks current information for the year {current_year_str}. Generate search queries targeting RECENT NEWS and breaking stories from {current_year_str}.\n"
                f"2. IGNORE AND EXCLUDE legacy Q&A threads (e.g. Quora, Reddit) and historical retrospective archives from past years.\n"
                f"3. For sports events or breaking news, evaluate match schedules and scores in the user's local timezone ({USER_SYSTEM_TIMEZONE}).\n"
                f"4. Provide a direct, factual summary in English based ONLY on recent news. If no information is found, state 'SEARCH_NO_RESULTS'.\n\n"
                f"Conversation Context:\n{trimmed_history}\n\n"
                f"User Query: {query}"
            )

        search_summary = ""
        target_urls = []

        # 2. Try Google Custom Search JSON API first if configured
        if GOOGLE_CSE_CX:
            target_urls = self._google_custom_search_urls(query)

        # 3. Perform Google Search via Gemini Search Grounding
        client = self._get_gemini_client()
        if client:
            try:
                logger.info(f"Executing Gemini Search Grounding for context expansion: {query}")
                search_resp = client.models.generate_content(
                    model=search_model,
                    contents=search_prompt,
                    config=types.GenerateContentConfig(
                        tools=[types.Tool(google_search=types.GoogleSearch())],
                        temperature=0.0
                    )
                )
                self._accumulate_aux_tokens(search_resp)
                if search_resp and search_resp.text:
                    search_summary = search_resp.text.strip()
                    grounding_urls = self._extract_urls_from_grounding_metadata(search_resp)
                    if grounding_urls:
                        target_urls.extend(grounding_urls)
            except Exception as e:
                logger.warning(f"Google Search via Gemini ({search_model}) failed: {e}. Trying fallback gemini-2.5-flash...")
                try:
                    search_resp = client.models.generate_content(
                        model="gemini-2.5-flash",
                        contents=search_prompt,
                        config=types.GenerateContentConfig(
                            tools=[types.Tool(google_search=types.GoogleSearch())],
                            temperature=0.0
                        )
                    )
                    self._accumulate_aux_tokens(search_resp)
                    if search_resp and search_resp.text:
                        search_summary = search_resp.text.strip()
                        grounding_urls = self._extract_urls_from_grounding_metadata(search_resp)
                        if grounding_urls:
                            target_urls.extend(grounding_urls)
                except Exception as e2:
                    logger.warning(f"Fallback Gemini grounding search failed: {e2}")

        # 4. Fallback search (DuckDuckGo snippets and/or URLs) if no summary yet
        if not search_summary:
            logger.info("Falling back to DuckDuckGo search...")
            search_summary = self._duckduckgo_search(query)
            ddg_urls = self._duckduckgo_search_urls(query)
            target_urls.extend(ddg_urls)

        # 5. Extract Entity info from Google Knowledge Graph
        kg_info = ""
        if GOOGLE_KEY:
            kg_info = self._google_knowledge_graph_search(query)

        # 6. Scraping top target URLs for detailed web context (capped to 1-2 sources, max 1500 chars each)
        unique_urls = list(dict.fromkeys(target_urls))
        scraped_sections = []
        scraped_count = 0

        # Exclude legacy static Q&A and video/encyclopedia sites that distort fresh news
        static_domains = ["youtube.com", "youtu.be", "wikipedia.org", "quora.com", "reddit.com"]

        for url in unique_urls:
            if scraped_count >= 2:
                break
            if any(domain in url.lower() for domain in static_domains):
                continue

            logger.info(f"Expanded search scraping: {url}...")
            content = self._scrape_web_page(url)
            if content and not content.startswith("[Error"):
                content_clean = "\n".join([line.strip() for line in content.splitlines() if line.strip()])
                if len(content_clean) > 1500:
                    content_clean = content_clean[:1500] + "\n[Contenido recortado por longitud...]"
                scraped_sections.append(
                    f"--- CONTENIDO DETALLADO DE FUENTE WEB ({url}) ---\n"
                    f"{content_clean}\n"
                    f"--- FIN CONTENIDO FUENTE WEB ---"
                )
                scraped_count += 1

        # 7. Aggregate all information
        final_context_parts = []
        if search_summary:
            final_context_parts.append(search_summary)
        if kg_info:
            final_context_parts.append(kg_info)
        if scraped_sections:
            final_context_parts.extend(scraped_sections)

        final_context = "\n\n".join(final_context_parts)
        if not final_context.strip():
            return "SEARCH_NO_RESULTS"
        return final_context

    # Function that extract token usage counts from a response usage_metadata object.
    @staticmethod
    def _parse_token_info(usage) -> dict:
        """Extract token usage counts from a response usage_metadata object."""
        return {
            "prompt_tokens":     getattr(usage, 'prompt_token_count',     0) or 0,
            "candidates_tokens": getattr(usage, 'candidates_token_count', 0) or 0,
            "total_tokens":      getattr(usage, 'total_token_count',      0) or 0,
            "thinking_tokens":   getattr(usage, 'thoughts_token_count',   0) or 0,
        }

    def _accumulate_aux_tokens(self, response) -> int:
        """Read usage_metadata from an auxiliary Gemini response and accumulate into self._aux_gemini_tokens.
        Returns the total tokens counted from this call (0 if unavailable)."""
        if response is None:
            return 0
        meta = getattr(response, 'usage_metadata', None)
        if not meta:
            return 0
        pt  = getattr(meta, 'prompt_token_count',     0) or 0
        ct  = getattr(meta, 'candidates_token_count', 0) or 0
        tot = getattr(meta, 'total_token_count',      0) or 0
        self._aux_gemini_tokens["prompt_tokens"]     += pt
        self._aux_gemini_tokens["candidates_tokens"] += ct
        self._aux_gemini_tokens["total_tokens"]      += tot
        logger.info(f"[AuxGemini] +{tot} tokens (acum. total: {self._aux_gemini_tokens['total_tokens']})")
        return tot

    def _flush_aux_tokens(self, token_info: Union[dict, TokenInfo, None]) -> TokenInfo:
        """Merge accumulated auxiliary Gemini tokens into token_info and reset the accumulator.

        Accepts a raw legacy dict OR a TokenInfo instance for backward compatibility.
        Always returns a validated TokenInfo â€” fulfilling Skill 1.1 (Strict Typing & Pydantic V2).
        The grand total in the returned TokenInfo will include all auxiliary Gemini calls.
        """
        # Normalize input to a working dict so we can mutate it before constructing TokenInfo
        if token_info is None:
            base: dict = {"prompt_tokens": 0, "candidates_tokens": 0, "total_tokens": 0, "thinking_tokens": 0}
        elif isinstance(token_info, TokenInfo):
            base = token_info.to_legacy_dict()
        else:
            base = dict(token_info)  # shallow copy â€” never mutate caller's dict

        aux_total = self._aux_gemini_tokens["total_tokens"]
        if aux_total > 0:
            base["total_tokens"] = base.get("total_tokens", 0) + aux_total
            base["prompt_tokens"] = base.get("prompt_tokens", 0) + self._aux_gemini_tokens["prompt_tokens"]
            logger.info(
                f"[AuxGemini] Flushing {aux_total} auxiliary tokens into final token_info "
                f"(new total: {base['total_tokens']})"
            )

        # Reset accumulator for next message
        self._aux_gemini_tokens = {"prompt_tokens": 0, "candidates_tokens": 0, "total_tokens": 0}

        model_name = getattr(self, "model_version", getattr(self, "model_id", ""))
        pt = base.get("prompt_tokens", 0)
        ct = base.get("candidates_tokens", 0)
        tt = base.get("thinking_tokens", 0)
        base["cost_usd"] = calculate_cost_usd(model_name, pt, ct, tt)

        # Return a fully validated, immutable TokenInfo â€” Skill 1.1 compliant
        return TokenInfo.from_dict(base)

    # Function to extract raw audio bytes from a Gemini TTS response.
    @staticmethod
    def _extract_audio(resp) -> bytes | None:
        """Extract raw audio bytes from a Gemini TTS response."""
        if hasattr(resp, 'audio') and resp.audio:
            if hasattr(resp.audio, 'data'):
                return resp.audio.data
            elif hasattr(resp.audio, 'bytes'):
                return resp.audio.bytes
            elif isinstance(resp.audio, bytes):
                return resp.audio
        if hasattr(resp, 'candidates') and resp.candidates:
            candidate = resp.candidates[0]
            parts = candidate.content.parts if getattr(candidate, 'content', None) else None
            if isinstance(parts, list):
                for part in parts:
                    if hasattr(part, 'inline_data') and part.inline_data and getattr(part.inline_data, 'mime_type', '').startswith('audio/'):
                        return part.inline_data.data
        return None

    # Function to wrap raw PCM bytes in a WAV container.
    @staticmethod
    def _pcm_to_wav(pcm_bytes: bytes, sample_rate: int = 24000, num_channels: int = 1, sample_width: int = 2) -> bytes:
        """Wrap raw PCM bytes in a WAV container."""
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(num_channels)
            wf.setsampwidth(sample_width)
            wf.setframerate(sample_rate)
            wf.writeframes(pcm_bytes)
        return buf.getvalue()

    # Function to extract text content from a .docx file bytes using built-in libraries.
    def _extract_text_from_docx(self, file_bytes: bytes) -> str:
        """Extract text content from a .docx file bytes using built-in libraries."""
        return extract_text_from_docx(file_bytes)

    def _extract_images_from_docx(self, docx_bytes: bytes) -> list:
        """Extract all embedded images from .docx file bytes, returning a list of dicts with 'name', 'bytes', 'mime_type'."""
        images = []
        try:
            with zipfile.ZipFile(io.BytesIO(docx_bytes)) as z:
                for name in z.namelist():
                    if name.startswith('word/media/'):
                        img_bytes = z.read(name)
                        img_name = os.path.basename(name)
                        ext = img_name.split('.')[-1].lower()
                        if ext in ['jpg', 'jpeg']:
                            mime = "image/jpeg"
                        elif ext in ['png', 'gif', 'webp']:
                            mime = f"image/{ext}"
                        else:
                            mime = "image/png"
                        prepared = self._prepare_image_for_vision_api(
                            img_bytes, mime_type=mime, name=img_name, max_dim=1024
                        )
                        if not prepared:
                            continue
                        img_bytes, mime = prepared
                        images.append({
                            "name": img_name,
                            "bytes": img_bytes,
                            "mime_type": mime
                        })
                        if len(images) >= 5:
                            break
            logger.info(f"Extracted {len(images)} images from docx document")
        except Exception as e:
            logger.warning(f"Failed to extract images from docx: {e}")
        return images[:5]  # Limit to 5 images — sufficient for document analysis, avoids token overload

    def _extract_images_from_pdf(self, pdf_bytes: bytes) -> list:
        """Extract all embedded images from .pdf file bytes, returning a list of dicts with 'name', 'bytes', 'mime_type'."""
        images = []
        if pypdf is None and PyPDF2 is None:
            logger.warning("Neither pypdf nor PyPDF2 is installed to extract images from PDF.")
            return images

        try:
            reader = None
            if pypdf is not None:
                try:
                    reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
                except Exception as e:
                    logger.warning(f"pypdf extraction failed: {e}")
            if reader is None and PyPDF2 is not None:
                try:
                    reader = PyPDF2.PdfReader(io.BytesIO(pdf_bytes))
                except Exception as e:
                    logger.warning(f"PyPDF2 extraction failed: {e}")

            if reader is None:
                return images

            scan_limit = pdf_image_page_scan_limit()
            for i, page in enumerate(reader.pages):
                if i >= scan_limit:
                    logger.info(
                        "Stopping PDF image scan after %s pages (IGNITE_PDF_IMAGE_PAGE_SCAN_LIMIT)",
                        scan_limit,
                    )
                    break
                if hasattr(page, 'images') and page.images:
                    for j, image_file_object in enumerate(page.images):
                        img_bytes = getattr(image_file_object, 'data', None)
                        if not img_bytes:
                            continue
                        img_name = getattr(image_file_object, 'name', None) or f"image_p{i+1}_{j+1}.png"
                        ext = img_name.split('.')[-1].lower() if '.' in img_name else "png"
                        if ext in ['jpg', 'jpeg']:
                            mime = "image/jpeg"
                        elif ext in ['png', 'gif', 'webp']:
                            mime = f"image/{ext}"
                        else:
                            mime = "image/png"
                        prepared = self._prepare_image_for_vision_api(
                            img_bytes, mime_type=mime, name=img_name, max_dim=1024
                        )
                        if not prepared:
                            continue
                        img_bytes, mime = prepared
                        images.append({
                            "name": img_name,
                            "bytes": img_bytes,
                            "mime_type": mime
                        })
                        if len(images) >= 5:
                            break
                if len(images) >= 5:
                    break
            logger.info(f"Extracted {len(images)} images from pdf document")
        except Exception as e:
            logger.warning(f"Failed to extract images from pdf: {e}")
        return images[:5]  # Limit to 5 images — sufficient for document analysis, avoids token overload

    def _extract_text_from_image_via_ocr(self, img_bytes: bytes) -> str:
        """Runs local Tesseract OCR on image bytes and returns the extracted text."""
        if pytesseract is None:
            return ""
        try:
            # Ensure tesseract path is set
            tesseract_cmd = os.getenv("TESSERACT_CMD")
            if tesseract_cmd:
                pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
            else:
                if not shutil.which("tesseract"):
                    common_paths = [
                        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
                        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
                    ]
                    try:
                        local_app_data = os.environ.get("LOCALAPPDATA", "")
                        if local_app_data:
                            common_paths.append(os.path.join(local_app_data, "Tesseract-OCR", "tesseract.exe"))
                    except Exception:
                        pass
                    for path in common_paths:
                        if os.path.exists(path):
                            pytesseract.pytesseract.tesseract_cmd = path
                            break

            img = Image.open(io.BytesIO(img_bytes))
            try:
                text = pytesseract.image_to_string(img, lang="spa")
            except Exception:
                text = pytesseract.image_to_string(img)
            return text
        except Exception as e:
            logger.error(f"Local Tesseract OCR failed: {e}")
            return ""

    # Function that check if Gemini natively supports this mime type in generate_content.
    @staticmethod
    def _is_gemini_native_mime(mime: str) -> bool:
        """Return True if Gemini natively supports this mime type in generate_content."""
        m = mime.lower()
        if (m.startswith("image/") or
            m.startswith("audio/") or
            m.startswith("video/") or
            m == "application/pdf" or
            m.startswith("text/") or
            m in ["application/json", "application/xml", "application/javascript"]):
            return True
        return False

    # Function that resize image to have a maximum dimension of max_dim, preserving aspect ratio.
    def _resize_image_data(self, image_bytes: bytes, max_dim: int = 1024) -> bytes:
        """Resize an image to have a maximum dimension of max_dim, preserving aspect ratio.
        Includes fallback for older Pillow versions."""
        try:
            img = Image.open(io.BytesIO(image_bytes))
            if img.width > max_dim or img.height > max_dim:
                # Use LANCZOS (Pillow >= 9.1.0) with fallback for older versions
                resampling = getattr(Image, "Resampling", Image)
                resample_filter = getattr(resampling, "LANCZOS", getattr(Image, "ANTIALIAS", 1))
                img.thumbnail((max_dim, max_dim), cast(Any, resample_filter))
                out_buf = io.BytesIO()
                fmt = img.format or "PNG"
                img.save(out_buf, format=fmt)
                logger.info(f"Resized image from {img.width}x{img.height} to fit inside {max_dim}px")
                return out_buf.getvalue()
        except Exception as e:
            logger.warning(f"Error resizing image data: {e}")
        return image_bytes

    def _image_pixel_count(self, image_bytes: bytes) -> Optional[int]:
        """Return width*height for image bytes, or None if unreadable."""
        try:
            with Image.open(io.BytesIO(image_bytes)) as img:
                return int(img.width) * int(img.height)
        except Exception as e:
            logger.warning(f"Could not measure image pixels: {e}")
            return None

    def _is_vision_api_image_viable(self, image_bytes: bytes, name: str = "") -> bool:
        """True if image meets provider vision minimums (Grok rejects total pixels < 512)."""
        pixels = self._image_pixel_count(image_bytes)
        if pixels is None:
            return False
        min_pixels = vision_min_image_pixels()
        if pixels < min_pixels:
            label = name or "image"
            logger.info(
                "Skipping vision image '%s': %s total pixels (below minimum of %s)",
                label,
                pixels,
                min_pixels,
            )
            return False
        return True

    def _prepare_image_for_vision_api(
        self,
        image_bytes: bytes,
        mime_type: str = "image/png",
        name: str = "",
        max_dim: int = 1024,
    ) -> Optional[Tuple[bytes, str]]:
        """Normalize + downscale + drop tiny logos so multimodal APIs (e.g. Grok) accept the image."""
        try:
            scaled = self._resize_image_data(image_bytes, max_dim=max_dim)
        except Exception:
            scaled = image_bytes
        clean_bytes, valid_mime = self.normalize_image_media_type(mime_type, scaled)
        payload = clean_bytes or scaled
        if not self._is_vision_api_image_viable(payload, name=name):
            return None
        return payload, valid_mime

    # Function that checks if a file is a text or programming/code file based on mime type or extension
    @staticmethod
    def _is_text_or_code_file(mime: str, name: str) -> bool:
        """Checks if a file format is a text or programming/code file based on MIME type or file extension."""
        m = mime.lower()
        n = name.lower()
        # Common text/code MIME types
        if m.startswith("text/") or m in ["application/json", "application/xml", "application/javascript", "application/ecmascript", "application/sql"]:
            return True
        # Common programming/configuration file extensions
        code_extensions = (
            ".py", ".js", ".ts", ".tsx", ".jsx", ".html", ".htm", ".css", ".json", ".md", ".yaml", ".yml",
            ".ini", ".conf", ".sql", ".sh", ".bat", ".ps1", ".java", ".cpp", ".c", ".h", ".cs", ".go",
            ".rs", ".php", ".xml", ".kt", ".gradle", ".properties", ".toml", ".dockerfile", ".gitignore", ".env"
        )
        if n.endswith(code_extensions):
            return True
        return False

    # Function that attempts to decode file bytes as a text/code file
    def _try_decode_as_text(self, file_bytes: bytes, mime: str = "", name: str = "") -> Optional[str]:
        """Attempts to decode file_bytes as a text/code file. Returns the decoded string, or None if it appears binary."""
        # If it's a known text/code MIME type or extension, decode it directly
        if self._is_text_or_code_file(mime, name):
            try:
                return file_bytes.decode("utf-8")
            except UnicodeDecodeError:
                try:
                    return file_bytes.decode("latin-1")
                except Exception:
                    pass

        # Fallback logic: check if the bytes can be decoded as utf-8 or latin-1 and don't contain null bytes (binary indicator)
        try:
            decoded = file_bytes.decode("utf-8")
            if "\x00" not in decoded:
                return decoded
        except UnicodeDecodeError:
            try:
                decoded = file_bytes.decode("latin-1")
                if "\x00" not in decoded:
                    return decoded
            except Exception:
                pass
        return None

    # Function that extracts text content from a .xlsx Excel file bytes
    def _extract_text_from_xlsx(self, file_bytes: bytes) -> str:
        """Extract text content from a .xlsx Excel file bytes using built-in libraries."""
        return extract_text_from_xlsx(file_bytes)

    # Function that extracts text content from a .pptx PowerPoint file bytes
    def _extract_text_from_pptx(self, file_bytes: bytes) -> str:
        """Extract text content from a .pptx PowerPoint file bytes using built-in libraries."""
        return extract_text_from_pptx(file_bytes)

    def _transcription_cache_key(self, audio_bytes: bytes, mime_type: str = "audio/wav", expected_language: str = "") -> str:
        """Stable key so group participants reuse one Whisper pass per unique audio blob (tenant-scoped)."""
        digest = hashlib.sha256(audio_bytes or b"").hexdigest()
        lang = (expected_language or "").strip().lower()
        raw = f"{digest}|{(mime_type or '').split(';')[0].strip().lower()}|{lang}"
        return self._scoped_cache_key(raw)

    def _transcribe_audio_local(self, audio_bytes: bytes, mime_type: str = "audio/wav", expected_language: str = "") -> str:
        """
        Transcribe audio bytes using local faster-whisper.
        Returns the transcript string if successful, or None if not installed or fails.
        """
        tmp_path = None
        try:
            if WhisperModel is None:
                raise ImportError("faster-whisper is not installed")

            suffix = ".wav"
            if "mp3" in mime_type or "mpeg" in mime_type:
                suffix = ".mp3"
            elif "ogg" in mime_type:
                suffix = ".ogg"
            elif "webm" in mime_type:
                suffix = ".webm"
            elif "m4a" in mime_type or "mp4" in mime_type:
                suffix = ".m4a"

            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp.write(audio_bytes)
                tmp_path = tmp.name

            # Hold the lock for the full inference: concurrent CPU Whisper calls thrash and
            # make group chats (N participants Í— same files) extremely slow.
            with BaseChat._whisper_lock:
                if BaseChat._local_whisper_model is None:
                    logger.info("Initializing local faster-whisper model 'base' on CPU (First run initialization)...")
                    BaseChat._local_whisper_model = WhisperModel("base", device="cpu", compute_type="int8")
                model = BaseChat._local_whisper_model

                logger.info(f"Transcribing locally with faster-whisper from: {tmp_path}")
                beam_size = int(os.getenv("WHISPER_BEAM_SIZE", "1"))
                kwargs: Dict[str, Any] = {"beam_size": max(1, beam_size)}
                if expected_language and expected_language != "auto":
                    lang_iso = expected_language.split('-')[0].lower()
                    kwargs["language"] = lang_iso

                segments, info = model.transcribe(tmp_path, **kwargs)
                segments = list(segments)
                valid_segments = [seg.text for seg in segments if getattr(seg, "no_speech_prob", 0.0) < 0.6]
                transcript_text = " ".join(valid_segments).strip()

            logger.info(
                f"Local faster-whisper transcription successful "
                f"(Detected language: {info.language} with prob: {info.language_probability:.2f}): "
                f"{transcript_text[:80]}"
            )
            return transcript_text
        except ImportError:
            logger.info("faster-whisper package not installed. Skipping local path.")
            # Skill §12.3: return None so Gemini/OpenAI Whisper fallbacks still run.
            return None
        except Exception as e:
            logger.warning(f"Local faster-whisper transcription failed or skipped: {e}")
            return None
        finally:
            try:
                if tmp_path and os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except Exception as cleanup_err:
                logger.debug(
                    "Failed to remove temporary Whisper audio file %s: %s",
                    tmp_path,
                    cleanup_err,
                    exc_info=True,
                )

    # Function that transcribes audio bytes using local whisper with fallbacks
    def transcribe_audio(self, audio_bytes: bytes, mime_type: str = "audio/wav", fallback_models: list = [], expected_language: str = "") -> tuple:
        """
        Transcribe audio bytes using local faster-whisper, falling back to Gemini 1.5 Flash and OpenAI Whisper API.
        Returns (transcript_text, error_message).
        """
        cache_key = self._transcription_cache_key(audio_bytes, mime_type, expected_language)
        event_to_wait = None
        is_owner = False

        with BaseChat._transcription_cache_lock:
            cached = BaseChat._transcription_cache.get(cache_key)
            if cached is not None:
                logger.info("Reusing cached audio transcription for identical file (group/shared pass).")
                return cached
            if cache_key in BaseChat._transcription_locks:
                event_to_wait = BaseChat._transcription_locks[cache_key]
            else:
                BaseChat._transcription_locks[cache_key] = threading.Event()
                is_owner = True

        if event_to_wait is not None:
            logger.info("Waiting for in-flight Whisper transcription of the same audio file...")
            event_to_wait.wait(timeout=300.0)
            with BaseChat._transcription_cache_lock:
                cached = BaseChat._transcription_cache.get(cache_key)
                if cached is not None:
                    return cached
                # Timed out / worker failed: claim ownership before retrying.
                if cache_key in BaseChat._transcription_locks:
                    event_to_wait = BaseChat._transcription_locks[cache_key]
                else:
                    BaseChat._transcription_locks[cache_key] = threading.Event()
                    is_owner = True
            if not is_owner:
                # Another waiter became owner; wait once more then reuse/fail soft.
                event_to_wait.wait(timeout=300.0)
                with BaseChat._transcription_cache_lock:
                    cached = BaseChat._transcription_cache.get(cache_key)
                    if cached is not None:
                        return cached
                return (None, "Transcription timed out waiting for shared Whisper worker.")

        def _store_and_return(result: tuple) -> tuple:
            with BaseChat._transcription_cache_lock:
                BaseChat._transcription_cache[cache_key] = result
                BaseChat._prune_dict_locked(BaseChat._transcription_cache)
                event = BaseChat._transcription_locks.pop(cache_key, None)
            if event is not None:
                event.set()
            return result

        def _release_lock_without_cache() -> None:
            with BaseChat._transcription_cache_lock:
                event = BaseChat._transcription_locks.pop(cache_key, None)
            if event is not None:
                event.set()

        try:
            # 1. Primary path: Local faster-whisper transcription (0 API tokens, gratis)
            local_transcript = self._transcribe_audio_local(audio_bytes, mime_type, expected_language)
            if local_transcript is not None:
                return _store_and_return((local_transcript, None))

            # 2. Secondary path: Fallback to Gemini 1.5 Flash (contabilizando tokens)
            logger.info("Falling back to Gemini 1.5 Flash transcription...")
            try:
                lang_prompt = (
                    "Listen to this audio and transcribe it accurately in the ORIGINAL LANGUAGE that is being spoken.\n"
                    "CRITICAL SPEAKER FILTERING & TV AUDIO CANCELLATION INSTRUCTIONS:\n"
                    "- There is a television (TV) or video playing in the room. You must COMPLETELY FILTER OUT and IGNORE all TV audio, background voices, news broadcasts, show narrations, and movie/show dialogue.\n"
                    "- Focus ONLY on the user of this AI assistant who is speaking directly to you into the microphone.\n"
                    "- Distinguish them by acoustic presence: The user's voice is close to the microphone, clear, dry, and has direct foreground presence. The TV audio is distant, has room reverberation (echo), and sounds like background noise.\n"
                    "- Distinguish them by conversational intent: The user is speaking in a conversational tone directly addressing you (asking questions, giving instructions, chatting). The TV audio is narrating, reporting news, playing commercials, or acting in a show.\n"
                    "- If the user is silent and only the background TV is speaking, you MUST ignore the TV completely and return an EMPTY STRING (nothing at all).\n"
                    "- If both the user and the TV are speaking at the same time, isolate the user's voice and ONLY transcribe the user's words, ignoring the TV words.\n\n"
                    "Detect the language automatically (Spanish, English, French, German, Italian, Portuguese, etc.) "
                    "and return ONLY the spoken words in that language, nothing else. "
                    "Do NOT translate - preserve the exact language being spoken."
                )
                if expected_language:
                    lang_name = resolve_lang_name(expected_language)
                    lang_prompt += f" The expected language being spoken is {lang_name}. Please prioritize transcribing in {lang_name}."

                parts = [
                    types.Part.from_bytes(data=audio_bytes, mime_type=mime_type),
                    types.Part.from_text(text=lang_prompt),
                ]

                gemini_client = self._get_gemini_client()
                if not gemini_client:
                    raise RuntimeError("Gemini client is unavailable for fallback audio transcription.")

                response = gemini_client.models.generate_content(
                    model=GEMINI_SEARCH_MODEL,  # gemini-2.5-flash-lite for lightweight audio transcription fallback
                    contents=cast(Any, [types.Content(role="user", parts=parts)]),
                    config=types.GenerateContentConfig(
                        max_output_tokens=1024,
                        temperature=0.0
                    )
                )
                self._accumulate_aux_tokens(response)  # Track auxiliary Gemini tokens
                transcript = response.text.strip() if response.text else ""
                logger.info(f"Gemini transcription complete: {transcript[:80]}")
                return _store_and_return((transcript, None))
            except Exception as e:
                logger.error(f"Gemini transcription error: {e}. Falling back to Whisper API.")
                # 3. Tertiary path: Fallback to OpenAI Whisper API
                tmp_path = None
                try:
                    suffix = ".wav"
                    if "mp3" in mime_type or "mpeg" in mime_type:
                        suffix = ".mp3"
                    elif "ogg" in mime_type:
                        suffix = ".ogg"
                    elif "webm" in mime_type:
                        suffix = ".webm"
                    elif "m4a" in mime_type or "mp4" in mime_type:
                        suffix = ".m4a"

                    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                        tmp.write(audio_bytes)
                        tmp_path = tmp.name

                    openai_client = build_openai_client()
                    with open(tmp_path, "rb") as audio_file:
                        kwargs = {
                            "model": "whisper-1",
                            "file": audio_file
                        }
                        if expected_language:
                            lang_iso = expected_language.split('-')[0].lower()
                            kwargs["language"] = lang_iso
                        result = openai_client.audio.transcriptions.create(**kwargs)

                    transcript = result.text.strip() if result.text else ""
                    logger.info(f"Whisper API fallback transcription complete: {transcript[:80]}")
                    return _store_and_return((transcript, None))
                except Exception as whisper_err:
                    logger.error(f"Whisper API fallback error: {whisper_err}")
                    return _store_and_return((None, f"Gemini error: {e}. Whisper API error: {whisper_err}"))
                finally:
                    try:
                        if tmp_path and os.path.exists(tmp_path):
                            os.remove(tmp_path)
                    except Exception as cleanup_err:
                        logger.debug(
                            "Failed to remove temporary Whisper API audio file %s: %s",
                            tmp_path,
                            cleanup_err,
                            exc_info=True,
                        )
        except Exception:
            _release_lock_without_cache()
            raise

    # Function that generates a detailed scene-by-scene description of a video file using Gemini 1.5 Flash
    def describe_video(self, video_bytes: bytes, mime_type: str, user_query: str) -> str:
        """
        Use Gemini 1.5 Flash to generate a detailed scene-by-scene description of a video file.
        This allows non-multimodal video models to analyze video content.
        """
        client = self._get_gemini_client()
        if not client:
            logger.warning("Gemini client not available. Cannot describe video.")
            return "[Error: Gemini client not configured. Cannot analyze video files.]"

        try:

            prompt = (
                "Analyze this video and generate a detailed scene-by-scene description of its visuals and any spoken dialogue.\n"
                "Focus on describing the actions, objects, settings, characters, text on screen, and key event progression.\n"
                "If the video contains audio or speech, transcribe and summarize the key spoken points.\n"
                f"The user wants to know about this video in relation to the following query: '{user_query}'.\n"
                "Be detailed, factual, and direct."
            )

            parts = [
                types.Part.from_bytes(data=video_bytes, mime_type=mime_type),
                types.Part.from_text(text=prompt)
            ]

            response = client.models.generate_content(
                model=GEMINI_SEARCH_MODEL,  # gemini-2.5-flash-lite for cost-optimized video description fallback
                contents=cast(Any, [types.Content(role="user", parts=parts)]),
                config=types.GenerateContentConfig(
                    max_output_tokens=1024,
                    temperature=0.0
                )
            )
            description = response.text.strip() if response.text else ""
            logger.info("Video description generated successfully using Gemini Flash.")
            return description
        except Exception as e:
            logger.error(f"Error generating video description using Gemini Flash: {e}")
            return f"[Error analyzing video: {str(e)}]"

    @staticmethod
    def normalize_image_media_type(mime_type: str, data_bytes: Optional[bytes] = None) -> Tuple[Optional[bytes], str]:
        """
        Normalizes any image MIME type to a canonical standard supported by LLM APIs
        ('image/jpeg', 'image/png', 'image/gif', 'image/webp').
        Converts non-standard types (image/jpg, image/pjpeg, image/jfif -> image/jpeg)
        and converts unsupported image formats (BMP, TIFF, SVG, ICO, HEIC, etc.) to PNG/JPEG via PIL.
        """
        raw_mime = (mime_type or "").lower().split(";")[0].strip()
        if raw_mime in ("image/jpeg", "image/jpg", "image/pjpeg", "image/jfif"):
            return data_bytes, "image/jpeg"
        elif raw_mime in ("image/png", "image/x-png"):
            return data_bytes, "image/png"
        elif raw_mime == "image/gif":
            return data_bytes, "image/gif"
        elif raw_mime == "image/webp":
            return data_bytes, "image/webp"

        # If data_bytes is available and the mime is unsupported (e.g. BMP, TIFF, SVG, AVIF, HEIC, ICO), convert via PIL
        if data_bytes:
            try:
                with Image.open(io.BytesIO(data_bytes)) as img:
                    out_buf = io.BytesIO()
                    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
                        img.save(out_buf, format="PNG")
                        return out_buf.getvalue(), "image/png"
                    else:
                        rgb_img = img.convert("RGB")
                        rgb_img.save(out_buf, format="JPEG", quality=92)
                        return out_buf.getvalue(), "image/jpeg"
            except Exception as conv_err:
                logger.warning(f"Could not convert image with mime '{mime_type}' via PIL: {conv_err}")

        # Fallback
        if "jpg" in raw_mime or "jpeg" in raw_mime:
            return data_bytes, "image/jpeg"
        return data_bytes, "image/png"

    def describe_image(self, image_bytes: bytes, mime_type: str) -> str:
        """
        Use Gemini 1.5 Flash to generate a detailed description of an image file.
        This allows non-multimodal vision models (like Perplexity or DeepSeek) to analyze image content.
        """
        client = self._get_gemini_client()
        if not client:
            logger.warning("Gemini client not available. Cannot describe image.")
            return "[Error: Gemini client not configured. Cannot analyze image files.]"

        try:
            clean_bytes, valid_mime = self.normalize_image_media_type(mime_type, image_bytes)
            scaled_bytes = self._resize_image_data(clean_bytes or image_bytes, max_dim=1024)
            # Large PNG/JPEG after resize can still blow Gemini/aux path; compress further.
            if hasattr(self, "_is_vision_api_image_viable") and not self._is_vision_api_image_viable(
                scaled_bytes, name="describe_image"
            ):
                return "[Skipped tiny decorative image below vision minimum.]"
            try:
                # Prefer JPEG under ~4 MB for describe_image stability (Perplexity/DeepSeek path).
                max_desc_bytes = int(os.getenv("IGNITE_DESCRIBE_IMAGE_MAX_BYTES", str(4 * 1024 * 1024)))
            except (TypeError, ValueError):
                max_desc_bytes = 4 * 1024 * 1024
            if len(scaled_bytes) > max_desc_bytes:
                try:
                    with Image.open(io.BytesIO(scaled_bytes)) as img:
                        rgb = img.convert("RGB")
                        for quality in (80, 65, 50, 35):
                            buf = io.BytesIO()
                            rgb.save(buf, format="JPEG", quality=quality, optimize=True)
                            if len(buf.getvalue()) <= max_desc_bytes:
                                scaled_bytes = buf.getvalue()
                                valid_mime = "image/jpeg"
                                break
                        else:
                            scaled_bytes = buf.getvalue()
                            valid_mime = "image/jpeg"
                except Exception as compress_err:
                    logger.warning(f"describe_image compress failed: {compress_err}")
            image_part = types.Part.from_bytes(data=scaled_bytes, mime_type=valid_mime)
            prompt_part = types.Part.from_text(
                text=(
                    "Analyze this image thoroughly. Write a detailed, natural, narrative description of everything you see: "
                    "objects, people, colors, text on screen (transcribe any text perfectly), layout, mood, and any other relevant details. "
                    "Do NOT use the words 'transcription', 'transcript', or 'description'. Write it as flowing prose as if you are directly observing it."
                )
            )

            response = client.models.generate_content(
                model=GEMINI_SEARCH_MODEL,  # gemini-2.5-flash-lite for cost-optimized image description
                contents=cast(Any, [image_part, prompt_part]),
                config=types.GenerateContentConfig(
                    max_output_tokens=2048,
                    temperature=0.0
                )
            )
            desc = response.text.strip() if response.text else ""
            # Sanitize: remove any leaked 'transcript/transcription' wording from Gemini output
            desc = re.sub(r'\b[Tt]ranscri(?:pt|ption|bed|bing)\b', 'content', desc)
            return desc
        except Exception as e:
            logger.error(f"Error generating image description using Gemini Flash: {e}")
            return f"[Error analyzing image: {str(e)}]"

    def _extract_audio_metadata_from_bytes(self, audio_bytes: bytes, suffix: str = ".mp3") -> str:
        """Extract metadata (title, artist, album, genre, date, duration) from raw audio bytes using mutagen."""
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp.write(audio_bytes)
                tmp_path = tmp.name

            metadata_lines = []
            try:
                audio_meta = MutagenFile(tmp_path, easy=True)
                if audio_meta:
                    if audio_meta.get("title"): metadata_lines.append(f"Title: {audio_meta['title'][0]}")
                    if audio_meta.get("artist"): metadata_lines.append(f"Artist: {audio_meta['artist'][0]}")
                    if audio_meta.get("album"): metadata_lines.append(f"Album: {audio_meta['album'][0]}")
                    if audio_meta.get("genre"): metadata_lines.append(f"Genre: {audio_meta['genre'][0]}")
                    if audio_meta.get("date"): metadata_lines.append(f"Year: {audio_meta['date'][0]}")
                    if hasattr(audio_meta.info, 'length'):
                        length = audio_meta.info.length
                        metadata_lines.append(f"Duration: {int(length // 60)}m {int(length % 60)}s ({int(length)} seconds)")
                    if hasattr(audio_meta.info, 'bitrate'):
                        metadata_lines.append(f"Bitrate: {getattr(audio_meta.info, 'bitrate', 0) // 1000} kbps")
                    if hasattr(audio_meta.info, 'sample_rate'):
                        metadata_lines.append(f"Sample Rate: {getattr(audio_meta.info, 'sample_rate', 'N/A')} Hz")
            except Exception as meta_err:
                logger.warning(f"Mutagen metadata extraction failed: {meta_err}")
            finally:
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass

            if metadata_lines:
                return "\n".join(metadata_lines)
            return ""
        except Exception as e:
            logger.error(f"Error in _extract_audio_metadata_from_bytes: {e}")
            return ""

    @staticmethod
    def _clean_image_request_text(text: str) -> str:
        """Strips command verbs and introductory phrases from image requests."""
        cleaned = (text or "").strip()
        en_pattern = r"^(?:please\s+)?(?:can\s+you\s+)?(?:generate|create|draw|make|render|paint|show)\s+(?:an?\s+image|a\s+picture|a\s+photo|a\s+drawing|an\s+illustration)?\s*(?:where\s+it\s+shows|showing|that\s+shows|of|with)?\s*[:,-]?"
        es_pattern = r"^(?:por\s+favor\s+)?(?:me\s+puedes\s+)?(?:genera|generar|crea|crear|dibuja|dibujar|haz|hacer|muestra|mostrar|pinta|pintar)\s+(?:una?\s+imagen|un\s+dibujo|una\s+foto|una\s+ilustraci[oó]n|una\s+pintura)?\s*(?:donde\s+se\s+muestre|que\s+muestre|mostrando|de|con)?\s*[:,-]?"
        cleaned = re.sub(en_pattern, "", cleaned, flags=re.IGNORECASE).strip()
        cleaned = re.sub(es_pattern, "", cleaned, flags=re.IGNORECASE).strip()
        return cleaned or text

    @staticmethod
    def _is_ready_image_prompt(prompt: str) -> bool:
        """
        True when the prompt is already in English (or direct English visual description).
        Avoiding extra LLM rewrites preserves 100% subject fidelity.
        """
        if not prompt or not isinstance(prompt, str):
            return False
        text = prompt.strip()
        if len(text) < 10:
            return False
        # Check if Spanish markers exist
        spanish_markers = re.search(
            r"\b(el|la|los|las|un|una|unos|unas|del|para|por|con|sin|donde|genera|dibuja|crea|haz|imagen|foto|dibujo|hombre|mujer|conejo|perro|gato|pájaro|pajaro)\b",
            text,
            re.IGNORECASE,
        )
        return spanish_markers is None

    def _build_image_prompt_refine_instruction(self, prompt: str) -> str:
        return textwrap.dedent(f"""\
            ROLE: You are an expert Multilingual Visual Prompt Engineer for text-to-image AI models (OpenAI DALL-E 3 / Gemini Imagen).
            TASK: Rewrite the request below into ONE highly detailed image-generation prompt IN ENGLISH.
            Return ONLY the prompt text. No quotes, markdown, or commentary.

            CRITICAL MULTILINGUAL DISAMBIGUATION & SLANG RULES:
            1. CREATOR & SLANG DISAMBIGUATION:
               - The word "streamer", "youtuber", "vtuber", or "content creator" in ANY language (Spanish, English, Portuguese, French, etc.) ALWAYS refers to a human live broadcaster inside a broadcast room/studio. NEVER convert "streamer" into water streams, rivers, creeks, or paper decorations.
               - Handles and pseudonyms in sports/gaming contexts (e.g. "La Cobra", "Ibai", "Speed", "Gaules", "Rubius", "DjMaRiiO", "Razor Callahan") represent human creators/characters. NEVER translate "La Cobra" literally as a snake, tiger, or wild animal when used in a creator/sports context.
               - Terms like "DJ" (disc jockey), "portada musical" (music album cover), and gaming acronyms (e.g. "NFSMW" = Need for Speed Most Wanted, "GTA", "COD") MUST be recognized as music/gaming culture. NEVER convert a DJ request into a track athlete or runner.
            2. SUBJECT FIDELITY (MANDATORY):
               - Keep the PRIMARY SUBJECT identical (same species/person/object). Never turn a person into a wild beast, nor swap animals (e.g., never turn a rabbit into a dog/puppy, or a human into an animal).
            3. PROMPT STRUCTURE FORMULA:
               Build the prompt using this structure:
               [Primary Subject & Facial/Physical Traits] + [Action & Posture] + [Outfit & Apparel Details] + [Environment & Background] + [Lighting & Style Quality]
            4. OTHER RESTRICTIONS:
               - Do NOT use layout words like infographic, poster, chart, diagram, mindmap, banner, or text boxes.
               - Do NOT ask for readable text, quotes, or letters inside the image; describe visual symbols/gestures instead.
               - If a real public figure is named, describe them generically (looks, hair, clothing, pose).
               - Output MUST be 100% English.

            MULTILINGUAL FEW-SHOT EXAMPLES:

            [Example 1 - Spanish Slang & Pseudonyms]
            Request: genera la imagen en donde se muestre el streamer la cobra bailando con la camiseta del barcelona
            Output: A realistic digital artwork of a male internet streamer dancing enthusiastically inside a vibrant gaming stream setup, wearing a red and blue striped soccer jersey, dynamic pose, colorful RGB studio lighting, sharp focus, cinematic high detail

            [Example 2 - Portuguese Slang]
            Request: desenhe o streamer Gaules com a camisa do Brasil comemorando um gol
            Output: A highly detailed illustration of a male content creator celebrating passionately inside a modern streaming studio, wearing a yellow Brazil national team soccer jersey, triumphant gesture, stream background, cinematic lighting

            [Example 3 - English Slang]
            Request: draw streamer Speed wearing a red hoodie dancing with a dog
            Output: A vivid image of an energetic young male streamer wearing a red hoodie dancing in a bedroom streaming setup, a friendly dog sitting next to him, studio lighting, detailed character design

            [Example 4 - Gaming & Music Album Cover Request]
            Request: Genera una imagen de un dj que se parezca a razor callahan de NFSMW para una portada musical
            Output: A stylish music album cover art featuring a tough male DJ with short hair, leather jacket, and sunglasses standing in front of DJ turntables and a customized street racing car, street racing aesthetic, dramatic neon stage lighting, detailed cover art design

            Now process this request:
            Request: {prompt}

            Image generation prompt:
            """)

    def _refine_image_prompt_fast(self, prompt: str) -> str:
        """
        Fast prompt rewrite using a Flash model for non-English prompts.
        Falls back to a lightweight local English boost if Flash is unavailable.
        """
        cleaned = self._clean_image_request_text(prompt)
        instruction = self._build_image_prompt_refine_instruction(cleaned)
        try:
            gemini_client = self._get_gemini_client() if hasattr(self, "_get_gemini_client") else None
            if gemini_client is None and hasattr(self, "client"):
                gemini_client = self.client
            if gemini_client is not None:
                flash_model = (
                    os.getenv("GEMINI_IMAGE_PROMPT_MODEL", "gemini-2.5-flash").strip()
                    or "gemini-2.5-flash"
                )
                response = gemini_client.models.generate_content(
                    model=flash_model,
                    contents=instruction,
                    config=types.GenerateContentConfig(
                        max_output_tokens=280,
                        temperature=0.0,
                    ),
                )
                text = (getattr(response, "text", None) or "").strip().strip('"').strip("'")
                if text and not text.startswith("Error:"):
                    return text
        except Exception as e:
            logger.warning(f"Fast image-prompt refine failed: {e}")

        # Local fallback: append quality cues to the cleaned subject
        return (
            f"{cleaned}, highly detailed, photorealistic, cinematic lighting, "
            "natural colors, sharp focus"
        )

    def _prepare_image_generation_prompt(self, prompt: str) -> tuple:
        """
        Returns (final_prompt, script_tokens).
        When the prompt is already in English, cleans command prefixes and enhances quality directly (0ms, 100% subject fidelity).
        When translation is needed, uses Flash with zero temperature and no confusing few-shots.
        """
        original = (prompt or "").strip()
        if not original:
            return original, None

        if self._is_ready_image_prompt(original):
            cleaned = self._clean_image_request_text(original)
            if not any(q in cleaned.lower() for q in ["photorealistic", "cinematic", "sharp focus", "highly detailed"]):
                final_prompt = f"{cleaned}, highly detailed, photorealistic, cinematic lighting, natural colors, sharp focus"
            else:
                final_prompt = cleaned
            logger.info(f"Using direct English image prompt: {final_prompt[:180]}...")
            return final_prompt, None

        refined = self._refine_image_prompt_fast(original)
        logger.info(f"Refined image prompt: {refined[:180]}...")
        return refined or original, None

    @staticmethod
    def is_direct_image_request(text: str) -> bool:
        """True for clear 'generate/draw an image of X' requests (no mixed chat task)."""
        if not text or not isinstance(text, str):
            return False
        lower = text.strip().lower()
        if len(lower) > 400:
            return False
        # Require an explicit visual noun â€” bare "dibuja/draw" alone is too broad
        # (e.g. "dibuja el diagrama UML" should stay in normal chat).
        patterns = [
            r"^(por favor[, ]*)?(me\s+)?(puedes\s+)?(genera|generar|crea|crear|dibuja|dibujar|haz|hacer)\b.*\b(imagen|dibujo|foto|ilustraci[oó]n|pintura)\b",
            r"^(please[, ]*)?(can you\s+)?(generate|create|draw|make|paint)\b.*\b(image|picture|drawing|photo|illustration|painting)\b",
            r"^(genera|crea|dibuja)\s+la\s+imagen\b",
        ]
        return any(re.search(p, lower) for p in patterns)

    # Function that generates an image from a prompt
    def generate_image(self, prompt: str) -> tuple:
        """
        Generate an image from a prompt using OpenAI GPT Image models.
        Returns (image_bytes, mime_type, error_message, token_info).
        """
        script = None
        script_tokens = None
        try:
            script, script_tokens = self._prepare_image_generation_prompt(prompt)
            if not script:
                script = prompt

            logger.info(f"OpenAI Image prompt: {script[:180]}...")

            # Step 2: Call OpenAI Image Generation
            openai_client = build_openai_client()
            image_model = (OPENAI_IMAGE_MODEL_VERSION or "gpt-image-2").strip()
            fallback_image_model = (OPENAI_FALLBACK_IMAGE_MODEL or "gpt-image-1").strip()

            try:
                response = openai_client.images.generate(
                    model=image_model,
                    prompt=script[:3900],
                    n=1,
                    size="1024x1024"
                )
            except Exception as model_err:
                logger.warning(f"Image generation failed with {image_model}: {model_err}. Trying fallback {fallback_image_model}...")
                response = openai_client.images.generate(
                    model=fallback_image_model,
                    prompt=script[:3900],
                    n=1,
                    size="1024x1024"
                )

            if not response or not getattr(response, "data", None):
                raise ValueError("No image data returned by OpenAI API.")

            data = response.data[0]
            if not data:
                raise ValueError("Empty image data object returned by OpenAI API.")

            b64_json = getattr(data, "b64_json", None) if not isinstance(data, dict) else data.get("b64_json")
            url = getattr(data, "url", None) if not isinstance(data, dict) else data.get("url")

            if b64_json:
                image_bytes = base64.b64decode(b64_json)
            elif url:
                img_response = requests.get(url, timeout=30)
                img_response.raise_for_status()
                image_bytes = img_response.content
            else:
                raise ValueError("No image data (b64_json or url) returned by OpenAI API.")

            # Build token_info (OpenAI Images don't report tokens; use script tokens if available)
            token_info = None
            if script_tokens:
                token_info = dict(script_tokens)
                token_info.setdefault("thinking_tokens", 0)

            logger.info("OpenAI generated image successfully.")
            return image_bytes, "image/png", None, token_info

        except Exception as e:
            logger.warning(f"OpenAI Image generation error: {e}. Trying fallback to Gemini Image...")
            try:
                gemini_client = self._get_gemini_client()
                if gemini_client:
                    gemini_image_model = (GEMINI_IMAGE_MODEL_VERSION or "gemini-3.1-flash-image").strip()
                    logger.info(f"Generating image with Gemini fallback model {gemini_image_model}...")

                    if gemini_image_model.startswith("imagen-"):
                        response = gemini_client.models.generate_images(
                            model=gemini_image_model,
                            prompt=script or prompt,
                            config=types.GenerateImagesConfig(
                                number_of_images=1,
                                aspect_ratio="1:1",
                                safety_filter_level="block_only_high"
                            )
                        )
                        if response.generated_images:
                            gen_img = response.generated_images[0]
                            image_obj = getattr(gen_img, "image", None)
                            image_bytes = getattr(image_obj, "image_bytes", None) if image_obj is not None else getattr(gen_img, "image_bytes", None)
                            if isinstance(image_bytes, str):
                                image_bytes = base64.b64decode(image_bytes)
                            if image_bytes:
                                token_info = None
                                if hasattr(response, 'usage_metadata') and response.usage_metadata:
                                    token_info = self._parse_token_info(response.usage_metadata)
                                logger.info("Gemini fallback image generated successfully.")
                                return image_bytes, "image/png", None, token_info
                    else:
                        fidelity_prompt = (
                            "Generate an image that matches this description EXACTLY. "
                            "Do not replace the main subject with a different animal, person, or object.\n\n"
                            f"{script or prompt}"
                        )
                        response = gemini_client.models.generate_content(
                            model=gemini_image_model,
                            contents=fidelity_prompt,
                            config=types.GenerateContentConfig(
                                response_modalities=["IMAGE"]
                            )
                        )
                        if response.candidates:
                            candidate = response.candidates[0]
                            parts = candidate.content.parts if candidate.content else None
                            if isinstance(parts, list):
                                for part in parts:
                                    if part.inline_data and part.inline_data.mime_type and part.inline_data.mime_type.startswith('image/'):
                                        image_bytes = part.inline_data.data
                                        mime = part.inline_data.mime_type
                                        token_info = None
                                        if hasattr(response, 'usage_metadata') and response.usage_metadata:
                                            token_info = self._parse_token_info(response.usage_metadata)
                                        logger.info("Gemini fallback image generated successfully.")
                                        return image_bytes, mime, None, token_info
            except Exception as gemini_err:
                logger.error(f"Gemini fallback image generation failed: {gemini_err}")

            logger.error(f"OpenAI Image generation error: {e}")
            return {}, {}, f"Image generation failed: {str(e)}", {}

    # Function that generates spoken audio from a prompt
    def generate_audio(self, prompt: str, language: str = "", fallback_models: list = []) -> tuple:
        """
        Generate spoken audio from a prompt using OpenAI TTS.
        Returns (audio_bytes, mime_type, error_message, token_info, script).
        """
        script = None
        script_tokens = None
        try:
            # Resolve BCP-47 language code to human-readable language name
            lang_name = "the SAME language as the Request"
            if language:
                base_lang = language.split('-')[0].lower()
                _LANG_NAMES = {
                    "es": "Spanish",
                    "en": "English",
                    "fr": "French",
                    "de": "German",
                    "pt": "Portuguese",
                    "it": "Italian",
                    "zh": "Chinese",
                    "ja": "Japanese",
                    "ko": "Korean"
                }
                lang_name = _LANG_NAMES.get(base_lang, "the SAME language as the Request")

            # Step 1: Generate a natural-sounding spoken script using this model's own generate_response
            script_instruction = textwrap.dedent(f"""\
            Write a short, natural-sounding spoken paragraph (max 50 words, about 15-20 seconds when read aloud) that matches the following request.
            The speaker is a person talking conversationally.

            CRITICAL LANGUAGE REQUIREMENT: You MUST write the spoken text in {lang_name}.

            Return ONLY the spoken text, without any extra commentary, quotes, or markdown.

            Request: {prompt}

            Spoken script:
            """)
            original_search_state = getattr(self, "google_search_enabled", False)
            try:
                self.google_search_enabled = False
                try:
                    script, script_tokens = self.generate_response(script_instruction, history=None, max_tokens=150)
                except Exception as e:
                    logger.warning(f"Script generation failed: {e}. Using raw prompt as script.")
                    script = prompt
                    script_tokens = None
            finally:
                self.google_search_enabled = original_search_state

            if not script or script.startswith("Error:"):
                script = prompt
                script_tokens = None
            else:
                script = script.strip().strip('"').strip("'")

            logger.info(f"OpenAI TTS script: {script}")

            # --- Try VoiceProcessor TTS if configured ---
            if self.voice_processor.is_configured():
                voice_cat = self.voice_processor.determine_voice_category(prompt)
                try:
                    audio_bytes = self.voice_processor.generate_tts(script, voice_category=voice_cat)
                    if not audio_bytes:
                        raise ValueError("VoiceProcessor returned empty or null audio bytes")
                    token_info = None
                    if script_tokens:
                        token_info = dict(script_tokens)
                        token_info.setdefault("thinking_tokens", 0)

                    logger.info(f"VoiceProcessor TTS generated audio with voice category '{voice_cat}' successfully.")
                    return audio_bytes, "audio/mp3", None, token_info, script
                except Exception as e:
                    logger.warning(f"VoiceProcessor TTS failed: {e}. Falling back to OpenAI TTS...")

            # --- Dynamic voice selection based on gender keywords in prompt ---
            lower_prompt = prompt.lower()
            female_keywords = ["woman", "female", "girl", "lady", "mother", "wife", "daughter", "she", "her", "hers",
                               "mujer", "femenino", "chica", "niña", "dama", "madre", "esposa", "hija", "ella"]
            male_keywords = ["man", "male", "guy", "boy", "gentleman", "father", "husband", "son", "he", "him", "his",
                             "hombre", "masculino", "chico", "niño", "caballero", "padre", "esposo", "hijo", "él", "lo"]

            # Function that gets the earliest keyword index
            def get_earliest_keyword_index(keywords, text):
                earliest = float('inf')
                for kw in keywords:
                    match = re.search(r'\b' + re.escape(kw) + r'\b', text)
                    if match and match.start() < earliest:
                        earliest = match.start()
                return earliest

            female_idx = get_earliest_keyword_index(female_keywords, lower_prompt)
            male_idx = get_earliest_keyword_index(male_keywords, lower_prompt)

            if female_idx < male_idx:
                voice = "nova"
            elif male_idx < female_idx:
                voice = "onyx"
            else:
                voice = OPENAI_TTS_VOICE or "onyx"   # env-configured default

            tts_model = OPENAI_AUDIO_MODEL_VERSION or "tts-1"

            # Step 2: Call OpenAI TTS (with fallback)
            openai_client = build_openai_client()
            audio_bytes = None

            try:
                fibonacci_wait = wait_chain(*[wait_fixed(s) for s in OPENAI_RETRY_SEQUENCE])
                tts_response = None
                for attempt in Retrying(stop=stop_after_attempt(len(OPENAI_RETRY_SEQUENCE)), wait=fibonacci_wait, reraise=True):
                    with attempt:
                        tts_response = openai_client.audio.speech.create(
                            model=tts_model,
                            voice=voice,
                            input=script,
                            response_format="mp3"
                        )
                audio_bytes = tts_response.content if tts_response else None  # raw MP3 bytes
            except Exception as e:
                fallback_model = OPENAI_FALLBACK_AUDIO_MODEL_VERSION or "tts-1"
                logger.warning(f"Primary OpenAI TTS model {tts_model} failed: {e}. Trying fallback model {fallback_model}...")
                fibonacci_wait = wait_chain(*[wait_fixed(s) for s in OPENAI_RETRY_SEQUENCE])
                tts_response = None
                for attempt in Retrying(stop=stop_after_attempt(len(OPENAI_RETRY_SEQUENCE)), wait=fibonacci_wait, reraise=True):
                    with attempt:
                        tts_response = openai_client.audio.speech.create(
                            model=fallback_model,
                            voice=voice,
                            input=script,
                            response_format="mp3"
                        )
                audio_bytes = tts_response.content if tts_response else None
                # Update tts_model to the fallback one for logging info
                tts_model = fallback_model

            # Build token_info (OpenAI TTS doesn't report tokens; use script tokens if available)
            token_info = None
            if script_tokens:
                token_info = dict(script_tokens)
                token_info.setdefault("thinking_tokens", 0)

            logger.info(f"OpenAI TTS generated audio with voice '{voice}' via model '{tts_model}'")
            return audio_bytes, "audio/mp3", None, token_info, script

        except Exception as e:
            logger.error(f"OpenAI TTS error: {e}")
            if script:
                # Fallback: return browser-tts with the script so the user still hears something
                return None, "browser-tts", None, script_tokens, script
            return None, None, f"Audio generation failed: {str(e)}", None, None

    def _extract_text_from_pdf(self, file_bytes: bytes, user_query: str = "") -> str:
        """
        Extract text from PDF bytes. Whole-document requests keep the full text when it
        fits IGNITE_PDF_MAX_FULL_TEXT_CHARS, otherwise sample pages across the book.
        Pinpoint questions still use keyword retrieval.
        """
        reader = None
        if pypdf is not None:
            try:
                reader = pypdf.PdfReader(io.BytesIO(file_bytes))
            except Exception as e:
                logger.warning(f"pypdf extraction failed: {e}")

        if reader is None and PyPDF2 is not None:
            try:
                reader = PyPDF2.PdfReader(io.BytesIO(file_bytes))
            except Exception as e2:
                logger.warning(f"PyPDF2 extraction failed: {e2}")

        if reader is None:
            logger.error("No PDF parser available or PDF is encrypted/corrupted.")
            return "[Error: Could not extract PDF text - no valid PDF parser available]"

        try:
            pages_text = []
            total_chars = 0
            for i, page in enumerate(reader.pages):
                page_text = page.extract_text() or ""
                pages_text.append((i + 1, page_text))
                total_chars += len(page_text)

            max_full_chars = pdf_max_full_text_chars()
            max_retrieved_pages = pdf_max_retrieved_pages()
            page_count = len(reader.pages)

            if total_chars <= max_full_chars:
                logger.info(
                    "PDF text extract full pages=%s chars=%s query_full_read=%s",
                    page_count,
                    total_chars,
                    wants_full_document_read(user_query),
                )
                text_parts = [f"--- Page {num} ---\n{text}" for num, text in pages_text if text.strip()]
                return "\n\n".join(text_parts)

            if wants_full_document_read(user_query):
                selected_pages = _sample_pages_evenly(pages_text, pdf_summary_sample_pages())
                sorted_selected = sorted(selected_pages.items())
                logger.info(
                    "PDF summary sample pages=%s/%s chars=%s",
                    len(sorted_selected),
                    page_count,
                    total_chars,
                )
                text_parts = [
                    f"[SYSTEM NOTE: The uploaded document has {page_count} pages ({total_chars} characters). "
                    f"The system sampled pages across the whole book so a chapter-level summary remains possible. "
                    f"Query: '{user_query}']\n"
                ]
                for num, text in sorted_selected:
                    text_parts.append(f"--- Page {num} ---\n{text}")
                return "\n\n".join(text_parts)

            stop_words = {
                "the", "and", "a", "of", "to", "in", "is", "that", "it", "on", "for", "with", "as", "by", "at", "an", "this", "from",
                "de", "la", "el", "en", "y", "que", "un", "una", "los", "las", "con", "por", "para", "como", "del", "al", "es", "su",
                "about", "how", "what", "where", "who", "why", "which", "would", "could", "should", "please", "analyze", "document",
                "pdf", "file", "read", "explain", "summarize", "find", "search"
            }
            query_words = []
            if user_query:
                words = re.findall(r'\w+', user_query.lower())
                query_words = [w for w in words if len(w) > 2 and w not in stop_words]

            scored_pages = []
            for num, text in pages_text:
                if not text.strip():
                    continue
                score = 0
                lower_text = text.lower()
                for word in query_words:
                    score += lower_text.count(word)
                scored_pages.append((num, text, score))

            scored_pages.sort(key=lambda x: x[2], reverse=True)

            selected_pages = {}
            for num, text in pages_text[:2]:
                if text.strip():
                    selected_pages[num] = text

            for num, text, score in scored_pages:
                if len(selected_pages) >= max_retrieved_pages:
                    break
                if num not in selected_pages:
                    selected_pages[num] = text

            sorted_selected = sorted(selected_pages.items())
            logger.info(
                "PDF keyword retrieve pages=%s/%s chars=%s",
                len(sorted_selected),
                page_count,
                total_chars,
            )
            text_parts = [
                f"[SYSTEM NOTE: The uploaded document has {page_count} pages ({total_chars} characters). Due to rate limits, the system retrieved the cover pages and the most relevant sections based on your query: '{user_query}']\n"
            ]
            for num, text in sorted_selected:
                text_parts.append(f"--- Page {num} ---\n{text}")

            return "\n\n".join(text_parts)

        except Exception as e:
            logger.error(f"Error filtering PDF text: {e}")
            return f"[Error filtering PDF document text: {e}]"


def _env_positive_int(name: str, default: int, minimum: int = 0) -> int:
    """Read a non-negative int from env; invalid/empty values fall back to default."""
    raw = os.getenv(name)
    try:
        value = int(default if raw in (None, "") else raw)
    except (TypeError, ValueError):
        value = default
    return max(minimum, value)


_PDF_FULL_READ_RE = re.compile(
    r"\b(resumen|summarize|summary|sinopsis|cap[ií]tulos?|chapters?|libro|book)\b",
    re.IGNORECASE,
)


def wants_full_document_read(user_query: str) -> bool:
    """True when the user asked to summarize/read the whole document, not a pinpoint Q&A."""
    return bool(_PDF_FULL_READ_RE.search(user_query or ""))


def pdf_max_full_text_chars() -> int:
    return _env_positive_int("IGNITE_PDF_MAX_FULL_TEXT_CHARS", 400000, 1000)


def pdf_max_retrieved_pages() -> int:
    return _env_positive_int("IGNITE_PDF_MAX_RETRIEVED_PAGES", 12, 1)


def pdf_summary_sample_pages() -> int:
    return _env_positive_int("IGNITE_PDF_SUMMARY_SAMPLE_PAGES", 80, 4)


def pdf_image_page_scan_limit() -> int:
    return _env_positive_int("IGNITE_PDF_IMAGE_PAGE_SCAN_LIMIT", 8, 1)


def vision_min_image_pixels() -> int:
    """Grok multimodal rejects images with total pixels below this (default 512)."""
    return _env_positive_int("IGNITE_VISION_MIN_IMAGE_PIXELS", 512, 1)


def pdf_native_max_bytes() -> int:
    return _env_positive_int("IGNITE_PDF_NATIVE_MAX_BYTES", 20 * 1024 * 1024, 1024)


def pdf_native_max_pages() -> int:
    return _env_positive_int("IGNITE_PDF_NATIVE_MAX_PAGES", 100, 1)


def gemini_http_timeout_ms() -> int:
    """Gemini SDK http timeout. Must stay below the UI document poll budget."""
    return _env_positive_int("IGNITE_GEMINI_HTTP_TIMEOUT_MS", 900000, 60000)


def llm_http_timeout_seconds() -> int:
    """OpenAI-compatible / Anthropic client timeout for long document turns."""
    return _env_positive_int("IGNITE_LLM_HTTP_TIMEOUT", 900, 60)


def should_send_native_pdf(file_bytes: bytes) -> bool:
    return bool(file_bytes) and len(file_bytes) <= pdf_native_max_bytes()


def _sample_pages_evenly(pages_text: List[Tuple[int, str]], limit: int) -> Dict[int, str]:
    """Keep cover pages, the last page, and evenly spaced pages across the book."""
    selected: Dict[int, str] = {}
    if not pages_text or limit <= 0:
        return selected
    for num, text in pages_text[:2]:
        if text.strip():
            selected[num] = text
    last_num, last_text = pages_text[-1]
    if last_text.strip():
        selected[last_num] = last_text
    remaining = max(0, limit - len(selected))
    if remaining == 0 or len(pages_text) <= len(selected):
        return selected
    step = len(pages_text) / (remaining + 1)
    for i in range(1, remaining + 1):
        idx = min(len(pages_text) - 1, max(0, int(round(i * step))))
        num, text = pages_text[idx]
        if text.strip():
            selected[num] = text
    return selected


def get_current_date_and_time_strings() -> tuple[str, str, str]:
    """
    Returns (current_date_str, current_time_str, current_year_str)
    with the timezone/UTC offset explicitly appended to the time.
    """
    now = datetime.now()
    current_date_str = now.strftime("%A, %B %d, %Y")
    current_year_str = str(now.year)

    tz_name = USER_SYSTEM_TIMEZONE
    tz_offset_val = "-0500"
    try:
        local_tz = now.astimezone()
        tz_name = local_tz.tzname() or USER_SYSTEM_TIMEZONE
        tz_offset = local_tz.strftime('%z')
        if tz_offset:
            tz_offset_val = tz_offset
            # Format offset as -05:00 instead of -0500
            tz_str = f"{tz_name} (UTC{tz_offset[:3]}:{tz_offset[3:]})"
        else:
            tz_str = tz_name
    except Exception:
        tz_str = USER_SYSTEM_TIMEZONE

    offset_formatted = f"UTC{tz_offset_val[:3]}:{tz_offset_val[3:]}" if len(tz_offset_val) >= 5 else "UTC-05:00"
    current_time_24 = now.strftime('%H:%M')
    current_time_12 = now.strftime('%I:%M %p')

    current_time_str = (
        f"{current_time_12} ({current_time_24} in 24-hour format) {tz_str}. "
        f"IMPORTANT: The timezone offset of the user is {offset_formatted} (local name: {tz_name}). "
        f"Do NOT rely on timezone names for conversions (e.g. names containing 'Pacific' or 'Eastern' may refer to different regions than you expect). "
        f"Instead, rely ONLY on the numerical UTC offset ({offset_formatted}) to convert scheduled times. "
        f"When comparing this with events/matches scheduled in other timezones, "
        f"carefully convert the scheduled event time to the user's local time zone ({offset_formatted}) using 24-hour values "
        f"to determine if the event is in the past or the future. Do not mix up AM/PM transitions."
    )
    return current_date_str, current_time_str, current_year_str
