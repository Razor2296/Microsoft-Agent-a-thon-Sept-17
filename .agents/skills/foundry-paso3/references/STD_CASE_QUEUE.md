# STD Case Queue — Foundry Paso 3 (Agent-a-thon)

Metodología **STD Queue**: cola ordenada de casos canónicos.  
Cada caso = un contrato. Si el código o el chat diverge, **el caso gana**.  
Actualizar esta cola cuando cambie el acuerdo con el usuario — **no perder el hilo**.

Estado: `OPEN` | `DONE` | `DEFERRED` | `BLOCKED`

---

## Queue (prioridad de lectura arriba → abajo)

| ID | Caso | Estado | Regla |
| --- | --- | --- | --- |
| **STD-001** | Scope solo Agent-a-thon | OPEN | Repo `Microsoft-Agent-a-thon-Sept-17` / `_agentathon/` únicamente |
| **STD-002** | NO TOCAR IgniteChat | OPEN | Cero commits/PRs/edits al remote `IgniteChat` |
| **STD-003** | NO TOCAR IgniteAPI | OPEN | Cero commits/PRs/edits al remote `IgniteAPI` (solo contrato de channels) |
| **STD-004** | Agentes segregados por modalidad | OPEN | Un agente por tipo: document / image / audio / video + orchestrator |
| **STD-005** | Create-if-missing | OPEN | Si el agente/workflow **no existe** en Foundry → **créalo** en cada turno Chat o Chat→Ignite API extract (`ensure` siempre re-lista; no cachea “ya listo” si el usuario borró agentes en el portal) |
| **STD-006** | Nombres canónicos = portal | OPEN | Exactamente los de Build → Agents en `juliancuray-7914` (ver tabla abajo) |
| **STD-007** | Traces activan flujo multiagente | OPEN | Chat turn / post-extract → `setup_tracing` → ensure → **`invoke_workflow`** (misma sesión = historia) |
| **STD-008** | Historia en la misma sesión de chat | OPEN | Plan + especialistas + synthesize visibles en Traces + footer burbuja |
| **STD-009** | Persistencia JSON (Cosmos / Postgres / …) | DEFERRED | Mostrar historia en BD JSON-capable — **dejar en paz** hasta pedido explícito |
| **STD-010** | Modelo Gemini primero | OPEN | `MODEL_DEPLOYMENT_NAME=gemini-2.5-flash` salvo que el usuario pida otro |
| **STD-011** | Fallo loud si no llega a Foundry | OPEN | Sin `PROJECT_CONNECTION_STRING` → `NO LLEGÓ A FOUNDRY` en burbuja + logs `FOUNDRY ...` |
| **STD-013** | Diagnóstico: ¿repo correcto? | OPEN | Al arrancar Agent-a-thon debe verse `FOUNDRY BOOT` y el banner del `run_app.bat`. Si el log solo tiene Gemini→Ignite API sin `FOUNDRY`, estás en **producto IgniteChat** (no este snapshot) |

---

## Nombres canónicos (STD-004 / STD-006)

| Agente | Modalidad |
| --- | --- |
| `ignite-orchestrator-agent` | plan / synthesize |
| `ignite-document-agent` | document |
| `ignite-image-agent` | image |
| `ignite-audio-agent` | audio |
| `ignite-video-agent` | video |
| `ignite-document-workflow` | grafo (Traces) |

**Prohibido:** inventar `ignite-media-agent` como default único que colapse image/audio/video.

---

## Create-if-missing (STD-005) — triggers

Se ejecuta en **ambos** caminos del snapshot Agent-a-thon (no remotes de producto):

| Trigger | Hook | Qué pasa |
| --- | --- | --- |
| Solo Chat (`Extrae DOC-001`, adjunta imagen, “analiza…”) | `maybe_run_foundry_turn` → `run_traced_orchestration` | Traces ON → **ensure** → workflow |
| Chat → Ignite API extract | `notify_foundry_after_extract` → mismo `run_traced_orchestration` | Tras extract OK → **ensure** → workflow |

`ensure_agents_and_workflow()` **siempre re-lista** el proyecto. Si borraste agentes en el portal, el próximo turno los vuelve a crear (doc/image/audio/video + orch + workflow).

```text
list agents in project
for each canonical name:
    if missing → create_version(...)
    if present → keep (FOUNDRY_REFRESH_AGENTS=true → republish)
invoke_workflow under Traces
```

Código: `foundry/runtime.py` + `foundry/agent_names.py`.
Agentes **segregados** (STD-004): nunca un media genérico.

---

## Hilo de conversación (no perder)

1. Usuario: Traces vacíos / “nunca llegó a Foundry”.
2. Causa: path offline o repo equivocado; mirar agente correcto.
3. Modelo: Gemini primero (Claude después si pide).
4. Estructura: modificar lo suficiente, no reestructurar producto.
5. Portal real: 5 agentes prompt (orch + doc/image/audio/video).
6. Skills: documentar + **NO TOCAR IgniteChat/API**.
7. Visión: Traces → multiagente → historia misma sesión; Cosmos/Postgres **después** (STD-009 DEFERRED).
8. Ahora: STD Queue + create-if-missing + segregación.

---

## Cómo usar esta cola en cada turno de agente

1. Leer STD-001…012 antes de editar.
2. Si el usuario cambia un acuerdo → actualizar fila + estado aquí **en el mismo PR**.
3. No implementar STD-009 sin pedido explícito.
4. No “arreglar” IgniteChat/API aunque el log de extract se vea en producto.
