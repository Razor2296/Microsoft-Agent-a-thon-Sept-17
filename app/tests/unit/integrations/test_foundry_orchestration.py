"""Unit tests for Foundry orchestration bridge (offline, no Azure / no pydantic)."""
from __future__ import annotations

import importlib.util
import os
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
FOUNDRY = REPO / "foundry"
MOD_PATH = REPO / "app" / "backend" / "integrations" / "foundry_orchestration.py"


def _load_mod():
    sys.path.insert(0, str(FOUNDRY))
    spec = importlib.util.spec_from_file_location("foundry_orchestration_under_test", MOD_PATH)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


class TestFoundryOrchestration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["FOUNDRY_USE_IGNITE_API"] = "false"
        os.environ.pop("PROJECT_CONNECTION_STRING", None)
        os.environ["FOUNDRY_BRAIN_LIVE"] = "false"
        os.environ["FOUNDRY_WORKFLOW_LIVE"] = "false"
        cls.mod = _load_mod()

    def setUp(self):
        os.environ["FOUNDRY_ORCHESTRATION_ENABLED"] = "true"

    def test_disabled_returns_none(self):
        os.environ["FOUNDRY_ORCHESTRATION_ENABLED"] = "false"
        self.assertIsNone(self.mod.maybe_run_foundry_turn("Extrae DOC-001"))

    def test_extract_routes_to_brain(self):
        out = self.mod.maybe_run_foundry_turn("Extrae la receta DOC-001", language="es-MX")
        self.assertIsNotNone(out)
        self.assertEqual(out["status"], "success")
        self.assertTrue(out["foundry"])
        self.assertIn("DOC-001", out["message"])
        self.assertEqual(out["foundry_plan"]["intent"], "EXTRACT")

    def test_media_routes(self):
        out = self.mod.maybe_run_foundry_turn("Describe MED-IMG-001", language="es")
        self.assertIsNotNone(out)
        self.assertEqual(out["foundry_plan"]["modality"], "image")

    def test_plain_chat_skips_foundry(self):
        self.assertIsNone(self.mod.maybe_run_foundry_turn("hola, cómo estás?"))

    def test_files_force_route(self):
        self.assertTrue(self.mod.should_handle_turn("mira esto", [{"name": "scan.pdf"}]))


if __name__ == "__main__":
    unittest.main()
