"""
FastAPI HTTP facade over PyWebViewApi.

Exposes the same public methods used by the desktop UI so the thin client can
proxy window.pywebview.api.* calls to Azure Container Apps.

Each desktop client is isolated via X-Ignite-Session-Id → SessionApiStore.
"""

from __future__ import annotations

import asyncio
import contextvars
import inspect
import logging
import os
import sys
import time
from contextlib import asynccontextmanager
from typing import Any

# Ensure `app/` is on sys.path whether launched as `python -m server.main`
# or `uvicorn server.main:app` from the app directory.
_APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_DIR not in sys.path:
    sys.path.insert(0, _APP_DIR)

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from backend.core.runtime_identity import set_runtime_user_name
from backend.core.telemetry import get_metrics_snapshot, record_invoke, trace_span
from main.api import PyWebViewApi
from server.auth import require_api_key
from server.session_store import SessionApiStore

try:
    import uvicorn
except ImportError:
    uvicorn = None

# Multi-env .env selection before API construction (IGNITE_ENV=dev|staging|prod).
try:
    from main.env_config import load_environment

    _loaded_env = load_environment(_APP_DIR)
except Exception:  # pragma: no cover - keep server bootable without dotenv file
    _loaded_env = ""

logger = logging.getLogger("ignite.server")
if _loaded_env:
    logger.info("Loaded environment file: %s", _loaded_env)

# Public methods the desktop bridge is allowed to invoke remotely.
ALLOWED_METHODS = frozenset(
    {
        "get_initial_state",
        "get_history",
        "get_token_totals",
        "get_cost_totals",
        "get_accumulated_cost_stats",
        "set_provider",
        "set_model",
        "set_participant_model",
        "clear_history",
        "create_group",
        "delete_group",
        "send_message_async",
        "cancel_generation",
        "get_generation_status",
        "send_message",
        "generate_image",
        "generate_audio",
        "determine_voice_category",
        "generate_cartesia_tts",
        "export_message_to_file",
        "open_file_path",
        "open_external_link",
        "translate_message",
        "summarize_chat",
        "save_welcome_message",
        "set_theme_window_size",
        "get_available_plugins",
        "reload_plugins",
        "execute_plugin",
        "execute_sandbox_code",
        "scrape_web_url",
        "handle_mcp_request",
        "synthesize_voice_clone",
        "generate_plotly_chart",
        "add_rag_document",
        "search_rag_memory",
        "clear_rag_memory",
        "get_system_capabilities",
        "validate_and_save_api_key",
        "get_productivity_metrics",
        "get_smart_fallback",
    }
)

# Class to define the structure of an invoke request
class InvokeRequest(BaseModel):
    method: str = Field(..., description="PyWebViewApi method name")
    args: list[Any] = Field(default_factory=list)
    kwargs: dict[str, Any] = Field(default_factory=dict)
    client_user_name: str | None = Field(
        default=None,
        description="Windows display name from the thin desktop client",
    )

# Class to define the structure of an invoke response
class InvokeResponse(BaseModel):
    status: str = "success"
    result: Any = None
    error: str | None = None
    session_id: str | None = None

# Function to build the PyWebViewApi
def _build_api(tenant_key: str):
    return PyWebViewApi(tenant_key=tenant_key)

# Function to get the session ID from the request
def _session_id_from_request(request: Request) -> str | None:
    return (
        request.headers.get("X-Ignite-Session-Id")
        or request.headers.get("x-ignite-session-id")
        or None
    )

# Function to create the FastAPI app
def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # One isolated PyWebViewApi per desktop client session (not a shared singleton).
        app.state.session_store = SessionApiStore(factory=_build_api)
        logger.info("SessionApiStore ready for multi-user ACA isolation")
        yield

    app = FastAPI(
        title="Ignite Chat API",
        version="1.0.0",
        description="HTTP backend for Ignite Chat hybrid desktop + Azure Container Apps",
        lifespan=lifespan,
    )
    cors_origins = [
        o.strip()
        for o in (os.getenv("IGNITE_CORS_ORIGINS") or "*").split(",")
        if o.strip()
    ]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins or ["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Ignite-Session-Id"],
    )

    # Health check endpoint
    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "mode": "aca"}

    # Readiness check endpoint
    @app.get("/ready")
    async def ready() -> dict[str, Any]:
        store = getattr(app.state, "session_store", None)
        if store is None:
            raise HTTPException(status_code=503, detail="Session store not initialized")
        return {
            "status": "ready",
            "active_sessions": store.active_count(),
        }

    # Metrics endpoint
    @app.get("/metrics")
    async def metrics() -> dict[str, Any]:
        """In-process counters (latency / errors / tokens). Auth not required for ops scrape."""
        store = getattr(app.state, "session_store", None)
        snap = get_metrics_snapshot()
        snap["active_sessions"] = store.active_count() if store is not None else 0
        return snap

    # Session store helper
    def _get_store() -> SessionApiStore:
        store = getattr(app.state, "session_store", None)
        if store is None:
            raise HTTPException(status_code=503, detail="Session store not initialized")
        return store

    # Invoke method endpoint
    async def _invoke_method(
        payload: InvokeRequest,
        request: Request,
        response: Response,
    ) -> InvokeResponse:

        method = (payload.method or "").strip()
        if method not in ALLOWED_METHODS:
            raise HTTPException(
                status_code=404, detail=f"Unknown or disallowed method: {method}"
            )

        store = _get_store()
        session_id, api = store.get_or_create(_session_id_from_request(request))
        response.headers["X-Ignite-Session-Id"] = session_id

        desktop_user = (
            (payload.client_user_name or "")
            or request.headers.get("X-Ignite-User-Name")
            or request.headers.get("x-ignite-user-name")
            or ""
        ).strip()

        # Function to apply the desktop user identity
        def _apply_identity() -> None:
            if not desktop_user:
                return
            try:
                set_runtime_user_name(desktop_user)
                if hasattr(api, "_user_name"):
                    api._user_name = desktop_user
                logger.info(
                    "Applied desktop user identity for session %s: %s",
                    session_id,
                    desktop_user,
                )
            except Exception as exc:
                logger.warning(
                    "Could not apply desktop user name '%s': %s",
                    desktop_user,
                    exc,
                )

        target = getattr(api, method, None)
        if target is None or not callable(target):
            raise HTTPException(status_code=404, detail=f"Method not found: {method}")

        # Synchronous wrapper for non-async methods
        def _call() -> Any:
            _apply_identity()
            return target(*payload.args, **payload.kwargs)

        started = time.perf_counter()
        ok = True
        try:
            with trace_span("api.invoke", {"method": method, "session_id": session_id}):
                if inspect.iscoroutinefunction(target):
                    _apply_identity()
                    result = await target(*payload.args, **payload.kwargs)
                else:
                    # Preserve ContextVar identity across the worker thread.
                    ctx = contextvars.copy_context()
                    result = await asyncio.to_thread(ctx.run, _call)
            return InvokeResponse(
                status="success",
                result=result,
                session_id=session_id,
            )
        except HTTPException:
            ok = False
            raise
        except Exception as exc:
            ok = False
            logger.error("Error invoking %s: %s", method, exc, exc_info=True)
            return InvokeResponse(
                status="error",
                error=str(exc),
                session_id=session_id,
            )
        finally:
            record_invoke(
                method,
                (time.perf_counter() - started) * 1000.0,
                ok=ok,
            )

    @app.post(
        "/api/invoke",
        response_model=InvokeResponse,
        dependencies=[Depends(require_api_key)],
    )
    async def invoke(
        payload: InvokeRequest,
        request: Request,
        response: Response,
    ) -> InvokeResponse:
        return await _invoke_method(payload, request, response)

    # Convenience aliases matching common desktop calls
    @app.post("/api/send_message_async", dependencies=[Depends(require_api_key)])
    async def send_message_async(
        body: dict[str, Any],
        request: Request,
        response: Response,
    ) -> Any:
        return (
            await _invoke_method(
                InvokeRequest(method="send_message_async", kwargs=body),
                request,
                response,
            )
        ).result

    @app.get(
        "/api/generation_status/{request_id}",
        dependencies=[Depends(require_api_key)],
    )
    async def generation_status(
        request_id: str,
        request: Request,
        response: Response,
    ) -> Any:
        return (
            await _invoke_method(
                InvokeRequest(method="get_generation_status", args=[request_id]),
                request,
                response,
            )
        ).result

    @app.get("/api/initial_state", dependencies=[Depends(require_api_key)])
    async def initial_state(request: Request, response: Response) -> Any:
        return (
            await _invoke_method(
                InvokeRequest(method="get_initial_state"),
                request,
                response,
            )
        ).result

    return app


app = create_app()

# Main entry point
def main() -> None:
    if uvicorn is None:
        raise RuntimeError("uvicorn is required to run the server directly")
    host = os.getenv("IGNITE_API_HOST", "0.0.0.0")
    port = int(os.getenv("IGNITE_API_PORT", "8000"))
    uvicorn.run("server.main:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
