---
name: foundry-paso3
description: "Microsoft Agent-a-thon Paso 3 / Foundry. Canonical segregated agents (doc/image/audio/video + orch), create-if-missing, Traces→workflow, Gemini. STD Case Queue methodology. NEVER touch IgniteChat or IgniteAPI remotes. Cosmos/Postgres persistence DEFERRED."
---

# Skill: Foundry Paso 3 (Agent-a-thon)

**Repo de entrega ÚNICO:** `Razor2296/Microsoft-Agent-a-thon-Sept-17`  
Trabajo bajo `_agentathon/` (o clone de ese repo). Nada más.

## Leer siempre (no perder el hilo)

1. [references/STD_CASE_QUEUE.md](references/STD_CASE_QUEUE.md) — **metodología STD Queue** (casos OPEN/DEFERRED)
2. [references/FOUNDRY_AGENTS.md](references/FOUNDRY_AGENTS.md) — nombres canónicos del portal
3. [references/DEMO_VIDEO_CHECKLIST.md](references/DEMO_VIDEO_CHECKLIST.md) — **antes de grabar** el video ≤3 min

## PROHIBIDO — no negociable

- **Git / ramas:** ❌ Nunca inventar ramas (`fix/…`, `ci/…`, `cursor/…`). ✅ Commits y PRs solo en **`Develop`** (otra rama solo con pedido explícito del usuario).
- **NO TOCAR Ignite API** (`Razor2296/IgniteAPI`: remote, PRs, server extract, ACA).
- **NO TOCAR Ignite Chat** (`Razor2296/IgniteChat`: remote, PRs, UI producto).
- Snapshot `app/` en Agent-a-thon = **copia de concurso**; no empujar Foundry a remotes de producto.
- Si “parece” necesitar Chat/API: documentar en esta skill / STD queue; **no** abrir PR allá.

## STD Queue (metodología)

Cola ordenada de casos (`STD-001`…). Antes de editar: leer la cola, respetar estados.  
Si el usuario cambia un acuerdo → actualizar la fila en el **mismo** cambio.  
Create-if-missing = **STD-005**. Segregación = **STD-004**. Cosmos/Postgres = **STD-009 DEFERRED**.

## Reglas críticas

1. **Agentes canónicos** `juliancuray-7914` (portal = verdad), **segregados**:
   - `ignite-orchestrator-agent`
   - `ignite-document-agent`
   - `ignite-image-agent`
   - `ignite-audio-agent`
   - `ignite-video-agent`
   - `ignite-document-workflow`
2. **Create-if-missing:** si no existen → créalos (`ensure_agents_and_workflow`); si existen → úsalos (refresh solo con `FOUNDRY_REFRESH_AGENTS=true`).
3. **Prohibido** un único `ignite-media-agent` que colapse image/audio/video.
4. **Traces → flujo multiagente** en la **misma sesión de chat** (historia). JSON store Cosmos/Postgres: **no implementar ahora**.
5. **Flujo:** Traces ON → ensure → **`invoke_workflow()`**. Sin endpoint → `NO LLEGÓ A FOUNDRY`.
6. **Modelo:** Gemini `gemini-2.5-flash` por defecto de concurso.
7. **Logs:** `FOUNDRY ...`
8. **Scope:** solo Agent-a-thon.
9. **Mic / voz (STD-012):** turnos `from_mic` o `Voice_Message_*` también abren Traces (`trigger=chat_mic`). No depender de `files` tras STT.
10. **Todo Chat → Foundry (STD-014):** generación de imagen/audio y el resto de turnos también planifican/rastrean; Chat sigue emitiendo bytes.
11. **Video-safe:** turnos no-intercept (mic, gen, chat) trazan **async** (`FOUNDRY_TRACE_ASYNC=true` default). Extract/doc sigue **sync** para el footer en burbuja.
