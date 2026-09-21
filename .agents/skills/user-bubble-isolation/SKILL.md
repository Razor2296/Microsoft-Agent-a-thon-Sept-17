---
name: user-bubble-isolation
description: "Anti-regresión burbuja usuario Ignite Chat: detectar/evitar que RAG ([LOCAL PERSISTENT MEMORY RECALLED]), assemblies multimodales o enriched_text del processor aparezcan en el mensaje del usuario. USE WHEN: adjuntos/imagen, RAG memory, burbuja YOU contaminada, System Prompt Isolation, enriched_text, generate_response_with_inline_files, strip_model_context_from_user_content."
---

# Skill: User Bubble Isolation (RAG / multimodal)

La burbuja **YOU** solo puede mostrar:

1. Texto **escrito o dictado** por el usuario (STT incluido).
2. La **card/preview** del adjunto (`wa-file-card` / imagen).

Nunca debe mostrar contexto armado para el LLM.

## Marcadores prohibidos en `role=user` content

Si aparecen en historial o UI, es regresión:

- `[LOCAL PERSISTENT MEMORY RECALLED]`
- `[USER QUERY]` (prefijo de `_text_for_model_with_rag`)
- `<image_file` / `<video_file` / `<audio_recording` / `<file name=`
- `[What I can see in this image:]` / `[What I can see and hear in this video:]`
- `[System Note:` / `[Content of ` (assemblies de processor)

## Causa raíz conocida

En `app/main/api.py`, tras `generate_response_with_inline_files`:

```python
# FORBIDDEN — contaminaba la burbuja en TODOS los providers (3-tuple)
reply, token_info, enriched_text = res
self._history[provider][-1]["content"] = enriched_text
```

`enriched_text` es el prompt multimodal (RAG + descripciones de archivo). Debe quedarse **solo** en el call al modelo. El historial conserva el `text` de `_preprocess_input`.

## Contrato correcto

| Capa | Qué hace |
| --- | --- |
| `_text_for_model_with_rag(text)` | Prefija RAG al texto **solo** para el LLM |
| `generate_response_with_inline_files(text_for_model, ...)` | Puede devolver 3er valor model-facing |
| Historial / UI | `content` = texto usuario; files = cards |
| `strip_model_context_from_user_content` | Limpia sesiones ya contaminadas |
| `_clean_history_for_frontend` / `_clean_history_for_saving` | Deben llamar el strip en `role=user` |

## Checklist al tocar send / adjuntos / RAG

1. Buscar en `api.py`: `enriched_text` + asignación a `[-1]["content"]` → **cero** hits de overwrite.
2. Confirmar `strip_model_context_from_user_content` existe y se usa en cleaners.
3. Correr tests obligatorios (abajo).
4. Smoke: imagen sola → burbuja sin bloque MEMORY; imagen + caption → card + caption.

## Tests obligatorios (no borrar)

- `app/tests/unit/server/test_user_bubble_strips_rag.py`
- Debe incluir aserción **estática** sobre el source de `_send_message_sync`: no puede reaparecer el overwrite a `[-1]["content"] = enriched_text`.

```bash
.venv_x64\Scripts\python.exe -m pytest app/tests/unit/server/test_user_bubble_strips_rag.py -q
```

## Relacionado

- System Prompt Isolation en `funcionalidades-core/references/SKILLS_CORE.md`
- Preview WhatsApp: `wa-file-card` (el adjunto se ve por `files`, no por pegar base64/descripción en `content`)
