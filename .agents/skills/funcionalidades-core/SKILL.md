---
name: funcionalidades-core
description: "Capacidades y limitaciones Ignite Chat: voz, docs, scrape/grounding (body <800, todos los providers incl. Gemini), preview WhatsApp de archivos enviados (wa-file-card, sin PDF base64 en el DOM), multi-proveedor (Alibaba UI-quarantine), idioma forzado + chrome localizado, welcome coherente, ACA isolation, RAG/sandbox/MCP (scope real)."
---

# Skill: Funcionalidades Core (Ignite Chat)

Consulta la matriz de capacidades/limitaciones y las reglas de grounding, idioma y welcome en:

[references/SKILLS_CORE.md](references/SKILLS_CORE.md)

Reglas críticas anti-regresión:
- Grounding: umbral 800 chars sobre el **cuerpo scrapeado**, no sobre guards de idioma; Gemini incluido (`should_enable_search_after_scrape`).
- Idioma: sticky al inicio + switch explícito **o** utterance claramente monolingüe (`conversation_language.py`); defaults vía `IGNITE_DEFAULT_CONVERSATION_LANGUAGE` (sin hardcode en call sites); welcome/`currentLang`; chrome multi-locale; **todos** los providers → `append_mandatory_reply_language` + `wrap_user_query_for_language` + `multimodal_describe_prompt` (contrato README; no soft-notes ni captions Gemini solo-EN).
- ACA: aislamiento por `X-Ignite-Session-Id`; STT/search caches y CSE-403 disable por tenant; RAG `local_rag__{tenant}.db` bajo `IGNITE_DATA_DIR` (nunca desde `__file__`, se borra en cada restart).
- Runtime: default desktop `IGNITE_RUNTIME_MODE=local` (capabilities ≡ launcher ≡ `.env.example`).
- Documentos largos: PDF nativo Gemini/Anthropic; poll UI ≥ LLM HTTP ≥ Cloud Run; umbrales vía `.env` (`IGNITE_DOCUMENT_POLL_TIMEOUT_MS`, `IGNITE_PDF_*`). Prohibido recortar un libro a 12 páginas o cancelar a los 6 min.
- Preview archivos (WhatsApp): burbuja `wa-file-card` + overlay `#file-preview-overlay`; `filesForUi` sin PDF/PPTX `base64` completo (sí `preview_base64`); historial conserva miniatura; `collectMessageFileGroup` vía `fileFromPreviewElement`. Overlay PDF = pdf.js canvas (no iframe blob). Download = `save_file_to_downloads`. Burbuja user = solo texto del usuario + card del adjunto (nunca RAG `[LOCAL PERSISTENT MEMORY RECALLED]` ni assemblies multimodales) — skill `user-bubble-isolation` + test `test_user_bubble_strips_rag.py`.
- **Voz (WhatsApp player IMMUTABLE):** mic → `Voice_Message_*.webm` + `buildVoicePlayerHTML` (waveform/play/✓✓). `filesForUi` **conserva** `base64` de voz. `refreshMessageAttachments` / hydrate PDF **NUNCA** deben vaciar la burbuja de voz (`buildMessageAttachmentsHTML` filtra `Voice_Message_*`). Guardas: `dataset.isVoice`, skip refresh voice-only, test `test_voice_bubble_refresh_guard.py`. Al tocar send/hydrate/adjuntos: correr ese test + no romper player.

* 🖼️ **Grok + PDF/DOCX:** omitir imágenes con width*height < IGNITE_VISION_MIN_IMAGE_PIXELS (default 512) vía _prepare_image_for_vision_api — evita invalid_image por logos diminutos. No upscale.
* 🖼️ **Anthropic:** comprimir imágenes > IGNITE_ANTHROPIC_MAX_IMAGE_BYTES (default 10 MiB) antes de Messages API — evita 400 image too large.
* 🔍 **Perplexity:** sin vision nativo (describe_image Gemini); truncar prompt IGNITE_PERPLEXITY_MAX_PROMPT_CHARS; comprimir describe IGNITE_DESCRIBE_IMAGE_MAX_BYTES; errores 429/context/timeout user-safe.
