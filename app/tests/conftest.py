"""
app/tests/conftest.py — Shared pytest fixtures and automatic results logger for Ignite Chat tests.
"""
from datetime import datetime
import logging
import os
import sys

logger = logging.getLogger("pytest_results")

# Ensure the 'app/' directory is on the Python path so imports like
# 'from backend.schemas import TokenInfo' work from any test file.
APP_DIR = os.path.join(os.path.dirname(__file__), "..")
if APP_DIR not in sys.path:
    sys.path.insert(0, os.path.abspath(APP_DIR))

# Ensure the app/tests/unit/results folder exists
RESULTS_DIR = os.path.join(os.path.dirname(__file__), "unit", "results")
os.makedirs(RESULTS_DIR, exist_ok=True)

import types
from unittest.mock import MagicMock

def _stub_module(name: str, **attrs):
    """Install a lightweight stub module in sys.modules."""
    if name in sys.modules and not getattr(sys.modules[name], "__ignite_stub__", False):
        mod = sys.modules[name]
        for k, v in attrs.items():
            if not hasattr(mod, k):
                setattr(mod, k, v)
        return mod

    mod = types.ModuleType(name)
    mod.__ignite_stub__ = True  # type: ignore[attr-defined]
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod
    parts = name.split(".")
    for i in range(1, len(parts)):
        parent = ".".join(parts[:i])
        if parent not in sys.modules:
            parent_mod = types.ModuleType(parent)
            parent_mod.__ignite_stub__ = True  # type: ignore[attr-defined]
            sys.modules[parent] = parent_mod
        child_name = parts[i]
        parent_mod = sys.modules[parent]
        if not hasattr(parent_mod, child_name):
            setattr(parent_mod, child_name, sys.modules.get(".".join(parts[: i + 1]), mod))
    return mod

def _maybe_stub(name: str, **attrs):
    """Stub only when the real package cannot be imported."""
    if name in sys.modules and not getattr(sys.modules[name], "__ignite_stub__", False):
        return sys.modules[name]
    try:
        __import__(name)
        return sys.modules[name]
    except Exception:
        return _stub_module(name, **attrs)

# Pre-stub common optional packages if not installed
_maybe_stub("mutagen", File=MagicMock())
_maybe_stub("youtube_transcript_api", YouTubeTranscriptApi=MagicMock())
_maybe_stub("tenacity", Retrying=MagicMock(), RetryError=Exception, stop_after_attempt=MagicMock(), wait_chain=MagicMock(), wait_fixed=MagicMock())
_maybe_stub("openai", OpenAI=MagicMock(), APIError=Exception, APIConnectionError=Exception, RateLimitError=Exception, InternalServerError=Exception)
_maybe_stub("openai.types.chat", ChatCompletion=MagicMock())
_maybe_stub("anthropic", Anthropic=MagicMock())
_maybe_stub("google.genai", types=MagicMock(), Client=MagicMock())
_maybe_stub("google.genai.types", GenerateContentConfig=MagicMock())
try:
    import google
    if not hasattr(google, "genai"):
        setattr(google, "genai", MagicMock())
except Exception:
    _stub_module("google", genai=MagicMock())
_maybe_stub("faster_whisper", WhisperModel=MagicMock())
_maybe_stub("cartesia", Cartesia=MagicMock())
def _mock_detect(text: str) -> str:
    # Heuristic mock for testing when langdetect library is not present in local python env
    if any(ch in text for ch in ("¿", "¡", "ñ", "á", "é", "í", "ó", "ú")):
        return "es"
    es_terms = {"que", "tal", "como", "estas", "buen", "dia", "hola", "sistemas", "trabajo", "tengo", "anos"}
    words = {w.lower() for w in text.split()}
    return "es" if (words & es_terms) else "en"
_maybe_stub("langdetect", detect=_mock_detect)



def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """Pytest hook: Automatically saves full test execution results to a .txt file
    inside app/tests/unit/results/ named with the local current timestamp (dynamically).
    """
    now = datetime.now()
    timestamp_str = now.strftime("%Y%m%d_%H%M%S")
    report_file = os.path.join(RESULTS_DIR, f"test_results_{timestamp_str}.txt")

    lines = []
    lines.append("================================================================================")
    lines.append("IGNITE CHAT — AUTOMATED TEST EXECUTION REPORT")
    lines.append(f"Timestamp (Local): {now.strftime('%Y-%m-%d %I:%M:%S %p')}")
    lines.append(f"Exit Status Code : {exitstatus}")
    lines.append("================================================================================\n")

    stats = terminalreporter.stats
    passed = len(stats.get("passed", []))
    failed = len(stats.get("failed", []))
    skipped = len(stats.get("skipped", []))
    errors = len(stats.get("error", []))
    total = passed + failed + skipped + errors

    lines.append(f"SUMMARY: Total={total} | Passed={passed} | Failed={failed} | Errors={errors} | Skipped={skipped}\n")
    lines.append("--------------------------------------------------------------------------------")
    lines.append("PASSED TESTS:")
    for report in stats.get("passed", []):
        lines.append(f"  [PASSED] {report.nodeid} ({report.duration:.3f}s)")

    if failed:
        lines.append("\n--------------------------------------------------------------------------------")
        lines.append("FAILED TESTS:")
        for report in stats.get("failed", []):
            lines.append(f"  [FAILED] {report.nodeid}")
            if hasattr(report, "longreprtext"):
                lines.append(f"    Details: {report.longreprtext}\n")

    if errors:
        lines.append("\n--------------------------------------------------------------------------------")
        lines.append("COLLECTION / RUNTIME ERRORS:")
        for report in stats.get("error", []):
            lines.append(f"  [ERROR] {report.nodeid}")
            if hasattr(report, "longreprtext"):
                lines.append(f"    Details: {report.longreprtext}\n")

    lines.append("\n================================================================================")

    try:
        with open(report_file, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        logger.info(f"Test results saved to: {report_file}")
    except Exception as err:
        logger.error(f"Could not save test report: {err}", exc_info=True)
