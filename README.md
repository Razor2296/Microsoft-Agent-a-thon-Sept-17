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

Install on Windows, talk or type, drop a PDF, get a card + overlay, ask in Spanish or English. No “paste this curl.” The agent asks less; it **does** extract → remember → answer → export.

### Impact — quantitative and qualitative

Qualitative: one thread instead of Acrobat + email + ChatGPT + Excel.  
Quantitative (honest): extraction timeouts, token/cost telemetry per turn, and job polling instead of a frozen UI — we measure latency and tokens (`app/backend/core/telemetry.py`), we do not invent ROI slides.

---

## Level 3 technical capabilities

What the live Q&A asked to make **visible**:

| Capability | How Ignite shows it | Honest limit |
| --- | --- | --- |
| **1. Agent design** | Chat = orchestrator (tools, language, session). API = specialist extractors. Guardrails (PII + prompt injection) before the model. Sticky conversation language. | Not Copilot Studio; custom Python agents on Foundry models. |
| **2. Observability** | Per-turn latency, tokens, errors; ACA logs; Key Vault via managed identity. | Foundry **tracing UI** is not the product’s primary dashboard — we show Chat telemetry + Azure logs in the demo. |
| **3. Quality evaluations** | Unit suite (welcome/session/STT, extraction client, PDF long-doc, tenant isolation). Extraction `mode=auto` + user-safe failure chrome. | We do **not** claim a Foundry Evaluation hub score yet. Week of 17–24 Sep can add a Foundry eval run on a golden set of docs if we want the extra checkbox. |
| **4. Multi-agent orchestration** | Chat decides when to call Ignite API vs local RAG vs web vs Office generator. API internally routes doc/image/audio/video processors. | Two production agents + tools — not a Foundry Agent Service graph exported from the lab. |

Lab scenarios from [FrontierWeekHack](https://github.com/microsoft/FrontierWeekHack) taught the Foundry skills; this submission **applies them to our enterprise-shaped workflow**, which is what the hosts asked.

---

## Demo (≈ 4 minutes, Founderz video)

1. **Problem** — a real PDF (prescription / invoice), not a toy prompt.  
2. **Usability** — Ignite Chat: attach → extract (API on ACA) → ask → export Office.  
3. **Foundry** — portal: resource `foundryignitechatsiu`, deployment in use, plus `ignite-api` on Azure Container Apps.  
4. **Multi-agent** — say out loud: Chat orchestrates, API extracts, Foundry serves the model.  
5. **Observability** — one turn’s token/latency line or ACA log.  
6. Stop. No Autopilot roadmap.

---

## Azure / Foundry (this contest)

- Foundry project for **Ignite Chat** models: `foundryignitechatsiu` (East US).  
- Foundry / Azure OpenAI for **Ignite API**: `igniteapifoundry2296` (East US 2) — different resource, same subscription.  
- Runtime: Azure Container Apps, Key Vault, optional Azure Files for session data.  
- Student / Foundry access: [Azure for Students](https://azure.microsoft.com/en-us/free/students) · [AI Foundry](https://azure.microsoft.com/en-us/products/ai-foundry/) · [ai.azure.com/nextgen](https://ai.azure.com/nextgen)

---

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
- Not a claim that we already filled every Foundry Evaluation / tracing checkbox — we show the production loop we run, and we label gaps.
