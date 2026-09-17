"""
app/tests/unit/test_coordinator.py
Unit tests for Databases/coordinator.py (Log & Session telemetry export pipeline).
"""
import json
import os
import tempfile
import pytest
from Databases.coordinator import LogExportCoordinator


class TestLogExportCoordinatorState:
    def test_load_and_save_offsets(self, tmp_path):
        state_file = str(tmp_path / "export_state.json")

        coord = LogExportCoordinator(state_file=state_file)
        assert isinstance(coord.state, dict)

        # Save state/offset
        coord.state["test_log.log"] = 1024
        coord._save_state()
        assert os.path.exists(state_file)

        # Reload coordinator
        coord2 = LogExportCoordinator(state_file=state_file)
        assert coord2.state.get("test_log.log") == 1024

    def test_get_offset_default_zero(self, tmp_path):
        state_file = str(tmp_path / "export_state.json")
        coord = LogExportCoordinator(state_file=state_file)
        assert coord.state.get("non_existent_file.log", 0) == 0


class TestLogExportCoordinatorScan:
    def test_incremental_scan_log_file(self, tmp_path):
        state_file = str(tmp_path / "export_state.json")
        log_file = str(tmp_path / "test_app.log")

        with open(log_file, "w", encoding="utf-8") as f:
            f.write("2026-07-27 10:00:00 - INFO - First line\n")
            f.write("2026-07-27 10:01:00 - ERROR - Second line\n")

        coord = LogExportCoordinator(state_file=state_file)
        assert os.path.exists(log_file)
