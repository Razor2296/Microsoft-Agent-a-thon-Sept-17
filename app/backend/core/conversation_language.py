"""
Conversation language policy.

Sticky start: keep the language of the first real user turn so slang/loanwords
do not flip the thread. Switch when the user explicitly asks OR when the latest
utterance is clearly monolingual in another supported language (typed or STT).

No product-language hardcoding in call sites: defaults and maps come from env / this
config module. See skills funcionalidades-core (sticky language) and coding § no-hardcode.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional

try:
    from langdetect import detect as _langdetect
except ImportError:
    _langdetect = None

# ISO639-1 → BCP-47 locale (override with IGNITE_ISO_LANG_MAP_JSON)
_DEFAULT_ISO_TO_LOCALE: Dict[str, str] = {
    "es": "es-MX",
    "en": "en-US",
    "fr": "fr-FR",
    "de": "de-DE",
    "it": "it-IT",
    "pt": "pt-BR",
    "ja": "ja-JP",
    "zh-cn": "zh-CN",
    "zh-tw": "zh-TW",
    "ko": "ko-KR",
    "ru": "ru-RU",
}

# Spoken/written language names → locale (override with IGNITE_LANG_NAME_ALIASES_JSON)
_DEFAULT_LANG_NAME_ALIASES: Dict[str, str] = {
    "spanish": "es-MX",
    "espanol": "es-MX",
    "castellano": "es-MX",
    "english": "en-US",
    "ingles": "en-US",
    "french": "fr-FR",
    "frances": "fr-FR",
    "francais": "fr-FR",
    "german": "de-DE",
    "aleman": "de-DE",
    "deutsch": "de-DE",
    "italian": "it-IT",
    "italiano": "it-IT",
    "portuguese": "pt-BR",
    "portugues": "pt-BR",
}

# Unique script/punctuation hints → locale (not a product default; detection only)
_DEFAULT_SCRIPT_HINTS: Dict[str, str] = {
    "ñ": "es-MX",
    "Ñ": "es-MX",
    "¿": "es-MX",
    "¡": "es-MX",
}

# Explicit switch intent templates; `{names}` is replaced with alias alternation
_DEFAULT_SWITCH_PATTERNS: List[str] = [
    r"\b(?:hablame|habla|hablemos|responde|contestame|contesta)\s+(?:por\s+favor\s+)?en\s+({names})\b",
    r"\b(?:cambia|cambiemos|pasemos)\s+(?:el\s+)?(?:idioma|lenguaje)\s+(?:a|al|para)\s+({names})\b",
    r"\b(?:hola|habla|responde|contesta)\s+en\s+({names})\b",
    r"\b(?:switch|change)\s+(?:the\s+)?(?:language\s+)?(?:to\s+)?({names})\b",
    r"\b(?:speak|reply|answer|respond)\s+(?:to\s+me\s+)?(?:in\s+)?({names})\b",
    r"\b(?:let'?s|lets)\s+(?:switch\s+to|speak)\s+({names})\b",
    r"\b(?:from\s+now\s+on|a\s+partir\s+de\s+ahora)\s*.{0,40}\b(?:in|en)\s+({names})\b",
    r"\b(?:can\s+we|could\s+we)\s+(?:speak|talk)\s+(?:in\s+)?({names})\b",
]

# Function words used only to tell slang/mixed turns from a real language shift.
_DEFAULT_FUNCTION_WORDS: Dict[str, str] = {
    "es": "el la los las de del que y en un una por para con como hola tal me te se no si esto esta este estas estos muy pero porque gracias favor estoy nada todo estaba sobre claramente escuchas espanol analiza analizar boletas boleta factura receta pago pagos",
    "en": "the is are you and to of in for this that with please can we it on was be have not hello hey",
    "fr": "le la les et je tu nous vous pas une des que dans pour bonjour",
    "de": "der die das und ich du nicht ein eine ist zu auf hallo",
    "it": "il la di e che un una per non ciao sono",
    "pt": "o a os as de que e em um uma nao para com ola",
}


def _load_json_dict(env_key: str, default: Dict[str, str]) -> Dict[str, str]:
    raw = (os.getenv(env_key) or "").strip()
    if not raw:
        return dict(default)
    try:
        data = json.loads(raw)
        if isinstance(data, dict) and data:
            return {str(k).lower(): str(v) for k, v in data.items()}
    except Exception:
        pass
    return dict(default)


def _load_json_list(env_key: str, default: List[str]) -> List[str]:
    raw = (os.getenv(env_key) or "").strip()
    if not raw:
        return list(default)
    try:
        data = json.loads(raw)
        if isinstance(data, list) and data:
            return [str(x) for x in data if str(x).strip()]
    except Exception:
        pass
    return list(default)


def get_default_conversation_language() -> str:
    """
    Ultimate fallback when no UI language, sticky history, or detection exists.
    Configured via IGNITE_DEFAULT_CONVERSATION_LANGUAGE (preferred) or SPEECH_RECOGNITION_LANG.
    Never hardcode a product language in call sites — always call this helper.
    """
    for key in ("IGNITE_DEFAULT_CONVERSATION_LANGUAGE", "SPEECH_RECOGNITION_LANG"):
        val = (os.getenv(key) or "").strip()
        if val:
            return val
    return "en-US"


def iso_to_locale_map() -> Dict[str, str]:
    return _load_json_dict("IGNITE_ISO_LANG_MAP_JSON", _DEFAULT_ISO_TO_LOCALE)


def lang_name_aliases() -> Dict[str, str]:
    return _load_json_dict("IGNITE_LANG_NAME_ALIASES_JSON", _DEFAULT_LANG_NAME_ALIASES)


def script_hints() -> Dict[str, str]:
    return _load_json_dict("IGNITE_SCRIPT_LANG_HINTS_JSON", _DEFAULT_SCRIPT_HINTS)


def switch_patterns() -> List[str]:
    return _load_json_list("IGNITE_LANG_SWITCH_PATTERNS_JSON", _DEFAULT_SWITCH_PATTERNS)


def function_word_sets() -> Dict[str, frozenset]:
    raw = (os.getenv("IGNITE_LANG_FUNCTION_WORDS_JSON") or "").strip()
    source: Dict[str, str] = dict(_DEFAULT_FUNCTION_WORDS)
    if raw:
        try:
            data = json.loads(raw)
            if isinstance(data, dict) and data:
                for key, val in data.items():
                    iso = str(key).lower().strip()
                    if isinstance(val, list):
                        source[iso] = " ".join(str(x) for x in val)
                    else:
                        source[iso] = str(val)
        except Exception:
            pass
    sets: Dict[str, frozenset] = {}
    for iso, blob in source.items():
        tokens = {normalize_lang_key(t) for t in str(blob).split() if t.strip()}
        if tokens:
            sets[iso] = frozenset(tokens)
    return sets


def _env_int(name: str, default: str) -> int:
    raw = os.getenv(name, default)
    try:
        return max(0, int(raw if raw not in (None, "") else default))
    except (TypeError, ValueError):
        try:
            return max(0, int(default))
        except (TypeError, ValueError):
            return 0


def utterance_switch_min_chars() -> int:
    return max(1, _env_int("IGNITE_LANG_UTTERANCE_SWITCH_MIN_CHARS", "24"))


def script_hint_min_chars() -> int:
    return max(1, _env_int("IGNITE_LANG_SCRIPT_HINT_MIN_CHARS", "8"))


def function_word_margin() -> int:
    return _env_int("IGNITE_LANG_FUNCTION_WORD_MARGIN", "2")


def function_word_min_score() -> int:
    return max(1, _env_int("IGNITE_LANG_FUNCTION_WORD_MIN_SCORE", "3"))


def locale_iso_prefix(locale: Optional[str]) -> str:
    if not locale or not isinstance(locale, str):
        return ""
    return locale.strip().split("-")[0].lower()


def function_word_scores(text: str) -> Dict[str, int]:
    tokens = re.findall(r"[a-z]+", normalize_lang_key(text or ""))
    scores: Dict[str, int] = {}
    for iso, vocab in function_word_sets().items():
        scores[iso] = sum(1 for tok in tokens if tok in vocab)
    return scores


def detect_clear_utterance_language(text: str, sticky: Optional[str] = None) -> Optional[str]:
    """Locale when the latest utterance is clearly monolingual in another language.

    Slang / mixed turns must return None so the sticky thread language is kept.
    """
    if not text or not isinstance(text, str):
        return None
    raw = text.strip()
    if not raw:
        return None

    sticky_iso = locale_iso_prefix(sticky)
    hinted = None
    for ch, locale in script_hints().items():
        if ch and ch in text:
            hinted = locale
            break
    if hinted and locale_iso_prefix(hinted) != sticky_iso and len(raw) >= script_hint_min_chars():
        return hinted

    if len(raw) < utterance_switch_min_chars():
        return None

    detected = detect_language_from_text(text, default_language=None)
    det_iso = locale_iso_prefix(detected)
    if not det_iso or (sticky_iso and det_iso == sticky_iso):
        return None

    scores = function_word_scores(text)
    det_score = int(scores.get(det_iso, 0) or 0)
    sticky_score = int(scores.get(sticky_iso, 0) or 0) if sticky_iso else 0
    margin = function_word_margin()
    min_score = function_word_min_score()
    if det_score >= sticky_score + margin or (det_score >= min_score and sticky_score == 0):
        return detected
    return None


def normalize_lang_key(text: str) -> str:
    t = (text or "").lower().strip()
    t = re.sub(r"[áàäâ]", "a", t)
    t = re.sub(r"[éèëê]", "e", t)
    t = re.sub(r"[íìïî]", "i", t)
    t = re.sub(r"[óòöô]", "o", t)
    t = re.sub(r"[úùüû]", "u", t)
    t = re.sub(r"[ñ]", "n", t)
    t = re.sub(r"[ç]", "c", t)
    return t


def detect_language_from_text(text: str, default_language: Optional[str] = None) -> str:
    """NLP + script hints. Fallback chain: default_language → env default (never a call-site literal)."""
    fallback_lang = (default_language or "").strip() or get_default_conversation_language()
    if not text or not isinstance(text, str) or not text.strip():
        return fallback_lang

    try:
        clean_text = re.sub(r"https?://\S+", "", text).strip()
        if not clean_text:
            return fallback_lang

        if _langdetect is not None and len(clean_text) >= 15:
            try:
                det = _langdetect(clean_text)
                mapped = iso_to_locale_map().get(str(det).lower())
                if mapped:
                    return mapped
            except Exception:
                pass

        hints = script_hints()
        for ch, locale in hints.items():
            if ch and ch in text:
                return locale
    except Exception:
        pass

    return fallback_lang


def detect_explicit_language_switch(text: str) -> Optional[str]:
    """Locale only when the user explicitly asks to change language (not slang)."""
    if not text or not isinstance(text, str):
        return None
    raw = text.strip()
    if len(raw) < 8:
        return None

    aliases = lang_name_aliases()
    if not aliases:
        return None
    names = "|".join(re.escape(normalize_lang_key(k)) for k in aliases.keys())
    low = normalize_lang_key(raw)
    for template in switch_patterns():
        pat = template.replace("{names}", names)
        m = re.search(pat, low, flags=re.IGNORECASE)
        if not m:
            continue
        key = normalize_lang_key(m.group(1))
        code = aliases.get(key)
        if code:
            return code
    return None


def history_has_real_user_turns(history: Optional[List[Any]]) -> bool:
    if not history:
        return False
    for msg in history:
        if not isinstance(msg, dict):
            continue
        if msg.get("is_welcome"):
            continue
        role = msg.get("role") or ("user" if msg.get("is_user") else None)
        if role == "user" and (msg.get("content") or "").strip():
            return True
    return False


def get_sticky_conversation_language(history: Optional[List[Any]]) -> Optional[str]:
    if not history:
        return None
    for msg in reversed(history):
        if not isinstance(msg, dict) or msg.get("is_welcome"):
            continue
        role = msg.get("role") or ("user" if msg.get("is_user") else None)
        if role != "user":
            continue
        stored = msg.get("conversation_language")
        if isinstance(stored, str) and stored.strip():
            return stored.strip()
    for msg in history:
        if not isinstance(msg, dict) or msg.get("is_welcome"):
            continue
        role = msg.get("role") or ("user" if msg.get("is_user") else None)
        if role != "user":
            continue
        content = (msg.get("content") or "").strip()
        if content:
            return detect_language_from_text(content, default_language=None)
    return None


def resolve_conversation_language(
    text: str,
    *,
    history: Optional[List[Any]] = None,
    incoming_language: Optional[str] = None,
) -> str:
    """
    Sticky policy:
    - Keep the language the user started with (slang / mixed loanwords must not flip it).
    - Switch on explicit request OR a clearly monolingual latest utterance (voice or typed).
    - Fresh thread: detect from first message, else incoming UI lang, else env default.
    """
    explicit = detect_explicit_language_switch(text or "")
    if explicit:
        return explicit

    sticky = get_sticky_conversation_language(history)
    clear = detect_clear_utterance_language(text or "", sticky=sticky)
    if clear:
        return clear

    incoming = (incoming_language or "").strip() or None

    if sticky and history_has_real_user_turns(history):
        if text and str(text).strip() and incoming:
            detected = detect_language_from_text(text, default_language=incoming)
            in_iso = locale_iso_prefix(incoming)
            det_iso = locale_iso_prefix(detected)
            sticky_iso = locale_iso_prefix(sticky)
            if in_iso and det_iso and in_iso == det_iso and sticky_iso and in_iso != sticky_iso:
                scores = function_word_scores(text)
                if int(scores.get(in_iso, 0) or 0) >= function_word_min_score():
                    return detected
        return sticky

    if text and str(text).strip():
        return detect_language_from_text(text, default_language=incoming)

    return incoming or sticky or get_default_conversation_language()
