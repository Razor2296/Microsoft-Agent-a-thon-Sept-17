"""Golden-set tool tests (no Azure, no Ignite API network)."""
from __future__ import annotations

import json
import os
import unittest

# Force offline catalog so CI never hits Ignite API
os.environ["FOUNDRY_USE_IGNITE_API"] = "false"

from tools import FIXTURES_DIR, inspect_document, load_documents


class TestInspectDocument(unittest.TestCase):
    def test_known_ids(self):
        ids = {d["doc_id"] for d in load_documents()}
        self.assertEqual(ids, {"DOC-001", "DOC-002", "DOC-003"})

    def test_medical_order_fields(self):
        payload = json.loads(inspect_document("doc-001"))
        self.assertEqual(payload["kind"], "medical_order")
        self.assertEqual(payload["fields"]["diagnosis"], "Acute rhinopharyngitis")
        self.assertEqual(payload.get("source"), "catalog")

    def test_unknown_id(self):
        payload = json.loads(inspect_document("DOC-999"))
        self.assertIn("error", payload)

    def test_fixtures_present(self):
        for doc_id in ("DOC-001", "DOC-002", "DOC-003"):
            path = FIXTURES_DIR / f"{doc_id}.txt"
            self.assertTrue(path.is_file(), f"missing fixture {path}")


if __name__ == "__main__":
    unittest.main()
