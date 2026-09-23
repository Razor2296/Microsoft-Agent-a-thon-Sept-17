# Guion de demo — Ignite · Microsoft Agent-a-thon (Level 3 Architect)

**Duración objetivo:** 6–8 minutos  
**Repo:** `Razor2296/Microsoft-Agent-a-thon-Sept-17`  
**Foundry:** proyecto `juliancuray-7914`  
**Deadline contest:** 24 Sep 2026, 23:59 PDT  

---

## Antes de grabar / presentar (checklist 2 min)

1. Abrir el snapshot Agent-a-thon (no el producto IgniteChat “limpio” sin Foundry).
2. Consola debe mostrar `FOUNDRY BOOT` al arrancar.
3. `foundry/.env` + `app/.env`: `FOUNDRY_ORCHESTRATION_ENABLED=true`, `PROJECT_CONNECTION_STRING` del proyecto, `MODEL_DEPLOYMENT_NAME=gemini-2.5-flash`.
4. Checklist completo: [`.agents/skills/foundry-paso3/references/DEMO_VIDEO_CHECKLIST.md`](../.agents/skills/foundry-paso3/references/DEMO_VIDEO_CHECKLIST.md).
5. Tener listos:
   - Fixture `DOC-001` / PDF de prueba,
   - foto de **receta médica**,
   - portal Foundry → Agents + Traces ya abiertos.
6. Provider en UI: Gemini (preferido concurso).

**Nota:** extract/doc puede mostrar footer Foundry en la burbuja. Mic / generar imagen-audio: Chat ejecuta; Foundry rastrea en Traces (`chat_mic`, `chat_generate_*`).

---

## 0. Apertura (30–40 s)

> “Hola — soy Julian. Este es **Ignite**, mi entrega Level 3 Architect del Microsoft Agent-a-thon.  
> El problema que ya tengo en el día a día: PDFs, recetas e invoices desordenados. El chat olvida; yo no quiero volver a tipear.  
> Ignite no es un chatbot: es un **agente de escritorio** que toma el archivo, **extrae**, **recuerda** y puede **devolver Office** — con **Microsoft Foundry** observando la orquestación.”

*(Mostrar logo / ventana WhatsApp-style.)*

---

## 1. Arquitectura en una frase (40 s)

*(Slide o dibujo mental en pantalla: Chat → API → Foundry.)*

> “**Ignite Chat** conversa, rutea tools, RAG y voz.  
> **Ignite API** solo extrae multimodal en Azure Container Apps.  
> **Foundry** (`juliancuray-7914`) es el plano de agentes + Traces: planifica y observa; Chat ejecuta la UX.”

Criterios que vamos a tocar: **Innovation · Usability · Impact** + Level 3: **design · observability · evals · multi-agent**.

---

## 2. Demo en vivo — Usability (2–2.5 min)

### 2a. Documento → extract → burbuja

1. Arrancar `run_app.bat` — señalar en consola: `FOUNDRY BOOT`.
2. Adjuntar PDF / DOC (ej. fixture o tesis).
3. Escribir: *“Extrae los datos clave de este documento”* (o el intent natural).
4. Mostrar:
   - burbuja con respuesta útil (no “No response”),
   - card WhatsApp del archivo / overlay si aplica,
   - que el hilo sigue siendo del **provider** (Gemini/Grok), no texto Foundry.

> “El extract va a Ignite API. Foundry observa **después**, async — la UX no se congela.”

### 2b. Foto de receta → image-agent (modalidad)

1. Subir **foto de receta médica**.
2. Pedir análisis / extract.
3. En Foundry Traces / Agents: señalar ruta a **`ignite-image-agent`** (no document).

> “Agentes segregados por modalidad: document / image / audio / video + orchestrator. El portal es la fuente de verdad.”

### 2c. (Opcional 20 s) Voz

1. Mic → mensaje de voz.
2. Mostrar player WhatsApp (waveform), no solo “Tokens Consumed”.

---

## 3. Level 3 — Foundry (2 min)

Abrir portal → **Build → Agents** y **Traces**.

| Decir | Mostrar |
| --- | --- |
| Agent design | Agentes: `ignite-document-agent`, `ignite-image-agent`, … + orchestrator |
| Observability | Trace del mismo linaje `Provider\|model\|session_id` |
| Multi-agent | Workflow / plan tras extract (side-effect) |
| Care Digest | Si está ON: digest post-extract (archivo local; email solo con flag) |

> “`REPLACE_CHAT` está **off**. Foundry no roba el reply. Si solo ves extract en Traces y no el follow-up, rompemos STD-008 — aquí trackeamos la conversación completa del provider.”

Consola útil: líneas `FOUNDRY ` / create-if-missing.

---

## 4. Innovation / Impact — un golpe (40 s)

> “Innovation: desktop agent + segundo agente de extract + Foundry como telemetría de producción, no un prompt único.  
> Impact: un hilo en lugar de Acrobat + mail + ChatGPT + Excel. Medimos tokens y latencia; no inventamos ROI.”

*(Opcional)* Mencionar fix de producción: Grok ya no cae con `invalid_image` por logos &lt; 512 px en PDFs — el agente aguanta documentos reales.

---

## 5. Cierre (20–30 s)

> “Repo de entrega: **Microsoft-Agent-a-thon-Sept-17**.  
> Producto vivo: Ignite Chat + Ignite API.  
> Foundry: `juliancuray-7914`.  
> Level 3 Architect — agentes listos para producción, no solo un lab. Gracias.”

---

## Plan B (si falla la red / Foundry)

| Fallo | Qué hacer en cámara |
| --- | --- |
| Sin `FOUNDRY BOOT` | “Mal snapshot” → reiniciar `run_app.bat` del repo Agent-a-thon |
| Extract lento | Narrar timeouts UI ≥ API; mostrar job/poll sin cancelar |
| Traces vacíos | Mostrar `brain.py` Plan JSON offline + explicar que Traces necesitan `PROJECT_CONNECTION_STRING` |
| Grok 400 image | Usar Gemini para esa toma; mencionar filtro de píxeles ya mergeado |

---

## Timing resumen

| Bloque | Tiempo |
| --- | --- |
| Apertura + problema | 0:40 |
| Arquitectura | 0:40 |
| Demo Chat + extract + receta | 2:30 |
| Foundry Agents/Traces | 2:00 |
| Innovation/Impact + cierre | 1:00 |
| **Total** | **~7:00** |

---

## Frases que NO decir

- “Foundry responde siempre en la burbuja” (solo extract/doc; mic/gen dejan el reply del Chat).
- “Esto es solo el lab de FrontierWeekHack copiado.”
- “Ignite API vive en este mismo repo” (es remoto público aparte).
