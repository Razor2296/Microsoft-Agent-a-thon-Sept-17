"""
app/backend/sandbox_runner.py
Skill 2.2 — Live Code Sandbox (Isolated Subprocess Execution)

Executes Python code snippets in an isolated subprocess with time and output limits.
Automatically captures Matplotlib figures and converts them to Base64 PNG data URIs.

LLM Reference: See app/skills/02_core_features/SKILLS_CORE.md § 2.2
"""
from __future__ import annotations

import base64
import os
import subprocess
import sys
import tempfile
import time
from typing import Optional

from backend.core.libraries import get_assistant_logger
from backend.core.schemas import SandboxExecutionRequest, SandboxExecutionResult

logger = get_assistant_logger("sandbox_runner")


class SandboxRunner:
    """
    Subprocess-based live code sandbox with timeout limits,
    stdout/stderr capture, and Matplotlib chart auto-rendering to Base64.
    """

    def __init__(self, default_timeout: float = 10.0):
        self.default_timeout = default_timeout

    def execute_code(
        self,
        code: str,
        timeout_seconds: Optional[float] = None,
        language: str = "python",
    ) -> SandboxExecutionResult:
        """
        Execute code snippet safely in an isolated Python subprocess.

        Args:
            code: Python source code string.
            timeout_seconds: Subprocess execution timeout in seconds.
            language: Programming language string (currently supports "python").

        Returns:
            SandboxExecutionResult envelope containing success status, stdout, stderr,
            execution time, and optional Base64 image data URI if Matplotlib generated a chart.
        """
        req = SandboxExecutionRequest(
            language=language,
            code=code,
            timeout_seconds=timeout_seconds or self.default_timeout,
        )

        if req.language.lower() != "python":
            return SandboxExecutionResult(
                success=False,
                error=f"Unsupported language '{req.language}'. Only 'python' is supported.",
            )

        start_time = time.time()
        temp_dir = tempfile.mkdtemp(prefix="ignite_sandbox_")
        script_file = os.path.join(temp_dir, "sandbox_script.py")
        chart_file = os.path.join(temp_dir, "generated_chart.png")

        # Instrument Python script: intercept matplotlib plt.show() to save to PNG
        wrapped_code = self._wrap_code_with_matplotlib_interceptor(req.code, chart_file)

        try:
            with open(script_file, "w", encoding="utf-8") as f:
                f.write(wrapped_code)

            # Spawn isolated python subprocess using current interpreter
            process = subprocess.run(
                [sys.executable, script_file],
                capture_output=True,
                text=True,
                timeout=req.timeout_seconds,
                cwd=temp_dir,
            )

            elapsed_ms = (time.time() - start_time) * 1000.0
            stdout_text = process.stdout.strip()
            stderr_text = process.stderr.strip()
            success = process.returncode == 0

            # Check if a chart PNG image was produced by Matplotlib
            base64_img = None
            if os.path.exists(chart_file) and os.path.getsize(chart_file) > 0:
                try:
                    with open(chart_file, "rb") as img_f:
                        img_bytes = img_f.read()
                        base64_str = base64.b64encode(img_bytes).decode("utf-8")
                        base64_img = f"data:image/png;base64,{base64_str}"
                        logger.info("Captured Matplotlib figure from sandbox code execution.")
                except Exception as img_err:
                    logger.warning(f"Failed to read generated sandbox chart: {img_err}")

            return SandboxExecutionResult(
                success=success,
                stdout=stdout_text,
                stderr=stderr_text,
                execution_time_ms=round(elapsed_ms, 2),
                base64_image=base64_img,
                error=None if success else f"Process exited with code {process.returncode}",
            )

        except subprocess.TimeoutExpired:
            elapsed_ms = (time.time() - start_time) * 1000.0
            logger.warning(f"Sandbox execution timed out after {req.timeout_seconds}s")
            return SandboxExecutionResult(
                success=False,
                execution_time_ms=round(elapsed_ms, 2),
                error=f"Execution timed out after {req.timeout_seconds} seconds.",
            )
        except Exception as err:
            elapsed_ms = (time.time() - start_time) * 1000.0
            logger.error(f"Sandbox execution exception: {err}", exc_info=True)
            return SandboxExecutionResult(
                success=False,
                execution_time_ms=round(elapsed_ms, 2),
                error=f"Sandbox error: {str(err)}",
            )
        finally:
            # Clean up temp files safely
            try:
                if os.path.exists(script_file):
                    os.remove(script_file)
                if os.path.exists(chart_file):
                    os.remove(chart_file)
                if os.path.exists(temp_dir):
                    os.rmdir(temp_dir)
            except Exception:
                pass

    def _wrap_code_with_matplotlib_interceptor(self, code: str, output_image_path: str) -> str:
        """Injects non-interactive Agg backend and auto-savefig for Matplotlib."""
        clean_path = output_image_path.replace("\\", "/")
        interceptor = f"""
import sys
try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    _original_show = plt.show
    def _custom_show(*args, **kwargs):
        plt.savefig(r"{clean_path}", bbox_inches='tight')
        plt.close('all')
    plt.show = _custom_show
except Exception:
    pass

# --- User Code ---
"""
        return interceptor + code
