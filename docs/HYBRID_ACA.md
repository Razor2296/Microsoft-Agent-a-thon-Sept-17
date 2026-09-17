# Ignite Chat — Hybrid Desktop + Azure Container Apps

## Goal

Keep the **same PyWebView UI** on Windows while moving heavy compute (Whisper, group chat, RAG, processors) to an **Azure Container Apps** HTTP backend.

## Runtime modes

| Mode | Where | `.env` |
| --- | --- | --- |
| Local desktop (baseline) | All processors in-process | `IGNITE_RUNTIME_MODE=local` (default) |
| Remote desktop (thin client) | UI local, API remote | `IGNITE_RUNTIME_MODE=remote` + `IGNITE_API_BASE_URL` + `IGNITE_API_KEY` |
| ACA server | FastAPI in Linux container | `IGNITE_RUNTIME_MODE=server` (set by Dockerfile) |

### Desktop remote `.env` example

```env
IGNITE_RUNTIME_MODE=remote
IGNITE_API_BASE_URL=https://<aca-fqdn>
IGNITE_API_KEY=<same-key-as-aca>
IGNITE_API_TIMEOUT=120
```

### Server `.env` / Key Vault

Consumption secrets live in RG **`IgniteChat`** vault **`kvignitechatsiu`** (PAYG)  
(`https://kvignitechatsiu.vault.azure.net/`). Do not store IgniteChat provider keys in IgniteAPI’s `kvsecret2296siu`.

| ACA secret | Key Vault secret | Env var |
| --- | --- | --- |
| `ignite-api-key` | `IGNITE-API-KEY` | `IGNITE_API_KEY` |
| `gemini-api-key` | `GEMINI-API-KEY` | `GEMINI_API_KEY` |
| `openai-api-key` | `OPENAI-API-KEY` | `OPENAI_API_KEY` |
| `anthropic-api-key` | `ANTHROPIC-API-KEY` | `ANTHROPIC_API_KEY` |
| `perplexity-api-key` | `PERPLEXITY-API-KEY` | `PERPLEXITY_API_KEY` |
| `grok-api-key` | `GROK-API-KEY` | `GROK_API_KEY` |
| `deepseek-api-key` | `DEEPSEEK-API-KEY` | `DEEPSEEK_API_KEY` |
| `azure-openai-api-key` | `AZURE-OPENAI-API-KEY` | `AZURE_OPENAI_API_KEY` |

OpenAI chat uses **Azure AI Foundry** (PAYG `foundryignitechatsiu`) via:

- `OPENAI_BASE_URL` / `AZURE_OPENAI_ENDPOINT` = `https://foundryignitechatsiu-87996.openai.azure.com/openai/v1`
- Models (ACA `OPENAI_AVAILABLE_MODELS`): **`gpt-4.1-mini`** on PAYG until Foundry quota deploys `gpt-5.6-*` / replacement for `o3` (Students had five deployments; `o3` 2025-04-16 cannot be newly deployed).

Document extraction (Chat → **ignite-api** on the shared CAE):

- `IGNITE_EXTRACTION_ENABLED=true`
- `IGNITE_EXTRACTION_API_URL` = PAYG `ignite-api` FQDN (see workflow env in `deploy-aca.yml`)
- `IGNITE_EXTRACTION_API_KEY` = Key Vault `IGNITE-EXTRACTION-API-KEY` (same value as `IGNITE-MASTER-API-KEY` on `kvsecret2296siu`)

`ignitechat-api` uses **system-assigned managed identity** + role **Key Vault Secrets User** on `kvignitechatsiu`. ACA secrets are `keyvaultref:` bindings (not plaintext copies). Sessions persist under `IGNITE_DATA_DIR=/data` (Azure Files mount when configured).

## Components

- HTTP API: [`app/server/main.py`](../app/server/main.py) — FastAPI facade over `PyWebViewApi`
- Session store: [`app/server/session_store.py`](../app/server/session_store.py) — per-client API isolation
- Thin desktop proxy: [`app/main/remote_api_proxy.py`](../app/main/remote_api_proxy.py)
- Optional JS bridge: [`app/frontend/js/remoteBridge.js`](../app/frontend/js/remoteBridge.js)
- Container image: [`app/Dockerfile`](../app/Dockerfile) (no `pywebview` / `pythonnet`)
- IaC: [`infra/terraform/`](../infra/terraform/)
- CI lint/tests: [`.github/workflows/ci.yml`](../.github/workflows/ci.yml)
- CI deploy: [`.github/workflows/deploy-aca.yml`](../.github/workflows/deploy-aca.yml)

## Multi-user session isolation

Each thin desktop client sends a sticky `X-Ignite-Session-Id` (persisted locally under `~/.ignitechat_session_id`, overridable via `IGNITE_SESSION_ID`).

On ACA, `SessionApiStore` maps that id to an isolated `PyWebViewApi(tenant_key=...)` so history, groups, media, and generated files do not collide across clients. Disk paths go under `IGNITE_DATA_DIR/log/tenants/<session>/`.

| Env | Default | Purpose |
| --- | --- | --- |
| `IGNITE_SESSION_TTL_SECONDS` | `7200` | Idle eviction for in-memory API instances |
| `IGNITE_MAX_SESSIONS` | `50` | Cap concurrent isolated sessions per replica |

## Slim desktop package

For remote mode installs, use [`app/requirements-desktop.txt`](../app/requirements-desktop.txt) instead of the full `requirements.txt`.

Requirements on the user PC:

- Windows + WebView2
- Python x64 (or packaged PyInstaller build of the shell)
- Network access to the ACA FQDN

Whisper / SBERT / heavy ML stay in Azure.

## Local server smoke test

```bash
cd app
pip install -r requirements-server.txt
export IGNITE_API_KEY=dev-key
python -m uvicorn server.main:app --host 127.0.0.1 --port 8000
curl -H "X-API-Key: dev-key" http://127.0.0.1:8000/health
```

## Windows build/deploy via PowerShell + WSL Docker (same pattern as IgniteAPI)

Azure for Students blocks `az acr build`. Use Docker **inside WSL**, same shared stack as `ignite-api`:

| Piece | Value |
| --- | --- |
| Resource group (runtime host) | `IgniteAPI` (shared CAE/ACR on PAYG) |
| ACA Environment | `managedEnvironment-IgniteAPI-862f` |
| ACR | `igniteapisiuacr.azurecr.io` |
| Registry auth | ACR admin user + password secret |
| Resource group (consumption secrets) | `IgniteChat` |
| Key Vault | `kvignitechatsiu` |
| App name | `ignitechat-api` |
| Subscription (PAYG) | `4a614b14-fa98-4088-b2ec-dd6e3cc593bd` |

```powershell
cd C:\Users\julcu\IgniteChat-deploy   # clone outside OneDrive (recommended)
git pull origin cursor/cloud-agent-1786244185846-n7xvq

wsl -e docker version
az account set --subscription 4a614b14-fa98-4088-b2ec-dd6e3cc593bd

# IMPORTANT: build linux/amd64 (script already passes --platform linux/amd64 --provenance=false)
# Binds ACA secrets to kvignitechat (IgniteChat RG) via managed identity
pwsh -File .\scripts\Deploy-IgniteChatAca.ps1
```

Notes:
- Prefer a clone **outside OneDrive**. Building from `...\OneDrive\...` used to cancel with `context canceled` when `app/log` + media inflated the Docker context past 100MB+.
- The deploy script now stages a clean copy under WSL `/tmp/ignitechat-aca-build` (excludes `log/`, `Databases/`, `.venv`, tests) and `app/.dockerignore` keeps the context small.
- **`/data` must be a mounted Azure Files volume** (CAE storage `ignitechat-sessions` → share `ignite-sessions` on PAYG storage). Without the mount, `IGNITE_DATA_DIR=/data` is container-local and **every scale-to-zero wipes chats/groups/sessions**. `Deploy-IgniteChatAca.ps1` re-attaches it if missing; CI runs `scripts/ci/deploy-ignitechat-aca.sh` (image + env + KV refs; preserves volume).
- Keep billable/consumption secrets (KV, storage, optional IgniteChat ACR) in **`IgniteChat`**; only reuse IgniteAPI for the shared CAE/ACR host.
- Do **not** use the old `ignitechatbc08d0` ACR for ACA pulls if it produces attestation indexes without `linux/amd64`.
- On every update the script refreshes `az containerapp registry set` (avoids `ImagePullUnauthorized`) and ensures **Key Vault Secrets User** for the app MI.
- Omit `-ApiKey` on later deploys to keep `IGNITE-API-KEY` in `kvignitechat`; only pass it when you want to rotate.
- Save the printed `IGNITE_API_KEY` into the desktop `.env` when you set/rotate it.

## Branch strategy

- `main` + tag `v-desktop-baseline` — stable local desktop before hybrid
- `Develop` / feature branches — hybrid ACA work
- Compare with `git diff v-desktop-baseline...HEAD` or a PR into `main`

## Auto-deploy on merge to `main` (IgniteAPI-style)

Workflow: [`.github/workflows/deploy-aca.yml`](../.github/workflows/deploy-aca.yml)

**One workflow** on every push/merge to `main` (`deploy-aca` job):

1. Build & push `./app/Dockerfile` to ACR (`linux/amd64`, `provenance: false`, tags `sha` + `latest`).  
2. Azure login + `scripts/ci/deploy-ignitechat-aca.sh` (KV `keyvaultref`, Foundry + extraction URL).

**PRs** (`Develop` → `main`): only two checks — `ci.yml` (Ruff & Pytest) and `build-windows-installer.yml`. ACR build on Develop push is disabled (manual `workflow_dispatch` only) so it does not appear as a third/fourth PR check.

Repository secrets for `Razor2296/IgniteChat` and `Razor2296/IgniteAPI` (PAYG):

| GitHub secret | Purpose |
| --- | --- |
| `ACR_USERNAME` | `igniteapisiuacr` admin user |
| `ACR_PASSWORD` | `igniteapisiuacr` admin password |

**Azure login on merge (PAYG / SIU MFA):** default is **device code** (passkey OK). After the build step, open the **Azure login** job log, copy the code, visit https://microsoft.com/devicelogin, and approve within ~15 minutes.

Do **not** rely on `AZURE_USERNAME` / `AZURE_PASSWORD` in Actions — SIU MFA/passkey rejects ROPC and can lock the account.

Optional later: `AZURE_CREDENTIALS` (Service Principal JSON) for fully unattended deploy (requires Entra permission you may not have).

See also: [`scripts/github/README-GITHUB-CI-PAYG.md`](../scripts/github/README-GITHUB-CI-PAYG.md).

Tenant + subscription in workflow env: `19b73b1f-…` / `4a614b14-…`.

Manual WSL deploy: `scripts/Deploy-IgniteChatAca.ps1` (keep aligned with `scripts/ci/deploy-ignitechat-aca.sh`).

**IgniteAPI repo:** copy `scripts/github/IgniteAPI-deploy-aca-payg.yml` into `Razor2296/IgniteAPI` as `.github/workflows/deploy-aca-payg.yml` and point secrets to the same PAYG ACR.

### Natural bridge with IgniteAPI (next)

Both solutions already share:

- Subscription + CAE `managedEnvironment-IgniteAPI-862f`
- ACR `igniteapisiuacr`
- RG split: runtime in `IgniteAPI`, consumption secrets in product RG/KV

Future “natural connection” options (not implemented yet):

1. **Shared auth envelope** — same `X-API-Key` / Entra patterns between `ignite-api` and `ignitechat-api`
2. **Service-to-service calls** — IgniteChat tools calling IgniteAPI endpoints (or vice versa) inside the CAE
3. **Unified ingress / gateway** — one FQDN path prefix routing to both apps
4. **Shared observability** — same Log Analytics workspace + `/metrics` conventions

## Azure cost guardrails (first deploy)

Deploy into the existing resource group **`IgniteChat`** (`reuse_existing_rg=true`). Defaults are intentionally cheap:

| Setting | Default | Why |
| --- | --- | --- |
| `min_replicas` | `0` | Scale-to-zero when idle |
| `max_replicas` | `1` | Hard cap |
| CPU / memory | `1.0` / `2Gi` | Enough to smoke-test; raise later for Whisper |
| File share | `5 GB` | Sessions JSON only |
| Log retention | `7 days` | Lower Log Analytics cost |

Do **not** create AKS, Azure SQL, or always-on replicas unless explicitly requested.
