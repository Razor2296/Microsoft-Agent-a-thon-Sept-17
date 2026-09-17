---
name: funcionalidades-core
description: "Capacidades y limitaciones Ignite Chat: voz, docs, scrape/grounding (body <800, todos los providers incl. Gemini), preview WhatsApp de archivos enviados (wa-file-card, sin PDF base64 en el DOM), multi-proveedor (Alibaba UI-quarantine), idioma forzado + chrome localizado, welcome coherente, ACA isolation, RAG/sandbox/MCP (scope real)."
---

# Skill: Funcionalidades Core (Ignite Chat)

Consulta la matriz de capacidades/limitaciones y las reglas de grounding, idioma y welcome en:

[references/SKILLS_CORE.md](references/SKILLS_CORE.md)

Reglas críticas anti-regresión:
- Grounding: umbral 800 chars sobre el **cuerpo scrapeado**, no sobre guards de idioma; Gemini incluido (`should_enable_search_after_scrape`).
- Idioma: sticky al inicio + switch explícito **o** utterance claramente monolingüe (`conversation_language.py`); defaults vía `IGNITE_DEFAULT_CONVERSATION_LANGUAGE` (sin hardcode en call sites); welcome/`currentLang`; chrome multi-locale.
- ACA: aislamiento por `X-Ignite-Session-Id`; STT/search caches y CSE-403 disable por tenant; RAG `local_rag__{tenant}.db` bajo `IGNITE_DATA_DIR` (nunca desde `__file__`, se borra en cada restart).
- Runtime: default desktop `IGNITE_RUNTIME_MODE=local` (capabilities ≡ launcher ≡ `.env.example`).
- Documentos largos: PDF nativo Gemini/Anthropic; poll UI ≥ LLM HTTP ≥ Cloud Run; umbrales vía `.env` (`IGNITE_DOCUMENT_POLL_TIMEOUT_MS`, `IGNITE_PDF_*`). Prohibido recortar un libro a 12 páginas o cancelar a los 6 min.
- Preview archivos (WhatsApp): burbuja `wa-file-card` + overlay `#file-preview-overlay`; `filesForUi` sin PDF/PPTX `base64` completo (sí `preview_base64`); historial conserva miniatura; `collectMessageFileGroup` vía `fileFromPreviewElement`. Overlay PDF = pdf.js canvas (no iframe blob). Download = `save_file_to_downloads`.
