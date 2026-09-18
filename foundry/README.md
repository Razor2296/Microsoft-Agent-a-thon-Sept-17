# Foundry Level 3 slice (Ignite) — GOD path

**Ignite Chat turn → GenAI Traces → auto-ensure agents/workflow → orchestrate.**

You do **not** need to run `agents.py` / `workflow.py` by hand for the demo.
Those scripts stay as optional seed/debug. The live path is:

```text
Ignite Chat (app/)
   │  FOUNDRY_ORCHESTRATION_ENABLED=true
   ▼
foundry_orchestration.py
   │  1) runtime.setup_tracing()
   │  2) runtime.ensure_agents_and_workflow()   ← same as agents.py + workflow.py
   │  3) runtime.invoke_workflow()              ← orchestration under Traces
   │  4) brain Plan JSON (footer / offline)
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
MODEL_DEPLOYMENT_NAME=gpt-5-mini
```

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

In chat: `Extrae DOC-001` → open Foundry → **Tracing**.

## Offline / CI

Without `PROJECT_CONNECTION_STRING`, Chat still gets Plan JSON orchestration via `brain.py` (no live Traces).

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
| `foundry/runtime.py` | Traces + ensure agents/workflow + invoke |
| `foundry/brain.py` | Plan JSON + local tool execution |
| `app/backend/integrations/foundry_orchestration.py` | Chat / extract hooks |
| `app/main/api.py` | Calls hooks on turn + after extract |

Synthetic data only (`data/documents.json`, `data/modalities.json`) — no real PHI.
