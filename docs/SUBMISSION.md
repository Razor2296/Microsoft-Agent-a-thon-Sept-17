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

On project **`juliancuray-7914`** — deployment **`gpt-5-mini`**:

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

1. “Level 3 Architect. Foundry orchestrator emits Plan JSON; specialists extract documents or describe media; Traces tag modality.”  
2. Show `python brain.py` or portal Agents: EXTRACT DOC-001 + MEDIA MED-IMG-001.  
3. Foundry **`juliancuray-7914`**: Workflow graph → Tracing (`modality:*`) → Evaluations.  
4. Mention Ignite Chat/API only as the product this architecture mirrors — **this repo does not change them**.  
5. Stop. No Autopilot roadmap.

## Do not

- Paste the Google Devpost text.  
- Promise Autopilot.  
- Show only classic OpenAI deployments and call that “Agent Service.”  
- Commit real PHI or production secrets.
