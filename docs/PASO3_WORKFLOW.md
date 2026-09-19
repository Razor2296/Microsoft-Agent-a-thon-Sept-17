# Paso 3 — Flujo de trabajo de principio a fin (Level 3 Architect)

**Solución:** Ignite multi-agent on Microsoft Foundry  
**Repo de entrega:** [Razor2296/Microsoft-Agent-a-thon-Sept-17](https://github.com/Razor2296/Microsoft-Agent-a-thon-Sept-17)  
**Producto de referencia (no modificado en esta entrega):** Ignite Chat + Ignite API  
**Foundry project:** `juliancuray-7914` · modelo `gemini-2.5-flash` (Gemini primero)  
**Fecha objetivo:** 24 September 2026, 23:59 PDT  

Este documento cumple la rúbrica Founderz *Paso 3: Diseña el flujo de trabajo de principio a fin*.  
Datos de demo = catálogos sintéticos (`foundry/data/documents.json`, `foundry/data/modalities.json`) — **sin PHI real**.

---

## 1. Problema empresarial

El conocimiento operativo llega como PDF, foto de factura, nota de voz o captura de pantalla. El usuario necesita **extraer → entender → responder / exportar**, no un chatbot genérico.  

Ignite ya resuelve eso en producto (Chat orquesta, API extrae). En Foundry modelamos el **mismo contrato** como agentes de producción visibles para Architect: diseño, Traces, evaluaciones y workflow.

---

## 2. Arquitectura de agentes

| Agente | Rol | Herramientas | Entrada | Salida |
| --- | --- | --- | --- | --- |
| **ignite-orchestrator-agent** | **Cerebro** — emite Plan JSON (modalidad + intent + pasos) | ninguna (solo planifica) | turno de usuario | Plan JSON + reply final |
| **ignite-document-agent** | Especialista documentos | `inspect_document` | `doc_id` (DOC-001…) | campos estructurados |
| **ignite-image-agent** | Especialista imagen (Ignite API channel=image) | `describe_media` | `MED-IMG-*` | caption + tags |
| **ignite-audio-agent** | Especialista audio (channel=audio) | `describe_media` | `MED-AUD-*` | caption + tags |
| **ignite-video-agent** | Especialista video (channel=video) | `describe_media` | `MED-VID-*` | caption + tags |
| **ignite-document-workflow** | Grafo Foundry (kind: workflow) | orquesta los cinco | conversación | reply de negocio |

```text
Usuario
   │
   ▼
┌────────────────────────────┐
│ ignite-orchestrator-agent  │  ← Plan JSON = fuente de verdad
│ modality + intent + steps  │
└────────────┬───────────────┘
             │ steps[]
     ┌───────┴────────┐
     ▼                ▼
 document-agent   media-agent
 inspect_*        describe_*
     │                │
     └───────┬────────┘
             ▼
   orchestrator synthesize
             │
             ▼
   Resultado al usuario / proceso
   (+ trace_tags → Foundry Tracing)
```

Código: [`foundry/agents.py`](../foundry/agents.py), [`foundry/brain.py`](../foundry/brain.py), [`foundry/plan_schema.py`](../foundry/plan_schema.py).

---

## 3. Secuencia de interacciones (requisito 1)

1. **Trigger** — usuario en Ignite Chat (o Chat → Ignite API extract) con PDF / DOC-* / MED-* / “extrae…”.  
2. **Traces ON** — `runtime.setup_tracing()` (GenAI → Foundry Tracing / App Insights) **antes** de cualquier agente.  
3. **Auto-ensure** — `runtime.ensure_agents_and_workflow()` publica agentes + workflow con **Gemini** (`MODEL_DEPLOYMENT_NAME=gemini-2.5-flash`).  
4. **Orchestrate** — `runtime.invoke_workflow()` bajo esos Traces (plan → document → media → synthesize). Si el workflow vuelve vacío, pipeline por agente como fallback.  
5. **Plan mirror** — `brain.run_turn` aporta Plan JSON + reply estructurado a la burbuja.  
6. **End** — usuario ve resultado; judges ven Tracing + Agents + Workflow. Si no llega a Foundry, la burbuja muestra `⚠ NO LLEGÓ A FOUNDRY`.

No hace falta ejecutar `agents.py` / `workflow.py` a mano para la demo.

```powershell
# app/.env
FOUNDRY_ORCHESTRATION_ENABLED=true
PROJECT_CONNECTION_STRING=...
APPLICATIONINSIGHTS_CONNECTION_STRING=...
AZURE_EXPERIMENTAL_ENABLE_GENAI_TRACING=true
MODEL_DEPLOYMENT_NAME=gemini-2.5-flash
FOUNDRY_REFRESH_AGENTS=true

run_app.bat
# Chat: Extrae DOC-001  →  Foundry → ignite-document-workflow / ignite-image-agent Traces
# Console must show lines starting with "FOUNDRY " — if not, wrong repo or missing .env
```

---

## 4. Información transmitida entre agentes (requisito 2)

| De → A | Payload |
| --- | --- |
| Usuario → Orchestrator | Texto libre + ids (`DOC-001`, `MED-IMG-001`, …) |
| Orchestrator → Document | Plan step `{action: inspect_document, args: {doc_id}}` |
| Document → Orchestrator | JSON campos (`diagnosis`, `amount_usd`, …) + `source` |
| Orchestrator → Media | Plan step `{action: describe_media, args: {media_id}}` |
| Media → Orchestrator | `modality`, `caption`, `suggested_doc_id` |
| Orchestrator → Usuario | `final_user_message` (es/en) |

Esquema obligatorio del cerebro: ver `PLAN_JSON_SCHEMA_HINT` en `plan_schema.py`.

---

## 5. Herramientas y conocimiento (requisito 3)

| Tool | Conocimiento | Notas |
| --- | --- | --- |
| `inspect_document` | Catálogo `documents.json` o (opcional) Ignite API `POST /extract?mode=auto` vía fixtures | CI fuerza catálogo offline |
| `describe_media` | Catálogo `modalities.json` | imagen / audio / video sintéticos |

No se exponen secretos ni documentos reales en el vídeo ni en este PDF.

---

## 6. Resultado final de negocio (requisito 4)

Ejemplos que produce `brain.run_turn`:

| Pedido | Intent | Resultado |
| --- | --- | --- |
| “Extrae DOC-001” | EXTRACT | Resumen de orden ambulatoria (diagnóstico + medicación sample) |
| “Describe MED-IMG-001” | MEDIA_DESCRIBE | Caption de recibo + sugerencia DOC-002 |
| “Exporta DOC-002 a Excel” | EXPORT | Plan de exportación (bytes los genera el producto Chat; Foundry planifica) |
| “Hola” | CLARIFY | Lista de ids conocidos |

---

## 7. Despliegue, supervisión, evaluación y mejora (requisito 5)

### Despliegue

1. Foundry project `juliancuray-7914` + deployment `gemini-2.5-flash` (Gemini).  
2. `foundry/.env` ← Project endpoint + App Insights.  
3. `python agents.py` → crea/actualiza agentes.  
4. `python workflow.py` → publica grafo `ignite-document-workflow`.  
5. Runtime de producto (referencia): Chat + ACA Ignite API en suscripción PAYG — **fuera de este repo de entrega**.

### Supervisión (observability)

- `python monitor.py` → GenAI tracing a Application Insights.  
- Cada Plan lleva `trace_tags` (`modality:document`, `intent:EXTRACT`, …) para filtrar spans por canal (texto/doc/imagen/audio/video).  
- Portal: Foundry → **Tracing**.

### Evaluación

- `python evaluate.py` + `eval/eval_portal.jsonl` (Coherence / Fluency).  
- No habilitar Tool Call Accuracy en el juez cloud (tools locales).  
- Offline: `python test_tools.py` + `python test_brain.py`.

### Mejora continua

| Señal | Acción |
| --- | --- |
| Plans JSON inválidos | Ajustar instructions del orchestrator; heuristic_plan como red de seguridad |
| Baja fluency en evals | Ampliar golden set `eval/` |
| Nueva modalidad | Añadir entrada en `modalities.json` + tests |
| Extract incompleto | Revisar template / fixtures; opcional `FOUNDRY_USE_IGNITE_API=true` solo en lab privado |

---

## 8. Diagrama del workflow Foundry

```text
OnConversationStart
        │
        ▼
 step_plan          (ignite-orchestrator-agent)  → Plan JSON
        │
        ▼
 step_document      (ignite-document-agent)      → inspect_document
        │
        ▼
 step_media         (ignite-image-agent)         → describe_media (no-op si no hay MED-*)
        │
        ▼
 step_synthesize    (ignite-orchestrator-agent)  → reply usuario
        │
        ▼
 EndConversation
```

Capturas recomendadas para el vídeo: Agents list, Workflow graph, Tracing con `modality:*`, Evaluations scores, salida de `python brain.py`.

---

## 9. Guion corto del vídeo (≤ 3 min)

1. Problema (adjuntos → acción).  
2. Foundry Agents: cerebro + document + media.  
3. Correr / mostrar Plan JSON → reply (brain).  
4. Workflow + Tracing tags + Eval.  
5. Cierre: misma arquitectura que el producto Ignite; Foundry = plano Architect.

---

## 10. Cómo reproducir

```powershell
cd foundry
copy .env.example .env
# opcional: PROJECT_CONNECTION_STRING=... para portal
python -m pip install -r requirements.txt
python test_tools.py
python test_brain.py
python brain.py
# con Azure:
# python agents.py
# python monitor.py
# python evaluate.py
# python workflow.py
```

---

*Documento listo para exportar a PDF/Word desde este Markdown para la entrega Founderz.*
