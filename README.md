# Ignite — Microsoft Agent-a-thon (Level 3 Architect)

**Production-shaped agents on Microsoft Foundry** for a real workflow: messy documents and conversations that still need an answer, a file, and a memory.

This repository is the **Level 3 Architect** submission snapshot of **Ignite Chat** (desktop agent). It works with **[Ignite API](https://github.com/Razor2296/IgniteAPI)** (extraction agent on Azure Container Apps). We did not duplicate that API here — it is already public.

| Contest | Value |
| --- | --- |
| Program | [Microsoft Agent-a-thon — Level 3 Architect](https://aka.ms/FounderzRegister): *Build production-grade agents on Microsoft Foundry* |
| Problem statement | *Make it your own.* We built the agent around a problem we already have: unstructured PDFs, prescriptions, invoices, and long chats that should not be re-typed. |
| Submit | Last lesson on Founderz (*Final Activity*) — [aka.ms/FounderzLearn](https://aka.ms/FounderzLearn) |
| Deadline | **24 September 2026, 23:59 PDT** |
| Rules | [aka.ms/AgentathonRules](https://aka.ms/AgentathonRules) |
| Foundry | [ai.azure.com](https://ai.azure.com/) · [ai.azure.com/nextgen](https://ai.azure.com/nextgen) |
| Lab (learn, then apply) | [microsoft/FrontierWeekHack](https://github.com/microsoft/FrontierWeekHack) |

This is **not** a Google Devpost write-up. Judges here score a Foundry-era agent: **Innovation**, **Usability**, **Impact**, plus Level 3 architecture: **agent design**, **observability**, **quality evaluations**, **multi-agent orchestration**.

---

## The problem we own

Knowledge work still dies in attachments. A medical PDF, a bank statement, a meeting recording — the user pastes, waits, and then the next chat forgets everything.

Ignite is the agent we actually use: a WhatsApp-style desktop that **takes the file**, **extracts structure**, **remembers**, and **writes back** (Word / Excel / PowerPoint) instead of only chatting.

---

## What we submit (two agents, one loop)

```text
User (Windows desktop)
        │
        ▼
┌───────────────────────┐     orchestrates      ┌──────────────────────────┐
│  Ignite Chat (this    │ ───────────────────►  │  Ignite API (public)     │
│  repo)                │   extract / jobs      │  docs · images · audio   │
│  Agent: conversation, │                       │  Agent: multimodal ETL   │
│  memory, Office, voice│                       │  Azure Container Apps    │
└──────────┬────────────┘                       └────────────┬─────────────┘
           │                                                 │
           └──────────── Microsoft Foundry ──────────────────┘
                    Azure OpenAI models · Key Vault
```

| Piece | Role in Level 3 | Where |
| --- | --- | --- |
| **Ignite Chat** | Conversation agent, tool routing, RAG memory, voice, Office export, PII/injection guards | this repository (`app/`) |
| **Ignite API** | Specialist extraction agent (`/extract`, `/doc`, `/image`, `/audio`, `/video`, `/jobs`) | [Razor2296/IgniteAPI](https://github.com/Razor2296/IgniteAPI) |
| **Microsoft Foundry** | Model hosting for OpenAI-compatible chat (`gpt-4.1-mini` on `foundryignitechatsiu`) | [ai.azure.com](https://ai.azure.com/) |

Chat calls API with `mode=auto` (sync vs async by file size). Results land in RAG so a later question does not require the PDF again.

---

## Judging map

### Innovation — how original is the agent?

Not a chatbot skin on a single prompt. A **desktop agent** with a finite-state voice loop, WhatsApp file cards, and a **second agent** that only extracts. Foundry is the model plane for OpenAI; Azure Container Apps + Key Vault are the runtime plane. Original use case (our documents), not a copy of the FrontierWeekHack lab.

### Usability — how usable is the agent?

Install on Windows, talk or type, drop a PDF, get a card + overlay, ask in Spanish or English. No “paste this curl.” The agent asks less; it **does** extract → remember → answer → export. Every LLM provider molds to the same app prompting contract (sticky conversation language + multimodal captions — see [docs/IGNITE_CHAT.md](docs/IGNITE_CHAT.md) § Shared provider prompting contract).

### Impact — quantitative and qualitative

Qualitative: one thread instead of Acrobat + email + ChatGPT + Excel.  
Quantitative (honest): extraction timeouts, token/cost telemetry per turn, and job polling instead of a frozen UI — we measure latency and tokens (`app/backend/core/telemetry.py`), we do not invent ROI slides.

---

## Level 3 technical capabilities

Runnable slice (Foundry project **`juliancuray-7914`**, not the classic OpenAI resource): [`foundry/`](foundry/). Same four challenges as [FrontierWeekHack](https://github.com/microsoft/FrontierWeekHack), Ignite documents instead of the claims lab.

| Capability | In Foundry | Script |
| --- | --- | --- |
| **1. Agent design** | Orchestrator (**Plan JSON brain**) + document + media agents | `foundry/agents.py` |
| **2. Observability** | Tracing + `trace_tags` (`modality:*`, `intent:*`) | `foundry/monitor.py`, `brain.py` |
| **3. Quality evaluations** | Evaluations hub + `foundry/eval/eval_portal.jsonl` | `foundry/evaluate.py` |
| **4. Multi-agent orchestration** | `brain.py` (Plan → tools → reply) + `ignite-document-workflow` | `foundry/workflow.py` |

**Foundry is the brain:** the orchestrator’s Plan JSON decides modality and steps; specialists only execute. Offline demo: `cd foundry && python brain.py`. Paso 3 document: [docs/PASO3_WORKFLOW.md](docs/PASO3_WORKFLOW.md).

This contest repo does **not** change Ignite Chat or Ignite API source — they remain the product reference.

Lab scenarios from [FrontierWeekHack](https://github.com/microsoft/FrontierWeekHack) taught the Foundry skills; this submission **applies them to our enterprise-shaped workflow**.

---

## Demo (≤ 3 minutes, Founderz Paso 3 video)

1. **Problem** — messy PDF / photo / voice note → need a business answer.  
2. **Brain** — show Plan JSON (`python brain.py` or Foundry orchestrator).  
3. **Workflow + Tracing + Evals** on `juliancuray-7914`.  
4. Stop. No Autopilot. No live PHI.

---

## Azure / Foundry (this contest)

| Resource | Role |
| --- | --- |
| **`juliancuray-7914`** | Foundry **project** for Agent Service (agents, tracing, evals, workflow) — contest plane |
| **`foundryignitechatsiu`** | Azure OpenAI / Foundry for **Ignite Chat** chat models (e.g. `gpt-4.1-mini`) |
| **`igniteapifoundry2296`** | Foundry / OpenAI for **Ignite API** extraction |
| ACA + Key Vault | Runtime for Chat API and Ignite API |

Student / Foundry access: [Azure for Students](https://azure.microsoft.com/en-us/free/students) · [AI Foundry](https://azure.microsoft.com/en-us/products/ai-foundry/) · [ai.azure.com/nextgen](https://ai.azure.com/nextgen)

CI on this repo: [.github/CONTEST-CI.md](.github/CONTEST-CI.md) — pytest + Foundry offline tests. ACA deploy on **push to `main`** builds this repo’s image, pushes ACR, then updates the container (device-code Azure login, same as IgniteChat).

## Run locally (Chat)

```bat
run_app.bat
```

Copy `app/.env.example` → `app/.env` (never commit `.env`). Point OpenAI chat at Foundry:

- `AZURE_OPENAI_ENDPOINT` / `OPENAI_BASE_URL` = your Foundry v1 endpoint  
- `OPENAI_MODEL_VERSION` = a **deployment that exists in that project**

Full product notes: [docs/IGNITE_CHAT.md](docs/IGNITE_CHAT.md). Hybrid ACA: [docs/HYBRID_ACA.md](docs/HYBRID_ACA.md). Submission checklist: [docs/SUBMISSION.md](docs/SUBMISSION.md).

---

## What this repo is not

- Not the Devpost / Google Cloud story.  
- Not Autopilot (not in this build).  
- Not a dump of Ignite API source (use [IgniteAPI](https://github.com/Razor2296/IgniteAPI)).  
- Not a CI that deploys your PAYG Container Apps (removed on purpose — no ACR secrets on a public contest repo).
