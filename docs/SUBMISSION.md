# Founderz submission checklist — Level 3 Architect

Upload in the **last lesson** of Founderz (*Final Activity*), not to this GitHub as the official drop.  
Deadline: **24 September 2026, 23:59 PDT**.  
Rules: https://aka.ms/AgentathonRules

## Required story (from live Q&A + Paso 3)

- **Problem:** our own (unstructured documents + multimodal chat that must act).  
- **Build:** production-grade agents on **Microsoft Foundry** — **orchestrator Plan JSON is the brain**.  
- **Visible capabilities:** (1) agent design (2) observability / Traces (3) quality evaluations (4) multi-agent orchestration.  
- **Paso 3 deliverables:** PDF/Word ([docs/PASO3_WORKFLOW.md](PASO3_WORKFLOW.md)) + video ≤ 3 min.  
- **Judging reminder:** Innovation · Usability · Impact.  

## Package

| Item | Where |
| --- | --- |
| Contest code (Foundry slice + snapshot) | this GitHub repo |
| Paso 3 document | [docs/PASO3_WORKFLOW.md](PASO3_WORKFLOW.md) → export PDF/Word |
| Extraction reference | https://github.com/Razor2296/IgniteAPI (not edited for this submission) |
| Architecture | README + `docs/architecture.drawio` + PASO3 diagrams |
| Demo video ≤ 3 min | problem → Plan JSON / Workflow → Tracing → Evals |
| Founderz form | category, description, repo URL, diagram, video |

## Foundry brain (Architect checkboxes)

On project **`juliancuray-7914`** — deployment **`gemini-2.5-flash`** (Gemini first):

```powershell
cd foundry
copy .env.example .env
python test_brain.py
python brain.py       # offline Plan → tools → reply
python agents.py      # orchestrator + document + media
python monitor.py
python evaluate.py
python workflow.py    # portal workflow graph
```

## Demo script (speak this)

1. “Ignite Chat turn arms Foundry GenAI Tracing, auto-creates agents/workflow, and orchestrates under those traces.”  
2. `FOUNDRY_ORCHESTRATION_ENABLED=true` + project endpoint → `run_app.bat` → `Extrae DOC-001`.  
3. Show chat bubble (Plan footer) + Foundry Tracing / Agents / Workflow — no manual `agents.py`.  
4. Optional: same path after Chat → Ignite API extract.  
5. Stop. No Autopilot. No PHI.

## Do not

- Paste the Google Devpost text.  
- Promise Autopilot.  
- Show only classic OpenAI deployments and call that “Agent Service.”  
- Commit real PHI or production secrets.
