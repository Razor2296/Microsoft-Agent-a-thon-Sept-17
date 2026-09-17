"""Golden-set tool tests (no Azure)."""
from __future__ import annotations

import json
import unittest

from tools import inspect_document, load_documents


class TestInspectDocument(unittest.TestCase):
    def test_known_ids(self):
        ids = {d["doc_id"] for d in load_documents()}
        self.assertEqual(ids, {"DOC-001", "DOC-002", "DOC-003"})

    def test_medical_order_fields(self):
        payload = json.loads(inspect_document("doc-001"))
        self.assertEqual(payload["kind"], "medical_order")
        self.assertEqual(payload["fields"]["diagnosis"], "Acute rhinopharyngitis")

    def test_unknown_id(self):
        payload = json.loads(inspect_document("DOC-999"))
        self.assertIn("error", payload)


if __name__ == "__main__":
    unittest.main()
