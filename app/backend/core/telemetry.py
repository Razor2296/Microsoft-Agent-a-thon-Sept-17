"""Lightweight observability for Ignite Chat (latency / tokens / errors).

Enabled when IGNITE_OTEL_ENABLED=true. Emits structured logs and keeps
in-process counters exposed via get_metrics_snapshot() / GET /metrics.
"""

from __future__ import annotations
import logging
import os
import threading
import time
from contextlib import contextmanager
from collections.abc import Generator
from typing import Any

# Get logger
logger = logging.getLogger(__name__)

# Check if telemetry is enabled
_TRACING_ENABLED = (os.getenv("IGNITE_OTEL_ENABLED") or "false").strip().lower() in {
    "1",
    "true",
    "yes",
}

# Lock for thread safety
_LOCK = threading.Lock()

# Metrics dictionary
_METRICS: dict[str, Any] = {
    "invokes_total": 0,
    "invokes_error": 0,
    "invoke_latency_ms_sum": 0.0,
    "tokens_total": 0,
    "tokens_by_provider": {},
    "spans": {},
}

# Function to check if telemetry is enabled
def is_enabled() -> bool:
    return _TRACING_ENABLED

# Function to trace spans
@contextmanager
def trace_span(name: str, attributes: dict[str, Any] | None = None) -> Generator[None, None, None]:
    """Lightweight span wrapper. No-ops unless IGNITE_OTEL_ENABLED=true."""
    started = time.perf_counter()
    attrs = attributes or {}
    error = False
    try:
        yield
    except Exception:
        error = True
        if _TRACING_ENABLED:
            logger.error("otel.span_error name=%s attrs=%s", name, attrs, exc_info=True)
        raise
    finally:
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        if _TRACING_ENABLED:
            logger.info(
                "otel.span name=%s elapsed_ms=%.2f error=%s attrs=%s",
                name,
                elapsed_ms,
                error,
                attrs,
            )
        with _LOCK:
            bucket = _METRICS["spans"].setdefault(
                name, {"count": 0, "errors": 0, "latency_ms_sum": 0.0}
            )
            bucket["count"] += 1
            bucket["latency_ms_sum"] += elapsed_ms
            if error:
                bucket["errors"] += 1

# Function to record invoke
def record_invoke(method: str, latency_ms: float, *, ok: bool) -> None:
    with _LOCK:
        _METRICS["invokes_total"] += 1
        _METRICS["invoke_latency_ms_sum"] += latency_ms
        if not ok:
            _METRICS["invokes_error"] += 1
    if _TRACING_ENABLED:
        logger.info(
            "otel.invoke method=%s latency_ms=%.2f ok=%s",
            method,
            latency_ms,
            ok,
        )

# Function to record token usage
def record_token_usage(provider: str, total_tokens: int) -> None:
    tokens = max(0, total_tokens)
    prov = (provider or "").strip() or "unknown"
    with _LOCK:
        _METRICS["tokens_total"] += tokens
        by_prov = _METRICS["tokens_by_provider"]
        by_prov[prov] = by_prov.get(prov, 0) + tokens
    if _TRACING_ENABLED:
        logger.info("otel.tokens provider=%s total=%s", prov, tokens)

# Alias for record_token_usage
record_tokens = record_token_usage

# Function to get metrics snapshot
def get_metrics_snapshot() -> dict[str, Any]:
    with _LOCK:
        invokes = _METRICS["invokes_total"]
        latency_sum = _METRICS["invoke_latency_ms_sum"]
        avg = (latency_sum / invokes) if invokes else 0.0
        return {
            "otel_enabled": _TRACING_ENABLED,
            "invokes_total": invokes,
            "invokes_error": _METRICS["invokes_error"],
            "invoke_latency_ms_avg": round(avg, 2),
            "tokens_total": _METRICS["tokens_total"],
            "tokens_by_provider": dict(_METRICS["tokens_by_provider"]),
            "spans": {
                name: {
                    "count": bucket["count"],
                    "errors": bucket["errors"],
                    "latency_ms_avg": round(
                        bucket["latency_ms_sum"] / max(1, bucket["count"]),
                        2,
                    ),
                }
                for name, bucket in _METRICS["spans"].items()
            },
        }
