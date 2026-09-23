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
        self.runtime._READY = False
        self.runtime._TRACING_READY = False
        self.orch._STATUS_LOGGED = False
        # Block live Foundry/.env from flipping unit tests into Azure calls.
        self._env_patch = patch.dict(
            os.environ,
            {
                "FOUNDRY_ORCHESTRATION_ENABLED": "true",
                "FOUNDRY_USE_IGNITE_API": "false",
                "FOUNDRY_BRAIN_LIVE": "false",
                "FOUNDRY_WORKFLOW_LIVE": "false",
                "FOUNDRY_TRACE_ASYNC": "false",  # sync in unit tests
                "MODEL_DEPLOYMENT_NAME": "gemini-2.5-flash",
                "PROJECT_CONNECTION_STRING": "",
                "APPLICATIONINSIGHTS_CONNECTION_STRING": "",
            },
            clear=False,
        )
        self._env_patch.start()
        self._load_env_patch = patch.object(self.orch, "_load_foundry_env", lambda: None)
        self._load_env_patch.start()

    def tearDown(self):
        self._load_env_patch.stop()
        self._env_patch.stop()
        self.orch._STATUS_LOGGED = False

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
        with patch.dict(
            os.environ,
            {
                "FOUNDRY_ORCHESTRATION_ENABLED": "false",
                "PROJECT_CONNECTION_STRING": (
                    "https://example.services.ai.azure.com/api/projects/x"
                ),
            },
            clear=False,
        ):
            self.assertTrue(self.orch.foundry_orchestration_enabled())
        self.orch._STATUS_LOGGED = False

    def test_canonical_specialists(self):
        from agent_names import all_prompt_agents, specialist_for_media_id, specialist_for_modality

        names = all_prompt_agents()
        self.assertEqual(
            names,
            [
                "ignite-orchestrator-agent",
                "ignite-document-agent",
                "ignite-image-agent",
                "ignite-audio-agent",
                "ignite-video-agent",
            ],
        )
        self.assertEqual(specialist_for_modality("image"), "ignite-image-agent")
        self.assertEqual(specialist_for_modality("audio"), "ignite-audio-agent")
        self.assertEqual(specialist_for_modality("video"), "ignite-video-agent")
        self.assertEqual(specialist_for_media_id("MED-AUD-001"), "ignite-audio-agent")
        self.assertEqual(self.runtime.IMAGE_AGENT(), "ignite-image-agent")
        self.assertEqual(self.runtime.MEDIA_AGENT(), "ignite-image-agent")  # legacy alias

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

    def test_should_handle_mic_without_files_or_extract_hints(self):
        """After STT, Voice_Message is stripped — from_mic alone must still hit Foundry."""
        self.assertTrue(
            self.orch.should_handle_turn("Hola, ¿cómo estás?", from_mic=True)
        )
        # Contest default: every Chat turn is in scope when orchestration is on.
        self.assertTrue(
            self.orch.should_handle_turn("Hola, ¿cómo estás?", from_mic=False)
        )
        with patch.dict(os.environ, {"FOUNDRY_ORCHESTRATION_ALWAYS": "false"}, clear=False):
            self.assertFalse(
                self.orch.should_handle_turn("Hola, ¿cómo estás?", from_mic=False)
            )
            self.assertTrue(
                self.orch.should_handle_turn(
                    "",
                    [{"name": "Voice_Message_10-00.webm", "mime_type": "audio/webm"}],
                )
            )
            self.assertTrue(
                self.orch.should_handle_turn("Genera una imagen de un gato")
            )

    def test_casual_mic_traces_but_keeps_provider_reply(self):
        """Mic chat must arm Traces (chat_mic) without stealing the TTS bubble."""
        calls = {"n": 0}

        def fake_run(text, files=None, *, language=None, trigger="chat"):
            calls["n"] += 1
            calls["trigger"] = trigger
            calls["text"] = text
            return {
                "live": True,
                "source": "foundry_workflow",
                "message": "foundry-mic",
                "plan": {"modality": "audio", "intent": "ANSWER", "steps": []},
                "trace_tags": [f"trigger:{trigger}", "modality:audio"],
                "tracing_enabled": True,
                "error": None,
                "model": "gemini-2.5-flash",
            }

        with patch.object(self.orch, "run_foundry_turn", side_effect=fake_run):
            out = self.orch.maybe_run_foundry_turn(
                "Hola, cuéntame un chiste", language="es", from_mic=True
            )
        self.assertIsNone(out)  # keep provider LLM + TTS
        self.assertEqual(calls["n"], 1)
        self.assertEqual(calls["trigger"], "chat_mic")
        self.assertIn("channel=audio", calls["text"])
        self.assertIn("from_mic=true", calls["text"])

    def test_generate_image_traces_keeps_chat_bytes(self):
        calls = {"n": 0}

        def fake_run(text, files=None, *, language=None, trigger="chat"):
            calls["n"] += 1
            calls["trigger"] = trigger
            calls["text"] = text
            return {
                "live": True,
                "source": "foundry_workflow",
                "message": "planned",
                "plan": {"modality": "image", "intent": "GENERATE_IMAGE", "steps": []},
                "trace_tags": [f"trigger:{trigger}"],
                "tracing_enabled": True,
                "error": None,
                "model": "gemini-2.5-flash",
            }

        with patch.object(self.orch, "run_foundry_turn", side_effect=fake_run):
            out = self.orch.maybe_run_foundry_turn(
                "Genera una imagen de un atardecer", language="es"
            )
        self.assertIsNone(out)  # Chat still generates image bytes
        self.assertEqual(calls["trigger"], "chat_generate_image")
        self.assertIn("GENERATE_IMAGE", calls["text"])

    def test_notify_foundry_generation_audio(self):
        with patch.object(
            self.orch,
            "run_foundry_turn",
            return_value={
                "live": True,
                "plan": {"intent": "GENERATE_AUDIO"},
                "trace_tags": ["trigger:chat_generate_audio"],
                "error": None,
            },
        ) as mocked:
            out = self.orch.notify_foundry_generation(
                kind="audio", prompt="Crea un sonido de lluvia"
            )
        self.assertIsNotNone(out)
        self.assertTrue(out["foundry"])
        self.assertEqual(out["foundry_trigger"], "chat_generate_audio")
        mocked.assert_called_once()

    def test_non_intercept_can_spawn_async_trace(self):
        spawned = {"n": 0}

        def fake_spawn(*_a, **_k):
            spawned["n"] += 1

        with patch.dict(os.environ, {"FOUNDRY_TRACE_ASYNC": "true"}, clear=False), patch.object(
            self.orch, "_spawn_foundry_trace", side_effect=fake_spawn
        ), patch.object(self.orch, "run_foundry_turn") as run_mock:
            out = self.orch.maybe_run_foundry_turn(
                "Genera una imagen de un perro", language="es"
            )
        self.assertIsNone(out)
        self.assertEqual(spawned["n"], 1)
        run_mock.assert_not_called()

    def test_mic_extract_still_intercepts_bubble(self):
        """Spoken 'Extrae DOC-001' still returns Foundry footer (Architect demo)."""
        with patch.object(
            self.orch,
            "run_foundry_turn",
            return_value={
                "live": False,
                "source": "offline",
                "message": "plan-ok",
                "plan": {
                    "modality": "document",
                    "intent": "EXTRACT",
                    "steps": [{"action": "inspect_document", "agent": "ignite-document-agent"}],
                },
                "trace_tags": ["trigger:chat_mic"],
                "tracing_enabled": False,
                "error": "NO LLEGÓ A FOUNDRY (offline test)",
                "model": "gemini-2.5-flash",
                "trigger": "chat_mic",
            },
        ):
            out = self.orch.maybe_run_foundry_turn(
                "Extrae DOC-001", language="es", from_mic=True
            )
        self.assertIsNotNone(out)
        self.assertTrue(out["foundry"])
        self.assertEqual(out.get("foundry_plan", {}).get("intent"), "EXTRACT")
        self.assertIn("Foundry orchestration", out["message"])
        self.assertIn("trigger:chat_mic", " ".join(out.get("foundry_trace_tags") or []))


if __name__ == "__main__":
    unittest.main()
