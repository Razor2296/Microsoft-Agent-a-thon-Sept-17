# Checklist grabación demo (≤3 min) — GOD path

Antes de OBS/Loom. Repo: **Microsoft-Agent-a-thon-Sept-17** (no producto IgniteChat limpio).

## 1. Arranque (30 s)

- [ ] `run_app.bat` desde este snapshot
- [ ] Consola: `FOUNDRY BOOT` + líneas `FOUNDRY ...`
- [ ] `FOUNDRY_ORCHESTRATION_ENABLED=true` y `PROJECT_CONNECTION_STRING` en `foundry/.env`
- [ ] `MODEL_DEPLOYMENT_NAME=gemini-2.5-flash`
- [ ] Portal Foundry `juliancuray-7914`: Agents (5) + Tracing + Evaluations abiertos

## 2. Contrato UX vs Foundry (no improvisar)

| Acción en video | Qué debe verse | Qué NO hacer |
| --- | --- | --- |
| `Extrae DOC-001` / PDF | Footer `— Foundry orchestration` + Traces | No usar producto IgniteChat sin Foundry |
| Foto / `MED-IMG-*` | Ruta image-agent en Traces / footer | No esperar solo caption Gemini sin Traces |
| Mic | Player WhatsApp + Traces `chat_mic` | No grabar si la burbuja solo dice Tokens |
| `Genera una imagen…` | Imagen en chat + Traces `chat_generate_image` | No esperar que Foundry emita los bytes |
| `Crea un sonido…` | Audio en chat + Traces `chat_generate_audio` | Idem |

## 3. Anti-bugs ya cubiertos (si regresan = STOP)

- Mic vacío (solo Tokens) → `test_voice_bubble_refresh_guard.py`
- Mic sin Traces → STD-012 / `from_mic`
- Gen imagen congela UI → `FOUNDRY_TRACE_ASYNC=true` (default; traza en background)
- RAG en burbuja YOU → `user-bubble-isolation`
- Agente media colapsado → STD-004 (prohibido)

## 4. Plan B en cámara

| Fallo | Qué decir / hacer |
| --- | --- |
| Sin `FOUNDRY BOOT` | Reiniciar snapshot correcto |
| `NO LLEGÓ A FOUNDRY` | Mostrar `foundry/.env` Project endpoint + `az login` |
| Traces vacíos | Esperar 10–20 s; filtrar `chat_mic` / `chat_generate_*` |
| Extract lento | Narrar poll; no cancelar |

## 5. Frases que SÍ / NO

**Sí:** “Foundry planifica y rastrea; Ignite Chat ejecuta (bytes, TTS, UI).”  
**No:** “Foundry responde siempre en la burbuja” (solo extract/doc).  
**No:** “Ignite API vive en este repo.”
