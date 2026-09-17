import os
import re
import json
import logging
from datetime import datetime

logger = logging.getLogger("Ignite_DB_Kusto")

try:
    from azure.kusto.data import KustoConnectionStringBuilder
    from azure.kusto.data.data_format import DataFormat
    from azure.kusto.ingest import (
        BlobDescriptor,
        FileDescriptor,
        IngestionProperties,
        QueuedIngestClient,
        ReportLevel,
        ReportMethod,
    )
    KUSTO_AVAILABLE = True
except ImportError:
    KUSTO_AVAILABLE = False

LOG_LINE_REGEX = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}) - (\w+) - (.*)$")

class KustoExporter:
    """
    Kusto (Azure Data Explorer) exporter for conversation sessions and activity logs.
    """
    def __init__(self, cluster_ingest_uri=None, database=None, tenant_id=None, client_id=None, client_secret=None, use_msi=False):
        self.cluster_ingest_uri = cluster_ingest_uri or os.getenv("KUSTO_INGEST_URI")
        self.database = database or os.getenv("KUSTO_DB", "IgniteLogs")
        self.tenant_id = tenant_id or os.getenv("AZURE_TENANT_ID")
        self.client_id = client_id or os.getenv("AZURE_CLIENT_ID")
        self.client_secret = client_secret or os.getenv("AZURE_CLIENT_SECRET")
        self.use_msi = use_msi or (os.getenv("AZURE_USE_MSI", "false").lower() == "true")

        self.ingest_client = None

        if not KUSTO_AVAILABLE and self.cluster_ingest_uri:
            logger.warning("azure-kusto-data and/or azure-kusto-ingest are not installed. Kusto logging will only operate in mock/dry-run mode unless installed.")

    def _get_ingest_client(self):
        """Establishes connection to Kusto ingest service."""
        if not KUSTO_AVAILABLE:
            raise ImportError("azure-kusto-ingest is required to connect to Kusto.")

        if self.ingest_client:
            return self.ingest_client

        if not self.cluster_ingest_uri:
            raise ValueError("Kusto cluster ingest URI is not configured.")

        # Build Connection String
        if self.use_msi:
            logger.info(f"Connecting to Kusto ingest via Managed Identity: URI={self.cluster_ingest_uri}...")
            if self.client_id:
                kcsb = KustoConnectionStringBuilder.with_aad_managed_service_identity_authentication(
                    self.cluster_ingest_uri, client_id=self.client_id
                )
            else:
                kcsb = KustoConnectionStringBuilder.with_aad_managed_service_identity_authentication(
                    self.cluster_ingest_uri
                )
        elif self.client_id and self.client_secret and self.tenant_id:
            logger.info(f"Connecting to Kusto ingest via App Registration: URI={self.cluster_ingest_uri}, ClientID={self.client_id}...")
            kcsb = KustoConnectionStringBuilder.with_aad_application_key_authentication(
                self.cluster_ingest_uri,
                self.client_id,
                self.client_secret,
                self.tenant_id
            )
        else:
            # Interactive authentication fallback
            logger.info(f"Connecting to Kusto ingest via Interactive/Device authentication: URI={self.cluster_ingest_uri}...")
            kcsb = KustoConnectionStringBuilder.with_aad_device_authentication(
                self.cluster_ingest_uri
            )

        self.ingest_client = QueuedIngestClient(kcsb)
        return self.ingest_client

    def get_ddl_scripts(self):
        """
        Returns the Kusto DDL commands needed to set up tables.
        The user can execute these in their Azure Data Explorer web UI or Kusto explorer.
        """
        scripts = """
        // ----------------------------------------------------
        // KUSTO SCHEMA SETUP SCRIPTS
        // Run these queries in your Kusto Web UI / Kusto Explorer
        // ----------------------------------------------------

        // 1. Sessions Table (for chat history JSONs)
        .create table Sessions (
            SessionId: string,
            Provider: string,
            Model: string,
            CreatedAt: datetime,
            UpdatedAt: datetime,
            TokenTotal: int,
            Messages: dynamic
        )

        // 2. Activity Logs Table (for provider logger logs)
        .create table ActivityLogs (
            Provider: string,
            LogTimestamp: datetime,
            Level: string,
            Message: string
        )
        """
        return scripts

    def export_session_json(self, file_path):
        """
        Ingests a session JSON file directly into the Kusto Sessions table.
        """
        if not os.path.exists(file_path):
            logger.error(f"Session file not found: {file_path}")
            return False

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            logger.error(f"Error reading/parsing session JSON file {file_path}: {e}")
            return False

        session_id = data.get("session_id")
        provider = data.get("provider", "unknown")
        model = data.get("model", "")
        created_at_str = data.get("created_at")
        updated_at_str = data.get("updated_at")
        token_total = data.get("token_total", 0)
        messages = data.get("messages", [])

        if not session_id:
            logger.warning(f"Skipping session file {file_path} because session_id is missing.")
            return False

        # Format data as a flat record that maps to Kusto columns
        # Kusto expects dynamic array of messages directly in dynamic column
        kusto_record = {
            "SessionId": session_id,
            "Provider": provider,
            "Model": model,
            "CreatedAt": self._parse_datetime_iso(created_at_str),
            "UpdatedAt": self._parse_datetime_iso(updated_at_str),
            "TokenTotal": int(token_total),
            "Messages": messages
        }

        # Kusto ingest accepts JSON file, so we write a temporary formatted JSON file
        # containing one JSON record per line (Kusto JSON Multi-Line ingestion format)
        temp_filepath = file_path + ".kustotemp"
        try:
            with open(temp_filepath, "w", encoding="utf-8") as temp_f:
                json.dump(kusto_record, temp_f, ensure_ascii=False)
                temp_f.write("\n")
        except Exception as e:
            logger.error(f"Failed to create temporary Kusto export file: {e}")
            return False

        if not KUSTO_AVAILABLE:
            logger.info(f"Dry Run (Kusto): Prepared session record for Kusto: {session_id}")
            if os.path.exists(temp_filepath):
                os.remove(temp_filepath)
            return True

        try:
            client = self._get_ingest_client()

            # Setup Ingestion Properties
            ingestion_props = IngestionProperties(
                database=self.database,
                table="Sessions",
                data_format=DataFormat.MULTIJSON,
                report_level=ReportLevel.FailuresOnly,
                report_method=ReportMethod.Queue
            )

            client.ingest_from_file(temp_filepath, ingestion_properties=ingestion_props)
            logger.info(f"Successfully queued session {session_id} for Kusto ingestion.")
            return True
        except Exception as e:
            logger.error(f"Error ingesting session {session_id} to Kusto: {e}", exc_info=True)
            return False
        finally:
            if os.path.exists(temp_filepath):
                try:
                    os.remove(temp_filepath)
                except Exception:
                    pass

    def export_activity_log(self, file_path, provider, start_line_offset=0):
        """
        Parses log entries and ingests them into Kusto.
        Returns the number of processed records and the new line offset.
        """
        if not os.path.exists(file_path):
            logger.error(f"Activity log file not found: {file_path}")
            return 0, start_line_offset

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except Exception as e:
            logger.error(f"Error reading activity log {file_path}: {e}")
            return 0, start_line_offset

        total_lines = len(lines)
        if start_line_offset >= total_lines:
            return 0, total_lines

        new_lines = lines[start_line_offset:]
        parsed_records = []
        for line in new_lines:
            line = line.strip()
            if not line:
                continue

            match = LOG_LINE_REGEX.match(line)
            if match:
                time_str, level, msg = match.groups()
                try:
                    log_timestamp = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S,%f").isoformat()
                except ValueError:
                    log_timestamp = datetime.now().isoformat()

                parsed_records.append({
                    "Provider": provider,
                    "LogTimestamp": log_timestamp,
                    "Level": level,
                    "Message": msg
                })
            else:
                if parsed_records:
                    parsed_records[-1]["Message"] = parsed_records[-1]["Message"] + "\n" + line
                else:
                    parsed_records.append({
                        "Provider": provider,
                        "LogTimestamp": datetime.now().isoformat(),
                        "Level": "INFO",
                        "Message": line
                    })

        if not parsed_records:
            return 0, total_lines

        # Write parsed records to a temp Multi-JSON file for Kusto ingestion
        temp_filepath = file_path + ".kustologtemp"
        try:
            with open(temp_filepath, "w", encoding="utf-8") as temp_f:
                for record in parsed_records:
                    json.dump(record, temp_f, ensure_ascii=False)
                    temp_f.write("\n")
        except Exception as e:
            logger.error(f"Failed to create temporary Kusto log export file: {e}")
            return 0, start_line_offset

        if not KUSTO_AVAILABLE:
            logger.info(f"Dry Run (Kusto): Prepared {len(parsed_records)} log entries for {provider}.")
            if os.path.exists(temp_filepath):
                os.remove(temp_filepath)
            return len(parsed_records), total_lines

        try:
            client = self._get_ingest_client()

            ingestion_props = IngestionProperties(
                database=self.database,
                table="ActivityLogs",
                data_format=DataFormat.MULTIJSON,
                report_level=ReportLevel.FailuresOnly,
                report_method=ReportMethod.Queue
            )

            client.ingest_from_file(temp_filepath, ingestion_properties=ingestion_props)
            logger.info(f"Successfully queued {len(parsed_records)} activity logs for {provider} to Kusto.")
            return len(parsed_records), total_lines
        except Exception as e:
            logger.error(f"Error ingesting logs for {provider} to Kusto: {e}", exc_info=True)
            return 0, start_line_offset
        finally:
            if os.path.exists(temp_filepath):
                try:
                    os.remove(temp_filepath)
                except Exception:
                    pass

    def _parse_datetime_iso(self, dt_str):
        """Parses local datetime format to Kusto-compatible ISO format."""
        if not dt_str:
            return datetime.now().isoformat()

        formats = ["%Y-%m-%d %I:%M:%S %p", "%Y-%m-%d %I:%M %p", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"]
        for fmt in formats:
            try:
                return datetime.strptime(dt_str, fmt).isoformat()
            except ValueError:
                continue
        return datetime.now().isoformat()
