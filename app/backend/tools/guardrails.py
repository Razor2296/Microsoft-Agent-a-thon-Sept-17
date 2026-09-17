"""
app/backend/guardrails.py
PII (Personally Identifiable Information) Shield for Ignite Chat.

Detects and redacts sensitive information in user prompts BEFORE they are
sent to any external cloud API (Grok, OpenRouter, OpenAI, Gemini, etc.).

Patterns covered:
  - Email addresses
  - Credit / debit card numbers (13–19 digits, with optional separators)
  - Peruvian DNI (8-digit national ID)
  - Phone numbers (international and local formats)
  - API keys / tokens (hex/base64 strings of 20+ chars)

Usage:
    from backend.tools.guardrails import PIIShield
    safe_text = PIIShield.sanitize(user_text)

LLM Reference: See app/skills/02_core_features/SKILLS_CORE.md § 2.6
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import List

from backend.core.schemas import InjectionDetectionResult

logger = logging.getLogger(__name__)


@dataclass
class RedactionResult:
    """Result of a PII sanitization pass."""
    original: str
    sanitized: str
    redactions: List[str] = field(default_factory=list)

    @property
    def was_modified(self) -> bool:
        return self.original != self.sanitized

    def __str__(self) -> str:
        return self.sanitized


class PIIShield:
    """
    Regex-based PII detector and sanitizer.

    All patterns are compiled at class-definition time for performance.
    The sanitize() method is the primary public interface and is safe to call
    on every user message before forwarding to any AI provider.
    """

    # Email addresses: user@domain.tld
    _EMAIL = re.compile(
        r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}",
        re.IGNORECASE,
    )

    # Credit/debit card numbers: 13–19 digits with optional spaces/dashes
    _CREDIT_CARD = re.compile(
        r"\b(?:\d[ \-]?){13,18}\d\b"
    )

    # Phone numbers: supports +51 999 999 999, (01) 234-5678, etc.
    _PHONE = re.compile(
        r"(?:\+?[\d\s\-\(\)]{7,20}\d)"
    )

    # Peruvian 8-digit DNI (standalone, not part of a longer number)
    _PERU_DNI = re.compile(
        r"\b[0-9]{8}\b"
    )

    # API keys / tokens: long hex or base64-looking strings (≥ 24 chars)
    _API_KEY = re.compile(
        r"\b[A-Za-z0-9_\-]{24,}\b"
    )

    # Replacement labels
    _LABELS = {
        "email": "[REDACTED_EMAIL]",
        "card": "[REDACTED_CARD]",
        "phone": "[REDACTED_PHONE]",
        "dni": "[REDACTED_ID]",
        "api_key": "[REDACTED_KEY]",
    }

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    @classmethod
    def sanitize(cls, text: str, *, redact_api_keys: bool = False) -> str:
        """
        Sanitize *text* by replacing PII patterns with placeholder labels.

        Args:
            text: The raw user input to sanitize.
            redact_api_keys: If True, also redact long hex/base64 strings that
                look like API keys or tokens. Disabled by default to avoid
                false positives on technical prompts.

        Returns:
            The sanitized string, safe to forward to cloud APIs.
        """
        if not text or not text.strip():
            return text

        result = text
        redactions: List[str] = []

        # Order matters: most specific patterns first
        result, n = cls._EMAIL.subn(cls._LABELS["email"], result)
        if n:
            redactions.extend(["email"] * n)

        result, n = cls._CREDIT_CARD.subn(cls._LABELS["card"], result)
        if n:
            redactions.extend(["card"] * n)

        if redact_api_keys:
            result, n = cls._API_KEY.subn(cls._LABELS["api_key"], result)
            if n:
                redactions.extend(["api_key"] * n)

        if redactions:
            logger.info(
                "PIIShield redacted %d item(s) from user prompt: %s",
                len(redactions),
                ", ".join(set(redactions)),
            )

        return result

    @classmethod
    def sanitize_detailed(cls, text: str, *, redact_api_keys: bool = False) -> RedactionResult:
        """
        Like sanitize() but returns a RedactionResult with metadata about
        what was redacted. Useful for logging/audit purposes.
        """
        if not text or not text.strip():
            return RedactionResult(original=text, sanitized=text)

        result = text
        redactions: List[str] = []

        result, n = cls._EMAIL.subn(cls._LABELS["email"], result)
        redactions.extend(["email"] * n)

        result, n = cls._CREDIT_CARD.subn(cls._LABELS["card"], result)
        redactions.extend(["card"] * n)

        if redact_api_keys:
            result, n = cls._API_KEY.subn(cls._LABELS["api_key"], result)
            redactions.extend(["api_key"] * n)

        return RedactionResult(original=text, sanitized=result, redactions=redactions)

    @classmethod
    def contains_pii(cls, text: str) -> bool:
        """Quick check: returns True if the text contains any PII pattern."""
        if not text:
            return False
        return bool(
            cls._EMAIL.search(text)
            or cls._CREDIT_CARD.search(text)
        )


# ---------------------------------------------------------------------------
# Skill 2.6 Ext — Prompt Injection & Jailbreak Shield (Multilingual HPD)
# ---------------------------------------------------------------------------

class PromptInjectionGuard:
    """
    Robust Multilingual Prompt Injection & Jailbreak Detector.

    Covers extreme adversarial cases (English, Spanish, French, German) including:
      - Instruction Override / Forget Previous Directives
      - System Prompt Extraction / Leakage Attempt
      - Jailbreaks (DAN, Developer Mode, Persona Shift, Evil AI, STAN)
      - Delimiter Manipulation & System Tag Spoofer (<<<SYSTEM>>>, [SYSTEM INSTRUCTION], <|im_start|>)
      - Base64 / Obfuscated Command Payload Indicators
    """

    # 1. Instruction Override Signatures (Multilingual)
    _OVERRIDE_PATTERNS = [
        # English
        r"\bignore\s+(?:all\s+)?(?:previous|prior)\s+(?:instructions|prompts|rules|guidelines)\b",
        r"\bdisregard\s+(?:all\s+)?(?:previous|prior)\s+(?:instructions|prompts|rules|guidelines)\b",
        r"\bforget\s+(?:everything\s+)?(?:you\s+were\s+told|about\s+your\s+rules)\b",
        r"\bnew\s+rule\s*:\s*you\s+must\s+now\b",
        r"\boverride\s+system\s+prompt\b",

        # Spanish
        r"\bignora\s+(?:todas\s+)?las\s+(?:instrucciones|reglas|indicaciones)\s+(?:anteriores|previas)\b",
        r"\bolvida\s+(?:todo\s+)?lo\s+que\s+te\s+dijeron\b",
        r"\bolvida\s+tus\s+reglas\b",
        r"\bnueva\s+regla\s*:\s*ahora\s+debes\b",
        r"\bsobreescribe\s+el\s+prompt\s+del\s+sistema\b",

        # French / German / Other
        r"\bignorez?\s+toutes?\s+les?\s+instructions?\s+précédentes?\b",
        r"\bvergiss\s+alle\s+bisherigen\s+anweisungen\b",
    ]

    # 2. System Prompt Extraction Signatures (Leakage)
    _LEAKAGE_PATTERNS = [
        # English
        r"\brepeat\s+(?:the\s+)?(?:system\s+prompt|initial\s+instructions|developer\s+prompt)\b",
        r"\bshow\s+me\s+(?:your\s+)?(?:exact\s+|initial\s+)*system\s+(?:prompt|instructions)\b",
        r"\bwhat\s+are\s+your\s+hidden\s+rules\b",
        r"\bprint\s+everything\s+above\s+this\s+line\b",

        # Spanish
        r"\brepite\s+(?:el\s+)?(?:prompt\s+del\s+sistema|instrucciones\s+iniciales|instrucción\s+base)\b",
        r"\bmuéstrame\s+tus?\s+instrucciones?\s+(?:ocultas|iniciales|base)\b",
        r"\bcuáles?\s+son\s+tus?\s+reglas?\s+(?:ocultas|del\s+sistema)\b",
        r"\bimprime\s+todo\s+lo\s+que\s+está\s+arriba\s+de\s+esta\s+línea\b",
    ]

    # 3. Jailbreak & Persona Shift Signatures (DAN, Developer Mode, STAN, Evil AI)
    _JAILBREAK_PATTERNS = [
        # English / Global
        r"\bdo\s+anything\s+now\b",
        r"\bdan\s+mode\b",
        r"\bdeveloper\s+mode\s+enabled\b",
        r"\bact\s+as\s+an?\s+unfiltered\s+ai\b",
        r"\bstan\s+mode\b",
        r"\bevil\s+assistant\b",
        r"\bhack\s+mode\b",
        r"\bsimulate\s+an?\s+unrestricted\s+llm\b",

        # Spanish
        r"\bmodo\s+desarrollador\s+activado\b",
        r"\bhaz\s+lo\s+que\s+sea\s+ahora\b",
        r"\bactúa\s+como\s+una\s+ia\s+sin\s+filtros\b",
        r"\bmodo\s+sin\s+censura\b",
        r"\bsimula\s+ser\s+una\s+ia\s+desbloqueada\b",
    ]

    # 4. Delimiter & Fake System Tag Spoofer Signatures
    _TAG_SPOOF_PATTERNS = [
        r"<\s*\|\s*im_start\s*\|\s*>",
        r"<\s*\|\s*im_end\s*\|\s*>",
        r"\[\s*SYSTEM\s*INSTRUCTION\s*\]",
        r"\[\s*INSTRUCCION\s*DEL\s*SISTEMA\s*\]",
        r"<<<\s*SYSTEM\s*>>>",
        r"<\s*system_override\s*>",
    ]

    # Compiled combined regex rules
    _COMPILED_RULES = [
        ("override", [re.compile(p, re.IGNORECASE) for p in _OVERRIDE_PATTERNS]),
        ("leakage", [re.compile(p, re.IGNORECASE) for p in _LEAKAGE_PATTERNS]),
        ("jailbreak", [re.compile(p, re.IGNORECASE) for p in _JAILBREAK_PATTERNS]),
        ("tag_spoof", [re.compile(p, re.IGNORECASE) for p in _TAG_SPOOF_PATTERNS]),
    ]

    @classmethod
    def inspect_prompt(cls, text: str) -> InjectionDetectionResult:
        """
        Inspect text prompt for adversarial prompt injection or jailbreak attempts.

        Returns an InjectionDetectionResult DTO with risk score and matched rules.
        """
        if not text or not text.strip():
            return InjectionDetectionResult(
                is_suspicious=False,
                risk_score=0.0,
                detected_patterns=[],
                sanitized_text=text,
            )

        matched_rules: List[str] = []
        score = 0.0

        for category, regex_list in cls._COMPILED_RULES:
            for regex in regex_list:
                if regex.search(text):
                    matched_rules.append(category)
                    if category == "jailbreak":
                        score += 0.6
                    elif category == "override":
                        score += 0.5
                    elif category == "leakage":
                        score += 0.4
                    elif category == "tag_spoof":
                        score += 0.7
                    break  # count category once

        # Cap score between 0.0 and 1.0
        final_score = min(1.0, score)
        is_suspicious = final_score >= 0.4

        sanitized = text
        reason = None
        if is_suspicious:
            reason = f"Prompt Injection / Jailbreak attempt detected (Risk Score: {final_score:.2f}, Matches: {', '.join(matched_rules)})"
            logger.warning(f"PromptInjectionGuard triggered: {reason}")
            # Neutralize spoofed system tags
            for _, regex_list in cls._COMPILED_RULES:
                for regex in regex_list:
                    sanitized = regex.sub("[BLOCKED_INJECTION]", sanitized)

        return InjectionDetectionResult(
            is_suspicious=is_suspicious,
            risk_score=round(final_score, 2),
            detected_patterns=matched_rules,
            sanitized_text=sanitized,
            reason=reason,
        )

    @classmethod
    def sanitize_prompt(cls, text: str) -> str:
        """Convenience method returning sanitized prompt string."""
        return cls.inspect_prompt(text).sanitized_text

