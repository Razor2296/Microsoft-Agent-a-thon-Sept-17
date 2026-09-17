# Foundry Level 3 slice (Ignite)

Closes the Architect gaps **inside Microsoft Foundry**: agent design, tracing, evaluations, multi-agent workflow. This is the contest plane. **Ignite Chat product code is not modified here** — Chat and Ignite API stay as the live product; this folder mirrors their extract contract for judges.

Pattern follows [FrontierWeekHack](https://github.com/microsoft/FrontierWeekHack) (challenges 1–4) with **our** documents, not the claims lab.

## Where to run it

Agent Service needs a **Foundry project** ([ai.azure.com/nextgen](https://ai.azure.com/nextgen)), not the classic Azure OpenAI resource `foundryignitechatsiu`.

Use the project **`juliancuray-7914`** (you already deployed `gpt-5-mini` there). Chat’s `gpt-4.1-mini` on `foundryignitechatsiu` is a different resource.

1. Portal → project → copy **Project endpoint** into `foundry/.env` as `PROJECT_CONNECTION_STRING` (must include `/api/projects/<name>`).
2. `MODEL_DEPLOYMENT_NAME=gpt-5-mini` (must exist under Models + endpoints).
3. Tracing: project → **Tracing** → connect Application Insights → paste connection string.

```powershell
az login
cd foundry
copy .env.example .env
# edit .env
python -m pip install -r requirements.txt
python test_tools.py
python agents.py
python monitor.py
python evaluate.py
python workflow.py
```

Then in Foundry you should see:

| Capability | Where |
| --- | --- |
| Agent design | Build → Agents → `ignite-document-agent`, `ignite-orchestrator-agent` |
| Observability | Tracing + App Insights (after `monitor.py`) |
| Quality evaluations | Build → Evaluations (after `evaluate.py` or upload `eval/eval_portal.jsonl`) |
| Multi-agent | `ignite-document-workflow` (kind: workflow) after `workflow.py` |

Do not enable Tool Call Accuracy on portal evals (local `inspect_document` is not executed in the cloud judge). Keep Coherence / Fluency.

## Alignment with Ignite Chat + Ignite API

| Chat / API (product) | This slice (contest) |
| --- | --- |
| Chat orchestrates EXTRACT / ANSWER / EXPORT | `ignite-orchestrator-agent` |
| `POST /api/v1/extract?mode=auto` | `inspect_document` → same endpoint when `FOUNDRY_USE_IGNITE_API=true` |
| Attachment bytes | `data/fixtures/DOC-00*.txt` (synthetic, no real PHI) |
| Offline / CI | `FOUNDRY_USE_IGNITE_API=false` → `data/documents.json` catalog |

Seed scripts (`agents.py`, `monitor.py`, …) are **one-time** portal setup. Daily product use stays Ignite Chat — no need to run these from the desktop app.
