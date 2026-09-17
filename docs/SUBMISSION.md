# Founderz submission checklist — Level 3 Architect

Upload in the **last lesson** of Founderz (*Final Activity*), not to this GitHub as the official drop.  
Deadline: **24 September 2026, 23:59 PDT**.  
Rules: https://aka.ms/AgentathonRules

## Required story (from live Q&A)

- **Problem:** our own (unstructured documents + chat that must act).  
- **Build:** production-grade agents on **Microsoft Foundry**.  
- **Visible capabilities:** (1) agent design (2) observability (3) quality evaluations (4) multi-agent orchestration.  
- **Judging reminder slide:** Innovation · Usability · Impact.  
- **Lab:** [FrontierWeekHack](https://github.com/microsoft/FrontierWeekHack) is for learning; the submission is **our** scenario.

## Package

| Item | Where |
| --- | --- |
| This code (Ignite Chat + Foundry slice) | this GitHub repo |
| Extraction agent | https://github.com/Razor2296/IgniteAPI |
| Architecture | README diagram + `docs/architecture.drawio` + API drawio in IgniteAPI |
| Demo video ~4 min | problem → Chat → Foundry Agents/Tracing/Evals → optional ACA |
| Founderz form | category, description, repo URL, diagram, video |

## Foundry slice (Architect checkboxes)

On project **`juliancuray-7914`** ([ai.azure.com/nextgen](https://ai.azure.com/nextgen)) — use deployment **`gpt-5-mini`**:

```powershell
cd foundry
copy .env.example .env
# PROJECT_CONNECTION_STRING = project endpoint from Foundry Overview
python agents.py      # Agents tab
python monitor.py     # Tracing tab (App Insights linked)
python evaluate.py    # Evaluations tab (or upload eval/eval_portal.jsonl)
python workflow.py    # workflow agent graph
```

Details: [foundry/README.md](../foundry/README.md). CI already runs `python test_tools.py` offline.

## Demo script (speak this)

1. “Level 3 Architect. Ignite Chat + Ignite API on Azure; Foundry Agent Service for design, tracing, evals, and multi-agent workflow.”  
2. Desktop: drop a real PDF → extract → answer (Innovation / Usability).  
3. Foundry **`juliancuray-7914`**: Agents (`ignite-document-agent`, `ignite-orchestrator-agent`, workflow) → Tracing → Evaluations.  
4. Optional: Chat models on `foundryignitechatsiu` + ACA `ignite-api` (product runtime).  
5. Stop. No Autopilot roadmap.

## Do not

- Paste the Google Devpost text.  
- Promise Autopilot.  
- Show only classic OpenAI deployments and call that “Agent Service.” Judges want Agents / Tracing / Evaluations.
