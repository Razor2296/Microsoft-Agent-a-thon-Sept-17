# 🛠️ Category 3: Infrastructure as Code (IaC) & DevOps — Technical Specifications (Expanded)

This document specifies the comprehensive technical standards for cloud infrastructure provisioning (Azure), containerization workflows, CI/CD pipelines, observability architectures, and multi-environment configuration management for **Ignite Chat**.

---

## 1. Containerization Architecture (Docker & Docker Compose)

### 1.1 Multi-Stage Dockerfile (`app/Dockerfile`)
- **Stage 1 (Builder / Dependency Resolution):**
  - Uses `python:3.11-slim` or `python:3.12-slim` base image.
  - Installs compilation dependencies (`gcc`, `g++`, `build-essential`, `libffi-dev`, `git`).
  - Generates isolated Python virtual environment (`/opt/venv`), resolving and freezing all pinned wheels via `pip install --no-cache-dir -r requirements.txt`.
- **Stage 2 (Final Runtime Container):**
  - Ultra-lightweight Debian/Alpine-slim base containing only essential shared system runtime libraries (`ffmpeg` for audio stream processing, `libmediainfo`, `ca-certificates`).
  - Copies strictly the built `/opt/venv` from Stage 1 to minimize image footprint and attack surface.
  - Copies application source code (`app/`), static frontend assets (`app/frontend/`), and default templates.
  - **Security & User Isolation:** Creates and enforces a non-root system user (`igniteuser:ignitegroup`, UID/GID 10001) for runtime process execution.
  - **Exposed Ports & Startup:** Exposes backend HTTP/WebSocket port `8000`. Directs startup through `uvicorn app.backend.server:app --host 0.0.0.0 --port 8000 --workers 2`.

### 1.2 Local & Staging Orchestration (`app/docker-compose.yml`)
- **Service Topology:**
  - `ignite-backend`: Core FastAPI / PyWebView API server.
  - `redis-cache` (optional local mock): Ephemeral cache and message pub/sub.
  - `otel-collector` (optional observability sidecar): Collects OpenTelemetry traces and Prometheus metric scrapes.
- **Health Checks & Probes:**
  - Configures container health checks (`test: ["CMD", "curl", "-f", "http://localhost:8000/health"]`, interval: 15s, timeout: 5s, retries: 3, start_period: 20s).
- **Persistent Volume Mounts:**
  - Host directory mapping to container target `/data` to persist vector embeddings, session metadata, audio cache, and generated documents.

### 1.3 Persistent Storage on Azure Container Apps (ACA)
- **Mount Configuration:**
  - `/data` is backed by an Azure Files Storage Share mounted directly to the Container Apps Environment (CAE: `ignitechat-sessions`).
- **Scale-to-Zero Resilience:**
  - Persistent volume mounts ensure that dynamic scaling events (e.g., scaling down to 0 replicas during idle periods and cold-starting on incoming webhooks/queries) do not lose user conversational history, tenant vector embeddings, or uncollected binary reports.
- **Automated Provisioning Script:**
  - `scripts/Deploy-IgniteChatAca.ps1` automates Azure CLI session authentication, volume mount validation, container revision deployment, and rollout health verification across PowerShell and WSL environments.

### 1.4 Google Cloud Run request timeout
- `gcloud run deploy/update` for `ignitechat` and `igniteapi` MUST set `--timeout` ≥ `IGNITE_DOCUMENT_API_TIMEOUT` (default **900** seconds). Cloud Run's platform default of 300s cancels 100+ page book summaries.
- Keep Cloud Run `timeoutSeconds` aligned with `IGNITE_GEMINI_HTTP_TIMEOUT_MS` / `IGNITE_LLM_HTTP_TIMEOUT` (900s). The desktop UI poll (`IGNITE_DOCUMENT_POLL_TIMEOUT_MS`) MUST stay longer so it does not cancel first.

---

## 2. Azure Cloud Infrastructure via Terraform (HCL)

### 2.1 Declarative Infrastructure Architecture (`infra/terraform/`)
- **Terraform Workspace & State:**
  - Remote backend state stored securely in Azure Blob Storage with state locking enabled via Azure Storage Tables/Blob Leases.
- **Target Resource Group:** `IgniteAPI` (East US 2 / South Central US).
- **Managed Cloud Resources:**
  - **Azure Key Vault (`kvignitechat`):**
    - Stores critical secrets: `OPENAI_API_KEY`, `GEMINI_API_KEY`, `ANTHROPIC_API_KEY`, `DEEPSEEK_API_KEY`, `CARTESIA_API_KEY`, `REDIS_CONNECTION_STRING`.
    - Role-Based Access Control (RBAC) configured via Azure Key Vault Secrets User role assigned to ACA Managed Identity.
  - **Azure Container Registry (ACR):**
    - Shared registry `caacc1441625acr` with automated image scanning and vulnerability triage.
  - **Azure Container Apps Environment (CAE):**
    - Shared Managed Environment configured with custom Log Analytics workspace integration, VNet integration for private subnet isolation, and Azure Files storage mounts.
  - **Azure Container App (`ignitechat-api`):**
    - Ingress: External HTTPS enabled (port 8000), TLS termination managed by ACA.
    - Resources: Configured with 1.0 vCPU and 2.0 GiB RAM per replica.
    - Autoscaling Rules: HTTP concurrent request scaling (min replicas: 0, max replicas: 5, target concurrency: 30).
- **Hybrid Connection to IgniteAPI (`docs/HYBRID_ACA.md`):**
  - Unified CAE, shared ACR repository, and centralized Key Vault secrets linking Ignite Chat with the broader Ignite API ecosystem.

---

## 3. CI/CD Deployment Pipelines (GitHub Actions)

### 3.1 GitHub Actions Workflow Matrix

- **1. Continuous Integration & Quality Gate (`.github/workflows/ci.yml`):**
  - **Trigger:** Pull Requests targeted at `main` or `staging` branches modifying `app/**` or `infra/**`.
  - **Linting & Formatting:**
    - Python: Executes `ruff check app/` and `ruff format --check app/`.
    - Frontend: Executes `prettier --check app/frontend/`.
  - **Static Type Safety:** Runs `mypy app/` against backend schemas and core processors.
  - **Automated Testing Suite:** Runs `pytest app/tests/unit/ --cov=app --cov-report=xml --cov-fail-under=80` to enforce test coverage gates before PR merge eligibility.

- **2. Continuous Deployment to ACA (\.github/workflows/deploy-aca.yml\):**
  - **Trigger:** Push / merge to \main\ (and \workflow_dispatch\). Same pattern as IgniteChat.
  - **Execution Stages:**
    1. **Build & push:** Docker build of \pp/Dockerfile\ → ACR \igniteapisiuacr.azurecr.io/ignitechat-api\ tags \:sha\ and \:latest\ (needs \ACR_USERNAME\ / \ACR_PASSWORD\).
    2. **Azure auth:** Default **device code** (SIU MFA/passkey via https://microsoft.com/devicelogin); optional \AZURE_CREDENTIALS\ SP.
    3. **Container App update:** \scripts/ci/deploy-ignitechat-aca.sh\ points \ignitechat-api\ at the **new** image tag (env + Key Vault refs).
    4. Skip rebuild: Run workflow with \image_tag\ set to an existing ACR tag.

- **3. Manual & Local Deployment Fallback (`scripts/Deploy-IgniteChatAca.ps1`):**
  - PowerShell/WSL script allowing developers to manually build, tag, push, and deploy revisions directly via Azure CLI during offline emergency maintenance or direct staging tests.

### 3.2 Git Branching Standards: Direct `Develop` Workflow Policy
- **Active Working Branch:** All ongoing development, bug fixes, refactoring, and AI capability additions are applied directly to the `Develop` branch (`origin/Develop`).
- **No Temporary Remote Branches:** Agents and developers must NOT create secondary feature branches, temporary topic branches, or extra remote branches. Everything is committed and pushed directly to `Develop`.
- **Release Promotion to `main`:** Promotion from `Develop` to `main` for ACA container deployments is performed exclusively from the `Develop` branch after full unit test verification (`pytest app/tests/unit/`).

---

## 4. Observability, Telemetry & Reliability

### 4.1 In-Process Metrics & Instrumentation (`app/backend/telemetry.py`)
- **Metric Collection Engine:**
  - Embedded Prometheus client exposing application-level counters, gauges, and histograms.
- **FastAPI Endpoints:**
  - `GET /metrics`: Standardized Prometheus scrape target monitoring:
    - `ignite_requests_total`: Total invocations partitioned by HTTP path, method, and status code.
    - `ignite_request_duration_seconds`: Histogram measuring endpoint and LLM response latency.
    - `ignite_active_sessions`: Gauge tracking active PyWebView client sessions.
    - `ignite_tokens_consumed_total`: Counter monitoring token consumption (prompt + completion) partitioned by LLM provider (OpenAI, Gemini, Anthropic, DeepSeek).
    - `ignite_errors_total`: Error counter tracking exceptions categorized by module and error code.
  - `GET /health`: Liveness and readiness probe validating Key Vault connectivity, disk write access on `/data`, and downstream AI model provider availability.

### 4.2 Distributed Tracing & Structured Logging
- **OpenTelemetry Standard:**
  - Managed via environment flag `IGNITE_OTEL_ENABLED=true`.
  - Injects correlation identifiers (`trace_id`, `span_id`, `session_id`) into log records.
- **Log Aggregation:**
  - Directs structured JSON logs to Azure Log Analytics Workspace and `stdout` for centralized ingestion and querying with Kusto (KQL).

---

## 5. Multi-Environment Configuration Management

### 5.1 Dynamic Environment Resolver (`app/main/env_config.py`)
- **Hierarchy & Environment Resolution:**
  - Controlled by runtime variable `IGNITE_ENV` (`development`, `staging`, `production`).
  - Resolves target configuration files deterministically:
    - `development` $
ightarrow$ `.env`
    - `staging` $
ightarrow$ `.env.staging`
    - `production` $
ightarrow$ `.env.prod`
- **Template Synchronization & Security:**
  - Standardized `.env.example`, `.env.staging.example`, and `.env.prod.example` templates committed to source control for onboarding and schema tracking.
  - Actual `.env*` files containing secrets are strictly added to `.gitignore` to prevent credential leaks.
- **Runtime Binding:**
  - FastAPI server, Pydantic `BaseSettings`, and `PyWebViewApi` initialize configuration on boot, validating that all required provider keys, endpoints, and volume mounts exist before opening network listeners.

---

## 6. References & Linked Documentation

- 📖 **Coding Best Practices:** `SKILLS_CODING.md`
- ⚙️ **Core Backend & Frontend Capabilities:** `SKILLS_CORE.md`
- 🔗 **End-to-End Solution Integration:** `SKILL.md (integracion-e2e)`
- ☁️ **Hybrid ACA Deployment Architecture:** `docs/HYBRID_ACA.md`