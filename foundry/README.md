# Foundry Level 3 slice (Ignite)

**Foundry is the orchestration brain.** The orchestrator emits a **Plan JSON** (modality + intent + steps); document/media specialists execute tools; Traces tag `modality:*` / `intent:*`. This is the contest plane only — **Ignite Chat and Ignite API product repos are not modified here.**

Pattern follows [FrontierWeekHack](https://github.com/microsoft/FrontierWeekHack) (challenges 1–4) with **our** documents/media, not the claims lab.

## Mental model

```text
User turn → ignite-orchestrator-agent (Plan JSON)
                ↓
     inspect_document / describe_media
                ↓
         business reply + trace_tags
```

Offline (CI / no Azure): `python brain.py` uses `heuristic_plan` + `execute_plan`.  
Live: set `FOUNDRY_BRAIN_LIVE=true` and `PROJECT_CONNECTION_STRING` so the Plan comes from Foundry.

Paso 3 write-up: [docs/PASO3_WORKFLOW.md](../docs/PASO3_WORKFLOW.md).

## Where to run it

Agent Service needs a **Foundry project** ([ai.azure.com/nextgen](https://ai.azure.com/nextgen)), not the classic Azure OpenAI resource `foundryignitechatsiu`.

Use the project **`juliancuray-7914`** (`gpt-5-mini`).

1. Portal → project → copy **Project endpoint** into `foundry/.env` as `PROJECT_CONNECTION_STRING` (must include `/api/projects/<name>`).
2. `MODEL_DEPLOYMENT_NAME=gpt-5-mini`.
3. Tracing: project → **Tracing** → Application Insights connection string.

```powershell
az login
cd foundry
copy .env.example .env
python -m pip install -r requirements.txt
python test_tools.py
python test_brain.py
python brain.py
python agents.py          # creates orchestrator + document + media
python monitor.py
python evaluate.py
python workflow.py        # Part A offline always; B/C need .env
```

| Capability | Where |
| --- | --- |
| Agent design | `ignite-orchestrator-agent`, `ignite-document-agent`, `ignite-media-agent` |
| Observability | Tracing + `trace_tags` on every Plan |
| Quality evaluations | Evaluations hub / `evaluate.py` |
| Multi-agent | `brain.py` + `ignite-document-workflow` |

Do not enable Tool Call Accuracy on portal evals. Keep Coherence / Fluency.

## Alignment (reference only)

| Product (unchanged) | This contest slice |
| --- | --- |
| Chat routes EXTRACT / ANSWER / EXPORT | Plan JSON `intent` |
| Multimodal attachments | `modality` + `describe_media` |
| API `mode=auto` | optional `FOUNDRY_USE_IGNITE_API` on `inspect_document` |

Synthetic data only in `data/documents.json` + `data/modalities.json` (no real PHI).

## Ignite app → Foundry Traces + workflow

In this contest snapshot, `app/backend/integrations/foundry_orchestration.py` hooks
`api.py` so a user turn can:

1. Enable GenAI tracing (App Insights / Foundry Tracing).
2. Prefer `FOUNDRY_WORKFLOW_LIVE` → invoke `ignite-document-workflow`.
3. Else run `brain.run_turn` (Plan JSON → tools) offline or with `FOUNDRY_BRAIN_LIVE`.

Enable in `app/.env` (and seed agents once):

```env
FOUNDRY_ORCHESTRATION_ENABLED=true
AZURE_EXPERIMENTAL_ENABLE_GENAI_TRACING=true
PROJECT_CONNECTION_STRING=https://....services.ai.azure.com/api/projects/juliancuray-7914
APPLICATIONINSIGHTS_CONNECTION_STRING=...
# Optional live portal graph:
# FOUNDRY_WORKFLOW_LIVE=true
# FOUNDRY_BRAIN_LIVE=true
```

Then: `python agents.py` → `python workflow.py` once, start Ignite via `run_app.bat`,
send `Extrae DOC-001`, and open Foundry → **Tracing**.
