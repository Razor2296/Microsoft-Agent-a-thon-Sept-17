# Unit suite layers — mirror app/ source, not test style (no scenario/e2e folder).
#
#   core/          backend/core (+ windows_user)
#   frontend/      app/frontend HTML/JS/CSS contracts
#   integrations/  backend/integrations + Ignite API client + Office extract/gen
#   processors/    backend/processors
#   server/        app/main/api.py, app/server/*, remote proxy, session
#   tools/         backend/tools (RAG, guardrails, MCP, skill loader)
#   voice/         backend/voice + mic UX
#   results/       pytest run logs (not tests)
