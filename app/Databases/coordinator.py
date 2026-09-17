import sys
import os
import glob
import json
import logging
from datetime import datetime
from dotenv import load_dotenv

# For user resource files (.env, logs, Databases, assets), use execution folder if frozen
if getattr(sys, 'frozen', False):
    _exe_dir = os.path.dirname(sys.executable)
    if os.path.exists(os.path.join(_exe_dir, '.env')):
        app_root = _exe_dir
    elif os.path.exists(os.path.join(os.path.dirname(_exe_dir), '.env')):
        app_root = os.path.dirname(_exe_dir)
    else:
        app_root = _exe_dir
else:
    app_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Load environment variables from .env
env_path = os.path.join(app_root, '.env')
load_dotenv(dotenv_path=env_path, override=True)

try:
    from .sql_server import SQLServerExporter
    from .kusto import KustoExporter
except (ImportError, ValueError):
    from Databases.sql_server import SQLServerExporter
    from Databases.kusto import KustoExporter

logger = logging.getLogger("Ignite_DB_Coordinator")

class LogExportCoordinator:
    """
    Coordinates log exports from the local filesystem to SQL Server and Azure Kusto.
    Maintains a tracking state file to avoid duplicating work.
    """
    def __init__(self, log_dir=None, state_file=None, sql_exporter=None, kusto_exporter=None):
        current_dir = os.path.dirname(os.path.abspath(__file__))
        app_dir = os.path.dirname(current_dir)

        self.log_dir = log_dir or os.path.join(app_dir, "log")
        self.state_file = state_file or os.path.join(current_dir, "export_state.json")

        self.sql_exporter = sql_exporter or SQLServerExporter()
        self.kusto_exporter = kusto_exporter or KustoExporter()

        self.state = {
            "processed_sessions": {},  # filepath -> last_modified_timestamp
            "processed_logs": {}       # filepath -> last_processed_line_offset
        }

        self._load_state()

    def _load_state(self):
        """Loads processed state from disk."""
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, "r", encoding="utf-8") as f:
                    self.state = json.load(f)
                if "processed_sessions" not in self.state:
                    self.state["processed_sessions"] = {}
                if "processed_logs" not in self.state:
                    self.state["processed_logs"] = {}
                logger.info(f"Loaded database export state from {self.state_file}")
            except Exception as e:
                logger.error(f"Failed to load state file {self.state_file}: {e}")

    def _save_state(self):
        """Saves processed state to disk."""
        try:
            with open(self.state_file, "w", encoding="utf-8") as f:
                json.dump(self.state, f, ensure_ascii=False, indent=2)
            logger.info("Saved database export state.")
        except Exception as e:
            logger.error(f"Failed to write state file {self.state_file}: {e}")

    def run_export(self, export_to_sql=True, export_to_kusto=True):
        """
        Scans all logs and session records recursively, ingests new or updated files,
        and saves progress.
        """
        logger.info("Starting Log Database Export...")

        if not os.path.exists(self.log_dir):
            logger.error(f"Log directory {self.log_dir} does not exist. Aborting.")
            return False

        # Initialize schemas
        if export_to_sql:
            try:
                self.sql_exporter.initialize_schema()
            except Exception as e:
                logger.error(f"Failed to initialize SQL Server schema during export: {e}")

        # Note: Kusto tables are usually pre-created, but we print/log the DDL for the user
        if export_to_kusto:
            logger.info("Ensure the following Kusto schemas exist before running:\n" + self.kusto_exporter.get_ddl_scripts())

        # 1. Export Sessions
        self._export_all_sessions(export_to_sql, export_to_kusto)

        # 2. Export Activity Logs
        self._export_all_activity_logs(export_to_sql, export_to_kusto)

        # Save state
        self._save_state()
        logger.info("Log Database Export run completed successfully.")
        return True

    def _export_all_sessions(self, to_sql, to_kusto):
        """Finds and ingests session JSON files recursively."""
        # Find all JSON files in log directory and its provider subdirectories
        search_pattern = os.path.join(self.log_dir, "**", "*.json")
        json_files = glob.glob(search_pattern, recursive=True)

        logger.info(f"Found {len(json_files)} session JSON files to analyze.")

        for file_path in json_files:
            abs_path = os.path.abspath(file_path)

            # Skip temp files
            if ".kustotemp" in abs_path:
                continue

            try:
                mtime = os.path.getmtime(abs_path)
                mtime_str = datetime.fromtimestamp(mtime).isoformat()
            except Exception:
                mtime_str = ""

            # Check if file has been modified since last upload
            last_known_mtime = self.state["processed_sessions"].get(abs_path)
            if last_known_mtime == mtime_str and last_known_mtime:
                # Already processed and unmodified
                continue

            logger.info(f"Processing session file: {abs_path}")

            sql_success = True
            kusto_success = True

            if to_sql:
                try:
                    sql_success = self.sql_exporter.export_session_json(abs_path)
                except Exception as e:
                    logger.error(f"SQL Server ingestion failed for {abs_path}: {e}")
                    sql_success = False

            if to_kusto:
                try:
                    kusto_success = self.kusto_exporter.export_session_json(abs_path)
                except Exception as e:
                    logger.error(f"Kusto ingestion failed for {abs_path}: {e}")
                    kusto_success = False

            # If both exports (or whichever were selected) succeeded, mark file as processed
            if (not to_sql or sql_success) and (not to_kusto or kusto_success):
                self.state["processed_sessions"][abs_path] = mtime_str

    def _export_all_activity_logs(self, to_sql, to_kusto):
        """Finds and ingests provider activity log files."""
        # Provider names list
        providers = ["gemini", "deepseek", "openai", "anthropic", "perplexity", "grok", "alibabacloud"]

        # We search both layouts:
        # A: Root-level log/{provider}.log
        # B: Reorganized log/{provider}/Activity/*.log

        log_targets = []  # tuple of (file_path, provider_name)

        for prov in providers:
            # Layout A check
            root_log = os.path.join(self.log_dir, f"{prov}.log")
            if os.path.exists(root_log):
                log_targets.append((os.path.abspath(root_log), prov))

            # Layout B check
            sub_log_pattern = os.path.join(self.log_dir, prov, "Activity", "*.log")
            for sub_log in glob.glob(sub_log_pattern):
                log_targets.append((os.path.abspath(sub_log), prov))

        # Also search for any general activity log directories we might have missed
        # (excluding root app.log or pywebview_api.log or base_processor.log unless explicitly desired)
        for log_file in glob.glob(os.path.join(self.log_dir, "**", "*.log"), recursive=True):
            abs_path = os.path.abspath(log_file)
            basename = os.path.basename(abs_path)

            # Ignore pywebview_api.log and base_processor.log or app.log as requested
            if basename in ["pywebview_api.log", "app.log", "base_processor.log", "launcher_webview.log"]:
                continue

            # Avoid duplicating files already added
            if any(t[0] == abs_path for t in log_targets):
                continue

            # Deduce provider name from folder structure or filename
            parts = abs_path.split(os.sep)
            # Check if parent is Activity and grandparent is provider
            if len(parts) >= 3 and parts[-2].lower() == "activity":
                provider_name = parts[-3]
            else:
                provider_name = os.path.splitext(basename)[0]

            log_targets.append((abs_path, provider_name))

        logger.info(f"Found {len(log_targets)} activity log files to analyze.")

        for abs_path, provider in log_targets:
            if ".kustologtemp" in abs_path:
                continue

            last_offset = self.state["processed_logs"].get(abs_path, 0)

            # If the file size is smaller than the offset, it was likely cleared/rotated
            try:
                with open(abs_path, "r", encoding="utf-8") as f:
                    current_line_count = len(f.readlines())
            except Exception:
                current_line_count = 0

            if current_line_count < last_offset:
                logger.info(f"Log file {abs_path} appears to have been rotated. Resetting line offset from {last_offset} to 0.")
                last_offset = 0

            if current_line_count == last_offset:
                # No new log lines to ingest
                continue

            logger.info(f"Processing new log lines in {abs_path} from line {last_offset} (total lines: {current_line_count})")

            sql_processed = 0
            kusto_processed = 0

            new_offset_sql = last_offset
            new_offset_kusto = last_offset

            if to_sql:
                try:
                    sql_processed, new_offset_sql = self.sql_exporter.export_activity_log(abs_path, provider, last_offset)
                except Exception as e:
                    logger.error(f"SQL Server log ingestion failed for {abs_path}: {e}")
                    sql_processed = 0
                    new_offset_sql = last_offset

            if to_kusto:
                try:
                    kusto_processed, new_offset_kusto = self.kusto_exporter.export_activity_log(abs_path, provider, last_offset)
                except Exception as e:
                    logger.error(f"Kusto log ingestion failed for {abs_path}: {e}")
                    kusto_processed = 0
                    new_offset_kusto = last_offset

            # Update offset in state to the lowest successful offset (or the only one that was run)
            if to_sql and to_kusto:
                next_offset = min(new_offset_sql, new_offset_kusto)
            elif to_sql:
                next_offset = new_offset_sql
            else:
                next_offset = new_offset_kusto

            self.state["processed_logs"][abs_path] = next_offset

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    coordinator = LogExportCoordinator()
    coordinator.run_export(export_to_sql=True, export_to_kusto=False)
