# 🛠️ Category 1: Coding Best Practices (Python, JS, CSS) — Engineering Standards & Guidelines

This document specifies the mandatory, non-negotiable engineering standards for developing, refactoring, and maintaining code within the **Ignite Chat** codebase. Adhering to these rules guarantees **type safety**, **system resilience**, **information security**, and **testability** across both backend (FastAPI / PyWebView) and frontend layers.

---

## 1. Explicit Top-Level Imports & Anti-Wildcard Policy

### 1.1 The Strict Rule
- **All imports must be at the top level of the module:** Always declare all imports (standard library, third-party dependencies, and internal application modules) at the very beginning of the Python file. **Never import libraries or modules inside a function or method.**
- **Never use wildcard imports** (`from module import *` or `from main.libraries import *`).
- Every Python module must explicitly declare every function, class, type, or constant it consumes at top-level.
- Any heavy, OS-specific, or optional third-party dependency (e.g., `torch`, `pytesseract`, `yt_dlp`, `clr`, `openpyxl`, `python-docx`, `python-pptx`, `SQLServerExporter`) must be wrapped in a `try/except ImportError` block at the module top-level and set to `None` upon failure, rather than being imported lazily inside functions.

### 1.2 Rationale & Failure Modes
- **Hidden Dependencies & Overhead:** Inline imports inside functions obscure module dependencies from static analysis tools (`ruff`, `mypy`, `pyright`), introduce runtime overhead on hot paths, and make dependency tracking error-prone.
- **Namespace Pollution & Collision:** Star-imports obscure the true origin of symbols and cause silent variable shadowing.
- **Graceful Degradation:** When optional libraries are missing or unsupported on the host environment, wrapped top-level imports allow the application to boot safely and degrade functionality conditionally rather than terminating with an unhandled exception inside a running request.

### 1.3 Implementation Standard
```python
# GOOD: Explicit top-level imports and graceful optional fallbacks at module header
import os
import sys
import logging
from typing import Optional, Dict, Any, List

# Core internal schemas and services
from app.backend.schemas import TokenInfo, ChatMessageDTO, ProviderConfig
from app.backend.services import TranscriptionService

# Optional/heavy dependencies protected by top-level import guards
try:
    import yt_dlp
except ImportError:
    yt_dlp = None

try:
    import docx
except ImportError:
    docx = None

logger = logging.getLogger(__name__)
```

```python
# BAD: Wildcard imports, unguarded imports, or inline imports inside functions
from app.backend.libraries import *          # Pollutes namespace; breaks static analysis
import heavy_optional_library                 # Crashes entire app if package is missing

def process_file(data):
    import base64                             # FORBIDDEN: Inline import inside function
    from app.backend.service import run_job   # FORBIDDEN: Inline import inside function
    ...
```

---

## 2. Zero Hardcoding & Centralized Environment Configuration

### 2.1 The Strict Rule
- **Never hardcode secrets, API keys, URLs, model identifiers, port numbers, or timeouts.**
- All runtime parameters must be declared in typed Pydantic models (`pydantic_settings.BaseSettings` or `ProviderConfig`) and loaded from environment variables (`.env`, `.env.staging`, `.env.prod`).
- Multi-environment resolution is handled through `app/main/env_config.py` (`load_environment` / `resolve_env_file`) via `IGNITE_ENV`.

### 2.2 Standard Configuration Schema
```python
# app/backend/config.py
import os
from typing import Optional
from pydantic import Field
from pydantic_settings import BaseSettings

class ProviderSettings(BaseSettings):
    """Centralized configuration schema with environment fallbacks."""
    OPENAI_API_KEY: Optional[str] = Field(default=None, description="OpenAI API Key")
    GEMINI_API_KEY: Optional[str] = Field(default=None, description="Google Gemini API Key")
    ANTHROPIC_API_KEY: Optional[str] = Field(default=None, description="Anthropic API Key")
    DEFAULT_MODEL: str = Field(default="gemini-2.5-flash", description="Default provider model")
    API_TIMEOUT_SECONDS: int = Field(default=30, ge=5, le=300)
    IGNITE_REQUEST_TTL_SECONDS: int = Field(default=3600, description="Memory TTL for cached requests")
    IGNITE_OTEL_ENABLED: bool = Field(default=False, description="Enable structured OpenTelemetry logs")

    class Config:
        env_file = ".env"
        extra = "ignore"

settings = ProviderSettings()
```

---

## 3. Defensive Error Handling, Structured Logging & Variable Scope Safety

### 3.1 The Strict Rule
- **Absolute Ban on `print()` Statements (Zero `print()` Policy):** **Never, under any circumstances, use `print()` in the codebase.** For any message, tracing, debugging, inspection, or text output that needs to be visualized or reported, **always use `logger.info(...)`** (or appropriate levels: `logger.debug`, `logger.warning`, `logger.error`). `print()` bypasses log formatters, rotation handlers (`RotatingFileHandler`), timestamps, and multi-tenant audit trails.
- **Pre-initialize all function variables** before entering any `try/except` block (e.g., `error_msg = None`, `result = None`, `payload = None`).
- **Never swallow exceptions silently:** Ban `except Exception: pass` or bare `except:`.
- **Enforce detailed error logging:** Always include `logger.error(..., exc_info=True)` or `logger.exception(...)` to retain full stack traces.
- **Guard nullable references:** Verify `if obj is not None:` before invoking methods or accessing attributes.

### 3.2 Implementation Standard
```python
# app/backend/processors/base_processor.py
import logging

logger = logging.getLogger(__name__)

async def execute_provider_call(prompt: str, session_id: str) -> dict:
    # 1. Pre-initialize all local variables to prevent UnboundLocalError
    error_msg = None
    response_payload = None
    token_count = 0
    result = {"success": False, "data": None, "error": None}

    # GOOD: Use logger.info instead of print() for text output / tracing
    logger.info(f"Executing provider call for session_id={session_id}")

    try:
        if not prompt or not prompt.strip():
            raise ValueError("Prompt cannot be empty")
        
        response_payload = await call_external_llm_api(prompt, session_id)
        token_count = response_payload.get("usage", {}).get("total_tokens", 0)
        result["data"] = response_payload.get("text", "")
        result["success"] = True
        logger.info(f"Provider call completed successfully. Tokens consumed: {token_count}")

    except ValueError as ve:
        error_msg = f"Validation failure: {ve}"
        logger.warning(error_msg)
    except TimeoutError as te:
        error_msg = f"External provider timed out: {te}"
        logger.error(error_msg, exc_info=True)
    except Exception as exc:
        error_msg = f"Unexpected execution error: {exc}"
        logger.error(error_msg, exc_info=True)

    # 2. Safely inspect pre-initialized state
    if error_msg:
        result["error"] = error_msg
    
    return result
```

```python
# BAD: Using print() for tracing or output
def process_message(user_input: str):
    print(f"Processing input: {user_input}")  # FORBIDDEN: Never use print()
    print("Done!")                            # FORBIDDEN: Always use logger.info()
```

---

## 4. Strict Typing & Pydantic V2 Enforcement

### 4.1 The Strict Rule
- All internal payload transfer objects, request/response models, and session entities must be defined in `app/backend/schemas.py`.
- Unstructured `dict` / `Dict[str, Any]` arguments and returns must be replaced with typed Pydantic V2 models (`BaseModel`).
- Take advantage of `@field_validator` and `@model_validator(mode="after")` to enforce domain rules and compute dynamic metadata.

### 4.2 Core Schemas Example
```python
# app/backend/schemas.py
from typing import Optional, List, Literal
from pydantic import BaseModel, Field, model_validator

class TokenInfo(BaseModel):
    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def compute_total_tokens(self) -> "TokenInfo":
        if self.total_tokens == 0:
            self.total_tokens = self.prompt_tokens + self.completion_tokens
        return self

class ChatMessage(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str = Field(..., min_length=1)
    timestamp: float
    token_info: Optional[TokenInfo] = None

class APIRequestPayload(BaseModel):
    session_id: str = Field(..., min_length=1)
    message: ChatMessage
    provider: str = Field(default="gemini")
```

---

## 5. Async-First Architecture & Concurrency Control

### 5.1 The Strict Rule
- Use `asyncio` and `httpx.AsyncClient` or `aiohttp.ClientSession` for all network and I/O-bound tasks.
- CPU-heavy or legacy blocking operations must be offloaded using `await asyncio.to_thread(sync_func, *args)`.
- Use `AdjustableSemaphore` (`app/backend/semaphore.py`) to manage backend concurrency limits dynamically without deadlocking.
- **Audio/VAD Pragmatism:** Keep `voice_processor.py` async-compatible without spawning uncontrolled OS-level `threading.Thread` instances.

### 5.2 Implementation Standard
```python
import asyncio
import httpx
from app.backend.semaphore import AdjustableSemaphore

concurrency_limiter = AdjustableSemaphore(initial_limit=5)

async def stream_ai_response(endpoint_url: str, payload: dict) -> str:
    async with concurrency_limiter:
        async with httpx.AsyncClient(timeout=45.0) as client:
            response = await client.post(endpoint_url, json=payload)
            response.raise_for_status()
            data = response.json()
            
    # Offload blocking text sanitization / parsing if needed
    cleaned_output = await asyncio.to_thread(sanitize_and_format, data["content"])
    return cleaned_output
```

---

## 6. Frontend Finite State Machine (FSM)

### 6.1 The Strict Rule
- All UI state transitions in the PyWebView client are governed by `app/frontend/js/stateMachine.js`.
- Allowed states: `IDLE`, `RECORDING`, `THINKING`, `SPEAKING`, `ERROR`.
- Components must never directly toggle visibility flags using scattered booleans; all visual updates (mic glow, spinners, TTS playback, error dialogs) must subscribe to state machine transitions.

### 6.2 Transition Matrix & Invariants
- `IDLE` → `RECORDING` (User activates microphone)
- `RECORDING` → `THINKING` (Recording finishes; audio payload uploaded)
- `IDLE` → `THINKING` (Text prompt submitted)
- `THINKING` → `SPEAKING` (Audio response ready for playback)
- `THINKING` → `IDLE` (Text-only response completed)
- `SPEAKING` → `IDLE` (Audio playback finishes)
- `*` → `ERROR` (Any exception; user dismissal resets state to `IDLE`)
- **Illegal Transitions:** Directly jumping from `RECORDING` to `SPEAKING` or from `SPEAKING` to `RECORDING` without passing through `IDLE` is rejected by the FSM.

---

## 7. System Stability, PII Protection & Memory Safeguards

### 7.1 Stability Protections
- **Remote API Proxy Warmup & Retries:** `app/main/remote_api_proxy.py` performs cold-start warmup via `/health` and executes exponential retries on transient errors (`502`, `503`, `504`).
- **Memory Leak Protection (`_requests` TTL Pruning):** Historical request maps must be periodically pruned using `IGNITE_REQUEST_TTL_SECONDS` to prevent in-memory accumulation in long-running desktop sessions.
- **Log Rotation:** All activity log handlers must use `RotatingFileHandler` (max 10 MB per file, 3 backups) to protect local disk space.

### 7.2 PII Guardrails (`app/backend/guardrails.py`)
- Automatically detect and redact sensitive data before external LLM calls:
  - Email addresses (`[EMAIL_REDACTED]`)
  - 16-digit credit card numbers (`[CARD_REDACTED]`)
  - Peruvian DNI 8-digit numbers (`[DNI_REDACTED]`)
  - International phone numbers (`[PHONE_REDACTED]`)
  - API Keys / Auth Tokens (`[API_KEY_REDACTED]`)

### 7.3 Voice & Multimodal Audio Lifecycle (Post-Transcription Language Re-Detection)
- **Mandatory Re-Detection Rule:** When user input originates from the microphone (`from_mic=True`), the text prompt is empty before speech-to-text execution. Once `transcribe_audio()` produces the transcribed text, the system MUST run `_resolve_conversation_language` on that text (sticky first-turn language; slang must not flip it; switch on explicit request OR a clearly monolingual latest utterance).
- **No Stale Language Forwarding:** Never pass a stale UI-only default that contradicts the sticky conversation language. Host OS locale must not override an established thread language.
- **Sticky vs explicit / clear utterance switch:** Do not re-bind language from `langdetect` on slang or mixed turns. Only `_detect_explicit_language_switch` or `_detect_clear_utterance_language` (monolingual latest message, including STT) may change it.

---

## 8. Quality Automation, Linting & Comprehensive Test Suite

### 8.1 Pre-Commit Quality Standards
1. **Python Linter:** `ruff check app/`
2. **Frontend Formatter:** `prettier --check app/`
3. **Automated Unit Tests:** `pytest app/tests/unit/`

### 8.2 Dynamic Test Reporting
All test runs dynamically log execution summaries via `pytest_terminal_summary` in `app/tests/conftest.py` to:
$$\text{app/tests/unit/results/test\_results\_YYYYMMDD\_HHMMSS.txt}$$

### 8.3 Required Test Coverage by Module

| Test Module | Target File | Verification Scope |
| :--- | :--- | :--- |
| **`test_api.py`** | `app/main/api.py` | PyWebView bindings, localized error codes (503, 404, 403), multilingual goodbye intents (`chao`, `bye`, `hasta luego`). |
| **`test_frontend_assets.py`** | `app/frontend/` (`unit/frontend/`) | Asset presence, script order (`stateMachine.js` before `audio.js`), translation keys, DevTools blocking (`debug=False`). |
| **`test_whatsapp_file_preview.py`** | `app/frontend/index.html`, `css/chat.css`, `translations.js` | Layer `unit/frontend/`: **chrome locks only** (overlay IDs, `wa-file-card` CSS, `file_preview_*` en/es, `openAttachmentFile` / path on cards). No Playwright/jsdom. |
| **`test_file_preview_persistence.py`** | `app/main/api.py` | Layer `unit/server/`: `_preprocess_input` forwards preview fields + `path`; bytes from disk; history clean keeps `preview_base64`/`path`, drops full `base64`/`bytes`. |
| **`test_schemas.py`** | `app/backend/schemas.py` | Pydantic V2 validations, `TokenInfo` auto-computation via validator, model immutability. |
| **`test_guardrails.py`** | `app/backend/guardrails.py` | Sanitization of emails, cards, DNIs, phones, and API keys; validation of `RedactionResult`. |
| **`test_base_processor_imports.py`** | `app/backend/base_processor.py` | Optional module fallbacks (`pytesseract`, `yt_dlp`), schema exports. |
| **`test_state_machine.py`** | `app/frontend/js/stateMachine.js` | Valid FSM state transitions, rejection of invalid transitions, forced resets to `IDLE`. |
| **`test_voice_processor.py`** | `app/backend/voice_processor.py` | Cartesia TTS config loading, voice category classification, base64 audio payload generation. |
| **`test_semaphore.py`** | `app/backend/semaphore.py` | Context manager acquisition/release, runtime limit adjustments, status reporting. |
| **`test_windows_user.py`** | `app/backend/user/windows_user.py` | OS username via `ctypes`, language/timezone detection, dark mode detection, user folder paths. |
| **`test_document_generator.py`** | `app/main/document_generator.py` | Compilation of `.docx`, `.xlsx`, `.pptx`, color conversions, dependency check `_ensure_dependencies`. |
| **`test_coordinator.py`** | `app/Databases/coordinator.py` | Ingestion offset state in `export_state.json`, incremental log reads without duplicates. |
| **`test_llm_processors.py`** | `app/backend/base_processor.py` | Language resolution, input trimming, document request tags (`[GENERATE_WORD]`, `[GENERATE_EXCEL]`, `[GENERATE_PPT]`). |
| **`test_stability_fixes.py`** | `app/main/remote_api_proxy.py`, `app/main/api.py` | Proxy cold-start warmups, 502/503/504 retries, `_requests` TTL memory cleanup, `RotatingFileHandler`. |

---

## 10. Strict Git Workflow & Branching Policy (Direct `Develop` Enforcement)

### 10.1 The Strict Rule
- **All future developments, bug fixes, refactoring, and quality improvements must be committed and pushed directly to the `Develop` branch.**
- **Never create secondary feature branches, temporary topic branches, or additional remote branches.**
- The active working branch must always be `Develop`. Merges from `Develop` to `main` are handled exclusively by the project maintainer.
- **Pre-Push Quality Gate:** Every commit directly to `Develop` must execute and pass the full unit test suite (`pytest app/tests/unit/`) with 100% pass rate before pushing to `origin Develop`.

---

## 11. Operational User Experience, Setup Onboarding & Value Telemetry Standards

### 11.1 Zero-Config Setup Wizard (`get_system_capabilities`, `validate_and_save_api_key`)
- **Zero Manual Config:** Daily operational users must never be forced to open or manually edit `.env` configuration files in text editors.
- **Hardware & Environment Self-Diagnosis:** The application automatically discovers host hardware capabilities (NVIDIA CUDA acceleration, Tesseract OCR, Web Audio VAD, and Hybrid/ACA runtime mode).
- **Live Key Validation:** API Keys entered via UI must be verified live against official provider endpoints before being written atomically to `.env` and hot-reloaded into memory without application restart.
- **Non-Intrusive Dismissal:** If a user dismisses the onboarding wizard without entering a key, the choice is persisted in client storage (`ignite_wizard_dismissed`) to avoid blocking future app startups, while remaining accessible anytime from the Settings drawer.

### 11.2 Business & Productivity Telemetry (`get_productivity_metrics`)
- **Quantifiable Operational ROI:** Telemetry must track real productivity gains:
  - *Typing & Drafting Hours Saved:* $\approx \text{words generated} / (40\text{ WPM} \times 60)$.
  - *Document Formatting Hours Saved:* $\text{Office documents (.docx/.xlsx/.pptx)} \times 0.35\text{ hrs}$.
  - *Human Cost Equivalent:* $\text{Total hours saved} \times \$25.00/\text{hr}$ operational rate.
  - *ROI Multiplier:* $\text{Human Equivalent Value} / \max(\text{AI Cost}, \$0.01)$.

### 11.3 Human-Centric Error Recovery & Smart Fallbacks (`get_smart_fallback`)
- **No Dead-End Error Messages:** When a provider encounters transient saturation, 429 quota exhaustion, or 503 unavailability, the system must never display raw Python stack traces.
- **1-Click Smart Fallback:** The chat UI renders a proactive recovery card offering 1-click execution of the user's prompt against an alternative healthy configured provider (e.g. Gemini, DeepSeek, OpenAI) with zero re-typing friction.
- **Live Turns Only:** Interactive recovery cards are strictly bound to live incoming messages (`isLive = true`), ensuring historical session archives remain clean and free from obsolete retry buttons.

### 11.4 WhatsApp-Style Audio Messaging & Backend Voice Processing (IMMUTABLE STANDARD)
- **Zero Browser-Side Live Speech Typing:** The browser's Web Speech API (`SpeechRecognition` / `webkitSpeechRecognition`) must **NEVER** be used to type text live into `#message-input`. Real-time browser speech typing causes language corruption (e.g. English auto-transcription when speaking Spanish), pollutes the text input, and bypasses internal server models.
- **WhatsApp Voice Bubble Workflow:**
  1. Microphone recording captures raw audio via `MediaRecorder` + Web Audio API RMS VAD (`analyser`).
  2. Floating HUD displays live volume waveforms and "Escuchando..." / "Listening...".
  3. When recording completes, `MediaRecorder` compiles `.webm` audio, clears the input box, and appends a native **WhatsApp Voice Player message bubble** with waveforms, duration, and double checkmarks (`✓✓`).
  4. Audio payload (`Voice_Message_<timestamp>.webm`) is sent to the backend (`app/main/api.py`).
  5. Server-side **Faster-Whisper** / **Gemini Multimodal** performs robust internal transcription with dynamic NLP language detection (`_detect_language_from_text`).
  6. LLM responds in text, followed by TTS audio playback in the user's language.

### 11.5 WhatsApp-Style Sent-File Preview (IMMUTABLE STANDARD)
- **In-bubble document card:** `buildMessageAttachmentsHTML` MUST use `buildWhatsAppAttachmentCardHTML` for non-image/non-video files (`wa-file-card` + first-page `preview_base64`). Images stay `.attachment-image-preview` and open the same overlay. Hide `Voice_Message_*`.
- **No bulky bytes in the bubble DOM:** `sendMessage` `filesForUi` keeps image/video/`Voice_Message_*` payloads; for PDF/Office it MUST omit full `base64` and keep `preview_id`, `preview_base64`, `preview_mime`, `page_count`, `size`, `path`. Full bytes live only in `FILE_PREVIEW_STORE` for the live session.
- **Viewer:** `#file-preview-overlay` (`file-preview-toolbar`, `#file-preview-stage`, `#file-preview-thumbs`). Live PDFs render via bundled pdf.js into `.file-preview-pdf-pages` canvases (`renderPdfPagesInto` / `openPdfDocument`). Forbidden: blob `iframe` as the only PDF viewer (WebView2 has no PDF plugin → blank / “Preview unavailable”). `collectMessageFileGroup` MUST call `fileFromPreviewElement` (use `.wa-file-card-thumb` and `FILE_PREVIEW_STORE` name fallback). Forbidden: mapping group items to `{ preview_base64: '' }`.
- **Download:** `downloadRememberedFile` MUST call `pywebview.api.save_file_to_downloads` (same bridge as generated images). Forbidden: overlay download that only does `<a download>` — WebView2 silently ignores it.
- **Persistence:** `_preprocess_input` forwards preview fields. History cleaners strip `base64`/`bytes` and MUST retain `preview_base64` so reload still shows the first page.
- **Composer:** `hydrateFilePreview` (pdf.js, `FILE_PREVIEW_HYDRATE_TIMEOUT_MS`) then `attachment-chip--wa-preview`. Chrome: `file_preview_*` keys in `en` and `es`.
- **Send UX:** `sendMessage` MUST append the user bubble immediately; PDF thumb hydrate runs in background via `refreshMessageAttachments` (forbidden: blocking the bubble on pdf.js up to `FILE_PREVIEW_HYDRATE_TIMEOUT_MS`). **Voice-only:** skip `refreshMessageAttachments` (or preserve `buildVoicePlayerHTML`) — never empty the mic bubble. Test: `test_voice_bubble_refresh_guard.py`.
- **Generated docs:** attachments with `path` only (no inline `base64`) MUST open via `open_file_path` on card tap; `_preprocess_input` MUST forward `path` and load bytes from disk when present.
- **Memory:** `FILE_PREVIEW_STORE` MUST cap entries (`FILE_PREVIEW_STORE_MAX_ENTRIES`); evict oldest ids when exceeded.
- **Bundled pdf.js (desktop):** `app/frontend/vendor/pdfjs/` MUST ship in-repo (`pdf.min.js`, `pdf.worker.min.js`); `files.js` MUST NOT depend on jsDelivr for pdf.js. Worker MUST load via blob URL / absolute `file://` path (`configurePdfjsWorker`) so PyWebView hydrate and overlay render do not fail silently.
- **Vertical slice (no stacked half-fixes):** A user-visible fix MUST land in **one** coherent changeset: UI + CSS + HTML overlay + any vendored assets + `api.py` persistence + unit tests. Forbidden: merge “feature without assets” and a later “add missing asset” that assumes an unpublished intermediate build. CI installer artifact is always `IgniteChat_Setup-${{ github.sha }}` — verify SHA matches the commit you tested.

---

## 12. Anti-Regression Invariants (Welcome, Sessions, STT, Clear)

These rules exist because the same defects have already shipped in production UI. **Any PR that regresses them must fail CI.**

### 12.1 Welcome message lifecycle
- `save_welcome_message` MUST append **only** when provider history is empty, or contains **only** prior `is_welcome` messages (language rewrite). Never append a welcome after real user/assistant turns.
- Frontend clear flow MUST sequence: optimistic UI wipe → **await** `clear_history(provider)` → **then** `sendWelcomeMessage()` / `save_welcome_message`. Parallel fire-and-forget clear+welcome is forbidden.
- Language-change welcome rewrite MUST key off `msg.is_welcome === true` (not `!token_info`). Welcome payloads always include a truthy `token_info` object with zeros.
- After welcome or clear, sidebar MUST call `updateChatListItem(provider, lastMsg)` so preview matches the open chat.

### 12.2 Session isolation
- Every persisted `session_id` MUST start with `{provider}_` and include the **model** segment (`{provider}_{model}_{timestamp}`). Never reuse another provider’s or another model’s id via a global `_session_id` fallback.
- `clear_history` MUST immediately persist the **new empty** session file (or welcome-only) after minting the new `session_id`. Relying solely on a racing `save_welcome_message` to create the newest mtime file is forbidden (otherwise `_find_latest_session_file` restores the wiped chat).
- `_find_latest_session_file` MUST sort by `(mtime, path)` descending so **same-second mtimes** (common on Windows/temp FS) still prefer the newest `…_YYYYMMDD_HHMMSS` session id. Sorting by mtime alone is a known regression that revived cleared chats in tests.
- After `clear_history`, the active `{session_id}.json` MUST contain `messages: []` and MUST be what `_find_latest_session_file(provider, model)` returns.
- Class-level STT/search caches on multi-tenant ACA MUST be keyed by tenant/session (`X-Ignite-Session-Id` / `_tenant_key`) or disabled for shared processes.
- Google CSE 403 MUST disable via `_SEARCH_DISABLED_BY_TENANT[namespace]` only — never a process-global `SEARCH_DISABLED` boolean.
- `LocalRAGEngine` MUST use `default_db_path(tenant_key)` (`local_rag__{tenant}.db` on ACA; `local_rag.db` on desktop). Never one shared vector DB across tenants.
- Any on-disk state that must survive an ACA restart (vector DBs, sessions, media, generated docs) MUST derive its base dir from `IGNITE_DATA_DIR` and fall back to the app root. Never build persistent paths from `__file__` alone — that resolves inside `/app`, the container's ephemeral layer.
- Scrape path: `_process_urls_in_input(..., force_language=)`, `_gemini_grounded_scrape(..., force_language=)`, `format_url_inaccessible(..., force_language=)`, and `_scrape_language_guards` MUST follow conversation locale — never hardcode Spanish for FR/EN threads.
- Reply language: use `resolve_reply_language` — never `not force_language.startswith("en") else "es-ES"` and never `force_language or USER_SYSTEM_LANGUAGE`.

### 12.3 Speech-to-text fallbacks
- Local Whisper failure / missing package MUST return `None` (not `""`) so Gemini/OpenAI Whisper fallbacks still run.
- Never cache a successful empty transcript from a failed local path; empty string after a successful model pass is allowed only when the model intentionally heard silence.
- STT/search class caches MUST be tenant-scoped (`_scoped_cache_key` / `_tenant_key`) on multi-user ACA.
- **Sticky conversation language:** After STT (and for typed turns), `PyWebViewApi._preprocess_input` MUST call `backend.core.conversation_language.resolve_conversation_language`. Keep the language of the first real user turn; ignore slang/mixed-language flips. Switch on `detect_explicit_language_switch` **or** `detect_clear_utterance_language` (clear monolingual latest utterance, including Spanish mic after an English thread). Persist `conversation_language` on user history messages. Language defaults/maps MUST come from env (`IGNITE_DEFAULT_CONVERSATION_LANGUAGE` / JSON overrides) — never hardcode `es-MX` in `api.py` call sites.

### 12.4 Cancel / single-flight generation
- Frontend `cancelProviderProcessing` MUST call backend `cancel_generation(request_id, provider)`.
- `send_message_async` MUST supersede prior in-flight work for the same provider and workers MUST honor `cancelled` before appending history.
- Generation workers MUST run under `contextvars.copy_context()` so ACA `X-Ignite-User-Name` identity survives the thread hop.
- **Ignite extract gate:** Before starting `IgniteAPIClient.extract_sync` and again after it returns, workers MUST check `_is_request_cancelled(request_id)` and skip indexing/history append chrome when cancelled. Mid-flight HTTP abort is cooperative only (no hard kill of provider sockets yet) — do not claim hard abort in docs.

### 12.5 Localized system chrome & runtime defaults
- `_media_chrome_message` / `_friendly_error_message` / `_extract_success_chrome` / `IgniteAPIClient.user_failure_hint(..., lang=)` MUST localize for at least `es|en|fr|de|it|pt` from the conversation locale. Never use binary `is_spanish ? ES : EN` for image/audio/extract chrome (FR/DE must not fall through to English).
- `get_system_capabilities()["runtime_mode"]` default MUST be `"local"`, matching `launcher_webview.py` and `app/.env.example`. Do not default capabilities to `"hybrid"` while desktop boots local-first.
- Frozen desktop MUST resolve writable data via `backend.core.runtime_paths` (`%LOCALAPPDATA%\Ignite Chat` by default; `.portable` marker for side-by-side data). Never require write access under `Program Files` for `log/app.log` or crash dumps — that raises `PermissionError` and kills startup.
- Windows installer (`packaging/setup_installer.iss`) MUST default to per-user `{localappdata}\Programs\Ignite Chat`, exclude `.env` secrets, seed `.env` from `.env.example`, and warn when WebView2 is missing.
- Do not commit unreferenced machine-local CSS clones (`chat-NBPE*.css`); only stylesheets linked from `index.html` are canonical.
- `IGNITE_EXTRACTION_ENABLED` code default MUST be `"true"` (same as `app/.env.example` / E2E skill). Explicit `false` still disables.
- Gemini MUST use `should_enable_search_after_scrape` (body &lt;800 / no URLs) — never `if not scraped_urls` alone.
- AlibabaCloud MUST remain UI-quarantined (`baseProviders` / FSM init / status cards) while backend module may stay for tests.

### 12.7 Long documents & generation timeouts
- Frontend poll MUST come from `get_initial_state` (`generation_poll_timeout_ms` / `document_poll_timeout_ms` ← `IGNITE_GENERATION_POLL_TIMEOUT_MS` / `IGNITE_DOCUMENT_POLL_TIMEOUT_MS`). Forbidden: hardcoded `6 * 60 * 1000` in `api.js` that cancels a still-running worker (`cancel_generation`) while Gemini is still writing the book summary.
- UI poll MUST be **strictly longer** than LLM HTTP and Cloud Run/ACA request timeouts so the user sees a provider error rather than a false “generation timed out”. Defaults: document poll 1800s, Gemini HTTP 900s, `IGNITE_LLM_HTTP_TIMEOUT` 900s, Cloud Run `timeoutSeconds` 900, `IGNITE_DOCUMENT_API_TIMEOUT` 900.
- Gemini MUST send `application/pdf` natively via `should_send_native_pdf` (byte cap from `IGNITE_PDF_NATIVE_MAX_BYTES`). Forbidden: always running `_extract_text_from_pdf` with a 12-page / 50k-char cap on a 100+ page book, and forbidden: scanning every PDF page for images (`IGNITE_PDF_IMAGE_PAGE_SCAN_LIMIT`).
- Whole-book intents (`wants_full_document_read`) MUST keep full text or even-sample across the book — never keyword-only cover pages.
- Provider SDK timeouts (`build_openai_client`, Anthropic, Grok, DeepSeek, Perplexity, Alibaba) MUST use `llm_http_timeout_seconds()` / `gemini_http_timeout_ms()` — never `timeout=300.0` or `http_options={'timeout': 120000}` literals.
- `remoteBridge.js` fallback MUST follow the document poll budget, not 120s.

### 12.8 WhatsApp sent-file preview
- Chat bubbles for PDF/Office MUST use `wa-file-card` / `buildWhatsAppAttachmentCardHTML`, not a filename-only `attachment-card` as the primary sent-file UI.
- `filesForUi` MUST NOT put full PDF/PPTX `base64` into the message HTML. Keep `preview_base64` (thumbnail) + `preview_id`.
- Overlay PDF MUST render with pdf.js canvases (`renderPdfPagesInto`). Overlay Download MUST use `save_file_to_downloads`. Forbidden: blob iframe as the only PDF path; forbidden: `<a download>` as the only overlay download path.
- `collectMessageFileGroup` MUST reuse `fileFromPreviewElement`. Forbidden: `{ preview_base64: '' }` placeholders that make `#file-preview-overlay` show unavailable on a card that already has a thumb.
- Session save/load MUST keep `preview_base64` after stripping full `base64`/`bytes`.

### 12.6 Mandatory regression tests & pre-push gate
- `app/tests/unit/server/test_welcome_clear_session.py` — welcome append guard, clear persists empty session that wins `find_latest` (including same-second mtime tie), session_id prefix/model scope.
- `app/tests/unit/server/test_cancel_and_tenant_cache.py` — cancel + tenant-scoped STT keys + attachment bytes.
- `app/tests/unit/voice/test_usability_and_mic_features.py` — clear-then-welcome ordering (not parallel).
- Processor STT tests — local failure returns `None` and does not poison cache.
- `app/tests/unit/server/test_productivity_and_onboarding.py` — `runtime_mode` defaults to `local` when env unset.
- `app/tests/unit/server/test_api.py` — FR/DE media chrome + friendly errors (not English fallback); extract success chrome localized.
- `app/tests/unit/processors/test_tenant_search_and_rag_isolation.py` — CSE 403 tenant-scoped; RAG DB path isolation.
- `app/tests/unit/processors/test_url_inaccessible_scrape.py` — FR lang guards / URL_INACCESSIBLE not Spanish; search-after-scrape.
- `app/tests/unit/integrations/test_ignite_api_client.py` — extraction enabled default true; localized `user_failure_hint`.
- `app/tests/unit/processors/test_pdf_long_document.py` — full-book extract vs 12-page cap; native PDF byte cap; timeout stack UI poll ≥ Gemini HTTP; env fallbacks.
- `app/tests/unit/frontend/test_whatsapp_file_preview.py` — overlay chrome + i18n + path/native-open locks (not string-scenario theater).
- `app/tests/unit/frontend/test_files_for_ui_strip.py` — `filesForUi` mirror strips PDF/Office `base64`; send bubble before background hydrate.
- `app/tests/unit/frontend/test_file_preview_feature_complete.py` — vertical-slice gate (overlay + wa-file-card + vendor pdf.js + api preview fields).
- `app/tests/unit/server/test_file_preview_persistence.py` — preprocess (preview fields, missing `page_count`, generated `path` + disk bytes) + session save/load keep thumbnail/`path`, strip full PDF bytes.
- **Full suite gate:** before any push to `Develop`/`main`, run the **entire** unit suite with the project venv:
  - `.venv_x64\Scripts\python.exe -m pytest app/tests/unit -q`
  - Target: **0 failed** (skipped OK). Running only a subset after a bugfix is not sufficient — any failure seen once MUST be locked by a regression test + this skill rule so it cannot recur.

---

## 13. References & Linked Documentation

- ⚙️ **Core Backend & Frontend Capabilities:** [SKILLS_CORE.md](file:///c:/Users/julcu/OneDrive/Ignite%20API/Ignite%20API%20-%20AI%20Assistant/.agents/skills/funcionalidades-core/references/SKILLS_CORE.md)
- 🚀 **Infrastructure & CI/CD Pipelines:** [SKILLS_DEVOPS.md](file:///c:/Users/julcu/OneDrive/Ignite%20API/Ignite%20API%20-%20AI%20Assistant/.agents/skills/iac-devops/references/SKILLS_DEVOPS.md)
- 🔗 **E2E Solution Integration:** [SKILL.md (integracion-e2e)](file:///c:/Users/julcu/OneDrive/Ignite%20API/Ignite%20API%20-%20AI%20Assistant/.agents/skills/integracion-e2e/SKILL.md)
