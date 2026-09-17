"""
app/tests/unit/tools/test_core_features.py
Unit tests for Skills 2.2 to 2.7 (Live Code Sandbox, Web Agent, MCP Gateway, Voice Clone, Plotly)

LLM Reference: app/skills/02_core_features/SKILLS_CORE.md
"""
import os
import tempfile
import pytest

from backend.tools.mcp_gateway import MCPGateway
from backend.tools.plotly_service import PlotlyService
from backend.tools.sandbox_runner import SandboxRunner
from backend.core.schemas import (
    MCPResponse,
    PlotlyChartResult,
    SandboxExecutionResult,
    VoiceCloneResult,
    VoiceProfile,
    WebScrapeResult,
)
from backend.voice.voice_clone import VoiceCloneManager
from backend.tools.web_agent import WebAgent


# ---------------------------------------------------------------------------
# Skill 2.2 — Live Code Sandbox Tests
# ---------------------------------------------------------------------------

class TestSandboxRunner:
    def test_python_print_execution(self):
        sandbox = SandboxRunner()
        res = sandbox.execute_code("print('Hello from sandbox!')")
        assert res.success is True
        assert res.stdout == "Hello from sandbox!"
        assert res.stderr == ""
        assert res.execution_time_ms >= 0.0

    def test_syntax_error_handling(self):
        sandbox = SandboxRunner()
        res = sandbox.execute_code("def broken_func(:")
        assert res.success is False
        assert "SyntaxError" in res.stderr or "SyntaxError" in (res.error or "")

    def test_timeout_execution(self):
        sandbox = SandboxRunner()
        res = sandbox.execute_code("import time; time.sleep(5)", timeout_seconds=1.0)
        assert res.success is False
        assert "timed out" in (res.error or "").lower()

    def test_matplotlib_figure_capture(self):
        pytest.importorskip("matplotlib")
        sandbox = SandboxRunner()
        code = """
import matplotlib.pyplot as plt
plt.figure()
plt.plot([1, 2, 3], [4, 5, 6])
plt.title("Sandbox Test Chart")
plt.show()
"""
        res = sandbox.execute_code(code)
        assert res.success is True
        assert res.base64_image is not None
        assert res.base64_image.startswith("data:image/png;base64,")


# ---------------------------------------------------------------------------
# Skill 2.3 — Web Automation Agent Tests
# ---------------------------------------------------------------------------

class TestWebAgent:
    def test_scrape_valid_url(self, requests_mock=None):
        agent = WebAgent()
        # Test scraping a simple public website or mocked response
        res = agent.scrape_url("https://example.com")
        assert isinstance(res, WebScrapeResult)
        if res.success:
            assert res.url.startswith("https://example.com")
            assert len(res.text_content) > 0

    def test_invalid_url_handling(self):
        agent = WebAgent()
        res = agent.scrape_url("https://invalid-nonexistent-domain-12345.com")
        assert isinstance(res, WebScrapeResult)
        assert res.success is False
        assert res.error is not None


# ---------------------------------------------------------------------------
# Skill 2.4 — Personal MCP Gateway Tests
# ---------------------------------------------------------------------------

class TestMCPGateway:
    def test_default_tools_list_rpc(self):
        gateway = MCPGateway()
        req = {"jsonrpc": "2.0", "id": "1", "method": "tools/list"}
        res = gateway.handle_request(req)
        assert isinstance(res, MCPResponse)
        assert res.id == "1"
        assert res.error is None
        assert "tools" in res.result
        assert len(res.result["tools"]) >= 1

    def test_custom_tool_registration_and_execution(self):
        gateway = MCPGateway()
        gateway.register_tool(
            name="multiply",
            description="Multiplies two numbers",
            parameters={"type": "object"},
            handler=lambda args: args["a"] * args["b"],
        )

        req = {
            "jsonrpc": "2.0",
            "id": "2",
            "method": "tools/call",
            "params": {"name": "multiply", "arguments": {"a": 6, "b": 7}},
        }
        res = gateway.handle_request(req)
        assert res.id == "2"
        assert res.error is None
        assert "42" in res.result["content"][0]["text"]

    def test_unknown_tool_rpc_error(self):
        gateway = MCPGateway()
        req = {
            "jsonrpc": "2.0",
            "id": "3",
            "method": "tools/call",
            "params": {"name": "non_existent_tool"},
        }
        res = gateway.handle_request(req)
        assert res.error is not None
        assert res.error["code"] == -32601


# ---------------------------------------------------------------------------
# Skill 2.5 — Instant Voice Cloning Tests
# ---------------------------------------------------------------------------

class TestVoiceCloneManager:
    def test_create_and_list_profile(self):
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp.write(b"RIFF dummy wav content")
            sample_path = tmp.name

        try:
            manager = VoiceCloneManager()
            prof = manager.create_profile("v1", "User Voice", sample_path)
            assert isinstance(prof, VoiceProfile)
            assert prof.profile_id == "v1"
            assert prof.name == "User Voice"

            profiles = manager.list_profiles()
            assert len(profiles) == 1

            # Synthesize voice
            res = manager.synthesize_voice("v1", "Hola mundo")
            assert isinstance(res, VoiceCloneResult)
            assert res.success is True
            assert res.audio_base64 is not None
        finally:
            if os.path.exists(sample_path):
                os.remove(sample_path)

    def test_nonexistent_profile_synthesis_failed(self):
        manager = VoiceCloneManager()
        res = manager.synthesize_voice("unknown", "text")
        assert res.success is False
        assert "not found" in (res.error or "").lower()


# ---------------------------------------------------------------------------
# Skill 2.7 — Plotly Service Tests
# ---------------------------------------------------------------------------

class TestPlotlyService:
    def test_generate_bar_chart_html(self):
        service = PlotlyService()
        res = service.generate_chart_html(
            labels=["Q1", "Q2", "Q3", "Q4"],
            values=[10.5, 20.0, 15.2, 30.1],
            title="Quarterly Sales",
            chart_type="bar",
        )
        assert isinstance(res, PlotlyChartResult)
        assert res.success is True
        assert "Plotly.newPlot" in res.html_widget
        assert "Quarterly Sales" in res.html_widget
        assert "Q1" in res.html_widget

    def test_generate_pie_chart_html(self):
        service = PlotlyService()
        res = service.generate_chart_html(
            labels=["Python", "JS", "CSS"],
            values=[60, 30, 10],
            title="Tech Stack",
            chart_type="pie",
        )
        assert res.success is True
        assert '"type": "pie"' in res.html_widget
