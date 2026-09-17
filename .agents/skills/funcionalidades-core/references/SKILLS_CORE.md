# 🛠️ Category 2: Frontend & Backend Core Features — Technical Specifications (Expanded)

This document details the exhaustive technical specifications for core AI features, system capabilities, runtime constraints, automation engines, and user experience modules in **Ignite Chat**.

---

## 1. System Capabilities & Constraints Matrix

### 1.1 ⚙️ Backend Capabilities & Limitations

- **Integrated Voice Synthesis & Transcription (`voice_processor.py`):**
  - **Speech-to-Text (STT):** Powered by `faster-whisper` using quantized models (`base` / `small` / `medium`) with dynamic CPU/CUDA hardware detection. Incorporates Voice Activity Detection (VAD) via `webrtcvad` / `silero-vad` to filter out dead air, audio clipping, and background noise prior to model ingestion.
  - **Text-to-Speech (TTS):** Integrates Cartesia's ultra-low-latency `sonic-2` streaming model via WebSockets/REST, converting textual tokens to chunked PCM/MP3 audio buffers in sub-200ms TTFB (Time to First Byte).
- **Automated Office Document Compilation (`document_generator.py`):**
  - Parses Markdown tokens, structured JSON schemas, and HTML tables to generate professional binary documents dynamically.
  - **Word (`.docx`):** Uses `python-docx` to format typography, headers, footers, callout tables, and custom styles.
  - **Excel (`.xlsx`):** Uses `openpyxl` to format multi-sheet workbooks, apply conditional styling, data validation, column autofit, and formula computation.
  - **PowerPoint (`.pptx`):** Uses `python-pptx` to construct multi-slide decks with clean layout templates, speaker notes, and diagram placeholders.
- **Long PDF / book summaries (`base_processor.py`, `gemini_processor.py`, `api.js`):**
  - Users MUST be able to summarize 100+ page books (chapter-level) without a UI/Cloud Run timeout.
  - Gemini/Anthropic send the PDF **natively** when under `IGNITE_PDF_NATIVE_MAX_BYTES` / `IGNITE_PDF_NATIVE_MAX_PAGES`. Forbidden: extracting only 12 pages / 50k chars and calling that the whole book.
  - Whole-document queries (`resumen`, `summarize`, `capítulo`, `chapter`, `libro`, `book`) keep full text up to `IGNITE_PDF_MAX_FULL_TEXT_CHARS`, else sample pages **across** the book (`IGNITE_PDF_SUMMARY_SAMPLE_PAGES`). Pinpoint Q&A may still keyword-retrieve `IGNITE_PDF_MAX_RETRIEVED_PAGES`.
  - Do not scan every page for embedded images on textbooks (`IGNITE_PDF_IMAGE_PAGE_SCAN_LIMIT`).
  - Timeout stack (must not invert): UI poll (`IGNITE_DOCUMENT_POLL_TIMEOUT_MS`) ≥ Cloud Run/ACA `timeoutSeconds` / `IGNITE_DOCUMENT_API_TIMEOUT` ≥ LLM HTTP (`IGNITE_GEMINI_HTTP_TIMEOUT_MS` / `IGNITE_LLM_HTTP_TIMEOUT`). Forbidden: a 6-minute frontend poll that cancels a still-running backend. Call sites MUST read these from `.env` (no hardcoded `6 * 60 * 1000` / `timeout=300.0`).
- **Dynamic Multi-Platform Scraping & Media Extraction (`base_processor.py`):**
  - Extracts direct video/audio streams, subtitles, descriptions, and metadata across VK Video, TikTok, Vimeo, Twitter/X, Rutube, and Instagram via `yt-dlp`.
  - Fallback parsers utilize `BeautifulSoup4` and OpenGraph metadata scrapers (`og:title`, `og:description`, `og:image`, `og:video`) for JS-light web endpoints.
  - **Inaccessible / bot-walled URLs (soft-fail):** HTTP errors, timeouts, empty SPA bodies, and challenge pages (e.g. SoundCloud “browser isn't compatible”, Cloudflare/consent walls) MUST NOT crash the host. Emit an explicit `[URL_INACCESSIBLE: {url}]` marker instructing the model not to invent page content and to ask the user for a list/screenshot. Still allow search grounding when body &lt; 800 chars. Marker text and scrape language-guards MUST follow `force_language` / detected locale (`es|en|fr|de|it|pt`) — never hardcode “(Español)” or “IN SPANISH” for non-Spanish threads.
  - **`_gemini_grounded_scrape` language:** Summary prompts MUST request output in `resolve_lang_name(force_language)` (or “user's message language”), never a fixed “IN SPANISH”.
- **Intelligent Google Search Grounding:**
  - Automated threshold verification: if scraped webpage content or user context yields fewer than 800 characters of informative text, the query automatically delegates to Google Search Grounding to enrich LLM prompt context with fresh web results.
  - **Measure scrape BODY only:** the 800-character threshold MUST exclude language-guard header/footer wrappers appended by `_process_urls_in_input`. Counting the full padded string (~1000+ chars of guards alone) falsely disables search and is a regression.
  - **All providers including Gemini:** `BaseChat.should_enable_search_after_scrape` — enable search when there are no scraped URLs **or** body &lt; 800 (including `[URL_INACCESSIBLE]`). Forbidden: Gemini-only `if not scraped_urls` that skips enrichment after a short/bot-walled scrape.
  - **CSE 403 tenant scope:** Google Custom Search HTTP 403 MUST set disable only for `_cache_namespace()` / `_tenant_key` (`_SEARCH_DISABLED_BY_TENANT`). Forbidden: process-global `SEARCH_DISABLED = True` that blinds every ACA session on the replica.
- **Multi-Provider Parallel Engine:**
  - **Active Providers:** Google Gemini, DeepSeek, OpenAI, Anthropic (Claude), Perplexity, Grok (xAI) available via direct UI selector.
  - **Unified Client Interface:** Standardized interface routing system prompts, streaming responses, token telemetry, and unified error handling across heterogeneous provider APIs.
  - **Quarantine/Disabled:** AlibabaCloud (Qwen) remains in backend schemas/tests but MUST stay out of the live UI provider list (`state.js` `baseProviders`, `stateMachine.js` FSM init, status dashboard). Sidebar markup for Alibaba stays commented out.
- **ACA Multi-User Session Isolation (`SessionApiStore`):**
  - Desktop clients inject the `X-Ignite-Session-Id` header into all IPC/REST calls.
  - Backend dynamically instantiates an isolated `PyWebViewApi` scope per tenant, ensuring ephemeral conversation memory, local disk paths, and vector namespaces remain strictly sandboxed per session.
  - **RAG DB isolation:** `LocalRAGEngine.default_db_path(tenant_key)` → `local_rag__{tenant}.db` per session; desktop without tenant keeps `local_rag.db`. Forbidden: one shared `local_rag.db` across ACA tenants.
  - **RAG DB persistence:** `default_db_path` MUST resolve its base from `IGNITE_DATA_DIR` (Azure Files mount), same convention as sessions/media/logs in `api.py`; desktop falls back to `app/Databases/vector_store/`. Forbidden: paths derived only from `__file__`, which land inside `/app` and lose all RAG memory on every deploy or scale-to-zero.
- **Backend Constraints & Safety Rules:**
  - **System Prompt Isolation:** Master prompts, guardrail instructions, and system meta-directives are maintained exclusively server-side and stripped from frontend-facing payloads.
  - **Forced Language Enforcement & Voice Pipeline:** Conversation language via `backend.core.conversation_language` (`_resolve_conversation_language`). Keep the first-turn language so slang/loanwords do not flip it. Switch on an **explicit request** OR a **clearly monolingual latest utterance** (typed or microphone STT). A Spanish voice turn after an English thread MUST become `es-MX`. Defaults/maps come from env (`IGNITE_DEFAULT_CONVERSATION_LANGUAGE`, optional JSON maps) — call sites MUST NOT hardcode `es-MX`/`en-US` product defaults.
  - **Reply-language resolution:** Providers MUST use `resolve_reply_language(force_language, user_input, history)` with the sticky `force_language` from the API. Forbidden: remapping English→Spanish, OS-locale fallback, or call-site language literals.
  - **Welcome language coherence:** UI greetings (`sendWelcomeMessage` / `translations[currentLang].greeting`) MUST follow the active UI language selector. Never append a second welcome mid-thread when switching language; rewrite or clear+recreate the single welcome only (`is_welcome`). A Spanish conversation must never grow an English “Hello… How can I help you today?” at the bottom.
  - **System chrome language (media / errors):** Auto-generated image/audio bubble chrome (`_media_chrome_message`) and friendly provider errors (`_friendly_error_message`) MUST follow the conversation `language` / `force_language` locale (at least `es|en|fr|de|it|pt`). Forbidden: binary `is_spanish ? ES : EN` that dumps FR/DE users into English chrome.
  - **Runtime mode default:** Desktop/local-first default is `IGNITE_RUNTIME_MODE=local` (`launcher_webview.py`, `.env.example`, `get_system_capabilities`). Never report a different default (`hybrid`) from capabilities while the launcher boots as `local`.
  - **Graceful Degradation:** Optional packages (`yt-dlp`, `python-docx`, `openpyxl`, `python-pptx`, `pythonnet`/`clr`) fail cleanly via `try/except ImportError` fallbacks without crashing the host application.

---

### 1.2 🎨 Frontend Capabilities & Limitations

- **Voice Input & State UI (`audio.js`, `stateMachine.js`, `chat.js`):**
  - **WhatsApp-Style Audio Message Architecture (IMMUTABLE RULE):**
    - Clicking the microphone activates raw audio recording via `MediaRecorder` + Web Audio API RMS VAD (`analyser`).
    - The floating HUD displays live volume waveforms and "Escuchando..." / "Listening...".
    - **Zero In-Browser Live Speech Typing:** The browser's Web Speech API (`SpeechRecognition` / `webkitSpeechRecognition`) must **NEVER** type live text into `#message-input`. Live speech typing causes language misclassification (e.g. English auto-typing when speaking Spanish) and destroys the voice message workflow.
    - When recording completes (silence timeout or clicking stop), `MediaRecorder` compiles the `.webm` audio file (`Voice_Message_<timestamp>.webm`), clears the text input, and renders a native **WhatsApp Voice Player bubble** (`buildVoicePlayerHTML`) with waveforms, duration, and double checkmarks (`✓✓`).
    - The `.webm` audio is sent to the backend (`app/main/api.py`), where **Faster-Whisper** or **Gemini Multimodal** performs internal server-side transcription with dynamic NLP language detection (`_detect_language_from_text`).
    - The LLM processes the transcribed text and responds, followed by TTS voice playback.
  - **WhatsApp-Style File Preview (IMMUTABLE RULE):**
    - Sent documents (PDF first; Office as branded card) MUST render an in-bubble first-page preview (`wa-file-card` via `buildWhatsAppAttachmentCardHTML`), not a filename-only chip.
    - Tap opens `#file-preview-overlay` (toolbar + stage + multi-file thumbs). Live session uses the in-memory `FILE_PREVIEW_STORE` (full bytes → **pdf.js canvas** in `#file-preview-stage`, not a blob iframe — WebView2 has no PDF plugin). Reloaded history MAY show only `preview_base64` (never rehydrate the full PDF into the bubble DOM). Overlay Download MUST call `save_file_to_downloads` (PyWebView blocks `<a download>`).
    - `sendMessage` MUST strip bulky non-image `base64` from `filesForUi` and keep `preview_id` / `preview_base64` / `preview_mime` / `page_count` / `size`. Forbidden: embedding a full PPTX/PDF data-URI in the chat HTML (UI-thread freeze).
    - `collectMessageFileGroup` MUST map each card through `fileFromPreviewElement` (thumb fallback). Forbidden: rebuilding the group with empty `preview_base64: ''` (viewer shows “Preview unavailable”).
    - `_preprocess_input` MUST forward preview fields; `_clean_history_for_saving` / `_clean_history_for_frontend` MUST drop full `base64`/`bytes` and **keep** `preview_base64`.
    - Pending composer chips use `attachment-chip--wa-preview` after `hydrateFilePreview` (pdf.js first page, timeout `FILE_PREVIEW_HYDRATE_TIMEOUT_MS`). Hide `Voice_Message_*` from document cards.
    - `sendMessage` shows the user bubble immediately; PDF thumbnail hydrate refreshes the card in background (`refreshMessageAttachments`) — never block send on pdf.js.
    - Server-generated Office/PDF cards carry `path`; tap opens the native file when no inline bytes. `_preprocess_input` forwards `path` and reads bytes from disk when needed.
    - `FILE_PREVIEW_STORE` evicts oldest entries after `FILE_PREVIEW_STORE_MAX_ENTRIES` to avoid unbounded PDF memory.
    - Chrome keys: `file_preview_close` / `file_preview_download` / `file_preview_page` / `file_preview_pages` / `file_preview_unavailable` / `file_preview_open_native` in `en` and `es`.
  - Driven by a finite state machine managing strict state transitions (`IDLE`, `RECORDING`, `THINKING`, `SPEAKING`, `ERROR`) to lock out race conditions, prevent overlapping voice recording, and update DOM visuals reactively.
- **1-Click Document Export & Presentation:**
  - Interactive table rendering with embedded single-click export triggers to `.xlsx` alongside direct URL download buttons for server-generated `.docx` and `.pptx` files.
- **Automated Speech Playback:**
  - Streaming audio buffer queues via HTML5 Audio / Web Audio API with event hooks (`onended`, `onerror`) triggering state machine resets back to `IDLE`.
- **Frontend Constraints & Limitations:**
  - **Zero Direct Secret Access:** PyWebView client scripts operate inside an unprivileged web view without access to host file system roots, `.env` configurations, or provider API keys.
  - **TTS-Optimized Audio Constraints:** When voice input is active, backend prompts enforce concise, conversational LLM responses to avoid long TTS synthesis queues.
  - **Stylesheet ownership:** Only linked CSS under `app/frontend/css/` (`index.html` `<link>` tags) is shipping UI. Never commit machine-local duplicates (e.g. `chat-NBPE*.css`); edit `chat.css` / siblings that `index.html` actually loads.

---

## 2. Deep-Dive: Advanced Feature Specifications

### 2.1 Persistent Memory & Local RAG Engine (`rag_engine.py`)
- **Architecture:** Embedded vector storage using SQLite (`local_rag.db` desktop; `local_rag__{tenant}.db` per ACA `X-Ignite-Session-Id`) with dense embeddings and cosine similarity search, under `<IGNITE_DATA_DIR or app>/Databases/vector_store/`.
- **Embedding Pipeline:** Utilizes sentence-transformers (`sentence-transformers/all-MiniLM-L6-v2`) or hash/fallback embeddings when SBERT is unavailable.
- **Retrieval Strategy:** Top-$K$ semantic similarity search ($K=4$–$8$) with cosine scoring for context-rich chat injection.
- **Isolation rule:** `PyWebViewApi` MUST construct `LocalRAGEngine(tenant_key=self._tenant_key)` so tenants never share vectors.

### 2.2 Isolated Code Execution Sandbox (`sandbox_runner.py`)
- **Execution Environment:** Sandboxed subprocess executing Python/Node.js snippets inside isolated environments (restricted permissions, no host network access by default).
- **Resource Constraints:** Hard limits on execution time ($T \le 10	ext{s}$), RAM allocation ($\le 512	ext{MB}$), and CPU core quotas.
- **Output Handlers:** Captures `stdout`, `stderr`, execution traces, and serializes generated Matplotlib/Plotly figures into Base64 PNG strings for inline UI rendering.

### 2.3 Web Fetch Agent (`web_agent.py`) — shipping scope
- **Engine (current):** `requests` + BeautifulSoup4 HTML fetch/clean (not Playwright/Chromium).
- **Core Capabilities:** Fetch URL, strip scripts/styles, extract title + body text + hyperlinks, truncate to `max_length`.
- **Out of scope until implemented:** Headless Chromium, SPA click/fill, screenshot, anti-bot bypass. Do not document Playwright as shipped.

### 2.4 Personal Model Context Protocol (MCP) Gateway (`mcp_gateway.py`) — shipping scope
- **Protocol:** Local tool registry used by Ignite Chat (JSON-RPC-style tool list/call for in-process tools).
- **Tools shipping today:** `system_status`, `ignite_list_templates`, `ignite_extract_file` (Ignite API extraction bridge).
- **Not shipping yet:** Slack / Jira / GitHub / Gmail / Calendar workplace connectors. Do not claim them as live.

### 2.5 Voice profile helper (`voice_clone.py`) — shipping scope
- **Current:** Stores reference audio profiles and returns/encodes reference bytes for playback experiments.
- **Not shipping yet:** Coqui / RVC / XTTS neural cloning pipelines. Cartesia TTS remains the production voice path.

### 2.6 PII Guardrails & Security Shield (`guardrails.py`) — shipping scope
- **Detection Pipeline:** Regex scanners for emails, phones, cards, DNI-like IDs, long tokens/API keys, plus prompt-injection heuristics.
- **Not shipping yet:** spaCy NER / Microsoft Presidio pipelines. Do not document Presidio as active.
- **Sanitization Scope:** Masks matched PII before prompts leave the local machine for cloud LLM inference where the shield is invoked.

### 2.7 Interactive Data Dashboards (`plotly_service.py`, `chartRenderer.js`)
- **Data Pipeline:** LLM emits Plotly-compliant JSON data specifications.
- **Rendering Layer:** Embedded PyWebView `<iframe>` sandbox executing `plotly.js` via an isolated bridge, supporting zoom, pan, hover tooltips, and SVG/PNG image export without polluting the main window scope.

### 2.8 Dynamic Skill Store & Plugin Loader (`skill_loader.py`)
- **Plugin Architecture:** Discovers and registers custom agent tools and hooks at runtime via Python dynamic imports (`importlib.util`).
- **Lifecycle Management:** Allows hot-reloading, enabling/disabling skills, and validating skill schemas (Pydantic manifest validation) dynamically without terminating the main application process.

### 2.9 Setup Wizard, Productivity Value Telemetry & Smart Fallbacks (`api.py`)
- **Setup & Onboarding Wizard:** First-run and settings-accessible wizard that performs host hardware self-discovery (CUDA GPU, Tesseract OCR, Microphone) and live API key testing against provider endpoints with atomic `.env` persistence, user dismissal storage memory, and runtime hot-reloading.
- **Productivity & ROI Telemetry (`get_productivity_metrics`):** Aggregates lifetime tokens, estimated words, typing hours saved ($\approx \text{words} / 40 / 60$), Office document compilation hours ($0.35\text{ hrs/doc}$), and economic ROI multiplier based on standard human operational labor value (\$25 USD/hr).
- **Smart Fallback Recovery (`get_smart_fallback`, `window.triggerSmartFallback`, `window.switchAndRetry`):** Renders non-blocking interactive recovery cards in the live chat feed (`isLive = true`) upon provider errors/rate limits (429/503) enabling 1-click query execution against healthy alternate providers without session pollution.

---

## 3. References & Architecture Links

- 📖 **Coding Standards & Best Practices:** `SKILLS_CODING.md`
- 🚀 **DevOps, Packaging & CI/CD Pipelines:** `SKILLS_DEVOPS.md`
- 🔗 **End-to-End Solution Integration:** `SKILL.md (integracion-e2e)`