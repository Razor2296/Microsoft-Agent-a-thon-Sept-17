# Foundry Level 3 slice (Ignite) — GOD path

**Ignite Chat turn → GenAI Traces → auto-ensure agents/workflow (Gemini) → invoke workflow.**

You do **not** need to run `agents.py` / `workflow.py` by hand for the demo.
Those scripts stay as optional seed/debug. The live path is:

```text
Ignite Chat (app/)
   │  FOUNDRY_ORCHESTRATION_ENABLED=true
   │  MODEL_DEPLOYMENT_NAME=gemini-2.5-flash
   ▼
foundry_orchestration.py
   │  1) runtime.setup_tracing()                 ← Traces ON first
   │  2) runtime.ensure_agents_and_workflow()    ← Gemini agents + workflow
   │  3) runtime.invoke_workflow()               ← primary under Traces
   │  4) agent pipeline fallback if workflow empty
   │  5) brain Plan JSON (footer / offline)
   ▼
Foundry portal → Tracing + Agents + Workflow
```

Also after **Chat → Ignite API extract** (`notify_foundry_after_extract`).

## Enable

`app/.env` (+ `foundry/.env` for project strings):

```env
FOUNDRY_ORCHESTRATION_ENABLED=true
AZURE_EXPERIMENTAL_ENABLE_GENAI_TRACING=true
PROJECT_CONNECTION_STRING=https://....services.ai.azure.com/api/projects/juliancuray-7914
APPLICATIONINSIGHTS_CONNECTION_STRING=InstrumentationKey=...
MODEL_DEPLOYMENT_NAME=gemini-2.5-flash
FOUNDRY_REFRESH_AGENTS=true
```

Deploy **Gemini** in Foundry → Models + endpoints (name must match `MODEL_DEPLOYMENT_NAME`).

```powershell
az login
cd foundry
python -m pip install -r requirements.txt
# optional one-time seed (also auto-runs from Chat):
# python agents.py
# python workflow.py
cd ..
.\run_app.bat
```

In chat: `Extrae DOC-001` → open Foundry → **ignite-document-workflow** / **ignite-image-agent** / **ignite-document-agent** → **Traces**.

If Chat shows `⚠ NO LLEGÓ A FOUNDRY`, fix `.env` / `az login` — offline Plan alone never updates Traces.

Look for console lines starting with `FOUNDRY ` — if you never see them, you are not running the Agent-a-thon snapshot (or `.env` has no project endpoint).

## Offline / CI

Without `PROJECT_CONNECTION_STRING`, Chat still gets Plan JSON orchestration via `brain.py` (no live Traces) and the bubble shows a loud error banner.

```powershell
cd foundry
python test_brain.py
python test_tools.py
cd ..
python -m unittest app.tests.unit.integrations.test_foundry_orchestration
```

## Files

| File | Role |
| --- | --- |
| `foundry/runtime.py` | Traces → ensure → **workflow** (Gemini) |
| `foundry/brain.py` | Plan JSON + local tool execution |
| `app/backend/integrations/foundry_orchestration.py` | Chat / extract hooks |
| `app/main/api.py` | Calls hooks on turn + after extract |

Synthetic data only (`data/documents.json`, `data/modalities.json`) — no real PHI.
