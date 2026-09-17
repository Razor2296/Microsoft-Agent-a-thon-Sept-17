"""Pure helpers for document generation vs analysis intent detection."""

from __future__ import annotations
import re

# Shared system rule for providers that receive extracted Office/PDF text.
CRITICAL_DOCUMENT_ANALYSIS_RULE = (
    "\n\n[CRITICAL DOCUMENT RULE] The user may ask you to analyze a document "
    "(Word, Excel, PowerPoint, PDF). The raw text of these documents has been "
    "automatically extracted and appended to the user's prompt. You MUST read "
    "the appended text and fulfill the user's request. UNDER NO CIRCUMSTANCES "
    "should you refuse or claim that you cannot read .pptx, .docx, .xlsx, or "
    ".pdf files directly. You have the extracted text, so you MUST analyze it. "
    "If the user asks to analyze, review, summarize, explain, or extract from an "
    "attached document, DO NOT create or export a new Word/Excel/PowerPoint file "
    "and DO NOT restructure your whole answer as a new slide deck — answer in "
    "normal conversational analysis unless they explicitly ask you to generate "
    "a new document."
)

# Guidelines for document generation
DOCUMENT_GENERATION_GUIDELINES = (
    "\n\n## Document Generation Formatting Guidelines\n"
    "IMPORTANT — Analysis vs Generation:\n"
    "- If the user attached a file and asks to analyze/review/summarize/explain/"
    "extract from it (e.g. 'Analiza este ppt', 'resume este excel'), you MUST "
    "analyze the attached content in a normal conversational answer. Do NOT "
    "create a new document and do NOT use the slide/table export formats below.\n"
    "- Only use the formats below when the user EXPLICITLY asks to generate/"
    "create/export a NEW document (Word, Excel, or PowerPoint).\n"
    "If the user explicitly asks to generate a document (Word document, Excel "
    "spreadsheet, or PowerPoint presentation):\n"
    "- You MUST NOT include any conversational greetings, introductory remarks, "
    "or concluding sign-offs (e.g. do not say 'Here is the document...', "
    "'I hope this helps...', etc.). Start immediately with the structured "
    "document content.\n"
    "1. For Excel / Spreadsheet requests: You MUST format the data in a clear "
    "markdown table (using pipe syntax e.g., `| Header |` and `|---|`). Do not "
    "add conversational text around the table; only output the data and the "
    "table so it can be cleanly parsed and exported to Excel.\n"
    "2. For PowerPoint / Presentation requests: Structure the presentation "
    "slide-by-slide using Markdown headers for slide titles, followed by bullet "
    "points. You MUST use the following exact structure for each slide:\n"
    "   # Slide [Number]: [Title of Slide]\n"
    "   - [Bullet point 1]\n"
    "   - [Bullet point 2]\n"
    "   Example:\n"
    "   # Slide 1: Introducción\n"
    "   - Orígenes del proyecto\n"
    "   - Objetivos del año\n"
    "3. For Word / Document requests: Structure the response using standard "
    "Markdown headings (`#`, `##`, `###`), lists (`-`, `*`), inline bold "
    "(`**text**`), and markdown tables to structure the document clearly, so "
    "the document exporter can parse it into a formatted Word file.\n"
)

DOC_GUIDELINES_MARKER = "## Document Generation Formatting Guidelines"

# Function to detect document request
def detect_document_request(text: str, has_attachments: bool = False) -> str | None:
    """Classify if the prompt explicitly requests document *generation*.

    Analysis prompts like "Analiza este ppt" must NOT trigger generation —
    especially when the user attached a file. Generation requires a clear
    creation-intent verb.
    """
    if not text:
        return None
    lower = text.lower()

    # --- Analysis / review intent: never auto-generate a document ---
    analysis_patterns = [
        r'\b(analiza|analizar|análisis|analisis|revisa|revisar|resume|resumir|'
        r'explica|explicar|lee|leer|extrae|extraer|describe|describir|'
        r'evalúa|evalua|evaluar|comenta|comentar|interpreta|interpretar|'
        r'revisa\s+este|qué\s+dice|que\s+dice|qué\s+contiene|que\s+contiene)\b',
        r'\b(analyze|analyse|review|summarize|summarise|explain|read|extract|'
        r'describe|evaluate|interpret|comment\s+on|what\s+does|what\s+is\s+in|'
        r'look\s+at|go\s+through)\b',
    ]
    if any(re.search(pattern, lower) for pattern in analysis_patterns):
        return None

    # --- Creation intent verbs (Spanish + English) ---
    intent_patterns = [
        r'\b(crea|crear|genera|generar|hazme|haz|elabora|elaborar|prepara|preparar'
        r'|redacta|redactar|diseña|diseñar|exporta|exportar|convierte|convertir'
        r'|necesito|quiero|dame)\b',
        r'\b(create|make|generate|write|draft|build|prepare|produce|export|convert'
        r'|give\s+me|need\s+a|want\s+a|can\s+you\s+make|please\s+make)\b',
    ]
    has_intent = any(re.search(pattern, lower) for pattern in intent_patterns)

    # With attachments, only generate when the user clearly asks to create/export
    # something new (e.g. "genera un resumen en ppt de este archivo").
    if has_attachments and not has_intent:
        return None

    # Format keywords require creation intent. Mentions like "este ppt" /
    # "el docx" alone are references to existing files, not generation asks.
    excel_keywords = [
        r'\bxlsx\b', r'\bexcel\b', r'\bplanilla\b', r'\bspreadsheet\b',
        r'\bhoja de calculo\b', r'\bhoja de cálculo\b',
    ]
    ppt_keywords = [
        r'\bppt\b', r'\bpptx\b', r'\bpowerpoint\b',
        r'\bdiapositiva\b', r'\bdiapositivas\b',
        r'\bpresentacion\b', r'\bpresentación\b', r'\bslides\b',
    ]
    word_keywords = [
        r'\bdocx\b', r'\bword\b',
        r'\bdocumento de texto\b', r'\bdocumento de word\b', r'\bdocumento docx\b',
    ]

    if has_intent and any(re.search(pattern, lower) for pattern in excel_keywords):
        return 'xlsx'
    if has_intent and any(re.search(pattern, lower) for pattern in ppt_keywords):
        return 'pptx'
    if has_intent and any(re.search(pattern, lower) for pattern in word_keywords):
        return 'docx'

    return None

# Function to check if text is a document generation request
def is_document_generation_request(text: str, has_attachments: bool = False) -> bool:
    """Convenience helper returning True if text explicitly requests document generation."""
    return detect_document_request(text, has_attachments=has_attachments) is not None

# Function to check if text is a document analysis request
def is_document_analysis_request(text: str) -> bool:
    """Convenience helper returning True if text requests analysis of an attached document."""
    return not is_document_generation_request(text, has_attachments=True)
