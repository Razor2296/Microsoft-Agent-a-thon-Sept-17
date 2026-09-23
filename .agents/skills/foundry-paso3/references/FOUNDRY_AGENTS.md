# Foundry agents — contrato canónico (juliancuray-7914)

Fuente de verdad = portal Foundry → Build → Agents.  
Si el código diverge de esta tabla, **el código está mal**.

## Scope duro

| Permitido | Prohibido |
| --- | --- |
| Repo `Microsoft-Agent-a-thon-Sept-17` / `_agentathon/` | Remote / PRs **IgniteChat** |
| Foundry portal `juliancuray-7914` | Remote / PRs **IgniteAPI** |
| Snapshot `app/` + `foundry/` de concurso | “Arreglar producto” empujando a Chat/API |

Ignite API / Chat se **referencian** como contrato (channels, extract); **no se modifican**.

Ver también la cola de casos: [STD_CASE_QUEUE.md](STD_CASE_QUEUE.md).

## Agentes (Prompt)

| Nombre exacto | Modalidad / canal (contrato Ignite API) | Tool | Ids / señales |
| --- | --- | --- | --- |
| `ignite-orchestrator-agent` | todas (planifica) | ninguna en primer turno | Plan JSON |
| `ignite-document-agent` | `document` / PDF | `inspect_document` | `DOC-*`, channel=document |
| `ignite-image-agent` | `image` | `describe_media` (MED-IMG-*) | channel=image |
| `ignite-audio-agent` | `audio` | `describe_media` (MED-AUD-*) | channel=audio |
| `ignite-video-agent` | `video` | `describe_media` (MED-VID-*) | channel=video |

## Workflow

| Nombre exacto | Rol |
| --- | --- |
| `ignite-document-workflow` | plan → document → image → audio → video → synthesize |

## Sesión de chat + Traces (historia multiagente)

1. Un turno en el Chat **snapshot** arma Traces.
2. Eso **dispara** el workflow multiagente (misma conversación / sesión).
3. La “historia” del turno = spans en Traces + Plan footer en la burbuja.
4. **Mic / nota de voz (STD-012):** `from_mic=True` o `Voice_Message_*` → trigger `chat_mic` (aunque el STT ya haya quitado el webm de `files`). Chat casual: traza y deja el reply del provider; extract hablado: footer Foundry.
5. **Generación imagen/audio (STD-014):** `GENERATE_IMAGE` → `ignite-image-agent`; `GENERATE_AUDIO` → `ignite-audio-agent`. Foundry planifica y deja Traces; Ignite Chat genera los bytes.
6. **Más adelante** (NO ahora): persistir esa historia JSON en Cosmos DB, Postgres JSONB, u otra BD JSON. Dejar en paz hasta pedido explícito.

## Env

```env
IGNITE_ORCHESTRATOR_AGENT=ignite-orchestrator-agent
IGNITE_DOCUMENT_AGENT=ignite-document-agent
IGNITE_IMAGE_AGENT=ignite-image-agent
IGNITE_AUDIO_AGENT=ignite-audio-agent
IGNITE_VIDEO_AGENT=ignite-video-agent
IGNITE_WORKFLOW_AGENT=ignite-document-workflow
MODEL_DEPLOYMENT_NAME=gemini-2.5-flash
FOUNDRY_ORCHESTRATION_ENABLED=true
PROJECT_CONNECTION_STRING=https://....services.ai.azure.com/api/projects/juliancuray-7914
APPLICATIONINSIGHTS_CONNECTION_STRING=...
```

No inventar `IGNITE_MEDIA_AGENT` como agente canónico. Routing por modalidad → image|audio|video agent.

## Checklist antes de tocar nombres

- [ ] ¿Existe ya en Foundry Build → Agents?
- [ ] ¿Un especialista por modalidad?
- [ ] ¿Actualicé esta skill?
- [ ] ¿Cero commits a IgniteChat / IgniteAPI?
- [ ] ¿No implementé Cosmos/Postgres sin pedirlo?
