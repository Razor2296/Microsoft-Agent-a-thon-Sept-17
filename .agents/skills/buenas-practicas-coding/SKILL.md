---
name: buenas-practicas-coding
description: "Estándares Ignite Chat: imports explícitos, no hardcodeo, scope safety, Pydantic V2, async-first, FSM, anti-regresión welcome/clear/session/STT, pre-commit y tests."
---

# Skill: Buenas Prácticas de Coding (Ignite Chat)

Al desarrollar o modificar código, sigue de forma estricta:

1. **Importaciones explícitas** — nunca `from module import *`.
2. **No hardcodeo** — keys, modelos, timeouts y umbrales vía `.env` / config.
3. **Scope safety** — inicializa locales antes de `try`; nunca `except: pass` sin log.
4. **Pydantic V2** — DTOs en schemas; evita `dict` genéricos en contratos.
5. **Async-first** — evita `threading.Thread` nuevos en hot paths cuando haya asyncio.
6. **FSM frontend** — transiciones solo vía `stateMachine.js` (matriz legal).
7. **Anti-regresión (§12 de SKILLS_CODING.md)** — welcome solo en historial vacío; `clear` luego welcome; `session_id` por provider+model; Whisper falla con `None`; caches multi-tenant keyed; CSE-403 disable por tenant; RAG DB por tenant; scrape/guards/Gemini grounded sin español hardcodeado; idioma **sticky** al inicio + switch explícito o utterance monolingüe clara; `resolve_reply_language`; `find_latest` tie-break `(mtime, path)`; chrome multi-idioma; `runtime_mode` default `local`; Gemini search tras scrape &lt;800; Alibaba UI-quarantine; extract default `true`; cancel check pre/post `extract_sync`; frozen desktop logs/data vía `runtime_paths` (no escribir en Program Files); PDF nativo / poll de documentos vía `.env` (no `6 * 60 * 1000` ni recorte a 12 páginas); preview WhatsApp de archivos (`wa-file-card`, pdf.js canvas en overlay, `save_file_to_downloads`, slice vertical UI+api+tests, no `base64` completo en el DOM); suite completa `.venv_x64` en 0 failed antes de push.

Especificación completa: [references/SKILLS_CODING.md](references/SKILLS_CODING.md).
