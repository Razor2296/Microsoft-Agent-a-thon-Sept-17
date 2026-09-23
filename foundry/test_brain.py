"""Offline tests for Foundry brain / plan schema / media tools (no Azure)."""
from __future__ import annotations

import json
import os
import unittest

os.environ["FOUNDRY_USE_IGNITE_API"] = "false"
os.environ.pop("PROJECT_CONNECTION_STRING", None)

from brain import detect_modality, execute_plan, heuristic_plan, run_turn
from media_tools import describe_media, load_media
from plan_schema import parse_plan, validate_plan
from tools import inspect_document


class TestPlanSchema(unittest.TestCase):
    def test_parse_fenced_json(self):
        raw = """Here is the plan:
```json
{"modality":"document","intent":"EXTRACT","doc_id":"DOC-001","steps":[{"action":"inspect_document","agent":"ignite-document-agent","args":{"doc_id":"DOC-001"}}],"user_message_es":"","user_message_en":"","trace_tags":["modality:document","intent:EXTRACT"]}
```
"""
        plan = parse_plan(raw)
        self.assertEqual(plan["intent"], "EXTRACT")
        self.assertEqual(plan["doc_id"], "DOC-001")

    def test_validate_fills_default_steps(self):
        plan = validate_plan({"modality": "document", "intent": "EXTRACT", "doc_id": "DOC-002"})
        actions = [s["action"] for s in plan["steps"]]
        self.assertIn("inspect_document", actions)


class TestBrain(unittest.TestCase):
    def test_extract_doc001(self):
        result = run_turn("Extrae la receta DOC-001", lang="es", use_foundry=False)
        self.assertEqual(result["plan"]["intent"], "EXTRACT")
        self.assertIn("DOC-001", result["final_user_message"])
        self.assertIn("modality:document", result["trace_tags"])
        fields = result["tool_results"][0]["result"]["fields"]
        self.assertEqual(fields["diagnosis"], "Acute rhinopharyngitis")

    def test_media_image(self):
        result = run_turn("Describe la foto MED-IMG-001", lang="es", use_foundry=False)
        self.assertEqual(result["plan"]["intent"], "MEDIA_DESCRIBE")
        self.assertEqual(result["plan"]["modality"], "image")
        self.assertIn("MED-IMG-001", result["final_user_message"])

    def test_media_audio(self):
        result = run_turn("Resume el audio MED-AUD-001", lang="es", use_foundry=False)
        self.assertEqual(result["plan"]["modality"], "audio")

    def test_export(self):
        result = run_turn("Exporta DOC-002 a Excel", lang="es", use_foundry=False)
        self.assertEqual(result["plan"]["intent"], "EXPORT")

    def test_clarify(self):
        result = run_turn("Hola", lang="es", use_foundry=False)
        self.assertEqual(result["plan"]["intent"], "CLARIFY")

    def test_generate_image_plan(self):
        result = run_turn("Genera una imagen de un gato", lang="es", use_foundry=False)
        self.assertEqual(result["plan"]["intent"], "GENERATE_IMAGE")
        self.assertEqual(result["plan"]["modality"], "image")
        self.assertEqual(result["plan"]["steps"][0]["agent"], "ignite-image-agent")
        self.assertIn("intent:GENERATE_IMAGE", result["trace_tags"])

    def test_generate_audio_plan(self):
        result = run_turn("Crea un sonido de lluvia", lang="es", use_foundry=False)
        self.assertEqual(result["plan"]["intent"], "GENERATE_AUDIO")
        self.assertEqual(result["plan"]["modality"], "audio")
        self.assertEqual(result["plan"]["steps"][0]["agent"], "ignite-audio-agent")

    def test_generate_image_not_confused_with_describe(self):
        """'Genera una imagen' must not route to MEDIA_DESCRIBE / MED-IMG fixtures."""
        plan = heuristic_plan("Genera una imagen de un atardecer")
        self.assertEqual(plan["intent"], "GENERATE_IMAGE")
        self.assertNotEqual(plan["intent"], "MEDIA_DESCRIBE")

    def test_detect_modality(self):
        self.assertEqual(detect_modality("ver el video MED-VID-001"), "video")
        self.assertEqual(detect_modality("extrae DOC-003"), "document")


class TestMediaCatalog(unittest.TestCase):
    def test_ids(self):
        ids = {m["media_id"] for m in load_media()}
        self.assertEqual(ids, {"MED-IMG-001", "MED-AUD-001", "MED-VID-001"})

    def test_describe(self):
        payload = json.loads(describe_media("med-img-001"))
        self.assertEqual(payload["modality"], "image")


class TestInspectStillWorks(unittest.TestCase):
    def test_doc(self):
        payload = json.loads(inspect_document("DOC-001"))
        self.assertEqual(payload.get("source"), "catalog")


class TestHeuristicExecuteRoundtrip(unittest.TestCase):
    def test_execute_matches_plan(self):
        plan = heuristic_plan("Extrae DOC-002")
        out = execute_plan(plan, lang="en")
        self.assertIn("DOC-002", out["final_user_message_en"])


if __name__ == "__main__":
    unittest.main()
