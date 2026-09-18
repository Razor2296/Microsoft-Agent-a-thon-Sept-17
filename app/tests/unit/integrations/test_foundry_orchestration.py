"""Unit tests: Chat → Traces → auto ensure + orchestrate (offline)."""
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
        os.environ["FOUNDRY_BRAIN_LIVE"] = "false"
        os.environ["FOUNDRY_WORKFLOW_LIVE"] = "false"
        cls.orch = _load("foundry_orch_god", MOD_PATH)
        cls.runtime = _load("foundry_runtime_god", RUNTIME_PATH)

    def setUp(self):
        os.environ["FOUNDRY_ORCHESTRATION_ENABLED"] = "true"
        self.runtime._READY = False
        self.runtime._TRACING_READY = False

    def test_chat_turn_orchestrates_offline(self):
        out = self.orch.maybe_run_foundry_turn("Extrae DOC-001", language="es")
        self.assertIsNotNone(out)
        self.assertEqual(out["status"], "success")
        self.assertIn("DOC-001", out["message"])
        self.assertEqual(out["foundry_plan"]["intent"], "EXTRACT")
        self.assertIn("trigger:chat", " ".join(out["foundry_trace_tags"]))

    def test_post_extract_hook(self):
        out = self.orch.notify_foundry_after_extract(
            filename="receta.pdf",
            template_name="Medical_Prescription",
            extraction={"fields": {"diagnosis": "x"}},
            language="es",
        )
        self.assertIsNotNone(out)
        self.assertTrue(out["foundry"])
        self.assertEqual(out.get("foundry_trigger"), "chat_api_extract")

    def test_disabled_skips_both_hooks(self):
        os.environ["FOUNDRY_ORCHESTRATION_ENABLED"] = "false"
        self.assertIsNone(self.orch.maybe_run_foundry_turn("Extrae DOC-001"))
        self.assertIsNone(
            self.orch.notify_foundry_after_extract(
                filename="a.pdf", template_name="Invoice_Standard"
            )
        )

    def test_runtime_traced_orchestration_offline(self):
        result = self.runtime.run_traced_orchestration(
            "Describe MED-AUD-001", lang="es", trigger="chat"
        )
        self.assertEqual(result["plan"]["modality"], "audio")
        self.assertFalse(result["tracing_enabled"])  # no PROJECT_CONNECTION_STRING
        self.assertIn("trigger:chat", result["trace_tags"])

    def test_ensure_without_project_is_false(self):
        self.assertFalse(self.runtime.ensure_agents_and_workflow())


if __name__ == "__main__":
    unittest.main()
