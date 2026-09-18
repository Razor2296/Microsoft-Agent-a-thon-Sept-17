import os
import sys
import subprocess
import io
import json
import re
import logging
try:
    import pytz
except ImportError:
    pytz = None
import importlib
import random
import textwrap
import ctypes
import base64
import requests
import traceback
import threading
import time
import uuid
import shutil
import webbrowser
import hashlib
import glob
import contextvars
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional, Union, cast

# Optional desktop / Windows-only dependencies (absent in ACA Linux image)
try:
    import webview
except ImportError:
    webview = None
from main.document_generator import _ensure_dependencies
from main.document_generator import generate_docx, generate_xlsx, generate_pptx
from backend.voice.voice_processor import VoiceProcessor
from backend.processors.cost_calculator import calculate_cost_usd, calculate_media_cost_usd
from backend.core.semaphore import Semaphore

# Skill 2.6 — PII & Prompt Injection Guardrails
try:
    from backend.tools.guardrails import PIIShield, PromptInjectionGuard
    _PII_SHIELD_AVAILABLE = True
except ImportError:
    _PII_SHIELD_AVAILABLE = False

# Skill 2.8 — Skill Store & Dynamic Plugin Loader
try:
    from backend.tools.skill_loader import SkillLoader
    _SKILL_LOADER_AVAILABLE = True
except ImportError:
    _SKILL_LOADER_AVAILABLE = False

# Skill 2.1 — Persistent Memory (Local RAG)
try:
    from backend.tools.rag_engine import LocalRAGEngine
    _RAG_ENGINE_AVAILABLE = True
except ImportError:
    _RAG_ENGINE_AVAILABLE = False

# Skills 2.2 - 2.7 — Core Feature Processors
try:
    from backend.tools.sandbox_runner import SandboxRunner
    from backend.tools.web_agent import WebAgent
    from backend.tools.mcp_gateway import MCPGateway
    from backend.voice.voice_clone import VoiceCloneManager
    from backend.tools.plotly_service import PlotlyService
    _CORE_FEATURES_AVAILABLE = True
except ImportError:
    _CORE_FEATURES_AVAILABLE = False

# Add current directory to Python path to resolve imports correctly
current_dir = os.path.dirname(os.path.abspath(__file__))
code_dir = os.path.dirname(current_dir)
if code_dir not in sys.path:
    sys.path.insert(0, code_dir)

# For user resource files (.env, logs, Databases, assets), use execution folder if frozen
if getattr(sys, 'frozen', False):
    _exe_dir = os.path.dirname(sys.executable)
    if os.path.exists(os.path.join(_exe_dir, '.env')):
        app_dir = _exe_dir
    elif os.path.exists(os.path.join(os.path.dirname(_exe_dir), '.env')):
        app_dir = os.path.dirname(_exe_dir)
    else:
        app_dir = _exe_dir
else:
    app_dir = code_dir

# Sessions / media / groups / logs: IGNITE_DATA_DIR, or AppData when Program Files is read-only.
from backend.core.runtime_paths import get_writable_data_dir

DATA_DIR = get_writable_data_dir(app_dir)


def _generation_poll_timeout_ms() -> int:
    return max(60000, _env_positive_int("IGNITE_GENERATION_POLL_TIMEOUT_MS", "1200000"))


def _document_poll_timeout_ms() -> int:
    return max(60000, _env_positive_int("IGNITE_DOCUMENT_POLL_TIMEOUT_MS", "1800000"))

# Import backend components
from backend.processors.processor import (
    GeminiChat,
    DeepSeekChat,
    OpenAIChat,
    AnthropicChat,
    PerplexityChat,
    AlibabaCloudChat,
    GrokChat,
    USER_PROFILE_PICTURE_PATH,
    GEMINI_PROFILE_PICTURE_PATH,
    OPENAI_PROFILE_PICTURE_PATH,
    OPENAI_AVAILABLE_MODELS_DEFAULT,
    DEEPSEEK_PROFILE_PICTURE_PATH,
    ANTHROPIC_PROFILE_PICTURE_PATH,
    PERPLEXITY_PROFILE_PICTURE_PATH,
    ALIBABACLOUD_PROFILE_PICTURE_PATH,
    GROK_PROFILE_PICTURE_PATH,
    GROK_BASE_URL,
    USER_SYSTEM_LANGUAGE,
    BaseChat,
)
from backend.user.windows_user import get_user_display_name, get_downloads_path
from backend.core.libraries import get_assistant_logger
from backend.core.schemas import TokenInfo, APIRequestPayload, APIResponsePayload
from backend.core.runtime_identity import get_runtime_user_name, set_runtime_user_name
from backend.core.conversation_language import (
    detect_explicit_language_switch as _detect_explicit_language_switch,
    detect_language_from_text as _detect_language_from_text,
    get_default_conversation_language,
    resolve_conversation_language as _resolve_conversation_language,
)
from main.env_config import load_environment
from dotenv import load_dotenv

from backend.integrations.ignite_api_client import IgniteAPIClient
from backend.integrations.ignite_rag_transformer import extraction_to_rag_chunks
from backend.integrations.foundry_orchestration import (
    maybe_run_foundry_turn,
    notify_foundry_after_extract,
)


# Logger 
logger = get_assistant_logger("pywebview_api")

# Maximum number of past messages sent to the model per request (configurable via .env)
# Lower = fewer tokens per call; higher = more context. 20 pairs ≈ 10 full back-and-forth exchanges.
MAX_HISTORY_MESSAGES = int(os.getenv("MAX_HISTORY_MESSAGES", "20"))
# Cap concurrent group participant generations (AdjustableSemaphore).
GROUP_MAX_PARALLEL = max(1, int(os.getenv("GROUP_MAX_PARALLEL", "6")))
# First-query backfill of archived session JSON into local RAG (newest files first).
RAG_BACKFILL_MAX_FILES = max(1, int(os.getenv("RAG_BACKFILL_MAX_FILES", "50")))
RAG_BACKFILL_MAX_TURNS = max(1, int(os.getenv("RAG_BACKFILL_MAX_TURNS", "250")))

# ---------- Utility functions (mirroring Streamlit app) ----------
# Function to extract image generation prompt from tags or tool JSON (e.g. dalle.text2im)
def _extract_image_directive(reply: str) -> tuple[Optional[str], str]:
    """
    Extracts image generation prompt from standard tags, alternative tags,
    or ReAct/tool-calling JSON formats (like dalle.text2im, image_generation),
    and returns (img_prompt, cleaned_reply).
    """
    if not reply or not isinstance(reply, str):
        return None, reply

    # 1. Check for standard [GENERATE_IMAGE: ...] tag
    match = re.search(r'\[GENERATE_IMAGE:\s*(.*?)\]', reply, re.IGNORECASE | re.DOTALL)
    if match:
        img_prompt = match.group(1).strip()
        cleaned = re.sub(r'\[GENERATE_IMAGE:\s*.*?\]', '', reply, flags=re.IGNORECASE | re.DOTALL).strip()
        return img_prompt, cleaned

    # 2. Check for alternative square-bracket tags
    alt_match = re.search(r'\[(?:IMAGE|IMAGE_PROMPT|DALLE|DALL_E|TEXT2IM|GEN_IMAGE):\s*(.*?)\]', reply, re.IGNORECASE | re.DOTALL)
    if alt_match:
        img_prompt = alt_match.group(1).strip()
        cleaned = re.sub(r'\[(?:IMAGE|IMAGE_PROMPT|DALLE|DALL_E|TEXT2IM|GEN_IMAGE):\s*.*?\]', '', reply, flags=re.IGNORECASE | re.DOTALL).strip()
        return img_prompt, cleaned

    # 3. Check for JSON / ReAct tool-call formats
    json_candidates = []
    # 3a. Markdown code blocks ```json ... ```
    for m in re.finditer(r'```(?:json)?\s*(\{[\s\S]*?\})\s*```', reply, re.IGNORECASE):
        json_candidates.append((m.group(1), m.start(), m.end()))
    # 3b. Raw JSON objects starting with {
    for m in re.finditer(r'\{', reply):
        start_idx = m.start()
        try:
            decoder = json.JSONDecoder()
            obj, end_offset = decoder.raw_decode(reply[start_idx:])
            if isinstance(obj, dict):
                json_candidates.append((obj, start_idx, start_idx + end_offset))
        except Exception:
            pass

    for raw_obj, start_pos, end_pos in json_candidates:
        obj = None
        if isinstance(raw_obj, dict):
            obj = raw_obj
        elif isinstance(raw_obj, str):
            try:
                obj = json.loads(raw_obj)
            except Exception:
                pass

        if not isinstance(obj, dict):
            continue

        action = str(obj.get("action") or obj.get("name") or obj.get("tool") or "").lower()
        is_image_action = any(k in action for k in [
            "dalle", "text2im", "image_generation", "generate_image", 
            "image_gen", "text2image", "draw_image", "create_image", "image"
        ])
        if not is_image_action and ("prompt" in obj and ("image" in str(obj).lower() or "dalle" in str(obj).lower())):
            is_image_action = True

        if is_image_action:
            action_input = obj.get("action_input") or obj.get("parameters") or obj.get("arguments") or obj.get("input") or obj.get("prompt") or ""
            prompt_str = None
            if isinstance(action_input, dict):
                prompt_str = action_input.get("prompt") or action_input.get("description") or action_input.get("text")
            elif isinstance(action_input, str):
                action_input_str = action_input.strip()
                if action_input_str.startswith("{") and action_input_str.endswith("}"):
                    try:
                        inner_obj = json.loads(action_input_str)
                        if isinstance(inner_obj, dict):
                            prompt_str = inner_obj.get("prompt") or inner_obj.get("description") or inner_obj.get("text")
                    except Exception:
                        pass
                if not prompt_str:
                    p_match = re.search(r'"prompt"\s*:\s*"([^"\\]*(?:\\.[^"\\]*)*)"', action_input_str)
                    if p_match:
                        try:
                            prompt_str = bytes(p_match.group(1), "utf-8").decode("unicode_escape")
                        except Exception:
                            prompt_str = p_match.group(1)
                    else:
                        prompt_str = action_input_str

            if prompt_str and isinstance(prompt_str, str) and len(prompt_str.strip()) > 3:
                cleaned = (reply[:start_pos] + reply[end_pos:]).strip()
                cleaned = re.sub(r'```(?:json)?\s*```', '', cleaned).strip()
                return prompt_str.strip(), cleaned

    return None, reply


# Function to extract audio generation prompt from tags or tool JSON
def _extract_audio_directive(reply: str) -> tuple[Optional[str], str]:
    """
    Extracts audio generation prompt from standard tags, alternative tags,
    or tool-calling JSON formats, and returns (aud_prompt, cleaned_reply).
    """
    if not reply or not isinstance(reply, str):
        return None, reply

    # 1. Check for standard [GENERATE_AUDIO: ...] tag
    match = re.search(r'\[GENERATE_AUDIO:\s*(.*?)\]', reply, re.IGNORECASE | re.DOTALL)
    if match:
        aud_prompt = match.group(1).strip()
        cleaned = re.sub(r'\[GENERATE_AUDIO:\s*.*?\]', '', reply, flags=re.IGNORECASE | re.DOTALL).strip()
        return aud_prompt, cleaned

    # 2. Check for alternative square-bracket tags
    alt_match = re.search(r'\[(?:AUDIO|AUDIO_PROMPT|GEN_AUDIO|SOUND|TTS):\s*(.*?)\]', reply, re.IGNORECASE | re.DOTALL)
    if alt_match:
        aud_prompt = alt_match.group(1).strip()
        cleaned = re.sub(r'\[(?:AUDIO|AUDIO_PROMPT|GEN_AUDIO|SOUND|TTS):\s*.*?\]', '', reply, flags=re.IGNORECASE | re.DOTALL).strip()
        return aud_prompt, cleaned

    # 3. Check for JSON / ReAct tool-call formats
    json_candidates = []
    for m in re.finditer(r'```(?:json)?\s*(\{[\s\S]*?\})\s*```', reply, re.IGNORECASE):
        json_candidates.append((m.group(1), m.start(), m.end()))
    for m in re.finditer(r'\{', reply):
        start_idx = m.start()
        try:
            decoder = json.JSONDecoder()
            obj, end_offset = decoder.raw_decode(reply[start_idx:])
            if isinstance(obj, dict):
                json_candidates.append((obj, start_idx, start_idx + end_offset))
        except Exception:
            pass

    for raw_obj, start_pos, end_pos in json_candidates:
        obj = None
        if isinstance(raw_obj, dict):
            obj = raw_obj
        elif isinstance(raw_obj, str):
            try:
                obj = json.loads(raw_obj)
            except Exception:
                pass

        if not isinstance(obj, dict):
            continue

        action = str(obj.get("action") or obj.get("name") or obj.get("tool") or "").lower()
        if any(k in action for k in ["audio", "generate_audio", "sound", "tts", "music"]):
            action_input = obj.get("action_input") or obj.get("parameters") or obj.get("arguments") or obj.get("input") or obj.get("prompt") or ""
            prompt_str = None
            if isinstance(action_input, dict):
                prompt_str = action_input.get("prompt") or action_input.get("text") or action_input.get("description")
            elif isinstance(action_input, str):
                action_input_str = action_input.strip()
                if action_input_str.startswith("{") and action_input_str.endswith("}"):
                    try:
                        inner_obj = json.loads(action_input_str)
                        if isinstance(inner_obj, dict):
                            prompt_str = inner_obj.get("prompt") or inner_obj.get("text")
                    except Exception:
                        pass
                if not prompt_str:
                    prompt_str = action_input_str

            if prompt_str and isinstance(prompt_str, str) and len(prompt_str.strip()) > 3:
                cleaned = (reply[:start_pos] + reply[end_pos:]).strip()
                cleaned = re.sub(r'```(?:json)?\s*```', '', cleaned).strip()
                return prompt_str.strip(), cleaned

    return None, reply


# Function to extract document generation directive from LLM reply tags
def _extract_document_directive(reply: str) -> tuple[Optional[str], str]:
    """Extracts document generation intent from LLM-emitted tags in the assistant reply.

    The LLM is instructed (via inject_document_guidelines) to emit one of:
        [GENERATE_DOCX]
        [GENERATE_XLSX]
        [GENERATE_PPTX]
    at the end of its response when the user genuinely requested a new document.
    This replaces the previous hardcoded regex-over-user-input approach, which caused
    false positives on natural phrases like 'I want a word with you'.

    Returns:
        (doc_type, cleaned_reply) where doc_type is 'docx', 'xlsx', 'pptx', or None.
    """
    if not reply or not isinstance(reply, str):
        return None, reply

    # Map each possible LLM-emitted tag to its document type
    _TAG_MAP = [
        (r'\[GENERATE_DOCX\]', 'docx'),
        (r'\[GENERATE_WORD\]', 'docx'),
        (r'\[GENERATE_XLSX\]', 'xlsx'),
        (r'\[GENERATE_EXCEL\]', 'xlsx'),
        (r'\[GENERATE_PPTX\]', 'pptx'),
        (r'\[GENERATE_PPT\]', 'pptx'),
    ]
    for pattern, doc_type in _TAG_MAP:
        if re.search(pattern, reply, re.IGNORECASE):
            cleaned = re.sub(pattern, '', reply, flags=re.IGNORECASE).strip()
            return doc_type, cleaned

    return None, reply


# Function to get local time in HH:MM AM/PM format
def _get_time_str():
    now = datetime.now()
    return now.strftime("%I:%M %p")

def _get_iso_timestamp():
    return datetime.now().astimezone().isoformat()

# Function to get local date in YYYY-MM-DD format
def _get_date_str():
    now = datetime.now()
    return now.strftime("%Y-%m-%d")

# Function to check if the request is a goodbye message
def _is_goodbye_message(text: str) -> bool:
    if not text:
        return False
    clean = text.lower().strip()
    clean = re.sub(r'[áàäâ]', 'a', clean)
    clean = re.sub(r'[éèëê]', 'e', clean)
    clean = re.sub(r'[íìïî]', 'i', clean)
    clean = re.sub(r'[óòöô]', 'o', clean)
    clean = re.sub(r'[úùüû]', 'u', clean)
    clean = re.sub(r'[^a-z0-9\s]', '', clean)
    goodbye_phrases = [
        r'\badios\b', r'\bchao\b', r'\bchau\b', r'\bhasta luego\b',
        r'\bhasta la proxima\b', r'\bnos vemos\b', r'\bbye\b', r'\bgoodbye\b',
        r'\bsee you\b', r'\bme voy\b', r'\bme despido\b', r'\beso seria todo\b',
        r'\beso es todo\b', r'\bchao chao\b', r'\bchaochao\b', r'\bbye bye\b',
        r'\bbyebye\b', r'\btalk to you later\b', r'\bi must go\b', r'\btengo que irme\b',
        r'\bme tengo que ir\b', r'\bme retiro\b', r'\bque la pases bien\b',
        r'\bpasala bien\b', r'\bque la pase bien\b', r'\bpasela bien\b',
        r'\bque te vaya bien\b', r'\bque le vaya bien\b', r'\bque tengas un buen dia\b',
        r'\bque tenga un buen dia\b', r'\bten un buen dia\b', r'\btenga un buen dia\b',
        r'\bque tengas un lindo dia\b', r'\bque tenga un lindo dia\b', r'\bcuidate\b',
        r'\bcuidese\b', r'\bnos vemos luego\b', r'\bhave a good time\b',
        r'\bhave a good one\b', r'\bhave a good day\b', r'\bhave a nice day\b',
        r'\btake care\b', r'\bhasta manana\b', r'\bnos vemos manana\b', 
        r'\bgracias y adios\b', r'\bgracias chao\b', r'\bgracias chau\b', 
        r'\bterminamos\b', r'\bya terminamos\b', r'\bya esta\b', 
        r'\bya esta todo\b', r'\bya es todo\b', r'^gracias$', 
        r'^muchas gracias$', r'^gracias por todo$', r'^muchas gracias por todo$', 
        r'^listo gracias$', r'^listo$',
        # Extra colloquial and multi-language phrases
        r'\bno tengo mas preguntas\b', r'\bno tengo preguntas\b', r'\bno mas preguntas\b',
        r'\bya no tengo mas preguntas\b', r'\bya no tengo preguntas\b',
        r'\bno more questions\b', r'\bi dont have more questions\b', r'\bi have no more questions\b',
        r'\bthats all thank you\b', r'\bthats all thanks\b', r'\beso seria todo gracias\b', r'\beso es todo gracias\b',
        r'\bno seria mas\b', r'\bno es mas\b', r'\bchao gracias\b', r'\badios gracias\b',
        r'\bciao gracias\b', r'\btchau gracias\b', r'\bciao chao\b',
        r'\bciao\b', r'\btchau\b', r'\badeus\b', r'\bau revoir\b', r'\badieu\b', r'\btschuss\b',
        r'\btermine\b', r'\bya termine\b', r'\bhe terminado\b', r'\bhemos terminado\b'
    ]
    return any(re.search(pattern, clean) for pattern in goodbye_phrases)

# Function to generate a friendly error message
def _friendly_error_message(error_text: str, lang: str = "en-US") -> str:
    base_lang = lang.split('-')[0].lower() if '-' in lang else lang.lower()
    templates = {
        "es": {
            "503": "⚠️ **El modelo de IA está experimentando una alta demanda.**\n\nPor favor, inténtalo de nuevo en un momento o selecciona otro modelo en la barra lateral.",
            "404": "❌ **Este modelo ya no está disponible para chatear.**\n\nPor favor, selecciona un modelo diferente de la barra lateral.",
            "403": "🚫 **Acceso denegado a este modelo.**\n\nEsto puede deberse a permisos suficientes o a una clave de API inválida. Por favor, verifica tu configuración.",
            "malformed": "⚠️ **No pude completar el análisis.**\n\nEl modelo falló al procesar el contenido. Por favor, inténtalo de nuevo o cambia de modelo.",
            "default": "❌ **Error:** {error_text}\n\nPor favor, inténtalo de nuevo o cambia de modelo."
        },
        "en": {
            "503": "⚠️ **This AI model is currently experiencing high demand.**\n\nPlease try again in a moment, or switch to another model from the sidebar.",
            "404": "❌ **This model is no longer available for chat.**\n\nPlease select a different model from the sidebar.",
            "403": "🚫 **Access denied to this model.**\n\nThis could be due to insufficient permissions or an invalid API key. Please check your API key and ensure it has access to the model.",
            "malformed": "⚠️ **I couldn't complete the analysis.**\n\nThe model failed while processing the content. Please try again or switch models.",
            "default": "❌ **Error:** {error_text}\n\nPlease try again or switch models."
        },
        "fr": {
            "503": "⚠️ **Ce modèle d'IA connaît actuellement une forte demande.**\n\nRéessayez dans un instant ou choisissez un autre modèle dans la barre latérale.",
            "404": "❌ **Ce modèle n'est plus disponible pour le chat.**\n\nVeuillez sélectionner un autre modèle dans la barre latérale.",
            "403": "🚫 **Accès refusé à ce modèle.**\n\nCela peut venir de permissions insuffisantes ou d'une clé API invalide. Vérifiez votre configuration.",
            "malformed": "⚠️ **Je n'ai pas pu terminer l'analyse.**\n\nLe modèle a échoué en traitant le contenu. Réessayez ou changez de modèle.",
            "default": "❌ **Erreur :** {error_text}\n\nRéessayez ou changez de modèle."
        },
        "de": {
            "503": "⚠️ **Dieses KI-Modell ist derzeit stark ausgelastet.**\n\nBitte versuche es gleich erneut oder wähle ein anderes Modell in der Seitenleiste.",
            "404": "❌ **Dieses Modell ist für den Chat nicht mehr verfügbar.**\n\nBitte wähle ein anderes Modell in der Seitenleiste.",
            "403": "🚫 **Zugriff auf dieses Modell verweigert.**\n\nUrsache können fehlende Berechtigungen oder ein ungültiger API-Schlüssel sein. Bitte prüfe die Konfiguration.",
            "malformed": "⚠️ **Die Analyse konnte nicht abgeschlossen werden.**\n\nDas Modell ist bei der Verarbeitung fehlgeschlagen. Bitte erneut versuchen oder das Modell wechseln.",
            "default": "❌ **Fehler:** {error_text}\n\nBitte erneut versuchen oder das Modell wechseln."
        },
        "it": {
            "503": "⚠️ **Questo modello di IA sta riscontrando un'elevata domanda.**\n\nRiprova tra un momento o seleziona un altro modello nella barra laterale.",
            "404": "❌ **Questo modello non è più disponibile per la chat.**\n\nSeleziona un modello diverso dalla barra laterale.",
            "403": "🚫 **Accesso negato a questo modello.**\n\nPotrebbe dipendere da permessi insufficienti o da una chiave API non valida. Controlla la configurazione.",
            "malformed": "⚠️ **Non sono riuscito a completare l'analisi.**\n\nIl modello non è riuscito a elaborare il contenuto. Riprova o cambia modello.",
            "default": "❌ **Errore:** {error_text}\n\nRiprova o cambia modello."
        },
        "pt": {
            "503": "⚠️ **Este modelo de IA está com alta demanda no momento.**\n\nTente novamente em instantes ou selecione outro modelo na barra lateral.",
            "404": "❌ **Este modelo não está mais disponível para chat.**\n\nSelecione um modelo diferente na barra lateral.",
            "403": "🚫 **Acesso negado a este modelo.**\n\nIsso pode ser por permissões insuficientes ou uma chave de API inválida. Verifique a configuração.",
            "malformed": "⚠️ **Não consegui concluir a análise.**\n\nO modelo falhou ao processar o conteúdo. Tente novamente ou troque de modelo.",
            "default": "❌ **Erro:** {error_text}\n\nTente novamente ou troque de modelo."
        },
    }
    t = templates.get(base_lang, templates["en"])
    if "503" in error_text or "UNAVAILABLE" in error_text:
        return t["503"]
    elif "404" in error_text:
        return t["404"]
    elif "403" in error_text or "permission" in error_text.lower():
        return t["403"]
    elif (
        "MALFORMED_FUNCTION_CALL" in error_text.upper()
        or "finish reason: tool_calls" in error_text.lower()
        or "finish reason: function_call" in error_text.lower()
        or "empty response" in error_text.lower()
        or "no response received" in error_text.lower()
    ):
        return t["malformed"]
    else:
        return t["default"].format(error_text=error_text)

# Helper to construct a localized confirmation message for generated documents
def _get_file_generated_message(doc_type: str, filename: str, lang: str = "en-US") -> str:
    base_lang = lang.split('-')[0].lower() if lang and '-' in lang else lang.lower() if lang else "en"
    doc_type_upper = doc_type.upper()
    templates = {
        "es": f"✅ Archivo {doc_type_upper} generado: **{filename}**",
        "pt": f"✅ Arquivo {doc_type_upper} gerado: **{filename}**",
        "fr": f"✅ Fichier {doc_type_upper} généré : **{filename}**",
        "it": f"✅ File {doc_type_upper} generato: **{filename}**",
        "de": f"✅ {doc_type_upper}-Datei generiert: **{filename}**",
        "en": f"✅ {doc_type_upper} file generated: **{filename}**",
    }
    return templates.get(base_lang, templates["en"])


def _media_chrome_message(kind: str, detail: str, lang: Optional[str] = None) -> str:
    """
    Localized chrome for auto-generated image/audio bubbles.
    Must follow conversation language (not binary es→ES / else→EN).
    kind: 'image' | 'audio' | 'audio_browser'
    """
    base = "en"
    if lang and isinstance(lang, str) and lang.strip():
        base = lang.strip().split("-")[0].lower()
    detail = detail or ""
    templates = {
        "image": {
            "es": f"🖼️ **Imagen generada**\n\n*Prompt: {detail}*",
            "fr": f"🖼️ **Image générée**\n\n*Prompt : {detail}*",
            "de": f"🖼️ **Bild generiert**\n\n*Prompt: {detail}*",
            "it": f"🖼️ **Immagine generata**\n\n*Prompt: {detail}*",
            "pt": f"🖼️ **Imagem gerada**\n\n*Prompt: {detail}*",
            "en": f"🖼️ **Generated image**\n\n*Prompt: {detail}*",
        },
        "audio": {
            "es": f"🎵 **Audio generado**\n\n*Prompt: {detail}*",
            "fr": f"🎵 **Audio généré**\n\n*Prompt : {detail}*",
            "de": f"🎵 **Audio generiert**\n\n*Prompt: {detail}*",
            "it": f"🎵 **Audio generato**\n\n*Prompt: {detail}*",
            "pt": f"🎵 **Áudio gerado**\n\n*Prompt: {detail}*",
            "en": f"🎵 **Generated audio**\n\n*Prompt: {detail}*",
        },
        "audio_browser": {
            "es": f"🎵 **Audio generado (browser fallback)**\n\n*Script: {detail}*",
            "fr": f"🎵 **Audio généré (fallback navigateur)**\n\n*Script : {detail}*",
            "de": f"🎵 **Audio generiert (Browser-Fallback)**\n\n*Script: {detail}*",
            "it": f"🎵 **Audio generato (fallback browser)**\n\n*Script: {detail}*",
            "pt": f"🎵 **Áudio gerado (fallback do navegador)**\n\n*Script: {detail}*",
            "en": f"🎵 **Generated audio (browser fallback)**\n\n*Script: {detail}*",
        },
    }
    kind_map = templates.get(kind) or templates["image"]
    return kind_map.get(base, kind_map["en"])


def _extract_success_chrome(
    template_name: str,
    indexed_count: int,
    lang: Optional[str] = None,
    *,
    standalone: bool = True,
) -> str:
    """Localized chrome for successful Ignite structured extraction (skill: system chrome language)."""
    base = "en"
    if lang and isinstance(lang, str) and lang.strip():
        base = lang.strip().split("-")[0].lower()
    rag = indexed_count > 0
    if standalone:
        if rag:
            msgs = {
                "es": f"✅ **Análisis estructurado finalizado ({template_name})**\n\n*Guardado en memoria RAG ({indexed_count} fragmentos)*",
                "fr": f"✅ **Analyse structurée terminée ({template_name})**\n\n*Enregistré en mémoire RAG ({indexed_count} fragments)*",
                "de": f"✅ **Strukturierte Analyse abgeschlossen ({template_name})**\n\n*In RAG-Speicher gespeichert ({indexed_count} Fragmente)*",
                "it": f"✅ **Analisi strutturata completata ({template_name})**\n\n*Salvato in memoria RAG ({indexed_count} frammenti)*",
                "pt": f"✅ **Análise estruturada concluída ({template_name})**\n\n*Salvo na memória RAG ({indexed_count} fragmentos)*",
                "en": f"✅ **Structured analysis complete ({template_name})**\n\n*Saved to RAG memory ({indexed_count} chunks)*",
            }
        else:
            msgs = {
                "es": f"✅ **Análisis estructurado finalizado ({template_name})**",
                "fr": f"✅ **Analyse structurée terminée ({template_name})**",
                "de": f"✅ **Strukturierte Analyse abgeschlossen ({template_name})**",
                "it": f"✅ **Analisi strutturata completata ({template_name})**",
                "pt": f"✅ **Análise estruturada concluída ({template_name})**",
                "en": f"✅ **Structured analysis complete ({template_name})**",
            }
        return msgs.get(base, msgs["en"])
    if rag:
        suffix = {
            "es": f"\n\n✅ *Análisis estructurado con '{template_name}' guardado en memoria RAG ({indexed_count} fragmentos).* ",
            "fr": f"\n\n✅ *Analyse structurée avec '{template_name}' enregistrée en mémoire RAG ({indexed_count} fragments).* ",
            "de": f"\n\n✅ *Strukturierte Analyse mit '{template_name}' im RAG-Speicher gespeichert ({indexed_count} Fragmente).* ",
            "it": f"\n\n✅ *Analisi strutturata con '{template_name}' salvata in memoria RAG ({indexed_count} frammenti).* ",
            "pt": f"\n\n✅ *Análise estruturada com '{template_name}' salva na memória RAG ({indexed_count} fragmentos).* ",
            "en": f"\n\n✅ *Structured analysis with '{template_name}' saved to RAG memory ({indexed_count} chunks).* ",
        }
    else:
        suffix = {
            "es": f"\n\n✅ *Análisis estructurado con '{template_name}' finalizado.* ",
            "fr": f"\n\n✅ *Analyse structurée avec '{template_name}' terminée.* ",
            "de": f"\n\n✅ *Strukturierte Analyse mit '{template_name}' abgeschlossen.* ",
            "it": f"\n\n✅ *Analisi strutturata con '{template_name}' completata.* ",
            "pt": f"\n\n✅ *Análise estruturada com '{template_name}' concluída.* ",
            "en": f"\n\n✅ *Structured analysis with '{template_name}' complete.* ",
        }
    return suffix.get(base, suffix["en"])

def _merge_token_info(base_info, extra_info):
    """Safely combine two token_info objects (dicts or Pydantic V2 TokenInfo instances)."""
    if not base_info:
        if isinstance(extra_info, dict):
            return extra_info
        elif hasattr(extra_info, "to_legacy_dict"):
            return extra_info.to_legacy_dict()
        elif hasattr(extra_info, "model_dump"):
            return extra_info.model_dump()
        return extra_info
    if not extra_info:
        if isinstance(base_info, dict):
            return base_info
        elif hasattr(base_info, "to_legacy_dict"):
            return base_info.to_legacy_dict()
        elif hasattr(base_info, "model_dump"):
            return base_info.model_dump()
        return base_info

    if isinstance(base_info, dict):
        p_base = base_info.get("prompt_tokens") or 0
        c_base = base_info.get("candidates_tokens") or base_info.get("completion_tokens") or 0
        th_base = base_info.get("thinking_tokens") or 0
        t_base = base_info.get("total_tokens") or (p_base + c_base + th_base)
    else:
        p_base = getattr(base_info, "prompt_tokens", 0) or 0
        c_base = getattr(base_info, "completion_tokens", None)
        if c_base is None:
            c_base = getattr(base_info, "candidates_tokens", 0) or 0
        th_base = getattr(base_info, "thinking_tokens", 0) or 0
        t_base = getattr(base_info, "total_tokens", 0) or (p_base + c_base + th_base)

    if isinstance(extra_info, dict):
        p_ext = extra_info.get("prompt_tokens") or 0
        c_ext = extra_info.get("candidates_tokens") or extra_info.get("completion_tokens") or 0
        th_ext = extra_info.get("thinking_tokens") or 0
        t_ext = extra_info.get("total_tokens") or (p_ext + c_ext + th_ext)
    else:
        p_ext = getattr(extra_info, "prompt_tokens", 0) or 0
        c_ext = getattr(extra_info, "completion_tokens", None)
        if c_ext is None:
            c_ext = getattr(extra_info, "candidates_tokens", 0) or 0
        th_ext = getattr(extra_info, "thinking_tokens", 0) or 0
        t_ext = getattr(extra_info, "total_tokens", 0) or (p_ext + c_ext + th_ext)

    p_total = p_base + p_ext
    c_total = c_base + c_ext
    th_total = th_base + th_ext
    t_total = t_base + t_ext or (p_total + c_total + th_total)

    return {
        "prompt_tokens": p_total,
        "candidates_tokens": c_total,
        "completion_tokens": c_total,
        "thinking_tokens": th_total,
        "total_tokens": t_total,
    }


def _write_media_data_uri(
    provider: str,
    session_id: str,
    data_uri: str,
    kind: str = "image",
    tenant_key: str | None = None,
) -> str:
    """
    Persist a data URI under log/<provider>/media/ and return a path relative to app_dir.
    Returns empty string on failure.
    """
    error_msg = None
    try:
        if not isinstance(data_uri, str) or not data_uri.startswith("data:") or "," not in data_uri:
            return ""
        header, b64_payload = data_uri.split(",", 1)
        mime = "image/png"
        if ";" in header:
            mime = header[5:].split(";")[0] or mime
        ext = "png"
        if "jpeg" in mime or "jpg" in mime:
            ext = "jpg"
        elif "webp" in mime:
            ext = "webp"
        elif "gif" in mime:
            ext = "gif"
        elif "audio" in mime or kind == "audio":
            ext = "mp3" if "mpeg" in mime else "webm"
        prov_lower = "groups" if provider.startswith("group_") else provider.lower()
        log_root = os.path.join(DATA_DIR, "log")
        tenant = _safe_tenant_segment(tenant_key)
        if tenant:
            log_root = os.path.join(log_root, "tenants", tenant)
        media_dir = os.path.join(log_root, prov_lower, "media")
        os.makedirs(media_dir, exist_ok=True)
        safe_session = re.sub(r"[^\w\-]+", "_", session_id or "session")[:80]
        filename = f"{safe_session}_{uuid.uuid4().hex[:12]}.{ext}"
        abs_path = os.path.join(media_dir, filename)
        with open(abs_path, "wb") as media_file:
            media_file.write(base64.b64decode(b64_payload))
        return os.path.relpath(abs_path, app_dir).replace("\\", "/")
    except Exception as err:
        error_msg = str(err)
        logger.warning(f"Failed to persist {kind} media: {error_msg}")
        return ""

# Function that makes images viewable again in the ui
def _rehydrate_media_paths(messages: list) -> list:
    """Load image_path / audio_path files back into data URIs for the UI."""
    hydrated = []
    for msg in messages or []:
        msg_copy = dict(msg)
        for path_key, data_key, default_mime in (
            ("image_path", "image_data", "image/png"),
            ("audio_path", "audio_data", "audio/mpeg"),
        ):
            rel_path = msg_copy.get(path_key)
            current = msg_copy.get(data_key)
            if not rel_path:
                continue
            if isinstance(current, str) and current.startswith("data:"):
                continue
            abs_path = rel_path if os.path.isabs(rel_path) else os.path.join(app_dir, rel_path)
            if not os.path.isfile(abs_path):
                continue
            try:
                with open(abs_path, "rb") as media_file:
                    raw = media_file.read()
                ext = os.path.splitext(abs_path)[1].lower().lstrip(".") or "png"
                mime = default_mime
                if ext in ("jpg", "jpeg"):
                    mime = "image/jpeg"
                elif ext == "webp":
                    mime = "image/webp"
                elif ext == "gif":
                    mime = "image/gif"
                elif ext in ("webm", "ogg"):
                    mime = f"audio/{ext}"
                msg_copy[data_key] = f"data:{mime};base64,{base64.b64encode(raw).decode('utf-8')}"
            except Exception as err:
                logger.warning(f"Failed to rehydrate {path_key}={rel_path}: {err}")
        hydrated.append(msg_copy)
    return hydrated


# Function to clean the history for saving to file (preserves full content for history context)
def _clean_history_for_saving(
    history,
    provider: str | None = None,
    session_id: str | None = None,
    tenant_key: str | None = None,
):
    clean_hist = []
    for msg in history:
        msg_copy = dict(msg)
        if "token_info" in msg_copy and msg_copy["token_info"] is not None:
            t_info = msg_copy["token_info"]
            if hasattr(t_info, "to_legacy_dict"):
                msg_copy["token_info"] = t_info.to_legacy_dict()
            elif hasattr(t_info, "model_dump"):
                msg_copy["token_info"] = t_info.model_dump()
            elif not isinstance(t_info, dict):
                msg_copy["token_info"] = str(t_info)

        if "files" in msg_copy and msg_copy["files"]:
            clean_files = []
            for f in msg_copy["files"]:
                f_copy = dict(f)
                if "bytes" in f_copy:
                    del f_copy["bytes"]
                if "base64" in f_copy and not f_copy.get("name", "").startswith("Voice_Message_"):
                    del f_copy["base64"]
                clean_files.append(f_copy)
            msg_copy["files"] = clean_files

        # Persist media to disk once, then omit multi-MB data URIs from session JSON.
        if isinstance(msg_copy.get("image_data"), str) and msg_copy["image_data"].startswith("data:"):
            if not msg_copy.get("image_path") and provider:
                persisted = _write_media_data_uri(
                    provider,
                    session_id or "session",
                    msg_copy["image_data"],
                    "image",
                    tenant_key=tenant_key,
                )
                if persisted:
                    msg_copy["image_path"] = persisted
            msg_copy["image_data"] = "<image omitted from session save>"
        elif isinstance(msg_copy.get("image_data"), bytes):
            msg_copy["image_data"] = f"<image bytes: {len(msg_copy['image_data'])}>"
        if isinstance(msg_copy.get("audio_data"), str) and msg_copy["audio_data"].startswith("data:"):
            if not msg_copy.get("audio_path") and provider:
                persisted = _write_media_data_uri(
                    provider,
                    session_id or "session",
                    msg_copy["audio_data"],
                    "audio",
                    tenant_key=tenant_key,
                )
                if persisted:
                    msg_copy["audio_path"] = persisted
            msg_copy["audio_data"] = "<audio omitted from session save>"
        clean_hist.append(msg_copy)
    return clean_hist

# Function to clean the history for the frontend
def _clean_history_for_frontend(history):
    clean_hist = []
    for msg in history:
        msg_copy = dict(msg)
        if "token_info" in msg_copy and msg_copy["token_info"] is not None:
            t_info = msg_copy["token_info"]
            if hasattr(t_info, "to_legacy_dict"):
                msg_copy["token_info"] = t_info.to_legacy_dict()
            elif hasattr(t_info, "model_dump"):
                msg_copy["token_info"] = t_info.model_dump()
            elif not isinstance(t_info, dict):
                msg_copy["token_info"] = str(t_info)

        if "notification_message" in msg_copy:
            msg_copy["content"] = msg_copy["notification_message"]
            del msg_copy["notification_message"]
        if "files" in msg_copy and msg_copy["files"]:
            clean_files = []
            for f in msg_copy["files"]:
                f_copy = dict(f)
                if "bytes" in f_copy:
                    del f_copy["bytes"]
                if "base64" in f_copy and not f_copy.get("name", "").startswith("Voice_Message_"):
                    del f_copy["base64"]
                clean_files.append(f_copy)
            msg_copy["files"] = clean_files
        clean_hist.append(msg_copy)
    return clean_hist

# Helper to format group conversation history for a specific model participant
def format_history_for_group_participant(group_history, target_provider):
    formatted = []
    for msg in group_history:
        role = msg.get("role")
        provider = msg.get("provider")
        content = msg.get("content", "")
        
        if role == "user":
            formatted.append({"role": "user", "content": content})
        else:
            if provider == target_provider:
                formatted.append({"role": "assistant", "content": content})
            else:
                formatted.append({"role": "user", "content": f"[{provider}]: {content}"})
                
    # Merge consecutive messages with the same role
    merged = []
    for msg in formatted:
        if not merged:
            merged.append(msg)
        else:
            last = merged[-1]
            if last["role"] == msg["role"]:
                last["content"] += "\n\n" + msg["content"]
            else:
                merged.append(msg)
    return merged

# Function to count tokens
def _count_prompt_tokens(chat, text):
    if not text or not text.strip():
        return 0
    try:
        if chat:
            if hasattr(chat, "count_tokens"):
                return chat.count_tokens(text)
    except Exception as e:
        logger.warning(f"Error counting tokens: {e}")
    try:
        words = len(re.findall(r'\w+', text))
        return max(1, int(words * 1.3))
    except Exception:
        return 0


def _safe_tenant_segment(tenant_key: str | None) -> str | None:
    if not tenant_key:
        return None
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "_", tenant_key.strip())[:64]
    return cleaned or None


def _env_nonneg_float(name: str, default: str) -> float:
    raw = os.getenv(name, default)
    try:
        value = float(raw if raw not in (None, "") else default)
    except (TypeError, ValueError):
        try:
            value = float(default)
        except (TypeError, ValueError):
            value = 0.0
    return max(0.0, value)


def _env_positive_int(name: str, default: str) -> int:
    raw = os.getenv(name, default)
    try:
        return max(1, int(raw if raw not in (None, "") else default))
    except (TypeError, ValueError):
        try:
            return max(1, int(default))
        except (TypeError, ValueError):
            return 1


def _budget_config() -> Dict[str, float]:
    """Local estimated-spend budget. 0 disables remaining-balance alerts."""
    budget = _env_nonneg_float("IGNITE_BUDGET_USD", "10")
    warn_pct = min(1.0, _env_nonneg_float("IGNITE_BUDGET_WARN_REMAINING_PCT", "0.20"))
    critical_pct = min(1.0, _env_nonneg_float("IGNITE_BUDGET_CRITICAL_REMAINING_PCT", "0.05"))
    if critical_pct > warn_pct:
        critical_pct = warn_pct
    return {
        "budget_usd": budget,
        "warn_pct": warn_pct,
        "critical_pct": critical_pct,
        "toast_ms": float(_env_positive_int("IGNITE_BUDGET_TOAST_MS", "7000")),
    }


def _budget_alert_level(
    remaining: float,
    budget: float,
    warn_pct: float,
    critical_pct: float,
) -> str:
    if budget <= 0:
        return "disabled"
    if remaining <= 0:
        return "exhausted"
    ratio = remaining / budget
    if ratio <= critical_pct:
        return "critical"
    if ratio <= warn_pct:
        return "warn"
    return "ok"


def _budget_alert_chrome(
    level: str,
    remaining: float,
    budget: float,
    lang: Optional[str] = None,
) -> str:
    """Localized chrome when estimated remaining credit crosses warn/empty."""
    base = "en"
    if lang and isinstance(lang, str) and lang.strip():
        base = lang.strip().split("-")[0].lower()
    rem = f"{max(0.0, remaining):.4f}"
    cap = f"{max(0.0, budget):.2f}"
    templates = {
        "warn": {
            "es": f"⚠️ Te queda poco saldo estimado: ${rem} de ${cap} USD.",
            "fr": f"⚠️ Solde estimé faible : ${rem} sur ${cap} USD.",
            "de": f"⚠️ Wenig geschätztes Guthaben übrig: ${rem} von ${cap} USD.",
            "it": f"⚠️ Saldo stimato basso: ${rem} di ${cap} USD.",
            "pt": f"⚠️ Pouco saldo estimado restante: ${rem} de ${cap} USD.",
            "en": f"⚠️ Low estimated balance remaining: ${rem} of ${cap} USD.",
        },
        "critical": {
            "es": f"⚠️ Saldo estimado muy bajo: ${rem} de ${cap} USD.",
            "fr": f"⚠️ Solde estimé très faible : ${rem} sur ${cap} USD.",
            "de": f"⚠️ Geschätztes Guthaben fast leer: ${rem} von ${cap} USD.",
            "it": f"⚠️ Saldo stimato molto basso: ${rem} di ${cap} USD.",
            "pt": f"⚠️ Saldo estimado muito baixo: ${rem} de ${cap} USD.",
            "en": f"⚠️ Estimated balance almost gone: ${rem} of ${cap} USD.",
        },
        "exhausted": {
            "es": f"⛔ Se acabó el saldo estimado de este presupuesto (${cap} USD). Recarga tu crédito en el proveedor para seguir usando el chat.",
            "fr": f"⛔ Budget estimé épuisé (${cap} USD). Rechargez le crédit chez le fournisseur pour continuer.",
            "de": f"⛔ Geschätztes Budget aufgebraucht (${cap} USD). Laden Sie das Guthaben beim Anbieter auf, um weiterzuschreiben.",
            "it": f"⛔ Budget stimato esaurito (${cap} USD). Ricarica il credito presso il provider per continuare.",
            "pt": f"⛔ Saldo estimado esgotado (${cap} USD). Recarregue o crédito no provedor para continuar.",
            "en": f"⛔ Estimated budget used up (${cap} USD). Top up your provider credit to keep chatting.",
        },
    }
    kind_map = templates.get(level) or {}
    if not kind_map:
        return ""
    return kind_map.get(base, kind_map["en"])


# ---------- PyWebView API ----------
class _ContinueGroupFlow(Exception):
    """Internal control-flow signal: continue group generation after preprocess."""
    def __init__(self, processed_files, language, text, participants, request_id, from_mic, provider):
        self.processed_files = processed_files
        self.language = language
        self.text = text
        self.participants = participants
        self.request_id = request_id
        self.from_mic = from_mic
        self.provider = provider


class PyWebViewApi:
    def __init__(self, tenant_key: str | None = None):
        self._init_lock = threading.Lock()
        # Per-conversation locks so OpenAI/Group/etc. can generate and save in parallel.
        self._provider_locks_guard = threading.Lock()
        self._provider_locks = {}
        self._provider_init_errors = {}
        # ACA multi-user isolation key (None = local desktop / single-tenant).
        self._tenant_key = (tenant_key or "").strip() or None
        # Verify document generation libraries and install if missing
        try:
            _ensure_dependencies()
        except Exception as dep_err:
            logger.error(f"Failed to check/install document generation dependencies: {dep_err}")

        # Copy custom Office icons from assets if present
        try:
            dest_dir = os.path.join(app_dir, 'frontend', 'assets')
            os.makedirs(dest_dir, exist_ok=True)
            src_dir = os.path.join(app_dir, 'assets')
            
            src_mapping = {
                "word-icon.png": os.path.join(src_dir, "word-icon.png"),
                "excel-icon.png": os.path.join(src_dir, "excel-icon.png"),
                "ppt-icon.png": os.path.join(src_dir, "ppt-icon.png")
            }
            for filename, src_path in src_mapping.items():
                if os.path.exists(src_path):
                    shutil.copy(src_path, os.path.join(dest_dir, filename))
                    logger.info(f"Successfully copied custom icon {filename} to frontend/assets")
        except Exception as copy_err:
            logger.warning(f"Failed to copy custom icons: {copy_err}")

        # Ensure mp3 assets are copied to frontend/assets/ for local file WebView2 access
        try:
            frontend_assets_dir = os.path.join(app_dir, 'frontend', 'assets')
            os.makedirs(frontend_assets_dir, exist_ok=True)
            src_dir = os.path.join(app_dir, 'assets')
            if os.path.exists(src_dir):
                # Overwrite light mode image.png with WhatsApp_light_mode_2.jpg
                src_jpg = os.path.join(src_dir, 'WhatsApp_light_mode_2.jpg')
                if os.path.exists(src_jpg):
                    shutil.copy2(src_jpg, os.path.join(src_dir, 'light mode image.png'))
                    shutil.copy2(src_jpg, os.path.join(frontend_assets_dir, 'light mode image.png'))
                    logger.info("Overwrote light mode image.png with WhatsApp_light_mode_2.jpg from API init")
                for file_name in os.listdir(src_dir):
                    if file_name.endswith(('.mp3', '.svg', '.png', '.jpg', '.jpeg')):
                        src_file = os.path.join(src_dir, file_name)
                        dest_file = os.path.join(frontend_assets_dir, file_name)
                        if not os.path.exists(dest_file):
                            shutil.copy2(src_file, dest_file)
                            logger.info(f"Copied {file_name} to frontend/assets/ from API init")
        except Exception as e:
            logger.error(f"Failed to copy mp3 assets from API init: {e}")

        self._session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._session_created_at = datetime.now().strftime("%Y-%m-%d %I:%M:%S %p")
        self._providers = ["Gemini", "DeepSeek", "OpenAI", "Anthropic", "Perplexity", "Grok"]
        self._current_provider = "Gemini"
        self._chat_instances = {}
        
        # Skill 2.8 — Initialize SkillLoader
        self.skill_loader = None
        if _SKILL_LOADER_AVAILABLE:
            try:
                self.skill_loader = SkillLoader()
                self.skill_loader.load_plugins()
                logger.info(f"Initialized SkillLoader with {len(self.skill_loader.list_plugins_metadata())} plugins")
            except Exception as err:
                logger.error(f"Failed to initialize SkillLoader: {err}")

        # Skill 2.1 — Initialize Local RAG Engine (tenant-scoped DB on ACA)
        self.rag_engine = (
            LocalRAGEngine(tenant_key=self._tenant_key) if _RAG_ENGINE_AVAILABLE else None
        )
        self._rag_sessions_backfilled = False

        # Skills 2.2 - 2.7 — Initialize Core Feature Processors
        self.sandbox_runner = SandboxRunner() if _CORE_FEATURES_AVAILABLE else None
        self.web_agent = WebAgent() if _CORE_FEATURES_AVAILABLE else None
        self.mcp_gateway = MCPGateway() if _CORE_FEATURES_AVAILABLE else None
        self.voice_clone_manager = VoiceCloneManager() if _CORE_FEATURES_AVAILABLE else None
        self.plotly_service = PlotlyService() if _CORE_FEATURES_AVAILABLE else None

        # Load custom AI groups (tenant-scoped when running as an ACA session)
        self._groups = {}
        groups_file = self._groups_file_path()
        if os.path.exists(groups_file):
            try:
                with open(groups_file, "r", encoding="utf-8") as f:
                    self._groups = json.load(f)
                for group_id in self._groups:
                    if group_id not in self._providers:
                        self._providers.append(group_id)
            except Exception as e:
                logger.error(f"Error loading custom groups: {e}")

        # Each provider/group has its own separate history
        self._history = {p: [] for p in self._providers}
        self._token_totals = {p: 0 for p in self._providers}
        self._cost_totals = {p: 0.0 for p in self._providers}
        self._lifetime_spend_lock = threading.Lock()
        self._lifetime_cost_usd = 0.0
        self._last_budget_alert_level = "ok"
        self._load_lifetime_spend()
        self._model_sessions = {}

        try:
            self._user_name = get_runtime_user_name()
            set_runtime_user_name(self._user_name)
        except Exception:
            self._user_name = get_user_display_name()

        # Load environment variables to init default models (IGNITE_ENV aware).
        try:
            load_environment(app_dir)
        except Exception:
            env_path = os.path.join(app_dir, ".env")
            load_dotenv(dotenv_path=env_path, override=True)

        self._models = {
            "Gemini": [
                m.strip()
                for m in os.getenv(
                    "GEMINI_AVAILABLE_MODELS",
                    "gemini-3.1-flash-lite,gemini-3.5-flash-lite,gemini-3.5-flash,gemini-3.1-pro-preview",
                ).split(",")
                if m.strip()
            ],
            "DeepSeek": [
                m.strip()
                for m in os.getenv(
                    "DEEPSEEK_AVAILABLE_MODELS",
                    "deepseek-v4-pro,deepseek-v4-flash",
                ).split(",")
                if m.strip()
            ],
            "OpenAI": [
                m.strip()
                for m in os.getenv(
                    "OPENAI_AVAILABLE_MODELS",
                    OPENAI_AVAILABLE_MODELS_DEFAULT,
                ).split(",")
                if m.strip()
            ],
            "Anthropic": [
                m.strip()
                for m in os.getenv(
                    "ANTHROPIC_AVAILABLE_MODELS",
                    "claude-fable-5,claude-opus-5,claude-opus-4-8,claude-opus-4-6,claude-haiku-4-5-20251001",
                ).split(",")
                if m.strip()
            ],
            "Perplexity": [
                m.strip()
                for m in os.getenv(
                    "PERPLEXITY_AVAILABLE_MODELS",
                    "sonar,sonar-pro,sonar-reasoning",
                ).split(",")
                if m.strip()
            ],
            "Grok": [
                m.strip()
                for m in os.getenv(
                    "GROK_AVAILABLE_MODELS",
                    "grok-4.3,grok-4.5,grok-4.20-0309-reasoning,grok-4.20-0309-non-reasoning",
                ).split(",")
                if m.strip()
            ],
        }

        # Image/video (imagine-*) and other media models stay out of the picker;
        # those flows are handled internally by the app.
        def _is_grok_text_model(model_id: str) -> bool:
            mid = (model_id or "").strip().lower()
            if not mid.startswith("grok"):
                return False
            blocked_tokens = (
                "imagine",
                "image",
                "video",
                "tts",
                "voice",
                "audio",
                "speech",
                "embedding",
                "whisper",
            )
            return not any(token in mid for token in blocked_tokens)

        self._models["Grok"] = [
            m for m in self._models["Grok"] if _is_grok_text_model(m)
        ] or [
            "grok-4.3",
            "grok-4.5",
            "grok-4.20-0309-reasoning",
            "grok-4.20-0309-non-reasoning",
        ]

        # Dynamically refresh Grok text/chat models if an API key is present.
        grok_key = os.getenv("GROK_API_KEY", "")
        if grok_key:
            def _fetch_grok_models():
                try:
                    resp = requests.get(
                        f"{GROK_BASE_URL}/models",
                        headers={"Authorization": f"Bearer {grok_key}"},
                        timeout=5,
                    )
                    if resp.status_code == 200:
                        fetched = [
                            m["id"]
                            for m in resp.json().get("data", [])
                            if _is_grok_text_model(m.get("id", ""))
                        ]
                        if fetched:
                            self._models["Grok"] = sorted(fetched)
                except Exception as e:
                    logger.error(f"Failed to fetch Grok models: {e}")
            threading.Thread(target=_fetch_grok_models, daemon=True).start()

        self._current_model = {
            "Gemini": os.getenv("GEMINI_MODEL_VERSION", self._models["Gemini"][0]),
            "DeepSeek": os.getenv("DEEPSEEK_MODEL_VERSION", self._models["DeepSeek"][0]),
            "OpenAI": os.getenv("OPENAI_MODEL_VERSION", self._models["OpenAI"][0]),
            "Anthropic": os.getenv("ANTHROPIC_MODEL_VERSION", self._models["Anthropic"][0]),
            "Perplexity": os.getenv("PERPLEXITY_MODEL_VERSION", self._models["Perplexity"][0]),
            "Grok": os.getenv("GROK_MODEL_VERSION", self._models["Grok"][0])
        }
        
        # Register custom group structures in current models
        for group_id in self._groups:
            self._current_model[group_id] = "Group"
            self._models[group_id] = ["Group"]

        # Request tracking for async operations (short critical sections only).
        self._requests = {}
        self._request_lock = threading.Lock()
        # provider -> active request_id (single-flight + cancel support)
        self._active_request_by_provider = {}
        self._window = None

        # One-time startup: migrate group welcomes, activate Gemini, warm other chats.
        # (Must NOT run from _append_history_message — that caused parallel-chat storms.)
        self._migrate_group_welcome_messages()
        self._activate_session("Gemini", self._current_model["Gemini"])

        is_testing = "pytest" in sys.modules or "PYTEST_CURRENT_TEST" in os.environ
        if not is_testing:
            def warm_up_chats():
                time.sleep(1.0)
                for prov in self._providers:
                    if prov != "Gemini" and not prov.startswith("group_"):
                        try:
                            model = self._current_model.get(prov)
                            if model and model != "Group":
                                self._activate_session(prov, model)
                        except Exception as e:
                            try:
                                logger.warning(f"Background warm-up failed for {prov}: {e}")
                            except Exception:
                                pass

            threading.Thread(target=warm_up_chats, daemon=True).start()

    def _provider_lock(self, provider: str) -> threading.RLock:
        """Return a re-entrant lock scoped to one conversation/provider."""
        key = provider or "_unknown"
        with self._provider_locks_guard:
            lock = self._provider_locks.get(key)
            if lock is None:
                lock = threading.RLock()
                self._provider_locks[key] = lock
            return lock

    def _append_history_message(self, provider: str, message: dict, *, save: bool = True) -> None:
        """Thread-safe history append for parallel multi-conversation use."""
        with self._provider_lock(provider):
            if provider not in self._history:
                self._history[provider] = []
            self._history[provider].append(message)
            if save:
                # Re-entrant: save uses the same per-provider RLock.
                self._save_conversation_history(provider)

    # Function to set the window
    def set_window(self, window):
        self._window = window

    # Function to set the theme window size
    def set_theme_window_size(self, theme):
        # Keep window size preserved when theme is changed
        return {"status": "success"}

    # Function to open an external link
    def open_external_link(self, url):
        try:
            if url.startswith("http://") or url.startswith("https://"):
                webbrowser.open(url)
                return {"status": "success"}
            return {"status": "error", "message": "Invalid URL protocol"}
        except Exception as e:
            logger.error(f"Failed to open external link {url}: {e}")
            return {"status": "error", "message": str(e)}

    def _tenant_log_root(self) -> str:
        """Root log directory; tenant-scoped under ACA multi-user sessions."""
        tenant = _safe_tenant_segment(getattr(self, "_tenant_key", None))
        if tenant:
            return os.path.join(DATA_DIR, "log", "tenants", tenant)
        return os.path.join(DATA_DIR, "log")

    def _provider_log_dir(self, provider: str, *parts: str) -> str:
        prov_lower = "groups" if provider.startswith("group_") else provider.lower()
        return os.path.join(self._tenant_log_root(), prov_lower, *parts)

    def _groups_file_path(self) -> str:
        return os.path.join(self._tenant_log_root(), "groups.json")

    def _lifetime_spend_path(self) -> str:
        return os.path.join(self._tenant_log_root(), "lifetime_spend.json")

    def _load_lifetime_spend(self) -> None:
        """Lifetime estimated spend survives clear/restart; session cost still resets."""
        if not hasattr(self, "_lifetime_spend_lock") or self._lifetime_spend_lock is None:
            self._lifetime_spend_lock = threading.Lock()
        path = self._lifetime_spend_path()
        spent = 0.0
        last_level = "ok"
        try:
            if os.path.isfile(path):
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    spent = float(data.get("lifetime_cost_usd") or 0.0)
                    last = str(data.get("last_alert_level") or "ok").strip().lower()
                    if last in ("ok", "warn", "critical", "exhausted", "disabled"):
                        last_level = last
        except Exception as e:
            logger.warning(f"Failed to load lifetime spend ledger: {e}")
        self._lifetime_cost_usd = round(max(0.0, spent), 6)
        self._last_budget_alert_level = last_level

    def _persist_lifetime_spend(self) -> None:
        path = self._lifetime_spend_path()
        payload = {
            "lifetime_cost_usd": round(float(getattr(self, "_lifetime_cost_usd", 0.0) or 0.0), 6),
            "last_alert_level": str(getattr(self, "_last_budget_alert_level", "ok") or "ok"),
        }
        try:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            tmp_path = f"{path}.tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, path)
        except Exception as e:
            logger.error(f"Failed to persist lifetime spend ledger: {e}")

    def _add_lifetime_spend(self, delta: float) -> None:
        """Add a positive cost delta to the lifetime ledger (never subtract on clear)."""
        try:
            amount = float(delta or 0.0)
        except (TypeError, ValueError):
            return
        if amount <= 0:
            return
        if not hasattr(self, "_lifetime_spend_lock") or self._lifetime_spend_lock is None:
            self._lifetime_spend_lock = threading.Lock()
        with self._lifetime_spend_lock:
            current = float(getattr(self, "_lifetime_cost_usd", 0.0) or 0.0)
            self._lifetime_cost_usd = round(current + amount, 6)
            self._persist_lifetime_spend()

    def _session_id_prefix(self, provider: str) -> str:
        return f"{provider}_"

    def _is_valid_session_id(self, provider: str, session_id, model: str | None = None) -> bool:
        if not session_id:
            return False
        sid = str(session_id)
        if model:
            return sid.startswith(f"{provider}_{model}_")
        return sid.startswith(self._session_id_prefix(provider))

    def _new_session_id(self, provider: str, model: str | None = None) -> str:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        tenant = _safe_tenant_segment(getattr(self, "_tenant_key", None))
        suffix = f"_{tenant[:8]}" if tenant else ""
        return f"{provider}_{model or 'default'}_{timestamp}{suffix}"

    def _resolve_provider_session_id(self, provider: str, model: str | None = None, candidate=None) -> str:
        """Return a session_id that always belongs to this provider+model (never cross-contaminated)."""
        selected_model = model if model is not None else self._current_model.get(provider)
        if self._is_valid_session_id(provider, candidate, selected_model):
            return str(candidate)
        if selected_model:
            cached = self._model_sessions.get((provider, selected_model), {})
            cached_id = cached.get("session_id")
            if self._is_valid_session_id(provider, cached_id, selected_model):
                return str(cached_id)
        # Do not fall back to global _session_id across models — mint a fresh id.
        return self._new_session_id(provider, selected_model)

    def _snapshot_model_session(self, provider: str, model: str):
        """Persist in-memory session state for provider+model without leaking foreign session_ids."""
        if not model:
            return
        # Groups use the synthetic model name "Group" and must still snapshot.
        existing = self._model_sessions.get((provider, model), {})
        session_id = self._resolve_provider_session_id(
            provider, model, candidate=existing.get("session_id")
        )
        created_at = existing.get("session_created_at") or getattr(
            self, "_session_created_at", datetime.now().strftime("%Y-%m-%d %I:%M:%S %p")
        )
        self._model_sessions[(provider, model)] = {
            "history": self._history.get(provider, []),
            "token_total": self._token_totals.get(provider, 0),
            "session_id": session_id,
            "session_created_at": created_at,
            "chat_instance": self._chat_instances.get(provider),
        }

    def _find_latest_session_file(self, provider, model):
        """Return absolute path of newest session JSON for provider+model, or None.

        Falls back to the newest session for the provider regardless of model so
        history survives default-model changes across deploys.
        """
        try:
            log_dir = self._provider_log_dir(provider, "Sessions")
            if not os.path.isdir(log_dir):
                return None
            exact_prefix = f"{provider}_{model}_"
            provider_prefix = f"{provider}_"
            exact_candidates = []
            provider_candidates = []
            for name in os.listdir(log_dir):
                if not name.endswith(".json"):
                    continue
                path = os.path.join(log_dir, name)
                if name.startswith(exact_prefix):
                    exact_candidates.append((os.path.getmtime(path), path))
                elif name.startswith(provider_prefix):
                    provider_candidates.append((os.path.getmtime(path), path))
            candidates = exact_candidates or provider_candidates
            if not candidates:
                return None
            # Tie-break by path/name so same-second mtimes (Windows/temp FS) still
            # prefer the lexicographically newest session id (…_YYYYMMDD_HHMMSS).
            candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
            if not exact_candidates:
                logger.info(
                    "No session for %s/%s; falling back to newest provider session %s",
                    provider,
                    model,
                    os.path.basename(candidates[0][1]),
                )
            return candidates[0][1]
        except Exception as err:
            logger.warning(f"Failed scanning sessions for {provider}/{model}: {err}")
            return None

    def _load_session_from_disk(self, provider, model):
        """Load latest session for provider+model and rehydrate media paths."""
        path = self._find_latest_session_file(provider, model)
        if not path:
            return None
        try:
            with open(path, "r", encoding="utf-8") as session_file:
                data = json.load(session_file)
            messages = _rehydrate_media_paths(data.get("messages") or [])
            session_id = data.get("session_id") or os.path.splitext(os.path.basename(path))[0]
            if not self._is_valid_session_id(provider, session_id, model):
                session_id = os.path.splitext(os.path.basename(path))[0]
                if not self._is_valid_session_id(provider, session_id, model):
                    session_id = self._new_session_id(provider, model)
            return {
                "history": messages,
                "token_total": int(data.get("token_total") or 0),
                "session_id": session_id,
                "session_created_at": data.get("created_at")
                or datetime.now().strftime("%Y-%m-%d %I:%M:%S %p"),
            }
        except Exception as err:
            logger.warning(f"Failed loading session {path}: {err}")
            return None

    # Function to save conversation history
    def _save_conversation_history(self, provider):
        try:
            # Per-provider lock: Group disk I/O must not block OpenAI/Gemini saves.
            with self._provider_lock(provider):
                # Prune local memory history to a maximum of 200 messages to prevent JSON file bloat
                if provider in self._history and len(self._history[provider]) > 200:
                    self._history[provider] = self._history[provider][-200:]

                selected_model = self._current_model.get(provider)
                cached_id = None
                if selected_model:
                    cached_id = self._model_sessions.get((provider, selected_model), {}).get("session_id")
                session_id = self._resolve_provider_session_id(
                    provider, selected_model, candidate=cached_id
                )
                # Keep the active pointer aligned only when saving the current provider.
                if provider == getattr(self, "_current_provider", None):
                    self._session_id = session_id

                if provider.startswith("group_"):
                    prov_lower = "groups"
                else:
                    prov_lower = provider.lower()
                log_dir = self._provider_log_dir(provider, "Sessions")
                os.makedirs(log_dir, exist_ok=True)

                # Sync session state with cache to prevent loss during provider switches
                if selected_model:
                    session_key = (provider, selected_model)
                    if session_key not in self._model_sessions:
                        self._model_sessions[session_key] = {
                            "history": self._history[provider],
                            "token_total": self._token_totals.get(provider, 0),
                            "session_id": session_id,
                            "session_created_at": self._session_created_at if hasattr(self, "_session_created_at") else datetime.now().strftime("%Y-%m-%d %I:%M:%S %p"),
                            "chat_instance": self._chat_instances.get(provider)
                        }
                    else:
                        self._model_sessions[session_key]["history"] = self._history[provider]
                        self._model_sessions[session_key]["token_total"] = self._token_totals.get(provider, 0)
                        self._model_sessions[session_key]["session_id"] = session_id
                        if hasattr(self, "_session_created_at"):
                            self._model_sessions[session_key]["session_created_at"] = self._session_created_at

                clean_history = _clean_history_for_saving(
                    self._history[provider],
                    provider=provider,
                    session_id=session_id,
                    tenant_key=getattr(self, "_tenant_key", None),
                )
                # Mirror persisted paths back into in-memory history for later reloads this session.
                for live_msg, clean_msg in zip(self._history[provider], clean_history):
                    if clean_msg.get("image_path") and not live_msg.get("image_path"):
                        live_msg["image_path"] = clean_msg["image_path"]
                    if clean_msg.get("audio_path") and not live_msg.get("audio_path"):
                        live_msg["audio_path"] = clean_msg["audio_path"]

                if not hasattr(self, "_session_created_at"):
                    self._session_created_at = datetime.now().strftime("%Y-%m-%d %I:%M:%S %p")

                selected_model = self._current_model.get(provider, "")

                data = {
                    "session_id": session_id,
                    "provider": provider,
                    "model": selected_model,
                    "created_at": self._session_created_at,
                    "updated_at": datetime.now().strftime("%Y-%m-%d %I:%M:%S %p"),
                    "token_total": self._token_totals.get(provider, 0),
                    "messages": clean_history
                }

                filename = f"{session_id}.json"
                filepath = os.path.join(log_dir, filename)
                tmp_path = filepath + ".tmp"
                with open(tmp_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                os.replace(tmp_path, filepath)
                logger.info(f"Saved conversation history for {provider} to {filepath}")
                # Runtime persistence is local JSON only. Optional SQL Server / Kusto
                # exporters live under app/Databases/ and can be run offline via
                # LogExportCoordinator (CLI), but are not hooked into the live API path.

        except Exception as e:
            logger.error(f"Error saving conversation history for {provider}: {e}", exc_info=True)

    # ---------- Skill 2.8 — Plugin Store API endpoints ----------
    def get_available_plugins(self):
        """Return list of active plugins metadata to PyWebView frontend."""
        if not self.skill_loader:
            return []
        try:
            metas = self.skill_loader.list_plugins_metadata()
            return [m.model_dump() for m in metas]
        except Exception as err:
            logger.error(f"Error fetching plugin metadata list: {err}")
            return []

    def reload_plugins(self):
        """Hot-reload all dynamic plugins from app/plugins/ directory."""
        if not self.skill_loader:
            return {"success": False, "error": "SkillLoader not available"}
        try:
            self.skill_loader.reload_plugins()
            metas = self.skill_loader.list_plugins_metadata()
            return {"success": True, "count": len(metas), "plugins": [m.model_dump() for m in metas]}
        except Exception as err:
            logger.error(f"Error hot-reloading plugins: {err}")
            return {"success": False, "error": str(err)}

    def execute_plugin(self, name, user_input=""):
        """Execute a specific plugin by name with provided input parameters."""
        if not self.skill_loader:
            return {"success": False, "error": "SkillLoader not available"}
        try:
            res = self.skill_loader.execute_plugin(name, user_input)
            return res.model_dump()
        except Exception as err:
            logger.error(f"Error executing plugin '{name}': {err}")
            return {"success": False, "error": str(err)}

    # ---------- Skills 2.2 - 2.7 — Core Feature API Endpoints ----------
    def execute_sandbox_code(self, code, timeout_seconds=10.0):
        """Skill 2.2 — Live Code Sandbox: execute Python snippet in isolated subprocess."""
        if not self.sandbox_runner:
            return {"success": False, "error": "SandboxRunner not available"}
        res = self.sandbox_runner.execute_code(code, timeout_seconds=timeout_seconds)
        return res.model_dump()

    def scrape_web_url(self, url, extract_links=True, max_length=5000):
        """Skill 2.3 — Web Automation Agent: scrape and parse dynamic page HTML."""
        if not self.web_agent:
            return {"success": False, "error": "WebAgent not available"}
        res = self.web_agent.scrape_url(url, extract_links=extract_links, max_length=max_length)
        return res.model_dump()

    def handle_mcp_request(self, request_payload):
        """Skill 2.4 — Personal MCP Gateway: process JSON-RPC tool requests."""
        if not self.mcp_gateway:
            return {"jsonrpc": "2.0", "id": "null", "error": {"code": -32603, "message": "MCP Gateway not available"}}
        res = self.mcp_gateway.handle_request(request_payload)
        return res.model_dump()

    def synthesize_voice_clone(self, profile_id, text):
        """Skill 2.5 — Instant Voice Cloning: synthesize custom voice audio."""
        if not self.voice_clone_manager:
            return {"success": False, "error": "VoiceCloneManager not available"}
        res = self.voice_clone_manager.synthesize_voice(profile_id, text)
        return res.model_dump()

    def generate_plotly_chart(
        self,
        labels,
        values,
        title="Chart",
        chart_type: Literal["bar", "line", "pie", "scatter"] = "bar",
        series_name="Values",
    ):
        """Skill 2.7 — Interactive Dashboards: generate Plotly HTML widget."""
        if not self.plotly_service:
            return {"success": False, "error": "PlotlyService not available"}
        res = self.plotly_service.generate_chart_html(
            labels=labels, values=values, title=title, chart_type=chart_type, series_name=series_name
        )
        return res.model_dump()

    # ---------- Skill 2.1 — Persistent Memory (Local RAG) API Endpoints ----------
    def add_rag_document(self, doc_id, text, metadata=None):
        """Skill 2.1 — Persistent Memory: Index a document in local RAG vector store."""
        if not self.rag_engine:
            return {"success": False, "error": "LocalRAGEngine not available"}
        success = self.rag_engine.index_document(doc_id, text, metadata or {})
        return {"success": success, "doc_id": doc_id}

    def search_rag_memory(self, query, top_k=3):
        """Skill 2.1 — Persistent Memory: Search relevant memories by vector similarity."""
        if not self.rag_engine:
            return []
        results = self.rag_engine.search_relevant_context(query, top_k=top_k)
        return [r.model_dump() for r in results]

    def clear_rag_memory(self):
        """Skill 2.1 — Persistent Memory: Clear all indexed RAG memories."""
        if not self.rag_engine:
            return {"success": False, "error": "LocalRAGEngine not available"}
        success = self.rag_engine.clear_memory()
        return {"success": success}

    # Function to initialize the chat instance    
    def _init_chat(self, provider):
        model = self._current_model.get(provider)
        if not model or model == "Group":
            return

        with self._init_lock:
            # Check if another thread initialized it while we waited for the lock
            existing = self._chat_instances.get(provider)
            if existing and getattr(existing, 'model_version', None) == model:
                return

            try:
                if provider == "Gemini":
                    self._chat_instances[provider] = GeminiChat(model_version=model)
                elif provider == "DeepSeek":
                    self._chat_instances[provider] = DeepSeekChat(model_version=model)
                elif provider == "OpenAI":
                    self._chat_instances[provider] = OpenAIChat(model_version=model)
                elif provider == "Anthropic":
                    self._chat_instances[provider] = AnthropicChat(model_version=model)
                elif provider == "Perplexity":
                    self._chat_instances[provider] = PerplexityChat(model_version=model)
                elif provider == "Grok":
                    self._chat_instances[provider] = GrokChat(model_version=model)
                
                # Media guidelines are always safe. Document export guidelines are injected
                # only when the user explicitly asks to generate a document (see send paths),
                # so analysis prompts like "Analiza este ppt" are not biased toward PPTX export.
                chat = self._chat_instances.get(provider)
                if chat:
                    # Propagate tenant so STT/search caches stay isolated per ACA session.
                    chat._tenant_key = getattr(self, "_tenant_key", None)
                    if hasattr(chat, 'inject_media_guidelines'):
                        chat.inject_media_guidelines()
                
                logger.info(f"Initialized {provider} with model {model} (Injected Media Instructions)")
                self._provider_init_errors.pop(provider, None)
            except Exception as e:
                logger.error(f"Failed to initialize {provider}: {e}", exc_info=True)
                self._chat_instances.pop(provider, None)
                self._provider_init_errors[provider] = str(e)

    # Function to get the initial state
    def get_initial_state(self):
        """Called by frontend on load to populate UI"""
        provider = self._current_provider

        # Ensure providers (including groups) restore latest disk sessions so
        # sidebar last_messages / unread previews are meaningful after restart.
        for p in self._providers:
            model = self._current_model.get(p) or ("Group" if p.startswith("group_") else None)
            if not model:
                continue
            if (p, model) not in self._model_sessions:
                try:
                    self._activate_session(p, model)
                except Exception as err:
                    logger.warning(f"Session restore for {p} failed: {err}")

        last_messages = {}
        for p in self._providers:
            history = self._history.get(p, [])
            if history:
                last_msg = history[-1]
                preview = last_msg.get("content", "")
                if isinstance(last_msg.get("image_data"), str) and last_msg["image_data"].startswith("data:"):
                    preview = preview or "🖼️ Image"
                last_messages[p] = {
                    "content": preview,
                    "timestamp": last_msg.get("timestamp", ""),
                    "iso_timestamp": last_msg.get("iso_timestamp", ""),
                    "date": last_msg.get("date", ""),
                    "role": last_msg.get("role", "")
                }
            else:
                last_messages[p] = None

        return {
            "user_name": self._user_name,
            "providers": self._providers,
            "current_provider": provider,
            "models": self._models,
            "current_model": self._current_model,
            "avatars": self._get_all_avatars(),
            "bg_image_dark": self._get_avatar_content(os.path.join(app_dir, "assets", "WhatsApp_dark_mode.png")),
            "bg_image_light": self._get_avatar_content(os.path.join(app_dir, "assets", "WhatsApp_light_mode.png")),
            "history": _clean_history_for_frontend(
                _rehydrate_media_paths(self._history.get(provider, []))
            ),
            "token_totals": self._token_totals,
            "system_language": USER_SYSTEM_LANGUAGE,
            "last_messages": last_messages,
            "groups": self._groups,
            "provider_init_errors": dict(self._provider_init_errors),
            "generation_poll_timeout_ms": _generation_poll_timeout_ms(),
            "document_poll_timeout_ms": _document_poll_timeout_ms(),
        }

    # Function to get the avatar content
    def _get_avatar_content(self, path):
        if not path or path == "None":
            return ""
        if not os.path.exists(path):
            filename = os.path.basename(path)
            candidate_paths = [
                os.path.join(app_dir, "assets", filename),
                os.path.join(app_dir, "_internal", "assets", filename),
                os.path.join(app_dir, "frontend", "assets", filename),
                os.path.join(app_dir, "_internal", "frontend", "assets", filename),
                os.path.join(code_dir, "assets", filename),
                os.path.join(code_dir, "frontend", "assets", filename),
            ]
            if getattr(sys, 'frozen', False):
                _exe = os.path.dirname(sys.executable)
                candidate_paths.extend([
                    os.path.join(_exe, "assets", filename),
                    os.path.join(_exe, "_internal", "assets", filename),
                    os.path.join(_exe, "frontend", "assets", filename),
                    os.path.join(_exe, "_internal", "frontend", "assets", filename),
                ])
                if hasattr(sys, '_MEIPASS'):
                    candidate_paths.append(os.path.join(sys._MEIPASS, "assets", filename))
                    candidate_paths.append(os.path.join(sys._MEIPASS, "frontend", "assets", filename))
            found_path = next((p for p in candidate_paths if os.path.exists(p)), None)
            if found_path:
                path = found_path
            else:
                return ""
        try:
            if path.lower().endswith(".svg"):
                with open(path, "r", encoding="utf-8") as f:
                    return f.read()
            else:
                with open(path, "rb") as f:
                    b64 = base64.b64encode(f.read()).decode()
                    ext = path.split('.')[-1].lower()
                    mime = f"image/{ext}" if ext in ['png', 'jpg', 'jpeg', 'gif', 'webp'] else "image/png"
                    return f"data:{mime};base64,{b64}"
        except Exception as e:
            logger.error(f"Error reading avatar {path}: {e}")
            return ""

    # Function to get all avatars
    def _get_all_avatars(self):
        user_avatar = self._get_avatar_content(USER_PROFILE_PICTURE_PATH)
        if not user_avatar:
            # Elegant SVG profile avatar fallback when host OS has no account picture
            user_avatar = '<svg height="1em" style="flex:none;line-height:1" viewBox="0 0 24 24" width="1em" xmlns="http://www.w3.org/2000/svg"><circle cx="12" cy="8" r="4.5" fill="#00a884"/><path d="M12 14c-4.42 0-8 2.24-8 5v1h16v-1c0-2.76-3.58-5-8-5z" fill="#00a884"/></svg>'
        return {
            "user": user_avatar,
            "Gemini": self._get_avatar_content(GEMINI_PROFILE_PICTURE_PATH),
            "DeepSeek": self._get_avatar_content(DEEPSEEK_PROFILE_PICTURE_PATH),
            "OpenAI": self._get_avatar_content(OPENAI_PROFILE_PICTURE_PATH),
            "Anthropic": self._get_avatar_content(ANTHROPIC_PROFILE_PICTURE_PATH),
            "Perplexity": self._get_avatar_content(PERPLEXITY_PROFILE_PICTURE_PATH),
            "Grok": self._get_avatar_content(GROK_PROFILE_PICTURE_PATH)
        }

    # Function to activate the session
    def _activate_session(self, provider, model):
        session_key = (provider, model)
        if session_key not in self._model_sessions:
            loaded = self._load_session_from_disk(provider, model)
            if loaded and loaded.get("history") is not None:
                logger.info(
                    f"Restored session for {provider}/{model}: "
                    f"{loaded['session_id']} ({len(loaded['history'])} messages)"
                )
                self._model_sessions[session_key] = {
                    "history": loaded["history"],
                    "token_total": loaded["token_total"],
                    "session_id": loaded["session_id"],
                    "session_created_at": loaded["session_created_at"],
                    "chat_instance": None,
                }
            else:
                session_id = self._new_session_id(provider, model)
                self._model_sessions[session_key] = {
                    "history": [],
                    "token_total": 0,
                    "session_id": session_id,
                    "session_created_at": datetime.now().strftime("%Y-%m-%d %I:%M:%S %p"),
                    "chat_instance": None
                }

        state = self._model_sessions[session_key]
        # Reject contaminated session ids restored from older buggy saves.
        if not self._is_valid_session_id(provider, state.get("session_id"), model):
            state["session_id"] = self._new_session_id(provider, model)
        # Ensure media paths are hydrated for UI whenever we activate.
        state["history"] = _rehydrate_media_paths(state.get("history") or [])
        self._history[provider] = state["history"]
        self._token_totals[provider] = state["token_total"]
        self._session_id = state["session_id"]
        self._session_created_at = state["session_created_at"]
        # Rebuild USD totals from restored messages so the sidebar matches this session.
        self._recalculate_token_totals(provider)

        if state["chat_instance"]:
            self._chat_instances[provider] = state["chat_instance"]
            chat = state["chat_instance"]
            if chat and hasattr(chat, 'remove_group_discussion_guidelines'):
                chat.remove_group_discussion_guidelines()
        else:
            self._init_chat(provider)
            state["chat_instance"] = self._chat_instances.get(provider)

    # Function to set the provider    
    def set_provider(self, provider):
        """Switch the UI-focused provider without cancelling other in-flight chats.

        Parallel generations are keyed by explicit provider on ``send_message_async``;
        switching only changes which history the desktop shows next.
        """
        if provider in self._providers:
            old_provider = self._current_provider
            # Snapshot previous session, but never touch other providers' workers.
            if old_provider != provider:
                old_model = self._current_model.get(old_provider)
                if old_model and old_model != "Group":
                    try:
                        self._snapshot_model_session(old_provider, old_model)
                    except Exception as snap_err:
                        logger.warning(
                            "Snapshot on switch from %s failed: %s",
                            old_provider,
                            snap_err,
                        )

            self._current_provider = provider
            new_model = self._current_model.get(provider)
            if provider.startswith("group_") and (not new_model or new_model == "Group"):
                new_model = "Group"
                self._current_model[provider] = "Group"
            if new_model:
                # Activate only the target conversation; background chats keep running.
                # Groups use model "Group" and must also restore from disk after restart.
                with self._provider_lock(provider):
                    self._activate_session(provider, new_model)

            init_error = self._provider_init_errors.get(provider)
            with self._provider_lock(provider):
                history_view = _clean_history_for_frontend(
                    _rehydrate_media_paths(list(self._history.get(provider, [])))
                )
            return {
                "status": "success",
                "history": history_view,
                "models": self._models,
                "current_model": self._current_model,
                "token_totals": self._token_totals,
                "provider_init_error": init_error,
            }
        return {"status": "error", "message": "Invalid provider"}

    # Function to set the model
    def set_model(self, provider, model):
        if provider in self._providers:
            old_model = self._current_model.get(provider)
            if old_model == model:
                return {
                    "status": "success",
                    "history": _clean_history_for_frontend(self._history[provider]),
                    "token_total": self._token_totals.get(provider, 0)
                }
            
            # Save the current history to the old session file one last time before clearing/switching
            if provider in self._history and self._history[provider]:
                self._save_conversation_history(provider)
            
            # Save the current state to the old model session key
            if old_model:
                self._snapshot_model_session(provider, old_model)
            
            # Set the new model and activate the session
            self._current_model[provider] = model
            self._activate_session(provider, model)
            
            return {
                "status": "success",
                "history": _clean_history_for_frontend(self._history[provider]),
                "token_total": self._token_totals.get(provider, 0)
            }
        return {"status": "error"}

    def set_participant_model(self, group_id: str, participant: str, model: str):
        """Switch a participant's active model inside a group chat without clearing history."""
        if not group_id.startswith("group_"):
            return {"status": "error", "message": "Not a group provider"}
        if participant not in self._providers:
            return {"status": "error", "message": f"Unknown participant: {participant}"}
        if model not in (self._models.get(participant) or []):
            return {"status": "error", "message": f"Unknown model {model} for {participant}"}

        old_model = self._current_model.get(participant)
        if old_model == model:
            return {"status": "success", "message": "No change"}

        # Store old session without contaminating it with the active group session_id
        if old_model:
            self._snapshot_model_session(participant, old_model)

        # Switch to new model — reinitialise the chat instance only (keep history)
        self._current_model[participant] = model
        if participant in self._chat_instances and hasattr(self._chat_instances[participant], 'set_model'):
            self._chat_instances[participant].set_model(model)
        else:
            # Re-initialise with new model
            self._init_chat(participant)

        return {
            "status": "success",
            "participant": participant,
            "model": model
        }

    # Function to clear the history    
    def clear_history(self, provider=None):
        """Clear only the current provider's history (mirrors Streamlit's per-provider clear)."""
        p = provider or self._current_provider
        
        # Save the current history to the old session file one last time before clearing
        if p in self._history and self._history[p]:
            self._save_conversation_history(p)
            
        # Reset the session ID and session creation time to start a new session
        current_model = self._current_model.get(p, "default")
        self._session_id = self._new_session_id(p, current_model)
        self._session_created_at = datetime.now().strftime("%Y-%m-%d %I:%M:%S %p")
        
        # Clear the history, token totals, and USD cost for this provider only.
        # Local RAG stays intact so a new chat can still recall older conversations.
        if p in self._history:
            self._history[p] = []
        if p in self._token_totals:
            self._token_totals[p] = 0
        self._cost_totals[p] = 0.0
        self._recalculate_token_totals(p)
            
        # Update the saved model session
        current_model = self._current_model.get(p)
        if current_model:
            self._model_sessions[(p, current_model)] = {
                "history": self._history[p],
                "token_total": 0,
                "session_id": self._session_id,
                "session_created_at": self._session_created_at,
                "chat_instance": self._chat_instances.get(p)
            }

        # Skill §12.2: persist empty new session immediately so mtime restore
        # cannot revive the archived chat after restart / remount.
        self._save_conversation_history(p)

        # Hard guarantee: active session file exists, is empty, and wins find_latest
        # even when the filesystem collapses mtimes to the same second.
        try:
            log_dir = self._provider_log_dir(p, "Sessions")
            new_path = os.path.join(log_dir, f"{self._session_id}.json")
            if os.path.isfile(new_path):
                # Bump mtime above any same-second siblings.
                now = time.time() + 1.0
                os.utime(new_path, (now, now))
        except Exception as touch_err:
            logger.debug("Could not bump mtime for cleared session file: %s", touch_err)
            
        return {"status": "success"}

    # Function to create a custom AI group
    def create_group(self, name, participants):
        try:
            group_id = f"group_{int(time.time())}"
            self._groups[group_id] = {
                "name": name,
                "participants": participants
            }
            
            # Save groups to log/groups.json (tenant-scoped on ACA)
            groups_file = self._groups_file_path()
            os.makedirs(os.path.dirname(groups_file), exist_ok=True)
            with open(groups_file, "w", encoding="utf-8") as f:
                json.dump(self._groups, f, ensure_ascii=False, indent=2)
                
            # Register group as provider
            if group_id not in self._providers:
                self._providers.append(group_id)
            self._history[group_id] = []
            self._token_totals[group_id] = 0
            self._cost_totals[group_id] = 0.0
            self._current_model[group_id] = "Group"
            self._models[group_id] = ["Group"]
            
            logger.info(f"Created group chat {name} ({group_id}) with participants {participants}")
            return {
                "status": "success",
                "group_id": group_id,
                "providers": self._providers,
                "groups": self._groups
            }
        except Exception as e:
            logger.error(f"Error creating group: {e}", exc_info=True)
            return {"status": "error", "message": str(e)}

    # Function to delete/exit a group chat
    def delete_group(self, group_id):
        try:
            if group_id in self._groups:
                del self._groups[group_id]
                
                # Save groups to log/groups.json (tenant-scoped on ACA)
                groups_file = self._groups_file_path()
                os.makedirs(os.path.dirname(groups_file), exist_ok=True)
                with open(groups_file, "w", encoding="utf-8") as f:
                    json.dump(self._groups, f, ensure_ascii=False, indent=2)
                    
                # Remove from providers and clear session mappings
                if group_id in self._providers:
                    self._providers.remove(group_id)
                if group_id in self._history:
                    del self._history[group_id]
                if group_id in self._token_totals:
                    del self._token_totals[group_id]
                if group_id in self._cost_totals:
                    del self._cost_totals[group_id]
                if group_id in self._current_model:
                    del self._current_model[group_id]
                if group_id in self._models:
                    del self._models[group_id]
                
                # Delete group session files (tenant-scoped on ACA)
                sess_dir = os.path.join(self._tenant_log_root(), "groups", "Sessions")
                if os.path.exists(sess_dir):
                    for filename in os.listdir(sess_dir):
                        if filename.startswith(group_id):
                            try:
                                os.remove(os.path.join(sess_dir, filename))
                            except Exception as rm_ex:
                                logger.error(f"Error removing group session file {filename}: {rm_ex}")
                                
                logger.info(f"Successfully deleted/exited group chat {group_id}")
                return {"status": "success", "providers": self._providers}
            return {"status": "error", "message": "Group not found"}
        except Exception as e:
            logger.error(f"Error exiting group {group_id}: {e}", exc_info=True)
            return {"status": "error", "message": str(e)}

    # Function to get the history
    def get_history(self, provider: str | None = None):
        p: str = provider if (provider and provider in self._providers) else self._current_provider
        return {"status": "success", "history": _clean_history_for_frontend(self._history.get(p, []))}

    # Function to get the token totals    
    def get_token_totals(self):
        return self._token_totals

    # Function to get the USD cost totals
    def get_cost_totals(self):
        return self._cost_totals

    # Function to get accumulated USD cost statistics per provider for Settings UI
    def get_accumulated_cost_stats(self, language=None):
        if not isinstance(language, str) or not language.strip():
            language = None
        stats = []
        grand_total_tokens = 0
        grand_total_cost = 0.0
        for p in self._providers:
            toks = self._token_totals.get(p, 0)
            cost = self._cost_totals.get(p, 0.0)
            grand_total_tokens += toks
            grand_total_cost += cost
            stats.append({
                "provider": p,
                "current_model": self._current_model.get(p, ""),
                "tokens": toks,
                "cost_usd": round(cost, 6)
            })
        cfg = _budget_config()
        budget = float(cfg["budget_usd"])
        spent = round(float(getattr(self, "_lifetime_cost_usd", 0.0) or 0.0), 6)
        remaining = max(0.0, budget - spent) if budget > 0 else None
        remaining_pct = (remaining / budget) if budget > 0 and remaining is not None else None
        level = _budget_alert_level(
            remaining if remaining is not None else 0.0,
            budget,
            cfg["warn_pct"],
            cfg["critical_pct"],
        )
        notify = False
        if not hasattr(self, "_lifetime_spend_lock") or self._lifetime_spend_lock is None:
            self._lifetime_spend_lock = threading.Lock()
        rank = {"disabled": 0, "ok": 0, "warn": 1, "critical": 2, "exhausted": 3}
        with self._lifetime_spend_lock:
            last = str(getattr(self, "_last_budget_alert_level", "ok") or "ok").strip().lower()
            if rank.get(level, 0) > rank.get(last, 0):
                notify = True
                self._last_budget_alert_level = level
                self._persist_lifetime_spend()
            elif level in ("ok", "disabled") and last not in ("ok", "disabled"):
                self._last_budget_alert_level = "ok"
                self._persist_lifetime_spend()
        chrome_lang = language or get_default_conversation_language()
        alert_message = ""
        if remaining is not None:
            alert_message = _budget_alert_chrome(level, remaining, budget, chrome_lang)
        return {
            "status": "success",
            "grand_total_tokens": grand_total_tokens,
            "grand_total_cost_usd": round(grand_total_cost, 6),
            "providers": stats,
            "budget_enabled": budget > 0,
            "budget_usd": round(budget, 6),
            "lifetime_cost_usd": spent,
            "remaining_usd": round(remaining, 6) if remaining is not None else None,
            "remaining_pct": round(remaining_pct, 4) if remaining_pct is not None else None,
            "alert_level": level,
            "budget_notify": notify,
            "alert_message": alert_message,
            "toast_ms": int(cfg["toast_ms"]),
        }

    # Skill: Setup Wizard & System Hardware Capabilities Diagnosis
    def get_system_capabilities(self) -> dict:
        """Inspects host system hardware (CUDA GPU, Tesseract OCR, Mic) and configured providers."""
        # 1. GPU / CUDA
        has_cuda = False
        gpu_name = "None (CPU Execution)"
        try:
            import torch
            if torch.cuda.is_available():
                has_cuda = True
                gpu_name = torch.cuda.get_device_name(0)
        except Exception:
            try:
                out = subprocess.check_output(
                    "nvidia-smi --query-gpu=name --format=csv,noheader",
                    shell=True,
                    timeout=2
                ).decode().strip()
                if out:
                    has_cuda = True
                    gpu_name = out.split("\n")[0].strip()
            except Exception:
                pass

        # 2. Tesseract OCR
        has_tesseract = False
        try:
            has_tesseract = bool(
                shutil.which("tesseract") or
                os.path.exists(r"C:\Program Files\Tesseract-OCR\tesseract.exe")
            )
        except Exception:
            has_tesseract = bool(shutil.which("tesseract"))

        # 3. Microphone availability
        has_mic = True  # Native PyWebView / Web Audio API support

        # 4. Check Provider API Keys
        provider_keys = {
            "Gemini": "GEMINI_API_KEY",
            "DeepSeek": "DEEPSEEK_API_KEY",
            "OpenAI": "OPENAI_API_KEY",
            "Anthropic": "ANTHROPIC_API_KEY",
            "Perplexity": "PERPLEXITY_API_KEY",
            "Grok": "GROK_API_KEY",
            "Cartesia": "CARTESIA_API_KEY",
        }
        configured_providers = {}
        for prov, env_key in provider_keys.items():
            key_val = os.getenv(env_key, "").strip()
            configured_providers[prov] = bool(
                key_val and not key_val.startswith("your_") and not key_val.startswith("tu_")
            )

        llm_providers = ["Gemini", "DeepSeek", "OpenAI", "Anthropic", "Perplexity", "Grok"]
        is_first_run = not any(configured_providers.get(p, False) for p in llm_providers)

        return {
            "status": "success",
            "cuda_available": has_cuda,
            "gpu_name": gpu_name,
            "tesseract_available": has_tesseract,
            "microphone_available": has_mic,
            "configured_providers": configured_providers,
            "is_first_run": is_first_run,
            # Must match launcher_webview.py / .env.example default (local-first desktop).
            "runtime_mode": os.getenv("IGNITE_RUNTIME_MODE", "local"),
            "user_name": self._user_name,
        }

    # Skill: Live API Key Validation & Atomic Environment Hot-Reload
    def validate_and_save_api_key(self, provider: str, api_key: str) -> dict:
        """Tests an API key against the provider's endpoint, and if valid, updates .env and hot-reloads the instance."""
        if not provider or not api_key or not isinstance(api_key, str) or not api_key.strip():
            return {"status": "error", "message": "API key cannot be empty"}

        api_key = api_key.strip()
        provider_env_keys = {
            "Gemini": "GEMINI_API_KEY",
            "DeepSeek": "DEEPSEEK_API_KEY",
            "OpenAI": "OPENAI_API_KEY",
            "Anthropic": "ANTHROPIC_API_KEY",
            "Perplexity": "PERPLEXITY_API_KEY",
            "Grok": "GROK_API_KEY",
            "Cartesia": "CARTESIA_API_KEY",
        }
        env_key = provider_env_keys.get(provider)
        if not env_key:
            return {"status": "error", "message": f"Unsupported provider: {provider}"}

        # 1. Live Validation Probe
        is_valid = False
        error_detail = None
        try:
            if provider == "Gemini":
                from google import genai
                test_client = genai.Client(api_key=api_key)
                test_resp = test_client.models.count_tokens(model="gemini-2.5-flash", contents="ping")
                if test_resp and getattr(test_resp, "total_tokens", 0) > 0:
                    is_valid = True
            elif provider == "DeepSeek":
                base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
                resp = requests.get(f"{base_url}/models", headers={"Authorization": f"Bearer {api_key}"}, timeout=8)
                if resp.status_code == 200:
                    is_valid = True
                else:
                    error_detail = f"Status {resp.status_code}: {resp.text[:100]}"
            elif provider == "OpenAI":
                resp = requests.get("https://api.openai.com/v1/models", headers={"Authorization": f"Bearer {api_key}"}, timeout=8)
                if resp.status_code == 200:
                    is_valid = True
                else:
                    error_detail = f"Status {resp.status_code}: {resp.text[:100]}"
            elif provider == "Anthropic":
                resp = requests.get("https://api.anthropic.com/v1/models", headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"}, timeout=8)
                if resp.status_code == 200:
                    is_valid = True
                else:
                    error_detail = f"Status {resp.status_code}: {resp.text[:100]}"
            elif provider == "Perplexity":
                base_url = os.getenv("PERPLEXITY_BASE_URL", "https://api.perplexity.ai").rstrip("/")
                resp = requests.post(
                    f"{base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json={"model": "sonar", "messages": [{"role": "user", "content": "ping"}], "max_tokens": 1},
                    timeout=8
                )
                if resp.status_code in (200, 400):
                    is_valid = True
                else:
                    error_detail = f"Status {resp.status_code}: {resp.text[:100]}"
            elif provider == "Grok":
                base_url = os.getenv("GROK_BASE_URL", "https://api.x.ai/v1").rstrip("/")
                resp = requests.get(f"{base_url}/models", headers={"Authorization": f"Bearer {api_key}"}, timeout=8)
                if resp.status_code == 200:
                    is_valid = True
                else:
                    error_detail = f"Status {resp.status_code}: {resp.text[:100]}"
            elif provider == "Cartesia":
                resp = requests.get("https://api.cartesia.ai/voices", headers={"X-API-Key": api_key, "Cartesia-Version": "2024-06-10"}, timeout=8)
                if resp.status_code == 200:
                    is_valid = True
                else:
                    error_detail = f"Status {resp.status_code}: {resp.text[:100]}"
        except Exception as val_err:
            error_detail = str(val_err)

        if not is_valid:
            logger.warning(f"API key validation failed for {provider}: {error_detail}")
            return {"status": "error", "message": f"Validation failed: {error_detail or 'Invalid API key or network error'}"}

        # 2. Persist to .env atomically and update runtime env
        os.environ[env_key] = api_key
        try:
            env_file = os.path.join(app_dir, ".env")
            lines = []
            if os.path.exists(env_file):
                with open(env_file, "r", encoding="utf-8") as f:
                    lines = f.readlines()

            key_found = False
            new_lines = []
            for line in lines:
                if line.strip().startswith(f"{env_key}="):
                    new_lines.append(f"{env_key}={api_key}\n")
                    key_found = True
                else:
                    new_lines.append(line)
            if not key_found:
                new_lines.append(f"\n{env_key}={api_key}\n")

            tmp_env = f"{env_file}.tmp"
            with open(tmp_env, "w", encoding="utf-8") as f:
                f.writelines(new_lines)
            os.replace(tmp_env, env_file)
            logger.info(f"Updated {env_key} in {env_file}")
        except Exception as save_err:
            logger.error(f"Failed to persist API key to .env: {save_err}")

        # 3. Hot-reload the chat instance in memory
        try:
            if provider in self._providers:
                self._init_chat(provider)
                if provider in self._provider_init_errors:
                    del self._provider_init_errors[provider]
                logger.info(f"Hot-reloaded chat instance for {provider}")
        except Exception as init_err:
            logger.warning(f"Hot-reload initialization warning for {provider}: {init_err}")

        return {
            "status": "success",
            "provider": provider,
            "message": f"API key for {provider} verified and saved successfully!"
        }

    # Skill: Productivity & ROI Value Dashboard Telemetry
    def get_productivity_metrics(self) -> dict:
        """Calculates executive ROI & productivity value metrics for the operational user."""
        total_tokens = sum(self._token_totals.values())
        total_cost_usd = sum(self._cost_totals.values())

        total_sessions = 0
        total_messages = 0
        total_words = 0

        try:
            log_root = self._tenant_log_root()
            if os.path.exists(log_root):
                for root, _, files in os.walk(log_root):
                    for f in files:
                        if f.endswith(".json") and not f.startswith("groups"):
                            total_sessions += 1
                            filepath = os.path.join(root, f)
                            try:
                                with open(filepath, "r", encoding="utf-8") as sfp:
                                    sdata = json.load(sfp)
                                    msgs = sdata.get("messages", [])
                                    total_messages += len(msgs)
                                    for m in msgs:
                                        if m.get("role") == "assistant":
                                            content = m.get("content", "")
                                            total_words += len(re.findall(r"\w+", content))
                            except Exception:
                                pass
        except Exception as e:
            logger.warning(f"Error aggregating session logs for productivity metrics: {e}")

        if total_words == 0 and total_tokens > 0:
            total_words = int(total_tokens * 0.75)

        # Count generated documents (.docx, .xlsx, .pptx)
        generated_docs_count = 0
        try:
            gen_dir = os.path.join(self._tenant_log_root(), "generated_files")
            if os.path.exists(gen_dir):
                generated_docs_count = len([f for f in os.listdir(gen_dir) if f.endswith((".docx", ".xlsx", ".pptx"))])
        except Exception:
            pass

        # 1. Typing & drafting hours saved (40 words/min average typing speed)
        typing_hours_saved = round(total_words / (40 * 60), 2)

        # 2. Document formatting & Excel spreadsheet compilation hours (~20 mins / 0.35h per doc)
        doc_hours_saved = round(generated_docs_count * 0.35, 2)

        total_hours_saved = round(typing_hours_saved + doc_hours_saved, 2)

        # 3. Equivalent Human-Hour Cost: $25 USD / hour standard operational rate
        equivalent_human_cost_usd = round(total_hours_saved * 25.0, 2)

        # 4. ROI Multiplier
        roi_multiplier = round(equivalent_human_cost_usd / max(total_cost_usd, 0.01), 1)

        return {
            "status": "success",
            "total_tokens": total_tokens,
            "total_words_generated": total_words,
            "total_messages": total_messages or len(self._history.get(self._current_provider, [])),
            "total_sessions": total_sessions or 1,
            "documents_generated": generated_docs_count,
            "typing_hours_saved": typing_hours_saved,
            "doc_hours_saved": doc_hours_saved,
            "total_hours_saved": total_hours_saved,
            "ai_cost_usd": round(total_cost_usd, 4),
            "equivalent_human_cost_usd": equivalent_human_cost_usd,
            "roi_multiplier": roi_multiplier,
            "provider_breakdown": {
                p: {
                    "tokens": self._token_totals.get(p, 0),
                    "cost_usd": self._cost_totals.get(p, 0.0),
                    "messages": len(self._history.get(p, []))
                } for p in self._providers if not p.startswith("group_")
            }
        }

    # Skill: Smart Proactive Fallback Recommendation
    def get_smart_fallback(self, provider: str, error_msg: Optional[str] = None) -> dict:
        """Determines proactive alternative provider suggestions when an API fails."""
        alternatives = []
        for p in ["Gemini", "DeepSeek", "OpenAI", "Anthropic", "Perplexity", "Grok"]:
            if p != provider and p in self._chat_instances and p not in self._provider_init_errors:
                alternatives.append(p)

        if not alternatives:
            alternatives = [p for p in ["Gemini", "DeepSeek", "OpenAI"] if p != provider]

        primary_fallback = alternatives[0] if alternatives else "Gemini"

        friendly_explanation = (
            f"El proveedor {provider} está experimentando saturación temporal o límite de cuota."
            if "es" in (USER_SYSTEM_LANGUAGE or "").lower() else
            f"The provider {provider} is temporarily busy or reached its rate limit."
        )

        return {
            "status": "success",
            "failed_provider": provider,
            "error_summary": friendly_explanation,
            "primary_fallback": primary_fallback,
            "alternatives": alternatives
        }

    # Function to save the welcome message
    def save_welcome_message(self, provider, text, msg_provider=None):
        """Persist a welcome only on empty / welcome-only history (never mid-thread)."""
        if provider not in self._history:
            return {"status": "error", "message": "Unknown provider"}

        history = self._history[provider]
        # Skill §12.1: never append welcome after real conversation turns.
        if any(not msg.get("is_welcome") for msg in history):
            logger.warning(
                "Ignored save_welcome_message for %s: history already has non-welcome messages",
                provider,
            )
            return {"status": "ignored", "reason": "history_not_empty"}

        is_already_saved = any(msg.get("content") == text for msg in history)
        if is_already_saved:
            return {"status": "success", "reason": "already_saved"}

        model_to_save = ""
        if msg_provider:
            model_to_save = self._current_model.get(msg_provider, "")
        else:
            model_to_save = self._current_model.get(provider, "")

        self._history[provider].append({
            "role": "assistant",
            "content": text,
            "timestamp": _get_time_str(),
            "iso_timestamp": _get_iso_timestamp(),
            "date": _get_date_str(),
            "is_welcome": True,
            "provider": msg_provider or provider,
            "model": model_to_save,
            "token_info": {
                "total_tokens": 0,
                "prompt_tokens": 0,
                "candidates_tokens": 0,
                "thinking_tokens": 0
            }
        })
        self._save_conversation_history(provider)
        return {"status": "success"}

    def _migrate_group_welcome_messages(self):
        log_dir = os.path.join(self._tenant_log_root(), "groups", "Sessions")
        if not os.path.exists(log_dir):
            return
            
        for filename in os.listdir(log_dir):
            if not filename.endswith(".json"):
                continue
            filepath = os.path.join(log_dir, filename)
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception as e:
                logger.error(f"Error reading group session file {filename}: {e}")
                continue
                
            messages = data.get("messages", [])
            has_generic = False
            welcome_idx = -1
            for idx, msg in enumerate(messages):
                prov = msg.get("provider", "")
                content = msg.get("content", "")
                if msg.get("is_welcome") and (not prov or prov.startswith("group_") or "group_" in str(prov) or "AI Group" in content):
                    has_generic = True
                    welcome_idx = idx
                    break
            
            if has_generic and welcome_idx != -1:
                group_id = data.get("provider")
                if not group_id:
                    group_id = filename.replace(".json", "")
                    if "_" in group_id:
                        parts = group_id.split("_")
                        group_id = f"{parts[0]}_{parts[1]}"
                
                group_info = self._groups.get(group_id)
                if group_info:
                    participants = group_info.get("participants", [])
                    original_welcome = messages[welcome_idx]
                    original_content = original_welcome.get("content", "")
                    
                    is_spanish = "Cómo te puedo ayudar" in original_content or "¡Hola" in original_content or "¿Qué tal?" in original_content
                    greeting_template = (
                        "¡Hola {name}! Soy tu asistente {provider}. ¿Cómo te puedo ayudar hoy?"
                        if is_spanish else
                        "Hello {name}! I'm your {provider} assistant. How can I help you today?"
                    )
                    
                    new_welcomes = []
                    for p in participants:
                        content = greeting_template.format(name=self._user_name, provider=p)
                        new_welcomes.append({
                            "role": "assistant",
                            "content": content,
                            "timestamp": original_welcome.get("timestamp") or datetime.now().strftime("%I:%M %p"),
                            "iso_timestamp": original_welcome.get("iso_timestamp") or _get_iso_timestamp(),
                            "date": original_welcome.get("date") or datetime.now().strftime("%Y-%m-%d"),
                            "is_welcome": True,
                            "provider": p,
                            "model": self._current_model.get(p, ""),
                            "token_info": {
                                "total_tokens": 0,
                                "prompt_tokens": 0,
                                "candidates_tokens": 0,
                                "thinking_tokens": 0
                            }
                        })
                    
                    messages[welcome_idx:welcome_idx+1] = new_welcomes
                    data["messages"] = messages
                    
                    try:
                        with open(filepath, "w", encoding="utf-8") as f:
                            json.dump(data, f, ensure_ascii=False, indent=2)
                        logger.info(f"Successfully migrated group welcome messages for file {filename}")
                    except Exception as e:
                        logger.error(f"Error writing migrated session file {filename}: {e}")

    # Function to update user token info
    def _update_user_token_info(self, provider, token_info):
        pass

    # Function to recalculate token totals and cost totals
    def _recalculate_token_totals(self, provider, *, accrue_lifetime: bool = False):
        old_cost = 0.0
        if hasattr(self, "_cost_totals") and self._cost_totals:
            try:
                old_cost = float(self._cost_totals.get(provider, 0.0) or 0.0)
            except (TypeError, ValueError):
                old_cost = 0.0
        total = 0
        total_cost = 0.0
        if provider in self._history:
            for msg in self._history[provider]:
                info = msg.get("token_info")
                if info:
                    if isinstance(info, dict):
                        p_tok = info.get("prompt_tokens") or 0
                        c_tok = info.get("candidates_tokens") or 0
                        t_tok = info.get("thinking_tokens") or 0
                        cost = float(info.get("cost_usd") or 0.0)
                    else:
                        p_tok = getattr(info, "prompt_tokens", 0) or 0
                        c_tok = getattr(info, "candidates_tokens", 0) or 0
                        t_tok = getattr(info, "thinking_tokens", 0) or 0
                        cost = float(getattr(info, "cost_usd", 0.0) or 0.0)

                    msg_model = msg.get("model") or self._current_model.get(provider, "")
                    if cost == 0.0 and (p_tok > 0 or c_tok > 0):
                        cost = calculate_cost_usd(msg_model, p_tok, c_tok, t_tok)

                    if msg.get("role") == "user":
                        total += p_tok
                    else:
                        total += c_tok + t_tok
                    total_cost += cost

        self._token_totals[provider] = total
        if not hasattr(self, "_cost_totals") or self._cost_totals is None:
            self._cost_totals = {}
        new_cost = round(total_cost, 6)
        self._cost_totals[provider] = new_cost
        if accrue_lifetime:
            delta = new_cost - old_cost
            if delta > 0:
                self._add_lifetime_spend(delta)

    @staticmethod
    def _is_indexable_assistant_reply(reply: str) -> bool:
        text = (reply or "").strip()
        if not text:
            return False
        if text.startswith("Error:") or text.startswith("⚠️"):
            return False
        return True

    def _ensure_rag_session_backfill(self) -> None:
        """Index archived session JSON into RAG once so old chats survive a new conversation."""
        if not self.rag_engine or getattr(self, "_rag_sessions_backfilled", False):
            return
        self._rag_sessions_backfilled = True
        try:
            indexed = 0
            seen_dirs: set[str] = set()
            files: list[tuple[float, str]] = []
            for provider in list(getattr(self, "_providers", []) or []):
                try:
                    log_dir = self._provider_log_dir(provider, "Sessions")
                except Exception:
                    continue
                if not log_dir or log_dir in seen_dirs or not os.path.isdir(log_dir):
                    continue
                seen_dirs.add(log_dir)
                for name in os.listdir(log_dir):
                    if not name.endswith(".json"):
                        continue
                    path = os.path.join(log_dir, name)
                    try:
                        files.append((os.path.getmtime(path), path))
                    except OSError:
                        continue
            files.sort(key=lambda item: (item[0], item[1]), reverse=True)
            for _, path in files[:RAG_BACKFILL_MAX_FILES]:
                if indexed >= RAG_BACKFILL_MAX_TURNS:
                    break
                try:
                    with open(path, "r", encoding="utf-8") as session_file:
                        data = json.load(session_file)
                except Exception as read_err:
                    logger.debug("Skipping unreadable session for RAG backfill %s: %s", path, read_err)
                    continue
                messages = data.get("messages") or []
                if not messages:
                    continue
                session_id = data.get("session_id") or os.path.splitext(os.path.basename(path))[0]
                remaining = RAG_BACKFILL_MAX_TURNS - indexed
                if remaining <= 0:
                    break
                indexed += int(
                    self.rag_engine.index_session_messages(messages[: remaining * 2], str(session_id))
                )
            if indexed:
                logger.info("Backfilled %s archived conversation turns into local RAG", indexed)
        except Exception as backfill_err:
            logger.warning("RAG session backfill failed: %s", backfill_err)

    def _text_for_model_with_rag(self, text: str) -> str:
        """Prefix the user query with recalled local memories when available.

        Skip RAG when the live message contains a URL/YouTube link so older videos
        or pages are not scraped or described in place of the link the user just sent.
        """
        if not text or not self.rag_engine:
            return text
        if BaseChat._query_has_external_url(text):
            return text
        self._ensure_rag_session_backfill()
        try:
            rag_snippet = self.rag_engine.get_rag_system_prompt_snippet(text, top_k=4)
            if rag_snippet:
                logger.info(
                    "Injecting RAG memory snippet (%s chars) into LLM context.",
                    len(rag_snippet),
                )
                return f"{rag_snippet}\n\n[USER QUERY]\n{text}"
        except Exception as rag_err:
            logger.warning("Failed to query RAG engine: %s", rag_err)
        return text

    def _index_conversation_turn_for_rag(
        self,
        user_text: str,
        assistant_reply: str,
        provider: str | None = None,
    ) -> None:
        if not self.rag_engine or not self._is_indexable_assistant_reply(assistant_reply):
            return
        user_text = (user_text or "").strip()
        if not user_text:
            return
        if BaseChat._query_has_external_url(user_text):
            return
        try:
            owner = provider or getattr(self, "_current_provider", None)
            session_id = getattr(self, "_session_id", None) or "default"
            turn_index = sum(
                1
                for msg in self._history.get(owner, [])
                if msg.get("role") == "assistant" and not msg.get("is_welcome")
            )
            if turn_index > 0:
                turn_index -= 1
            self.rag_engine.index_conversation_turn(
                user_text,
                assistant_reply.strip(),
                session_id=str(session_id),
                turn_index=turn_index,
            )
        except Exception as rag_idx_err:
            logger.warning("Failed to index conversation turn into RAG: %s", rag_idx_err)

    def _preprocess_input(self, text, files, from_mic, language, chat, provider_for_fallback, history=None):
        """Unified helper to decode base64 attachments, perform voice transcription, and run language policy.

        Language policy (skill): keep the language the user started with so slang
        does not flip the thread; switch on an explicit request OR a clearly
        monolingual latest utterance (including microphone STT).

        Skill 2.6 — PII Guardrails:
            After transcription/text is finalized, PIIShield.sanitize() redacts emails
            and credit card numbers from the text BEFORE it reaches any AI provider.
        """
        processed_files = []
        error_msg = None
        if files:
            for f in files:
                try:
                    disk_path = f.get("path") or ""
                    if "bytes" in f:
                        data_bytes = f["bytes"]
                    elif "base64" in f and f["base64"]:
                        data_bytes = base64.b64decode(f["base64"])
                    elif disk_path and os.path.exists(disk_path):
                        with open(disk_path, "rb") as fp:
                            data_bytes = fp.read()
                    else:
                        data_bytes = b""
                    processed_files.append({
                        "name": f.get("name", "file"),
                        "mime_type": f.get("mime_type", "application/octet-stream"),
                        "bytes": data_bytes,
                        "size": f.get("size") or (len(data_bytes) if data_bytes else 0),
                        "path": disk_path or None,
                        "preview_id": f.get("preview_id"),
                        "preview_base64": f.get("preview_base64"),
                        "preview_mime": f.get("preview_mime"),
                        "page_count": f.get("page_count"),
                    })
                except Exception as e:
                    logger.error(f"Error decoding file: {e}")

        if from_mic and processed_files:
            audio_files = [f for f in processed_files if f['mime_type'].startswith('audio/')]
            if audio_files:
                if chat and hasattr(chat, 'transcribe_audio'):
                    trans_result = chat.transcribe_audio(
                        audio_files[0]['bytes'], 
                        mime_type=audio_files[0]['mime_type'],
                        fallback_models=self._models.get(provider_for_fallback),
                        expected_language=None
                    )
                    if len(trans_result) == 3:
                        transcription, err, token_info = trans_result
                    else:
                        transcription, err = trans_result
                    
                    if err:
                        error_msg = _friendly_error_message(err, language)
                    elif not transcription or not transcription.strip():
                        base_lang = language.split('-')[0].lower() if language and '-' in language else (language or "en").lower()
                        error_msg = (
                            "No se detectó voz o sólo había ruido de fondo. Por favor, habla más de cerca o más fuerte." 
                            if base_lang == "es" else 
                            "No speech detected or only background noise was heard. Please speak closer or louder."
                        )
                    else:
                        text = transcription
                        logger.info(f"Microphone audio transcribed ({len(text)} chars).")
                        processed_files = [f for f in processed_files if f != audio_files[0]]

        # Sticky conversation language (after STT so voice text is included).
        language = _resolve_conversation_language(
            text or "",
            history=history,
            incoming_language=language,
        )
        logger.info("Resolved conversation language: %s", language)

        # Skill 2.6 — PII & Prompt Injection Guardrails: sanitize final text before returning to the caller
        if text and _PII_SHIELD_AVAILABLE:
            try:
                text = PIIShield.sanitize(text)
                if 'PromptInjectionGuard' in globals():
                    inj_res = PromptInjectionGuard.inspect_prompt(text)
                    text = inj_res.sanitized_text
            except Exception as pii_err:
                logger.warning(f"PIIShield/PromptInjectionGuard sanitization failed (non-blocking): {pii_err}")

        return {
            "text": text,
            "files": processed_files,
            "language": language,
            "error": error_msg
        }

    @staticmethod
    def _resolve_attachment_bytes(file_item: dict):
        """Resolve attachment bytes from memory, base64, or disk path (Ignite extract + processors)."""
        if not isinstance(file_item, dict):
            return None
        raw = file_item.get("bytes")
        if isinstance(raw, (bytes, bytearray)) and raw:
            return bytes(raw)
        b64 = file_item.get("base64")
        if isinstance(b64, str) and b64.strip():
            try:
                return base64.b64decode(b64)
            except Exception as err:
                logger.warning("Failed to decode attachment base64: %s", err)
        disk_path = file_item.get("path") or ""
        if disk_path and os.path.exists(disk_path):
            try:
                with open(disk_path, "rb") as fp:
                    return fp.read()
            except Exception as err:
                logger.warning("Failed to read attachment from disk %s: %s", disk_path, err)
        return None

    @staticmethod
    def _normalize_attachment_basename(name: str) -> str:
        cleaned = (name or "").strip().strip('"\'')
        return os.path.basename(cleaned).lower()

    def _collect_extract_attachment_candidates(self, *sources) -> list:
        """Merge attachment dicts for IGNITE_EXTRACT matching (current turn + raw payloads)."""
        merged = []
        seen = set()
        for source in sources:
            if not source:
                continue
            for item in source:
                if not isinstance(item, dict):
                    continue
                key = (
                    self._normalize_attachment_basename(item.get("name") or item.get("filename") or ""),
                    item.get("path") or "",
                    item.get("preview_id") or "",
                )
                if key in seen:
                    continue
                seen.add(key)
                merged.append(item)
        return merged

    _IGNITE_EXTRACT_TAG_RE = re.compile(
        r"\[IGNITE_EXTRACT:\s*(.*?)\|(.*?)\]",
        re.IGNORECASE | re.DOTALL,
    )

    _CHAT_PROVIDER_TO_IGNITE_LLM: Dict[str, str] = {
        "Gemini": "gemini",
        "OpenAI": "azure_openai",
        "DeepSeek": "deepseek",
        "Anthropic": "anthropic",
        "Grok": "grok",
        "Perplexity": "perplexity",
        "AlibabaCloud": "alibabacloud",
    }

    @classmethod
    def _ignite_llm_provider_for_chat(cls, chat_provider: Optional[str]) -> Optional[str]:
        if not chat_provider:
            return None
        key = str(chat_provider).strip()
        if key in cls._CHAT_PROVIDER_TO_IGNITE_LLM:
            return cls._CHAT_PROVIDER_TO_IGNITE_LLM[key]
        if key.startswith("group_"):
            return None
        return key.lower()

    def _active_chat_model_id(self, chat_provider: Optional[str]) -> Optional[str]:
        if not chat_provider:
            return None
        model = (self._current_model or {}).get(chat_provider)
        if model and str(model).strip() and str(model).strip().lower() != "group":
            return str(model).strip()
        return None

    @staticmethod
    def _user_requests_structured_extract(user_text: str) -> bool:
        """Heuristic when the model omits [IGNITE_EXTRACT] but the user asked for extraction."""
        if not user_text or not str(user_text).strip():
            return False
        t = str(user_text).lower()
        cues = (
            "analiza",
            "analyze",
            "analyse",
            "extrae",
            "extract",
            "extracción",
            "extraction",
            "structured",
            "estructurad",
            "factura",
            "invoice",
            "receipt",
            "recibo",
            "receta",
            "prescription",
            "guarda en memoria",
            "save to memory",
            "rag",
        )
        return any(c in t for c in cues)

    @staticmethod
    def _guess_extract_template(filename: str, mime_type: str = "") -> str:
        name = (filename or "").lower()
        mime = (mime_type or "").lower()
        if any(k in name for k in ("receta", "prescription", "medical", "rx_")):
            return "Medical_Prescription"
        if any(k in name for k in ("invoice", "factura", "receipt", "recibo")):
            return "Invoice_Standard"
        if "bank" in name or "statement" in name or "movimiento" in name:
            return "Bank_Statement"
        if name.endswith((".mp3", ".wav", ".m4a", ".ogg")) or mime.startswith("audio/"):
            return "Meeting_Minutes"
        if name.endswith((".png", ".jpg", ".jpeg", ".tiff", ".webp")) or mime.startswith("image/"):
            return "Invoice_Standard"
        return "Invoice_Standard"

    def _match_attachment_for_extract(
        self, target_file: str, candidates: list, *, tag_index: int = 0
    ) -> tuple:
        """Return (bytes, resolved_filename) for Ignite API extract, or (None, None)."""
        target_norm = self._normalize_attachment_basename(target_file)
        if not candidates:
            return None, None

        with_bytes = []
        for f in candidates:
            fname = f.get("name") or f.get("filename") or ""
            data = self._resolve_attachment_bytes(f)
            if not data:
                continue
            with_bytes.append((fname, data))

        if not with_bytes:
            return None, None

        if target_norm:
            for fname, data in with_bytes:
                fn_norm = self._normalize_attachment_basename(fname)
                if fn_norm == target_norm:
                    return data, fname
            partial = []
            for fname, data in with_bytes:
                fn_norm = self._normalize_attachment_basename(fname)
                if target_norm in fn_norm or fn_norm in target_norm:
                    partial.append((len(fn_norm), fname, data))
            if partial:
                partial.sort(key=lambda row: row[0])
                _, fname, data = partial[0]
                return data, fname

        if len(with_bytes) == 1:
            fname, data = with_bytes[0]
            logger.info(
                "IGNITE_EXTRACT: using sole attachment '%s' for target '%s'",
                fname,
                target_file or "(unspecified)",
            )
            return data, fname

        if 0 <= tag_index < len(with_bytes):
            fname, data = with_bytes[tag_index]
            logger.info(
                "IGNITE_EXTRACT: using attachment #%d '%s' for target '%s' (%d file(s) attached)",
                tag_index + 1,
                fname,
                target_file or "(unspecified)",
                len(with_bytes),
            )
            return data, fname

        return None, None

    def _execute_single_ignite_extract(
        self,
        matched_bytes: bytes,
        matched_name: str,
        template_name: str,
        language: str,
        request_id=None,
        log_prefix: str = "",
        chat_provider: Optional[str] = None,
        chat_model: Optional[str] = None,
    ) -> tuple:
        """Run one Ignite API extract + RAG index. Returns (success, chrome_suffix, fail_hint_or_none)."""
        prefix = f"{log_prefix} " if log_prefix else ""
        try:
            if self._is_request_cancelled(request_id):
                return False, "", None

            client = IgniteAPIClient()
            if not client.enabled:
                return False, "", IgniteAPIClient.user_failure_hint(
                    matched_name, "disabled", language
                )

            llm_provider = self._ignite_llm_provider_for_chat(chat_provider)
            model_id = chat_model or self._active_chat_model_id(chat_provider)
            logger.info(
                "%sCalling IgniteAPIClient.extract_sync for '%s' (%d bytes) llm=%s model=%s",
                prefix,
                matched_name,
                len(matched_bytes),
                llm_provider or "(server default)",
                model_id or "(server default)",
            )
            extraction_res = client.extract_sync(
                matched_bytes,
                matched_name,
                template_name,
                llm_provider=llm_provider,
                model=model_id,
            )

            if self._is_request_cancelled(request_id):
                return False, "", None

            if extraction_res:
                chunks = extraction_to_rag_chunks(
                    extraction_res,
                    matched_name,
                    session_id=getattr(self, "_tenant_key", None) or "default",
                )
                indexed_count = 0
                if self.rag_engine:
                    for doc_id, text_chunk, meta in chunks:
                        if self.rag_engine.index_document(doc_id, text_chunk, meta):
                            indexed_count += 1
                chrome = _extract_success_chrome(
                    template_name, indexed_count, language, standalone=False
                )
                # Chat → Ignite API extract also fires Foundry Traces + workflow orchestration.
                foundry_note = notify_foundry_after_extract(
                    filename=matched_name,
                    template_name=template_name,
                    extraction=extraction_res if isinstance(extraction_res, dict) else None,
                    language=language,
                )
                if foundry_note and foundry_note.get("message"):
                    logger.info(
                        "FOUNDRY post-extract attached to chrome live=%s source=%s",
                        foundry_note.get("foundry_live"),
                        foundry_note.get("foundry_source"),
                    )
                    chrome = f"{chrome}\n\n{foundry_note['message']}" if chrome else foundry_note["message"]
                else:
                    logger.warning(
                        "FOUNDRY post-extract returned nothing after '%s' — "
                        "check FOUNDRY_ORCHESTRATION_ENABLED / PROJECT_CONNECTION_STRING "
                        "in foundry/.env (Agent-a-thon repo).",
                        matched_name,
                    )
                return True, chrome, None

            return False, "", IgniteAPIClient.user_failure_hint(
                matched_name, client.last_error, language
            )
        except Exception as ext_err:
            logger.error(
                "%sError executing Ignite API extraction: %s",
                prefix,
                ext_err,
                exc_info=True,
            )
            return False, "", None

    def _apply_ignite_extract_from_reply(
        self,
        reply: str,
        attachment_candidates: list,
        language: str,
        request_id=None,
        log_prefix: str = "",
        user_text: str = "",
        chat_provider: Optional[str] = None,
        chat_model: Optional[str] = None,
    ) -> str:
        """Parse [IGNITE_EXTRACT: file|Template] (all tags), call Ignite API, index RAG."""
        reply = reply or ""
        prefix = f"{log_prefix} " if log_prefix else ""
        tag_pattern = r"\[IGNITE_EXTRACT:\s*.*?\]"
        matches = list(self._IGNITE_EXTRACT_TAG_RE.finditer(reply))

        if not matches:
            if (
                attachment_candidates
                and self._user_requests_structured_extract(user_text)
            ):
                jobs = []
                for f in attachment_candidates:
                    fname = f.get("name") or f.get("filename") or "file"
                    data = self._resolve_attachment_bytes(f)
                    if not data:
                        continue
                    mime = f.get("mime_type") or ""
                    jobs.append(
                        (data, fname, self._guess_extract_template(fname, mime))
                    )
                if jobs:
                    logger.info(
                        "%sAuto Ignite extract (no LLM tag): %d attachment(s) for user request",
                        prefix,
                        len(jobs),
                    )
                    chromes = []
                    fail_hints = []
                    for data, fname, template_name in jobs:
                        if self._is_request_cancelled(request_id):
                            break
                        logger.info(
                            "%sAuto extraction for '%s' with template '%s'",
                            prefix,
                            fname,
                            template_name,
                        )
                        ok, chrome, fail_hint = self._execute_single_ignite_extract(
                            data,
                            fname,
                            template_name,
                            language,
                            request_id=request_id,
                            log_prefix=log_prefix,
                            chat_provider=chat_provider,
                            chat_model=chat_model,
                        )
                        if ok and chrome:
                            chromes.append(chrome)
                        elif fail_hint:
                            fail_hints.append(fail_hint)
                    if chromes:
                        body = reply.strip()
                        combined = "".join(chromes)
                        if not body:
                            return combined.strip()
                        return body + combined
                    if fail_hints:
                        return reply.strip() + fail_hints[0]
            return reply

        chromes = []
        fail_hints = []
        for tag_index, extract_match in enumerate(matches):
            target_file = extract_match.group(1).strip()
            template_name = extract_match.group(2).strip()
            logger.info(
                "%sLLM triggered Ignite API extraction for file '%s' with template '%s'",
                prefix,
                target_file,
                template_name,
            )
            matched_bytes, matched_name = self._match_attachment_for_extract(
                target_file, attachment_candidates, tag_index=tag_index
            )
            if not matched_bytes:
                logger.warning(
                    "%sIGNITE_EXTRACT target file '%s' not found in attachments (%d candidate(s)).",
                    prefix,
                    target_file,
                    len(attachment_candidates or []),
                )
                continue

            ok, chrome, fail_hint = self._execute_single_ignite_extract(
                matched_bytes,
                matched_name,
                template_name,
                language,
                request_id=request_id,
                log_prefix=log_prefix,
                chat_provider=chat_provider,
                chat_model=chat_model,
            )
            if ok and chrome:
                chromes.append(chrome)
            elif fail_hint:
                fail_hints.append(fail_hint)

        cleaned = re.sub(tag_pattern, "", reply, flags=re.IGNORECASE | re.DOTALL).strip()
        if fail_hints and not chromes:
            return cleaned + fail_hints[0]
        if not chromes:
            return cleaned
        combined_chrome = "".join(chromes)
        if not cleaned:
            return combined_chrome.strip()
        return cleaned + combined_chrome

    def _is_request_cancelled(self, request_id: str) -> bool:
        if not request_id:
            return False
        with self._request_lock:
            req = self._requests.get(request_id) or {}
            return bool(req.get("cancelled")) or req.get("status") == "cancelled"

    def cancel_generation(self, request_id: str = None, provider: str = None):
        """Cancel in-flight generation(s). Frontend interrupt must call this, not only stop polling."""
        cancelled = []
        with self._request_lock:
            targets = []
            if request_id:
                targets.append(request_id)
            elif provider:
                active = self._active_request_by_provider.get(provider)
                if active:
                    targets.append(active)
                for rid, req in self._requests.items():
                    if req.get("provider") == provider and req.get("status") in ("queued", "processing"):
                        targets.append(rid)
            else:
                provider = self._current_provider
                active = self._active_request_by_provider.get(provider)
                if active:
                    targets.append(active)

            for rid in dict.fromkeys(targets):
                req = self._requests.get(rid)
                if not req:
                    continue
                req["cancelled"] = True
                if req.get("status") in ("queued", "processing"):
                    req["status"] = "cancelled"
                    req["error"] = "Cancelled by user"
                    req["finished_at"] = time.time()
                cancelled.append(rid)
                prov = req.get("provider")
                if prov and self._active_request_by_provider.get(prov) == rid:
                    self._active_request_by_provider.pop(prov, None)

        return {"status": "success", "cancelled": cancelled}

    # ---------- Asynchronous message handling ----------
    def send_message_async(
        self,
        text,
        files=None,
        language=None,
        from_mic=False,
        temperature=None,
        top_p=None,
        max_tokens=None,
        provider=None,
    ):
        """Initiate a generation request. Returns request_id immediately.

        Prefer an explicit ``provider`` from the desktop client so switching chats
        mid-flight cannot retarget the worker to ``_current_provider``.
        """
        provider = provider or self._current_provider
        request_id = str(uuid.uuid4())
        with self._request_lock:
            self._prune_requests_locked()
            # Single-flight: cancel prior in-flight work for this provider.
            prev = self._active_request_by_provider.get(provider)
            if prev and prev in self._requests:
                prev_req = self._requests[prev]
                if prev_req.get("status") in ("queued", "processing"):
                    prev_req["cancelled"] = True
                    prev_req["status"] = "cancelled"
                    prev_req["error"] = "Superseded by newer request"
                    prev_req["finished_at"] = time.time()
            self._active_request_by_provider[provider] = request_id
            self._requests[request_id] = {
                "status": "queued",
                "steps": ["Queuing request..."],
                "result": None,
                "error": None,
                "replies": [],
                "current_respondent": None,
                "cancelled": False,
                "provider": provider,
            }

        # Capture ContextVar identity for ACA workers (desktop user name / tenant).
        parent_ctx = contextvars.copy_context()

        # Start background thread
        def worker():
            nonlocal text, language
            try:
                with self._request_lock:
                    if self._requests.get(request_id, {}).get("cancelled"):
                        return
                    self._requests[request_id]["status"] = "processing"

                if self._is_request_cancelled(request_id):
                    return

                if provider.startswith("group_"):
                    group_info = self._groups.get(provider)
                    if not group_info:
                        raise Exception("Group not found")
                    participants = group_info.get("participants", [])
                    if not participants:
                        with self._request_lock:
                            self._requests[request_id]["status"] = "error"
                            self._requests[request_id]["error"] = "Group has no participants"
                            self._requests[request_id]["finished_at"] = time.time()
                        return
                    
                    # 1. Process files & transcription via unified helper
                    # Chat init uses _init_lock — never hold _request_lock around it.
                    trans_provider = participants[0]
                    trans_chat = self._chat_instances.get(trans_provider)
                    if not trans_chat:
                        self._init_chat(trans_provider)
                        trans_chat = self._chat_instances.get(trans_provider)

                    preprocess = self._preprocess_input(
                        text,
                        files,
                        from_mic,
                        language,
                        trans_chat,
                        trans_provider,
                        history=list(self._history.get(provider, [])),
                    )
                    if preprocess["error"]:
                        raise Exception(preprocess["error"])
                    text = preprocess["text"]
                    processed_files = preprocess["files"]
                    language = preprocess["language"]

                    if self._is_request_cancelled(request_id):
                        return

                    # 2. Append user message to group history
                    user_msg = {
                        "role": "user",
                        "content": text,
                        "provider": provider,
                        "files": list(processed_files) if processed_files else [],
                        "conversation_language": language,
                        "token_info": {
                            "total_tokens": 0,
                            "prompt_tokens": 0,
                            "candidates_tokens": 0,
                            "thinking_tokens": 0
                        },
                        "timestamp": _get_time_str(),
                        "iso_timestamp": _get_iso_timestamp(),
                        "date": _get_date_str(),
                        "from_mic": from_mic
                    }
                    self._append_history_message(provider, user_msg, save=True)

                    # Group image fast-path: generate once (first participant) instead of N Pro round-trips.
                    first_chat = self._chat_instances.get(trans_provider)
                    if not first_chat:
                        self._init_chat(trans_provider)
                        first_chat = self._chat_instances.get(trans_provider)
                    if (
                        not processed_files
                        and first_chat
                        and hasattr(first_chat, "is_direct_image_request")
                        and first_chat.is_direct_image_request(text)
                        and hasattr(first_chat, "generate_image")
                    ):
                        logger.info(f"Group image fast-path via {trans_provider}: {text[:120]}...")
                        is_spanish = language and str(language).startswith("es")
                        img_bytes, mime, err, token_info_img = first_chat.generate_image(text)
                        if self._is_request_cancelled(request_id):
                            return
                        if not err and img_bytes is not None:
                            image_data = f"data:{mime or 'image/png'};base64,{base64.b64encode(img_bytes).decode('utf-8')}"
                            reply = (
                                "¡Claro! Aquí tienes la imagen que pediste."
                                if is_spanish
                                else "Sure! Here is the image you requested."
                            )
                            assistant_msg = {
                                "role": "assistant",
                                "provider": trans_provider,
                                "content": reply,
                                "token_info": token_info_img,
                                "timestamp": _get_time_str(),
                                "iso_timestamp": _get_iso_timestamp(),
                                "date": _get_date_str(),
                                "from_mic": from_mic,
                                "files": [],
                                "image_data": image_data,
                            }
                            self._append_history_message(provider, assistant_msg, save=True)
                            self._recalculate_token_totals(provider, accrue_lifetime=True)
                            self._index_conversation_turn_for_rag(text, reply, provider=provider)
                            result = {
                                "status": "success",
                                "provider": provider,
                                "is_group": True,
                                "replies": [{
                                    "provider": trans_provider,
                                    "reply": reply,
                                    "token_info": token_info_img,
                                    "image_data": image_data,
                                    "files": [],
                                }],
                                "from_mic": from_mic,
                                "user_prompt": text,
                                "token_totals": self._token_totals,
                            }
                            with self._request_lock:
                                if not self._requests[request_id].get("cancelled"):
                                    self._requests[request_id]["status"] = "done"
                                    self._requests[request_id]["result"] = result
                                    self._requests[request_id]["replies"] = result["replies"]
                                    self._requests[request_id]["finished_at"] = time.time()
                            return
                        logger.warning(f"Group image fast-path failed: {err or 'empty image'}; using normal group flow.")

                    # Continue with existing group parallel flow — mark status for UI
                    # (rest of group logic remains below via fall-through by not rewriting entire method)
                    raise _ContinueGroupFlow(processed_files, language, text, participants, request_id, from_mic, provider)
                else:
                    if self._is_request_cancelled(request_id):
                        return
                    result = self._send_message_sync(
                        text,
                        files,
                        language,
                        from_mic,
                        provider=provider,
                        temperature=temperature,
                        top_p=top_p,
                        max_tokens=max_tokens,
                        request_id=request_id,
                    )
                    with self._request_lock:
                        if self._requests[request_id].get("cancelled"):
                            return
                        self._requests[request_id]["status"] = "done"
                        self._requests[request_id]["result"] = result
                        self._requests[request_id]["finished_at"] = time.time()
            except _ContinueGroupFlow as cont:
                # Handled by wrapping — see below
                self._run_group_generation_flow(
                    cont.processed_files,
                    cont.language,
                    cont.text,
                    cont.participants,
                    cont.request_id,
                    cont.from_mic,
                    cont.provider,
                    temperature=temperature,
                    top_p=top_p,
                    max_tokens=max_tokens,
                )
            except Exception as e:
                logger.error(f"Worker error: {traceback.format_exc()}")
                with self._request_lock:
                    if not self._requests.get(request_id, {}).get("cancelled"):
                        self._requests[request_id]["status"] = "error"
                        self._requests[request_id]["error"] = str(e)
                        self._requests[request_id]["finished_at"] = time.time()
            finally:
                with self._request_lock:
                    if self._active_request_by_provider.get(provider) == request_id:
                        status = (self._requests.get(request_id) or {}).get("status")
                        if status in ("done", "error", "cancelled"):
                            self._active_request_by_provider.pop(provider, None)

        t = threading.Thread(target=parent_ctx.run, args=(worker,))
        t.daemon = True
        t.start()
        return {"request_id": request_id}


    def _run_group_generation_flow(
        self,
        processed_files,
        language,
        text,
        participants,
        request_id,
        from_mic,
        provider,
        temperature=None,
        top_p=None,
        max_tokens=None,
    ):
        """Continue group parallel generation after preprocess + user message append."""
        if self._is_request_cancelled(request_id):
            return
        # 3. Call each model in parallel
        # Truncate to MAX_HISTORY_MESSAGES messages to control token usage in long conversations
        with self._provider_lock(provider):
            history_snapshot = list(self._history.get(provider, [])[:-1])[-MAX_HISTORY_MESSAGES:]
        generating_participants = list(participants)

        with self._request_lock:
            self._requests[request_id]["current_respondent"] = ", ".join(generating_participants)
            self._requests[request_id]["steps"] = [f"{p} is generating..." for p in generating_participants]

        def call_participant(p):
            if self._is_request_cancelled(request_id):
                return
            # Cap concurrent provider calls dynamically to allow all group participants to run simultaneously.
            effective_parallel = max(len(participants), GROUP_MAX_PARALLEL)
            with Semaphore("group_parallel", max_concurrent=effective_parallel):
                if self._is_request_cancelled(request_id):
                    return
                _run_group_participant(p)

        def _run_group_participant(p):
            reply = None
            token_info = None
            chat = None
            detected_group_lang = language or get_default_conversation_language()
            try:
                chat = self._chat_instances.get(p)
                if not chat:
                    self._init_chat(p)
                    chat = self._chat_instances.get(p)

                if not chat:
                    logger.error(f"Could not initialize participant {p}")
                    reply = f"⚠️ Failed to initialize participant {p}"
                    token_info = None
                else:
                    # Document guidelines always injected at session init via inject_media_guidelines.
                    # Inject group discussion guidelines to participate, debate, and collaborate
                    other_parts = [part for part in participants if part != p]
                    if hasattr(chat, 'inject_group_discussion_guidelines'):
                        chat.inject_group_discussion_guidelines(p, other_parts)

                    # Enforce Spanish default language (or language passed from frontend)
                    history_for_model = BaseChat.filter_history_for_model(
                        format_history_for_group_participant(history_snapshot, p)
                    )
                    text_for_model = self._text_for_model_with_rag(text)
                    if processed_files:
                        res = chat.generate_response_with_inline_files(
                            text_for_model, 
                            history_for_model, 
                            processed_files,
                            force_language=detected_group_lang
                        )
                        if isinstance(res, tuple) and len(res) == 3:
                            reply, token_info, enriched_text = res
                        else:
                            reply, token_info = res
                    else:
                        reply, token_info = chat.generate_response(
                            text_for_model, 
                            history=history_for_model,
                            force_language=detected_group_lang
                        )
            except Exception as e:
                logger.error(f"Error generating response from {p}: {e}")
                reply = f"⚠️ Failed to get response from {p}: {str(e)}"
                token_info = None

            if not isinstance(reply, str):
                reply = f"⚠️ Empty reply from {p}"
            else:
                reply = BaseChat.coerce_non_empty_reply(reply)
                if reply.startswith("Error:"):
                    reply = _friendly_error_message(reply, detected_group_lang)
                
            notification_message = None
            doc_files = []
            # Document generation driven by LLM-emitted tags in the reply
            doc_type, reply = _extract_document_directive(reply)
            if doc_type and not reply.startswith("Error:") and not reply.startswith("⚠️"):
                try:
                    generated_dir = os.path.join(self._tenant_log_root(), 'generated_files')
                    os.makedirs(generated_dir, exist_ok=True)
                    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
                    
                    filename = None
                    filepath = None
                    mime_type = None

                    if doc_type == 'docx':
                        filename = f"Documento_{p}_{timestamp_str}.docx"
                        filepath = os.path.join(generated_dir, filename)
                        generate_docx(reply, filepath)
                        mime_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                    elif doc_type == 'xlsx':
                        filename = f"Hoja_Excel_{p}_{timestamp_str}.xlsx"
                        filepath = os.path.join(generated_dir, filename)
                        generate_xlsx(reply, filepath)
                        mime_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    elif doc_type == 'pptx':
                        filename = f"Presentacion_{p}_{timestamp_str}.pptx"
                        filepath = os.path.join(generated_dir, filename)
                        generate_pptx(reply, filepath)
                        mime_type = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
                        
                    if filepath and filename and mime_type and os.path.exists(filepath):
                        file_size = os.path.getsize(filepath)
                        doc_files.append({
                            "name": filename,
                            "mime_type": mime_type,
                            "size": file_size,
                            "path": filepath
                        })
                        logger.info(f"Group participant {p} generated {doc_type} at {filepath}")
                        # Try to open the file automatically for instant user verification
                        try:
                            if os.name == 'nt':
                                os.startfile(filepath)
                            elif sys.platform == 'darwin':
                                subprocess.Popen(['open', filepath])
                            else:
                                subprocess.Popen(['xdg-open', filepath])
                        except Exception as open_err:
                            logger.warning(f"Could not open auto-generated file in group: {open_err}")
                        
                        # Construct notification message but DO NOT overwrite reply yet
                        user_lang = language or get_default_conversation_language()
                        notification_message = _get_file_generated_message(doc_type, filename, user_lang)
                except Exception as gen_err:
                    logger.error(f"Error generating document in group for {p}: {gen_err}", exc_info=True)

            # Fallback: scan assistant's reply text for local document paths to display as attachment cards
            try:
                paths_in_reply = re.findall(r'([A-Za-z]:\\[^\s\[\]"\']+\.(?:docx|xlsx|pptx))', reply)
                for path in paths_in_reply:
                    if os.path.exists(path):
                        filename = os.path.basename(path)
                        mime_type = "application/octet-stream"
                        if filename.endswith(".docx"):
                            mime_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                        elif filename.endswith(".xlsx"):
                            mime_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                        elif filename.endswith(".pptx"):
                            mime_type = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
                            
                        # Avoid duplicate attachments
                        if not any(f["path"] == path for f in doc_files):
                            doc_files.append({
                                "name": filename,
                                "mime_type": mime_type,
                                "size": os.path.getsize(path),
                                "path": path
                            })
            except Exception as scan_err:
                logger.warning(f"Error scanning reply for document paths: {scan_err}")

            # Intercept media generation commands from the group participant response
            img_prompt, reply = _extract_image_directive(reply)
            aud_prompt, reply = _extract_audio_directive(reply)

            image_data = None
            audio_data = None
            audio_mime = None
            audio_script = None

            if img_prompt and hasattr(chat, 'generate_image'):
                logger.info(f"Group participant {p} triggered image generation automatically for prompt: {img_prompt}")
                img_bytes, mime, err, token_info_img = chat.generate_image(img_prompt)
                if not err and img_bytes is not None:
                    b64_img = base64.b64encode(img_bytes).decode('utf-8')
                    if not reply:
                        reply = _media_chrome_message("image", img_prompt, detected_group_lang)
                    image_data = f"data:{mime or 'image/png'};base64,{b64_img}"
                    token_info = _merge_token_info(token_info, token_info_img)
                else:
                    fail_msg = err or "empty image bytes"
                    reply = (reply + f"\n\n⚠️ *(Image generation failed: {fail_msg})*").strip()

            if aud_prompt and hasattr(chat, 'generate_audio'):
                logger.info(f"Group participant {p} triggered audio generation automatically for prompt: {aud_prompt}")
                audio_bytes, mime, err, token_info_aud, script_text = chat.generate_audio(aud_prompt, language=detected_group_lang)
                if not err:
                    if mime == "browser-tts":
                        if not reply:
                            reply = _media_chrome_message("audio_browser", script_text, detected_group_lang)
                        audio_mime = mime
                        audio_script = script_text
                    else:
                        if audio_bytes is not None:
                            b64_audio = base64.b64encode(audio_bytes).decode('utf-8')
                            if not reply:
                                reply = _media_chrome_message("audio", aud_prompt, detected_group_lang)
                            audio_data = f"data:{mime};base64,{b64_audio}"
                            audio_mime = mime
                            if token_info and token_info_aud:
                                token_info = _merge_token_info(token_info, token_info_aud)
                        else:
                            reply = (reply + '\n\n⚠️ *(Audio generation failed: empty audio)*').strip()
                else:
                    reply = (reply + f"\n\n⚠️ *(Audio generation failed: {err})*").strip()

            extract_candidates = self._collect_extract_attachment_candidates(processed_files)
            reply = self._apply_ignite_extract_from_reply(
                reply,
                extract_candidates,
                detected_group_lang,
                request_id=request_id,
                log_prefix=f"Group participant {p}:",
                user_text=text,
                chat_provider=p,
                chat_model=self._current_model.get(p),
            )

            if token_info and not isinstance(token_info, dict):
                if hasattr(token_info, "to_legacy_dict"):
                    token_info = token_info.to_legacy_dict()
                elif hasattr(token_info, "model_dump"):
                    token_info = token_info.model_dump()

            assistant_msg = {
                "role": "assistant",
                "provider": p,
                "model": self._current_model.get(p, ""),
                "content": reply,
                "token_info": token_info,
                "timestamp": _get_time_str(),
                "iso_timestamp": _get_iso_timestamp(),
                "date": _get_date_str(),
                "files": doc_files
            }
            if image_data:
                assistant_msg["image_data"] = image_data
            if audio_data:
                assistant_msg["audio_data"] = audio_data
            if audio_mime:
                assistant_msg["audio_mime"] = audio_mime
            if audio_script:
                assistant_msg["script"] = audio_script

            if notification_message:
                assistant_msg["notification_message"] = notification_message
            
            if token_info:
                with self._provider_lock(provider):
                    self._token_totals[provider] = self._token_totals.get(provider, 0) + (
                        token_info.get("candidates_tokens", 0)
                        + token_info.get("thinking_tokens", 0)
                    )

            # Defer disk save: one write per group turn (after join) instead of
            # rewriting the full session JSON once per participant.
            self._append_history_message(provider, assistant_msg, save=False)
            self._index_conversation_turn_for_rag(text, reply, provider=provider)

            reply_entry = {
                "provider": p,
                "reply": notification_message if notification_message else reply,
                "token_info": token_info,
                "files": doc_files,
            }
            if image_data:
                reply_entry["image_data"] = image_data
            if audio_data:
                reply_entry["audio_data"] = audio_data
            if audio_mime:
                reply_entry["audio_mime"] = audio_mime
            if audio_script:
                reply_entry["script"] = audio_script

            with self._request_lock:
                self._requests[request_id]["replies"].append(reply_entry)
                if p in generating_participants:
                    generating_participants.remove(p)
                self._requests[request_id]["current_respondent"] = (
                    ", ".join(generating_participants) if generating_participants else None
                )
                self._requests[request_id]["steps"] = (
                    [f"{part} is generating..." for part in generating_participants]
                    if generating_participants
                    else ["Done"]
                )

        threads = []
        for p in participants:
            t = threading.Thread(target=call_participant, args=(p,))
            threads.append(t)
            t.start()
            
        for t in threads:
            t.join()

        # Single coalesced save for the whole group turn.
        self._recalculate_token_totals(provider, accrue_lifetime=True)
        self._save_conversation_history(provider)

        goodbye_detected = _is_goodbye_message(text)
        for r in self._requests[request_id]["replies"]:
            if _is_goodbye_message(r.get("reply", "")):
                goodbye_detected = True
                break

        with self._request_lock:
            self._requests[request_id]["status"] = "done"
            self._requests[request_id]["result"] = {
                "status": "success",
                "provider": provider,
                "is_group": True,
                "replies": self._requests[request_id]["replies"],
                "token_totals": self._token_totals,
                "user_prompt": text,
                "goodbye_detected": goodbye_detected,
                "from_mic": from_mic
            }

    def _prune_requests_locked(self):
        """Drop finished request entries after a grace period (memory leak guard).

        Caller must hold ``self._request_lock``. Finished entries are lazily
        timestamped on first sweep so every done/error site stays simple.
        """
        ttl = float(os.getenv("IGNITE_REQUEST_TTL_SECONDS", "900"))
        now = time.time()
        stale = []
        for rid, req in self._requests.items():
            if req.get("status") in ("done", "error", "cancelled"):
                finished_at = req.get("finished_at")
                if finished_at is None:
                    req["finished_at"] = now
                elif (now - float(finished_at)) > ttl:
                    stale.append(rid)
        for rid in stale:
            del self._requests[rid]

    def get_generation_status(self, request_id, since_reply_index=0):
        """Poll for status. Returns dict with 'status', 'steps', 'result', 'error'.

        ``since_reply_index`` returns only new group replies so concurrent polls
        do not re-ship large base64 media payloads on every tick.
        """
        try:
            since = int(since_reply_index or 0)
        except (TypeError, ValueError):
            since = 0
        if since < 0:
            since = 0

        with self._request_lock:
            self._prune_requests_locked()
            req = self._requests.get(request_id)
            if not req:
                return {"status": "unknown", "error": "Request not found"}
            if req["status"] == "queued":
                req["status"] = "processing"
            all_replies = req.get("replies", []) or []
            if since > len(all_replies):
                since = len(all_replies)
            delta = all_replies[since:]
            result = req.get("result")
            # Final result already contains full replies; omit duplicate fat list
            # on the done poll when the client has already streamed them.
            if (
                req["status"] == "done"
                and isinstance(result, dict)
                and result.get("is_group")
                and since >= len(all_replies)
            ):
                result = dict(result)
                result["replies"] = []
            return {
                "status": req["status"],
                "steps": list(req.get("steps", []) or []),
                "result": result,
                "error": req.get("error"),
                "replies": list(delta),
                "reply_offset": since,
                "replies_total": len(all_replies),
                "current_respondent": req.get("current_respondent"),
            }

    # ---------- Synchronous message (blocking) – kept for compatibility ----------
    def send_message(self, text, files=None, language=None, from_mic=False, temperature=None, top_p=None, max_tokens=None):
        """Synchronous version. Blocks until done."""
        return self._send_message_sync(text, files, language, from_mic, temperature=temperature, top_p=top_p, max_tokens=max_tokens)

    # Function to send the message
    def _send_message_sync(
        self,
        text,
        files=None,
        language=None,
        from_mic=False,
        provider=None,
        temperature=None,
        top_p=None,
        max_tokens=None,
        request_id=None,
    ):
        """Core synchronous implementation, used by both sync and async."""
        if not provider:
            provider = self._current_provider
        chat = self._chat_instances.get(provider)
        if not chat:
            self._init_chat(provider)
            chat = self._chat_instances.get(provider)
        if not chat:
            detail = self._provider_init_errors.get(provider) or "Chat instance not initialized."
            return {
                "status": "error",
                "message": f"Provider '{provider}' is unavailable: {detail}",
                "provider": provider,
                "from_mic": from_mic,
            }
            
        # Ensure language variable is populated for the rest of the function (falls back to system default)
        detected_lang = language or get_default_conversation_language()
        language = detected_lang

        # Preprocess input using the unified helper (sticky conversation language)
        preprocess = self._preprocess_input(
            text,
            files,
            from_mic,
            language,
            chat,
            provider,
            history=list(self._history.get(provider, [])),
        )
        if preprocess["error"]:
            friendly = preprocess["error"]
            # Append assistant error to history
            self._history[provider].append({
                "role": "assistant",
                "content": friendly,
                "provider": provider,
                "timestamp": _get_time_str(),
                "iso_timestamp": _get_iso_timestamp(),
                "date": _get_date_str(),
                "from_mic": from_mic
            })
            self._recalculate_token_totals(provider)
            self._save_conversation_history(provider)
            return {
                "status": "error",
                "message": friendly,
                "provider": provider,
                "from_mic": from_mic
            }

        text = preprocess["text"]
        processed_files = preprocess["files"]
        language = preprocess["language"]

        # Calculate prompt token counts
        user_tokens = _count_prompt_tokens(chat, text)

        # Capture history copy for the model call BEFORE appending the new user message
        # Truncate to MAX_HISTORY_MESSAGES messages to control token usage in long conversations
        history_for_model = BaseChat.filter_history_for_model(
            list(self._history[provider])[-MAX_HISTORY_MESSAGES:]
        )

        self._append_history_message(
            provider,
            {
                "role": "user",
                "content": text,
                "provider": provider,
                "files": list(processed_files) if processed_files else [],
                "conversation_language": language,
                "token_info": {
                    "total_tokens": user_tokens,
                    "prompt_tokens": user_tokens,
                    "candidates_tokens": 0,
                    "thinking_tokens": 0,
                },
                "timestamp": _get_time_str(),
                "iso_timestamp": _get_iso_timestamp(),
                "date": _get_date_str(),
                "from_mic": from_mic,
            },
            save=True,
        )

        # Contest / Architect path: Ignite turn → Foundry Traces + Plan/Workflow brain.
        # Off by default (FOUNDRY_ORCHESTRATION_ENABLED). Does not replace product Chat repos.
        foundry_out = maybe_run_foundry_turn(
            text, processed_files, language=language
        )
        if foundry_out is not None:
            reply = foundry_out.get("message") or ""
            status = foundry_out.get("status") or "success"
            self._append_history_message(
                provider,
                {
                    "role": "assistant",
                    "content": reply,
                    "provider": provider,
                    "foundry": True,
                    "foundry_source": foundry_out.get("foundry_source"),
                    "foundry_plan": foundry_out.get("foundry_plan"),
                    "foundry_trace_tags": foundry_out.get("foundry_trace_tags"),
                    "conversation_language": language,
                    "timestamp": _get_time_str(),
                    "iso_timestamp": _get_iso_timestamp(),
                    "date": _get_date_str(),
                    "from_mic": from_mic,
                },
                save=True,
            )
            return {
                "status": status,
                "message": reply,
                "provider": provider,
                "from_mic": from_mic,
                "foundry": True,
                "foundry_source": foundry_out.get("foundry_source"),
                "foundry_plan": foundry_out.get("foundry_plan"),
                "foundry_trace_tags": foundry_out.get("foundry_trace_tags"),
                "foundry_tracing_enabled": foundry_out.get("foundry_tracing_enabled"),
            }

        # Normal chat or file analysis
        try:
            if hasattr(chat, 'remove_group_discussion_guidelines'):
                chat.remove_group_discussion_guidelines()

            # Fast-path: pure image requests skip the slow Pro "thinking" chat round-trip.
            # Build prompt + generate image directly, then return a short confirmation.
            if (
                not processed_files
                and hasattr(chat, "generate_image")
                and hasattr(chat, "is_direct_image_request")
                and chat.is_direct_image_request(text)
            ):
                logger.info(f"Image fast-path triggered for: {text[:140]}...")
                is_spanish = language and str(language).startswith("es")
                img_bytes, mime, err, token_info_img = chat.generate_image(text)
                if not err and img_bytes is not None:
                    b64_img = base64.b64encode(img_bytes).decode("utf-8")
                    image_data = f"data:{mime};base64,{b64_img}"
                    reply = (
                        "¡Claro! Aquí tienes la imagen que pediste."
                        if is_spanish
                        else "Sure! Here is the image you requested."
                    )
                    token_info = token_info_img
                    if token_info and not isinstance(token_info, dict):
                        if hasattr(token_info, "to_legacy_dict"):
                            token_info = token_info.to_legacy_dict()
                        elif hasattr(token_info, "model_dump"):
                            token_info = token_info.model_dump()

                    assistant_msg = {
                        "role": "assistant",
                        "content": reply,
                        "token_info": token_info,
                        "timestamp": _get_time_str(),
                        "iso_timestamp": _get_iso_timestamp(),
                        "date": _get_date_str(),
                        "from_mic": from_mic,
                        "files": [],
                        "image_data": image_data,
                    }
                    self._history[provider].append(assistant_msg)
                    self._recalculate_token_totals(provider, accrue_lifetime=True)
                    self._save_conversation_history(provider)
                    return {
                        "status": "success",
                        "provider": provider,
                        "reply": reply,
                        "token_info": token_info,
                        "goodbye_detected": False,
                        "from_mic": from_mic,
                        "user_prompt_tokens": user_tokens,
                        "token_totals": self._token_totals,
                        "user_prompt": text,
                        "files": [],
                        "image_data": image_data,
                    }

                # Do not fall through to Pro chat (would re-run image generation and feel "stuck").
                fail_msg = err or "empty image bytes"
                logger.warning(f"Image fast-path failed: {fail_msg}")
                is_spanish = language and str(language).startswith("es")
                reply = (
                    f"⚠️ No pude generar la imagen: {fail_msg}"
                    if is_spanish
                    else f"⚠️ Could not generate the image: {fail_msg}"
                )
                assistant_msg = {
                    "role": "assistant",
                    "content": reply,
                    "timestamp": _get_time_str(),
                    "iso_timestamp": _get_iso_timestamp(),
                    "date": _get_date_str(),
                    "from_mic": from_mic,
                    "files": [],
                }
                self._history[provider].append(assistant_msg)
                self._save_conversation_history(provider)
                return {
                    "status": "error",
                    "message": reply,
                    "provider": provider,
                    "from_mic": from_mic,
                    "user_prompt": text,
                }

            # Document generation guidelines are always injected at session init via inject_media_guidelines.
            # No need to conditionally re-inject here based on user input regex.

            text_for_model = self._text_for_model_with_rag(text)

            if processed_files:
                res = chat.generate_response_with_inline_files(
                    text_for_model, 
                    history_for_model, 
                    processed_files, 
                    force_language=language,
                    temperature=temperature, 
                    top_p=top_p, 
                    max_tokens=max_tokens
                )
                if isinstance(res, tuple) and len(res) == 3:
                    reply, token_info, enriched_text = res
                    if self._history[provider] and self._history[provider][-1]["role"] == "user":
                        self._history[provider][-1]["content"] = enriched_text
                else:
                    reply, token_info = res
            else:
                reply, token_info = chat.generate_response(
                    text_for_model, 
                    history=history_for_model, 
                    force_language=language,
                    temperature=temperature, 
                    top_p=top_p, 
                    max_tokens=max_tokens
                )

            reply = BaseChat.coerce_non_empty_reply(reply)

            # Handle errors
            if reply.startswith("Error:"):
                friendly = _friendly_error_message(reply, language)
                reply = friendly
                token_info = None

            # Goodbye detection
            goodbye_detected = _is_goodbye_message(text) or _is_goodbye_message(reply)
            if goodbye_detected:
                # Remove [GOODBYE] tag if present (we don't add it in API, but just in case)
                reply = re.sub(r'\[GOODBYE\]', '', reply, flags=re.IGNORECASE).strip()
            
            # Document auto-generation: driven by LLM-emitted tags [GENERATE_DOCX/XLSX/PPTX]
            # The LLM decides whether to generate a document based on conversational intent,
            # not hardcoded keyword regex on the user's raw input.
            notification_message = None
            assistant_files = []
            doc_type, reply = _extract_document_directive(reply)
            if doc_type and not reply.startswith("Error:"):
                try:
                    generated_dir = os.path.join(self._tenant_log_root(), 'generated_files')
                    os.makedirs(generated_dir, exist_ok=True)
                    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
                    
                    filename = None
                    filepath = None
                    mime_type = None

                    if doc_type == 'docx':
                        filename = f"Documento_{timestamp_str}.docx"
                        filepath = os.path.join(generated_dir, filename)
                        generate_docx(reply, filepath)
                        mime_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                    elif doc_type == 'xlsx':
                        filename = f"Hoja_Excel_{timestamp_str}.xlsx"
                        filepath = os.path.join(generated_dir, filename)
                        generate_xlsx(reply, filepath)
                        mime_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    elif doc_type == 'pptx':
                        filename = f"Presentacion_{timestamp_str}.pptx"
                        filepath = os.path.join(generated_dir, filename)
                        generate_pptx(reply, filepath)
                        mime_type = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
                        
                    if filepath and filename and mime_type and os.path.exists(filepath):
                        file_size = os.path.getsize(filepath)
                        assistant_files.append({
                            "name": filename,
                            "mime_type": mime_type,
                            "size": file_size,
                            "path": filepath
                        })
                        logger.info(f"Auto-generated {doc_type} attachment for assistant message at {filepath}")
                        # Try to open the file automatically for instant user verification
                        try:
                            if os.name == 'nt':
                                os.startfile(filepath)
                            elif sys.platform == 'darwin':
                                subprocess.Popen(['open', filepath])
                            else:
                                subprocess.Popen(['xdg-open', filepath])
                        except Exception as open_err:
                            logger.warning(f"Could not open auto-generated file: {open_err}")
                        
                        # Construct notification message but DO NOT overwrite reply yet
                        lang_to_use = language or get_default_conversation_language()
                        notification_message = _get_file_generated_message(doc_type, filename, lang_to_use)
                except Exception as gen_err:
                    logger.error(f"Error during automatic document generation: {gen_err}", exc_info=True)

            # Fallback: scan assistant's reply text for local document paths (e.g. C:\...\*.docx) to display as attachment cards
            try:
                paths_in_reply = re.findall(r'([A-Za-z]:\\[^\s\[\]"\']+\.(?:docx|xlsx|pptx))', reply)
                for path in paths_in_reply:
                    if os.path.exists(path):
                        filename = os.path.basename(path)
                        mime_type = "application/octet-stream"
                        if filename.endswith(".docx"):
                            mime_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                        elif filename.endswith(".xlsx"):
                            mime_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                        elif filename.endswith(".pptx"):
                            mime_type = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
                            
                        # Avoid duplicate attachments
                        if not any(f["path"] == path for f in assistant_files):
                            assistant_files.append({
                                "name": filename,
                                "mime_type": mime_type,
                                "size": os.path.getsize(path),
                                "path": path
                            })
                            logger.info(f"Detected and attached document mentioned in reply: {path}")
            except Exception as scan_err:
                logger.warning(f"Error scanning reply for document paths: {scan_err}")

            # Intercept media generation commands from the LLM response
            img_prompt, reply = _extract_image_directive(reply)
            aud_prompt, reply = _extract_audio_directive(reply)

            image_data = None
            audio_data = None
            audio_mime = None
            audio_script = None

            if img_prompt and hasattr(chat, 'generate_image'):
                logger.info(f"LLM triggered image generation automatically for prompt: {img_prompt}")
                img_bytes, mime, err, token_info_img = chat.generate_image(img_prompt)
                if not err and img_bytes is not None:
                    b64_img = base64.b64encode(img_bytes).decode('utf-8')
                    if not reply:
                        reply = _media_chrome_message("image", img_prompt, language)
                    image_data = f"data:{mime or 'image/png'};base64,{b64_img}"
                    token_info = _merge_token_info(token_info, token_info_img)
                else:
                    fail_msg = err or "empty image bytes"
                    reply = (reply + f"\n\n⚠️ *(Image generation failed: {fail_msg})*").strip()

            if aud_prompt and hasattr(chat, 'generate_audio'):
                logger.info(f"LLM triggered audio generation automatically for prompt: {aud_prompt}")
                audio_bytes, mime, err, token_info_aud, script_text = chat.generate_audio(aud_prompt, language=language)
                if not err:
                    if mime == "browser-tts":
                        if not reply:
                            reply = _media_chrome_message("audio_browser", script_text, language)
                        audio_mime = mime
                        audio_script = script_text
                    else:
                        if audio_bytes is not None:
                            b64_audio = base64.b64encode(audio_bytes).decode('utf-8')
                            if not reply:
                                reply = _media_chrome_message("audio", aud_prompt, language)
                            audio_data = f"data:{mime};base64,{b64_audio}"
                            audio_mime = mime
                            if token_info and token_info_aud:
                                token_info = _merge_token_info(token_info, token_info_aud)
                        else:
                            reply = (reply + '\n\n⚠️ *(Audio generation failed: empty audio)*').strip()
                else:
                    reply = (reply + f"\n\n⚠️ *(Audio generation failed: {err})*").strip()

            extract_candidates = self._collect_extract_attachment_candidates(processed_files, files)
            reply = self._apply_ignite_extract_from_reply(
                reply,
                extract_candidates,
                language,
                request_id=request_id,
                user_text=text,
                chat_provider=provider,
                chat_model=self._current_model.get(provider),
            )

            if token_info and not isinstance(token_info, dict):
                if hasattr(token_info, "to_legacy_dict"):
                    token_info = token_info.to_legacy_dict()
                elif hasattr(token_info, "model_dump"):
                    token_info = token_info.model_dump()

            if user_tokens and not isinstance(user_tokens, dict):
                if hasattr(user_tokens, "to_legacy_dict"):
                    user_tokens = user_tokens.to_legacy_dict()
                elif hasattr(user_tokens, "model_dump"):
                    user_tokens = user_tokens.model_dump()

            assistant_msg = {
                "role": "assistant",
                "content": reply,
                "provider": provider,
                "token_info": token_info,
                "timestamp": _get_time_str(),
                "iso_timestamp": _get_iso_timestamp(),
                "date": _get_date_str(),
                "from_mic": from_mic,
                "files": assistant_files
            }
            if image_data:
                assistant_msg["image_data"] = image_data
            if audio_data:
                assistant_msg["audio_data"] = audio_data
            if audio_mime:
                assistant_msg["audio_mime"] = audio_mime
            if audio_script:
                assistant_msg["script"] = audio_script

            if notification_message:
                assistant_msg["notification_message"] = notification_message

            self._append_history_message(provider, assistant_msg, save=False)
            self._recalculate_token_totals(provider, accrue_lifetime=True)
            self._save_conversation_history(provider)
            self._index_conversation_turn_for_rag(text, reply, provider=provider)

            res_dict = {
                "status": "success",
                "provider": provider,
                "reply": notification_message if notification_message else reply,
                "token_info": token_info,
                "goodbye_detected": goodbye_detected,
                "from_mic": from_mic,
                "user_prompt_tokens": user_tokens,
                "token_totals": self._token_totals,
                "user_prompt": text,
                "files": assistant_files
            }
            if image_data:
                res_dict["image_data"] = image_data
            if audio_data:
                res_dict["audio_data"] = audio_data
            if audio_mime:
                res_dict["audio_mime"] = audio_mime
            if audio_script:
                res_dict["script"] = audio_script
            return res_dict
        except Exception as e:
            logger.error(f"Message error: {traceback.format_exc()}")
            friendly = _friendly_error_message(str(e), language)
            self._history[provider].append({
                "role": "assistant",
                "content": friendly,
                "provider": provider,
                "timestamp": _get_time_str(),
                "iso_timestamp": _get_iso_timestamp(),
                "date": _get_date_str(),
                "from_mic": from_mic
            })
            self._save_conversation_history(provider)
            return {"status": "error", "message": friendly, "provider": provider, "from_mic": from_mic}

    # ---------- Standalone generation methods (for manual triggering) ----------
    # Function to generate the image
    def generate_image(self, prompt):
        provider = self._current_provider
        chat = self._chat_instances.get(provider)
        if hasattr(chat, 'generate_image'):
            try:
                img_bytes, mime, err, token_info = chat.generate_image(prompt)
                if err:
                    return {"status": "error", "message": err}
                if img_bytes is None:
                    return {"status": "error", "message": "Image generation returned empty image bytes."}
                b64_img = base64.b64encode(img_bytes).decode('utf-8')
                return {
                    "status": "success",
                    "image_data": f"data:{mime};base64,{b64_img}",
                    "token_info": token_info
                }
            except Exception as e:
                return {"status": "error", "message": str(e)}
        return {"status": "error", "message": "Image generation not supported by this provider."}

    # Function to generate the audio
    def generate_audio(self, prompt):
        provider = self._current_provider
        chat = self._chat_instances.get(provider)
        if hasattr(chat, 'generate_audio'):
            try:
                audio_bytes, mime, err, token_info, script = chat.generate_audio(prompt)
                if err:
                    return {"status": "error", "message": err}
                if mime == "browser-tts":
                    return {
                        "status": "success",
                        "audio_data": None,
                        "audio_mime": "browser-tts",
                        "script": script,
                        "token_info": token_info
                    }
                if audio_bytes is None:
                    return {"status": "error", "message": "Audio generation returned empty audio bytes."}
                b64_audio = base64.b64encode(audio_bytes).decode('utf-8')
                return {
                    "status": "success",
                    "audio_data": f"data:{mime};base64,{b64_audio}",
                    "audio_mime": mime,
                    "token_info": token_info
                }
            except Exception as e:
                return {"status": "error", "message": str(e)}
        return {"status": "error", "message": "Audio generation not supported by this provider."}

    def determine_voice_category(self, text):
        """Determine voice category for a text content."""
        try:
            voice_proc = VoiceProcessor()
            return voice_proc.determine_voice_category(text)
        except Exception as e:
            logger.error(f"Error determining voice category: {e}")
            return "adult_male"

    def generate_cartesia_tts(self, text, voice_category=None):
        """Generates TTS using Cartesia API and returns base64 MP3 data."""
        voice_proc = VoiceProcessor()
        if not voice_proc.is_configured():
            return {"status": "error", "message": "Cartesia API key not configured"}
        
        try:
            # Determine voice category based on the text contents if not provided
            if not voice_category:
                voice_category = voice_proc.determine_voice_category(text)
            audio_bytes = voice_proc.generate_tts(text, voice_category=voice_category)
            if audio_bytes is None:
                return {"status": "error", "message": "Cartesia TTS generated empty audio."}
            b64_audio = base64.b64encode(audio_bytes).decode("utf-8")
            return {"status": "success", "audio_base64": b64_audio}
        except Exception as e:
            logger.error(f"Failed to generate Cartesia TTS: {e}")
            return {"status": "error", "message": str(e)}

    # Function to export a message's content to a Word, Excel, or PowerPoint document
    def export_message_to_file(self, content, file_type):
        """Displays a native save dialog and generates the requested document using dynamic generator."""
        if not self._window:
            return {"status": "error", "message": "WebView window is not initialized."}
            
        file_types = {
            'docx': ('Word Document (*.docx)', '*.docx'),
            'xlsx': ('Excel Spreadsheet (*.xlsx)', '*.xlsx'),
            'pptx': ('PowerPoint Presentation (*.pptx)', '*.pptx')
        }
        
        file_type = file_type.lower()
        if file_type not in file_types:
            return {"status": "error", "message": f"Unsupported file type: {file_type}"}
            
        label, pattern = file_types[file_type]
        
        try:
            if webview is None:
                return {
                    "status": "error",
                    "message": "Native save dialog requires the local desktop shell (pywebview).",
                }
            # Show Native Save File Dialog
            result = self._window.create_file_dialog(
                dialog_type=webview.SAVE_DIALOG,
                file_types=(label, pattern),
                save_filename=f"document.{file_type}"
            )
            
            if not result:
                return {"status": "cancelled"}
                
            filepath = result[0] if isinstance(result, (list, tuple)) else result
            if not filepath:
                return {"status": "cancelled"}
                
            # Perform document generation based on file_type
            
            if file_type == 'docx':
                generate_docx(content, filepath)
            elif file_type == 'xlsx':
                generate_xlsx(content, filepath)
            elif file_type == 'pptx':
                generate_pptx(content, filepath)
                
            # Try to open the file automatically for instant user verification
            try:
                if os.name == 'nt':
                    os.startfile(filepath)
                elif sys.platform == 'darwin':
                    subprocess.Popen(['open', filepath])
                else:
                    subprocess.Popen(['xdg-open', filepath])
            except Exception as open_err:
                logger.warning(f"Could not open exported file: {open_err}")
                
            return {"status": "success", "filepath": filepath}
            
        except Exception as e:
            logger.error(f"Error during document export ({file_type}): {e}", exc_info=True)
            return {"status": "error", "message": str(e)}

    # Function to open a local file path using the default system handler
    def get_local_file_media_url(self, filepath: str):
        """Return a file:// URI for in-webview audio/video preview (path must exist locally)."""
        try:
            if not filepath or not isinstance(filepath, str):
                return {"status": "error", "message": "Missing file path."}
            resolved = os.path.abspath(os.path.normpath(filepath))
            if not os.path.isfile(resolved):
                return {"status": "error", "message": "File does not exist."}
            import pathlib

            return {"status": "success", "url": pathlib.Path(resolved).as_uri()}
        except Exception as e:
            logger.error("get_local_file_media_url failed for %s: %s", filepath, e, exc_info=True)
            return {"status": "error", "message": str(e)}

    def open_file_path(self, filepath):
        """Opens a local file in the default associated application (e.g. Word, Excel, PowerPoint)."""
        try:
            if not os.path.exists(filepath):
                return {"status": "error", "message": "File does not exist."}
            if os.name == 'nt':
                os.startfile(filepath)
            elif sys.platform == 'darwin':
                subprocess.Popen(['open', filepath])
            else:
                subprocess.Popen(['xdg-open', filepath])
            return {"status": "success"}
        except Exception as e:
            logger.error(f"Error opening file path {filepath}: {e}", exc_info=True)
            return {"status": "error", "message": str(e)}

    # Function to save base64 file data directly to the user's Downloads folder
    def save_file_to_downloads(self, base64_data, filename):
        """Decodes base64 file data and saves it directly to the user's Downloads directory, opening it automatically."""
        try:
            downloads_dir = get_downloads_path()
            os.makedirs(downloads_dir, exist_ok=True)
            target_path = os.path.join(downloads_dir, filename)

            if "," in base64_data:
                base64_data = base64_data.split(",")[1]

            raw_bytes = base64.b64decode(base64_data)
            with open(target_path, "wb") as f:
                f.write(raw_bytes)

            if os.name == 'nt':
                try:
                    os.startfile(target_path)
                except Exception as open_err:
                    logger.warning(f"Could not open saved file: {open_err}")
            return {"status": "success", "filepath": target_path}
        except Exception as e:
            logger.error(f"Error in save_file_to_downloads: {e}", exc_info=True)
            return {"status": "error", "message": str(e)}

    # Function to translate message using current active LLM
    def translate_message(self, text, target_language):
        provider = self._current_provider
        chat = self._chat_instances.get(provider)
        if not chat:
            return {"status": "error", "message": "Chat not initialized"}
            
        prompt = f"Translate the following text to {target_language}. Respond ONLY with the translation, do not include any intro, outro, or quotes:\n\n{text}"
        try:
            force_lang = 'es' if target_language.lower() == 'spanish' else 'en'
            reply, token_info = chat.generate_response(prompt, history=[], force_language=force_lang)
            return {"status": "success", "translation": reply}
        except Exception as e:
            logger.error(f"Error in translate_message: {e}", exc_info=True)
            return {"status": "error", "message": str(e)}

    # Function to summarize chat using current active LLM
    def summarize_chat(self, language="en"):
        provider = self._current_provider
        chat = self._chat_instances.get(provider)
        if not chat:
            return {"status": "error", "message": "Chat not initialized"}
            
        history = self._history.get(provider, [])
        if not history:
            return {"status": "error", "message": "No messages to summarize"}
            
        formatted_messages = []
        for msg in history:
            role = "User" if msg["role"] == "user" else provider
            content = msg.get("content", "")
            formatted_messages.append(f"{role}: {content}")
            
        history_text = "\n".join(formatted_messages)
        
        prompt_es = f"Por favor, genera un resumen conciso y estructurado de la siguiente conversación:\n\n{history_text}"
        prompt_en = f"Please generate a concise and structured summary of the following conversation:\n\n{history_text}"
        prompt = prompt_es if language == "es" else prompt_en
        
        try:
            reply, token_info = chat.generate_response(prompt, history=[], force_language=language)
            return {"status": "success", "summary": reply}
        except Exception as e:
            logger.error(f"Error in summarize_chat: {e}", exc_info=True)
            return {"status": "error", "message": str(e)}