"""Unit tests: Chat → Traces → workflow (Gemini) / offline loud failure."""
from __future__ import annotations

import importlib.util
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[4]
FOUNDRY = REPO / "foundry"
MOD_PATH = REPO / "app" / "backend" / "integrations" / "foundry_orchestration.py"
RUNTIME_PATH = FOUNDRY / "runtime.py"


def _load(name: str, path: Path):
    sys.path.insert(0, str(FOUNDRY))
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


class TestFoundryOrchestrationGodPath(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["FOUNDRY_USE_IGNITE_API"] = "false"
        os.environ.pop("PROJECT_CONNECTION_STRING", None)
        os.environ.pop("APPLICATIONINSIGHTS_CONNECTION_STRING", None)
        os.environ["FOUNDRY_BRAIN_LIVE"] = "false"
        os.environ["FOUNDRY_WORKFLOW_LIVE"] = "false"
        os.environ["MODEL_DEPLOYMENT_NAME"] = "gemini-2.5-flash"
        cls.orch = _load("foundry_orch_god", MOD_PATH)
        cls.runtime = _load("foundry_runtime_god", RUNTIME_PATH)

    def setUp(self):
        os.environ["FOUNDRY_ORCHESTRATION_ENABLED"] = "true"
        os.environ.pop("PROJECT_CONNECTION_STRING", None)
        self.runtime._READY = False
        self.runtime._TRACING_READY = False

    def test_chat_turn_offline_surfaces_error(self):
        out = self.orch.maybe_run_foundry_turn("Extrae DOC-001", language="es")
        self.assertIsNotNone(out)
        self.assertEqual(out["status"], "error")
        self.assertIn("NO LLEGÓ A FOUNDRY", out["message"])
        self.assertIn("DOC-001", out["message"])
        self.assertEqual(out["foundry_plan"]["intent"], "EXTRACT")
        self.assertFalse(out["foundry_live"])
        self.assertEqual(out["foundry_model"], "gemini-2.5-flash")
        self.assertIn("trigger:chat", " ".join(out["foundry_trace_tags"]))

    def test_post_extract_hook_offline_loud(self):
        out = self.orch.notify_foundry_after_extract(
            filename="receta.pdf",
            template_name="Medical_Prescription",
            extraction={"fields": {"diagnosis": "x"}},
            language="es",
        )
        self.assertIsNotNone(out)
        self.assertTrue(out["foundry"])
        self.assertEqual(out.get("foundry_trigger"), "chat_api_extract")
        self.assertEqual(out["status"], "error")
        self.assertIn("NO LLEGÓ A FOUNDRY", out["message"])

    def test_disabled_skips_both_hooks(self):
        os.environ["FOUNDRY_ORCHESTRATION_ENABLED"] = "false"
        os.environ.pop("PROJECT_CONNECTION_STRING", None)
        # Reset one-shot status log so enable check re-evaluates.
        self.orch._STATUS_LOGGED = False
        self.assertIsNone(self.orch.maybe_run_foundry_turn("Extrae DOC-001"))
        self.assertIsNone(
            self.orch.notify_foundry_after_extract(
                filename="a.pdf", template_name="Invoice_Standard"
            )
        )

    def test_auto_enabled_when_project_set(self):
        self.orch._STATUS_LOGGED = False
        os.environ["FOUNDRY_ORCHESTRATION_ENABLED"] = "false"
        os.environ["PROJECT_CONNECTION_STRING"] = (
            "https://example.services.ai.azure.com/api/projects/x"
        )
        try:
            self.assertTrue(self.orch.foundry_orchestration_enabled())
        finally:
            os.environ.pop("PROJECT_CONNECTION_STRING", None)
            self.orch._STATUS_LOGGED = False

    def test_default_media_agent_is_image_tab(self):
        self.assertEqual(self.runtime.MEDIA_AGENT(), "ignite-image-agent")
        self.assertIn("ignite-image-agent", self.runtime.MEDIA_AGENT_ALIASES())
        self.assertIn("ignite-media-agent", self.runtime.MEDIA_AGENT_ALIASES())

    def test_runtime_traced_orchestration_offline(self):
        result = self.runtime.run_traced_orchestration(
            "Describe MED-AUD-001", lang="es", trigger="chat"
        )
        self.assertEqual(result["plan"]["modality"], "audio")
        self.assertFalse(result["tracing_enabled"])
        self.assertFalse(result["live"])
        self.assertEqual(result["model"], "gemini-2.5-flash")
        self.assertIn("NO LLEGÓ A FOUNDRY", result["error"])
        self.assertIn("trigger:chat", result["trace_tags"])

    def test_ensure_without_project_is_false(self):
        self.assertFalse(self.runtime.ensure_agents_and_workflow())

    def test_default_model_is_gemini(self):
        self.assertEqual(self.runtime.MODEL(), "gemini-2.5-flash")

    def test_workflow_preferred_over_pipeline(self):
        """When project is set, workflow runs first under Traces."""
        calls = {"workflow": 0, "pipeline": 0}

        def fake_workflow(_text):
            calls["workflow"] += 1
            return {
                "source": "foundry_workflow",
                "workflow": "ignite-document-workflow",
                "status": "completed",
                "message": "workflow-ok",
                "trace_tags": ["source:foundry_workflow"],
            }

        def fake_pipeline(_text):
            calls["pipeline"] += 1
            return {
                "source": "foundry_agent_pipeline",
                "message": "pipeline-ok",
                "plan": {"intent": "EXTRACT"},
                "trace_tags": [],
            }

        with patch.dict(
            os.environ,
            {
                "PROJECT_CONNECTION_STRING": "https://example.services.ai.azure.com/api/projects/x",
                "APPLICATIONINSIGHTS_CONNECTION_STRING": "InstrumentationKey=test",
            },
        ), patch.object(self.runtime, "setup_tracing", return_value=True), patch.object(
            self.runtime, "ensure_agents_and_workflow", return_value=True
        ), patch.object(self.runtime, "invoke_workflow", side_effect=fake_workflow), patch.object(
            self.runtime, "invoke_agent_pipeline", side_effect=fake_pipeline
        ):
            result = self.runtime.run_traced_orchestration(
                "Extrae DOC-001", lang="es", trigger="chat"
            )

        self.assertEqual(calls["workflow"], 1)
        self.assertEqual(calls["pipeline"], 0)  # skipped when workflow has text
        self.assertEqual(result["source"], "foundry_workflow")
        self.assertTrue(result["live"])
        self.assertEqual(result["message"], "workflow-ok")
        self.assertIn("path:workflow", result["trace_tags"])


if __name__ == "__main__":
    unittest.main()
