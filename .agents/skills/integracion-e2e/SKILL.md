---
name: integracion-e2e
description: "Integración Ignite Chat ↔ Ignite API: extract mode=auto, timeouts, feature flag, RAG chunks, mensajes user-safe."
---

# Skill: Integración E2E (Ignite API)

Consulta el contrato de extracción, env vars y fallos defensivos en:

[references/SKILLS_E2E.md](references/SKILLS_E2E.md)

Reglas críticas:
- **Git:** ❌ no inventar ramas; ✅ commits/PRs solo en **`Develop`** (salvo pedido explícito del usuario).
- Cliente: `app/backend/integrations/ignite_api_client.py` (no `app/backend/ignite_api_client.py`).
- Siempre `mode=auto`; timeouts split connect/write/read; poll tras HTTP 202.
- `IGNITE_EXTRACTION_ENABLED` default `true` (unset → enabled); `false` salta red.
- Chrome de éxito/fallo localizado (`_extract_success_chrome` / `user_failure_hint(..., lang=)`).
