# 🛠️ Category 4: E2E Integration & Microservices (Ignite Chat ↔ Ignite API) — Technical Specifications (Expanded)

This document defines the exhaustive architectural blueprint, design patterns, security protocols, and implementation standards for integrating **Ignite Chat** (the multi-model conversational orchestrator) with **Ignite API** (the multimodal enterprise ingestion and structured extraction engine), as well as external microservices and third-party tools.

---

## 1. Service-to-Service (S2S) Architecture & Orchestration Flow

Ignite Chat acts as the **conversational orchestrator**, while Ignite API operates as the **asynchronous extraction worker** running on Azure Container Apps (ACA).

```text
       User on Desktop / Web Client (PyWebView)
                         │
                         ▼
┌─────────────────────────────────────────────────────────┐
│                      Ignite Chat                        │
│  • Parses user intent & detects file attachments        │
│  • Emits structured extraction marker:                  │
│    [IGNITE_EXTRACT: filename.ext|TemplateName]          │
│  • Intercepts marker via regex & invokes IgniteAPIClient│
└────────────────────────────┬────────────────────────────┘
                             │
                             │ (Authenticated async HTTPS request via httpx)
                             │ Headers: X-API-Key: <IGNITE_MASTER_API_KEY>
                             ▼
┌─────────────────────────────────────────────────────────┐
│                      Ignite API                         │
│  (Multimodal Extraction Engine on Azure Container Apps) │
│  • Master Ingestion Router (/api/v1/extract?mode=auto)  │
│  • Domain Parsers: Documents, Audio, Images, Video      │
│  • Background Job Manager (/api/v1/jobs/{job_id})       │
└────────────────────────────┬────────────────────────────┘
                             │
                             │ Returns JSON (ExtractionResponse)
                             │ [Direct HTTP 200 OK  OR  HTTP 202 Accepted + Polling]
                             ▼
┌─────────────────────────────────────────────────────────┐
│           Semantic RAG Transformation Pipeline          │
│                 (ignite_rag_transformer.py)             │
│  • Serializes JSON + Confidence + Model Reasoning       │
│  • Formats human-readable & query-optimized markdown    │
└────────────────────────────┬────────────────────────────┘
                             │
                             │ Ingests structured RAG blocks & embeddings
                             ▼
┌─────────────────────────────────────────────────────────┐
│                    Local RAG Engine                     │
│    (SQLite Vector Store + SBERT all-MiniLM-L6-v2)       │
│  • Injects extracted domain facts into conversation memory│
└─────────────────────────────────────────────────────────┘
```

---



## 2. Core Architectural Components & Integration Patterns



### 2.1 Decoupled HTTP Client (`IgniteAPIClient`)

- **Module Location:** `app/backend/integrations/ignite_api_client.py`
- **Networking Stack:** Built on `httpx.AsyncClient` with configurable timeout boundaries (`IGNITE_EXTRACTION_MAX_WAIT`).
- **S2S Authentication:** Mutual security enforced via the `X-API-Key` HTTP header carrying the master secret token.
- **Unified Master Endpoint:** All extraction requests route to `POST /api/v1/extract` with query parameter `mode=auto` (allowing the upstream engine to select the optimal domain extractor).



#### Dual Synchronous / Asynchronous 202 Polling Pattern:

1. `HTTP 200 OK` **(Immediate Completion):**
  - The extraction completed synchronously in-flight. Returns the parsed `ExtractionResponse` payload immediately.
2. `HTTP 202 Accepted` **(Asynchronous Job Queue):**
  - The server queued the heavy file for background processing.
  - The client parses `job_id` (or `statusQueryGetUri`) from the JSON response.
  - **Non-blocking Polling Loop:** The client executes an asynchronous polling loop (`await asyncio.sleep(IGNITE_EXTRACTION_POLL_INTERVAL)`) against `GET /api/v1/jobs/{job_id}`.
  - **Terminal States:** Halts and resolves on `completed` (success) or `failed` (error). If `IGNITE_EXTRACTION_MAX_WAIT` (default 120s) elapses, the client triggers a timeout exception and falls back to local parsing.

```python
# app/backend/integrations/ignite_api_client.py
import asyncio
import logging
import httpx
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

class IgniteAPIClient:
    def __init__(self, base_url: str, api_key: str, poll_interval: int = 3, max_wait: int = 120):
        self.base_url = base_url.rstrip("/")
        self.headers = {"X-API-Key": api_key, "Accept": "application/json"}
        self.poll_interval = poll_interval
        self.max_wait = max_wait

    async def extract_structured_data(self, file_bytes: bytes, filename: str, template: Optional[str] = None) -> Dict[str, Any]:
        async with httpx.AsyncClient(timeout=30.0) as client:
            files = {"file": (filename, file_bytes)}
            data = {"template": template} if template else {}
            
            response = await client.post(f"{self.base_url}/api/v1/extract?mode=auto", headers=self.headers, files=files, data=data)
            
            # Fast path: instant synchronous extraction
            if response.status_code == 200:
                return response.json()
            
            # Async path: 202 Accepted polling loop
            if response.status_code == 202:
                job_data = response.json()
                job_id = job_data.get("job_id")
                return await self._poll_job(client, job_id)
            
            response.raise_for_status()

    async def _poll_job(self, client: httpx.AsyncClient, job_id: str) -> Dict[str, Any]:
        elapsed = 0
        while elapsed < self.max_wait:
            await asyncio.sleep(self.poll_interval)
            elapsed += self.poll_interval
            
            poll_resp = await client.get(f"{self.base_url}/api/v1/jobs/{job_id}", headers=self.headers)
            if poll_resp.status_code == 200:
                payload = poll_resp.json()
                status = payload.get("status", "").lower()
                
                if status == "completed":
                    return payload.get("result", {})
                elif status == "failed":
                    error_msg = payload.get("error", "Upstream job failed")
                    raise RuntimeError(f"Extraction job {job_id} failed: {error_msg}")
        
        raise TimeoutError(f"Extraction job {job_id} exceeded maximum wait time of {self.max_wait}s")
```

---



### 2.2 Marker Protocol & System Prompt Interception (`[IGNITE_EXTRACT]`)

- **System Prompt Injection:** All active LLMs (Gemini, OpenAI, Anthropic, DeepSeek, Grok, Perplexity) receive dynamic extraction guidelines via `inject_extraction_guidelines()`.
- **Standardized Marker Syntax:**
  ```text
  [IGNITE_EXTRACT: filename.ext|TemplateName]
  ```
  - `filename.ext`: Exact name of the uploaded document, audio, video, or image attachment.
  - `TemplateName`: Predefined target schema (e.g., `Invoice_Standard`, `Medical_Prescription`).



#### Backend Interception Pipeline (`app/main/api.py` / `app/backend/server.py`):

1. **Regex Detection:**
  ```python
   extract_match = re.search(r'\[IGNITE_EXTRACT:\s*(.*?)\|(.*?)\]', assistant_response_text)
  ```
2. **Dispatch & Extraction:** If a match occurs, the worker fetches the file from the local session attachment cache and executes `IgniteAPIClient.extract_structured_data()`.
3. **Semantic Serialization:** Converts raw JSON output into an enriched markdown block via `ignite_rag_transformer.py`.
4. **UI Sanitization:** Strips the raw `[IGNITE_EXTRACT: ...]` token from the chat bubble before rendering so end-users see a clean conversation.
5. **Vector Ingestion:** Enriches the local RAG engine (`app/Databases/vector_store/`) with the semantic markdown representation.

---



### 2.3 Semantic RAG Transformer (`ignite_rag_transformer.py`)

- **Core Rule:** Raw JSON blobs must **never** be injected directly into vector databases. Flat key-value trees produce poor semantic embeddings and lack contextual clarity.
- **Model Reasoning & Confidence Integration:** The transformer serializes the extracted value alongside model reasoning, confidence scores, and extraction metadata.



#### Semantic Output Format Standard:

```markdown
📄 EXTRACCIÓN ESTRUCTURADA: invoice_9842.pdf
• Proveedor/Modelo: azure_openai (gpt-4.1-mini)
• Plantilla: Invoice_Standard | Tiempo: 4.82s | Tokens: 1,450

DATOS EXTRAÍDOS CON RAZONAMIENTO DEL MODELO:
- Vendor_Name: "Acme Logistics Corp." (Confianza: 98%, Requerido)
  ↳ Razonamiento (gpt-4.1-mini): "Identificado en la cabecera superior izquierda del documento fiscal."
- Total_Amount: "USD 12,450.00" (Confianza: 95%, Requerido)
  ↳ Razonamiento (gpt-4.1-mini): "Monto final calculado tras sumar impuestos y subtotal."
- Tax_ID: "US-983241098" (Confianza: 92%, Opcional)
  ↳ Razonamiento (gpt-4.1-mini): "Número de identificación fiscal especificado junto al registro legal."
```



#### Multi-Row Tabular Data Serialization (`is_multi_row=true`):

For multi-row tables (e.g., invoices, payroll rosters, bank statements), each row is serialized as an independent semantic chunk (`row_1`, `row_2`, ...) containing column values, confidence metrics, and cell reasoning for high-precision semantic retrieval.

---



## 3. Multimodal Extraction Channel & Template Catalog


| Channel       | Supported File Formats           | Recommended Templates                                                                               | Business Domain & Use Case                                                                              |
| ------------- | -------------------------------- | --------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------- |
| **Documents** | `.pdf`, `.docx`, `.xlsx`, `.txt` | `Invoice_Standard` `Resume_CV` `Bank_Statement` `Employment_Contract` `Tax_Return`                  | Commercial contracts, vendor invoices, financial statements, resume screening, and tax forms.           |
| **Audio**     | `.mp3`, `.wav`, `.m4a`, `.ogg`   | `Meeting_Minutes` `Medical_Prescription` `Voice_Memo_Tasks` `Customer_Call_Audit` `Interview_Audit` | Executive meeting transcription, voice-dictated prescriptions, CRM call quality checks, and interviews. |
| **Images**    | `.png`, `.jpg`, `.jpeg`, `.tiff` | `Medical_Prescription` `Identity_Document` `Invoice_Standard`                                       | Handwritten prescription digitization, passport/ID verification, and receipt OCR.                       |
| **Video**     | `.mp4`, `.avi`, `.mov`, `.mkv`   | `Lecture_Summary` `Video_Ad_Analysis`                                                               | Video course summaries, conference recordings, and marketing video reviews.                             |


---



## 4. Configuration, Feature Flags & Resilient Fallbacks



### 4.1 Environment Variable Bindings (`app/.env`)

```env
# ── E2E Integration with Ignite API ──────────────────────────────────────────
IGNITE_EXTRACTION_ENABLED=true
IGNITE_EXTRACTION_API_URL=https://ignite-api.azurecontainerapps.io
IGNITE_EXTRACTION_API_KEY=your_master_api_key_here
IGNITE_EXTRACTION_POLL_INTERVAL=3
# Sync POST read budget + async poll budget (seconds). Default 300.
IGNITE_EXTRACTION_MAX_WAIT=300
IGNITE_EXTRACTION_CONNECT_TIMEOUT=30
IGNITE_EXTRACTION_WRITE_TIMEOUT=60
# Observability only — mirrors Ignite API doc sync threshold; server decides mode.
IGNITE_MAX_SYNC_DOC_MB=15
```

**Sync vs async contract:** Ignite Chat **always** calls `POST /api/v1/extract?mode=auto`. Ignite API alone chooses sync (HTTP 200) or async (HTTP 202 + job poll) from file size (`MAX_SYNC_FILE_SIZE_*_MB`: doc/extract 15MB, image/audio 10MB, video 25MB). Chat must not force `mode=sync`/`async` by re-implementing thresholds; it only splits httpx timeouts (connect / write / read) and polls after 202.



### 4.2 Defensive Failure Protocol

1. **Feature Flag Check:** Default is enabled (`IGNITE_EXTRACTION_ENABLED` unset → `true`, matching `app/.env.example`). When explicitly `false`, the client completely skips network calls without generating warnings.
2. **Graceful In-Process Degradation:** If network errors, 5xx outages, or timeouts occur, the system falls back immediately to local parsing engines (`office_extract.py`, `pypdf`, `pytesseract`).
3. **User-Safe Messaging:** Stack traces, HTTP error codes, and API keys are never exposed in user chat bubbles. Success/failure chrome is localized via `_extract_success_chrome` / `user_failure_hint(..., lang=)` (`es|en|fr|de|it|pt`). Internal errors are logged via `logger.error(..., exc_info=True)`.
4. **Provider Delegation:** Omit `llm_provider` and `model` in outbound payloads by default to allow Ignite API to select optimal server-side defaults.

---



## 5. Core Architectural Non-Negotiables for Agents

1. **Mandatory `mode=auto`:** Always call Ignite API with `mode=auto`; never re-decide sync/async by file size in Chat (server thresholds are the source of truth).
2. **Mandatory 202 Polling:** Implement asynchronous polling on `HTTP 202 Accepted`; never drop or abort pending extraction jobs prematurely. Poll budget starts after the 202, separate from the sync POST read timeout.
3. **No Raw JSON in Vector Memory:** Always convert extraction responses to structured, human-readable markdown with model reasoning before inserting into RAG.
4. **Strict Feature Flag Adherence:** Always evaluate `IGNITE_EXTRACTION_ENABLED` before making external HTTP requests.
5. **Zero-Crash Resilience:** Always catch S2S exceptions and fallback to standard in-process text extraction gracefully.

---



## 6. References & Linked Documentation

- 📖 **Coding Standards & Best Practices:** `SKILLS_CODING.md`
- ⚙️ **Core Features & System Capabilities:** `SKILLS_CORE.md`
- 🚀 **DevOps, Packaging & CI/CD Pipelines:** `SKILLS_DEVOPS.md`

