import os
import re
import json
import logging
from datetime import datetime

logger = logging.getLogger("Ignite_DB_SQLServer")

try:
    import pyodbc
    PYODBC_AVAILABLE = True
except ImportError:
    PYODBC_AVAILABLE = False
    logger.warning("pyodbc is not installed. SQL Server logging will only operate in mock/dry-run mode unless installed.")

# Regex to parse python logging asctime format: YYYY-MM-DD HH:MM:SS,mmm
LOG_LINE_REGEX = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}) - (\w+) - (.*)$")

class SQLServerExporter:
    """
    SQL Server database exporter for conversation sessions and activity logs.
    """
    def __init__(self, server=None, database=None, username=None, password=None, connection_string=None):
        self.server = server or os.getenv("SQL_SERVER_HOST", "localhost")
        self.database = database or os.getenv("SQL_SERVER_DB", "IgniteLogs")
        self.username = username or os.getenv("SQL_SERVER_USER")
        self.password = password or os.getenv("SQL_SERVER_PWD")
        self.connection_string = connection_string or os.getenv("SQL_SERVER_CONN_STR")

        self.conn = None

    def _get_connection(self):
        """Establishes connection to SQL Server database."""
        if not PYODBC_AVAILABLE:
            raise ImportError("pyodbc is required to connect to SQL Server.")

        if self.conn:
            try:
                # Test connection is alive
                self.conn.cursor()
                return self.conn
            except Exception:
                self.conn = None

        if self.connection_string:
            logger.info("Connecting to SQL Server via Connection String...")
            conn_str = self.connection_string
            if "driver=" not in conn_str.lower():
                conn_str = f"DRIVER={{ODBC Driver 17 for SQL Server}};{conn_str}"

            # Map ADO.NET parameter names to ODBC equivalents if driver was added
            if "server=" not in conn_str.lower() and "data source=" in conn_str.lower():
                conn_str = conn_str.replace("Data Source=", "Server=")
            if "database=" not in conn_str.lower() and "initial catalog=" in conn_str.lower():
                conn_str = conn_str.replace("Initial Catalog=", "Database=")
            if "uid=" not in conn_str.lower() and "user id=" in conn_str.lower():
                conn_str = conn_str.replace("User ID=", "Uid=")
            if "pwd=" not in conn_str.lower() and "password=" in conn_str.lower():
                conn_str = conn_str.replace("Password=", "Pwd=")

            # If password is not in connection string but self.password is available, append it
            if "pwd=" not in conn_str.lower() and self.password:
                conn_str += f";Pwd={self.password}"

            # Map ADO.NET booleans (True/False) to ODBC booleans (yes/no)
            conn_str = re.sub(r'(?i)encrypt\s*=\s*true', 'Encrypt=yes', conn_str)
            conn_str = re.sub(r'(?i)encrypt\s*=\s*false', 'Encrypt=no', conn_str)
            conn_str = re.sub(r'(?i)trustservercertificate\s*=\s*true', 'TrustServerCertificate=yes', conn_str)
            conn_str = re.sub(r'(?i)trustservercertificate\s*=\s*false', 'TrustServerCertificate=no', conn_str)

            # Map Application Name to APP
            if "app=" not in conn_str.lower() and "application name=" in conn_str.lower():
                conn_str = conn_str.replace("Application Name=", "APP=")

            # Filter out non-ODBC parameters to prevent "Invalid connection string attribute"
            parts = conn_str.split(';')
            clean_parts = []
            allowed_keys = {
                "driver", "server", "database", "uid", "pwd",
                "trusted_connection", "encrypt", "trustservercertificate",
                "app", "wsid", "port"
            }
            for part in parts:
                part = part.strip()
                if not part:
                    continue
                if '=' in part:
                    key, val = part.split('=', 1)
                    key_strip = key.strip()
                    val_strip = val.strip()
                    if key_strip.lower() in allowed_keys:
                        clean_parts.append(f"{key_strip}={val_strip}")
            conn_str = ';'.join(clean_parts)

            try:
                self.conn = pyodbc.connect(conn_str)
                logger.info("Successfully connected using connection string.")
                return self.conn
            except Exception as e1:
                logger.warning(f"Connection with default driver failed: {e1}. Trying fallback drivers and authentication methods...")
                # We will try both SQL Auth and Windows Auth (Trusted Connection) fallbacks for each driver
                for driver in ["{ODBC Driver 18 for SQL Server}", "{ODBC Driver 17 for SQL Server}", "{SQL Server}", "{SQL Server Native Client 11.0}"]:
                    # Try 1: with SQL Authentication
                    try:
                        if "driver=" in conn_str.lower():
                            alt_conn_str = re.sub(r'(?i)driver=\{[^}]+\}', f'DRIVER={driver}', conn_str)
                        else:
                            alt_conn_str = f"DRIVER={driver};{conn_str}"

                        # If driver 18 is used, handle certificate trust
                        if "18" in driver and "trustservercertificate=" not in alt_conn_str.lower():
                            alt_conn_str += ";TrustServerCertificate=yes;"

                        # If legacy drivers are used, remove Encrypt and TrustServerCertificate to prevent errors
                        if "sql server" in driver.lower() and "odbc driver" not in driver.lower():
                            alt_conn_str = re.sub(r'(?i)encrypt\s*=\s*\w+;?', '', alt_conn_str)
                            alt_conn_str = re.sub(r'(?i)trustservercertificate\s*=\s*\w+;?', '', alt_conn_str)

                        self.conn = pyodbc.connect(alt_conn_str)
                        logger.info(f"Successfully connected using SQL Authentication and driver: {driver}")
                        return self.conn
                    except Exception as e_alt:
                        logger.warning(f"Driver {driver} SQL Auth failed: {e_alt}")

                    # Try 2: with Windows Authentication (Trusted Connection) fallback
                    try:
                        if "driver=" in conn_str.lower():
                            alt_conn_str = re.sub(r'(?i)driver=\{[^}]+\}', f'DRIVER={driver}', conn_str)
                        else:
                            alt_conn_str = f"DRIVER={driver};{conn_str}"

                        if "18" in driver and "trustservercertificate=" not in alt_conn_str.lower():
                            alt_conn_str += ";TrustServerCertificate=yes;"
                        if "sql server" in driver.lower() and "odbc driver" not in driver.lower():
                            alt_conn_str = re.sub(r'(?i)encrypt\s*=\s*\w+;?', '', alt_conn_str)
                            alt_conn_str = re.sub(r'(?i)trustservercertificate\s*=\s*\w+;?', '', alt_conn_str)

                        # Strip Uid/Pwd and replace with Trusted_Connection=yes
                        trust_conn_str = re.sub(r'(?i)uid\s*=\s*[^;]+;?', '', alt_conn_str)
                        trust_conn_str = re.sub(r'(?i)pwd\s*=\s*[^;]+;?', '', trust_conn_str)
                        if "trusted_connection=" not in trust_conn_str.lower():
                            trust_conn_str += ";Trusted_Connection=yes;"

                        self.conn = pyodbc.connect(trust_conn_str)
                        logger.info(f"Successfully connected using Windows Authentication (Trusted Connection) fallback and driver: {driver}")
                        return self.conn
                    except Exception as e_trust:
                        logger.warning(f"Driver {driver} Windows Auth fallback failed: {e_trust}")
                raise e1
        else:
            logger.info(f"Connecting to SQL Server: Host={self.server}, DB={self.database}...")
            drivers = ["{ODBC Driver 17 for SQL Server}", "{ODBC Driver 18 for SQL Server}", "{SQL Server}", "{SQL Server Native Client 11.0}"]
            last_err = None
            for driver in drivers:
                try:
                    if self.username and self.password:
                        conn_str = (
                            f"DRIVER={driver};"
                            f"SERVER={self.server};"
                            f"DATABASE={self.database};"
                            f"UID={self.username};"
                            f"PWD={self.password};"
                        )
                    else:
                        conn_str = (
                            f"DRIVER={driver};"
                            f"SERVER={self.server};"
                            f"DATABASE={self.database};"
                            f"Trusted_Connection=yes;"
                        )
                    if "18" in driver:
                        conn_str += ";TrustServerCertificate=yes;Encrypt=optional;"

                    self.conn = pyodbc.connect(conn_str)
                    logger.info(f"Connected successfully using {driver}")
                    return self.conn
                except Exception as e:
                    last_err = e
                    logger.warning(f"Failed to connect using {driver}: {e}")
            if last_err:
                raise last_err

        if self.conn is None:
            raise ConnectionError("Failed to establish a connection to SQL Server.")
        return self.conn

    def initialize_schema(self):
        """Creates the required tables in SQL Server if they do not exist."""
        if not PYODBC_AVAILABLE:
            logger.warning("Dry Run: Schema initialization skipped (pyodbc not installed).")
            return False

        # Drop old tables if they exist with the old schema (checking for old columns)
        drop_old_schema = """
        IF EXISTS (SELECT * FROM sysobjects WHERE name='messages' AND xtype='U')
        BEGIN
            IF COL_LENGTH('messages', 'role') IS NOT NULL OR COL_LENGTH('messages', 'session_id') IS NOT NULL
                DROP TABLE messages;
        END

        IF EXISTS (SELECT * FROM sysobjects WHERE name='sessions' AND xtype='U')
        BEGIN
            IF COL_LENGTH('sessions', 'provider') IS NOT NULL
                DROP TABLE sessions;
        END
        """

        create_sessions_table = """
        IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='sessions' AND xtype='U')
        CREATE TABLE sessions (
            session_key SMALLINT IDENTITY(1,1) PRIMARY KEY,
            session_id NVARCHAR(4000) NOT NULL,
            session_provider VARCHAR(255) NOT NULL,
            session_model VARCHAR(255) NOT NULL,
            session_created_at DATETIME NOT NULL,
            session_updated_at DATETIME NOT NULL,
            session_token_total INT NOT NULL DEFAULT 0,
            CreationDate DATETIME NOT NULL DEFAULT GETDATE(),
            LastUpdate DATETIME NOT NULL DEFAULT GETDATE()
        );
        """

        alter_sessions_table = """
        IF EXISTS (SELECT * FROM sysobjects WHERE name='sessions' AND xtype='U')
        BEGIN
            IF COL_LENGTH('sessions', 'session_provider') IS NOT NULL
                ALTER TABLE sessions ALTER COLUMN session_provider VARCHAR(255) NOT NULL;
            IF COL_LENGTH('sessions', 'session_model') IS NOT NULL
                ALTER TABLE sessions ALTER COLUMN session_model VARCHAR(255) NOT NULL;
        END
        """

        create_messages_table = """
        IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='messages' AND xtype='U')
        CREATE TABLE messages (
            message_key INT IDENTITY(1,1) PRIMARY KEY,
            session_key SMALLINT NOT NULL,
            message_role VARCHAR(50) NOT NULL,
            message_content NVARCHAR(MAX) NOT NULL,
            message_datetime DATETIME NOT NULL,
            message_is_welcome BIT NOT NULL DEFAULT 0,
            message_from_mic BIT NOT NULL DEFAULT 0,
            message_total_tokens INT NOT NULL DEFAULT 0,
            message_prompt_tokens INT NOT NULL DEFAULT 0,
            message_candidates_tokens INT NOT NULL DEFAULT 0,
            message_thinking_tokens INT NOT NULL DEFAULT 0,
            CreationDate DATETIME NOT NULL DEFAULT GETDATE(),
            CONSTRAINT FK_session_messages_sessionid_01 FOREIGN KEY (session_key)
                REFERENCES sessions(session_key) ON DELETE CASCADE
        );
        """

        # Migration: drop provider/model columns from messages — they belong to sessions only
        alter_messages_table = """
        IF EXISTS (SELECT * FROM sysobjects WHERE name='messages' AND xtype='U')
        BEGIN
            IF COL_LENGTH('messages', 'message_provider') IS NOT NULL
                ALTER TABLE messages DROP COLUMN message_provider;
            IF COL_LENGTH('messages', 'message_model') IS NOT NULL
                ALTER TABLE messages DROP COLUMN message_model;
        END
        """

        create_activity_logs_table = """
        IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='activity_logs' AND xtype='U')
        CREATE TABLE activity_logs (
            log_id INT IDENTITY(1,1) PRIMARY KEY,
            provider NVARCHAR(50) NOT NULL,
            log_timestamp DATETIME2 NOT NULL,
            level NVARCHAR(20) NOT NULL,
            message NVARCHAR(MAX)
        );
        """

        try:
            conn = self._get_connection()
            if not conn:
                logger.error("Failed to initialize SQL Server schema: Connection is None.")
                return False
            cursor = conn.cursor()
            logger.info("Initializing SQL Server Schemas...")
            cursor.execute(drop_old_schema)
            cursor.execute(create_sessions_table)
            cursor.execute(alter_sessions_table)
            cursor.execute(create_messages_table)
            cursor.execute(alter_messages_table)
            cursor.execute(create_activity_logs_table)
            conn.commit()
            logger.info("SQL Server schemas initialized successfully.")
            return True
        except Exception as e:
            logger.error(f"Failed to initialize SQL Server schema: {e}", exc_info=True)
            return False

    def export_session_json(self, file_path):
        """
        Parses a session JSON file and exports it to SQL Server database.

        For GROUP sessions: creates one session row per AI participant, each with its own
        session_provider/session_model and only the messages relevant to that participant
        (user messages + that participant's assistant responses).

        For INDIVIDUAL sessions: a single session row as normal.
        """
        if not os.path.exists(file_path):
            logger.error(f"Session file not found: {file_path}")
            return False

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            logger.error(f"Error parsing session JSON file {file_path}: {e}")
            return False

        session_id = data.get("session_id")
        provider = data.get("provider", "unknown")
        model = data.get("model", "")
        created_at_str = data.get("created_at")
        updated_at_str = data.get("updated_at")
        token_total = data.get("token_total", 0)
        messages = data.get("messages", [])

        session_id = (session_id or "")[:4000]
        if not session_id:
            logger.warning(f"Skipping session file {file_path} because session_id is missing.")
            return False

        created_at = self._parse_datetime(created_at_str)
        updated_at = self._parse_datetime(updated_at_str)

        if not PYODBC_AVAILABLE:
            logger.info(f"Dry Run (SQL Server): Prepared session {session_id} with {len(messages)} messages.")
            return True

        try:
            conn = self._get_connection()
            if not conn:
                logger.error(f"Cannot export session {session_id}: Connection is None.")
                return False
            cursor = conn.cursor()

            insert_msg_sql = """
            INSERT INTO messages (
                session_key, message_role, message_content, message_datetime,
                message_is_welcome, message_from_mic, message_total_tokens,
                message_prompt_tokens, message_candidates_tokens, message_thinking_tokens,
                CreationDate
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, GETDATE())
            """

            def _insert_messages(session_key, msg_list):
                """Insert a list of messages linked to the given session_key."""
                cursor.execute("DELETE FROM messages WHERE session_key = ?", (session_key,))
                for msg in msg_list:
                    role = (msg.get("role") or "user")[:50]
                    content = msg.get("content") or " "
                    date_str = msg.get("date", "")
                    time_str = msg.get("timestamp", "")
                    msg_dt = None
                    if date_str and time_str:
                        msg_dt = self._parse_datetime(f"{date_str} {time_str}")
                    if not msg_dt:
                        msg_dt = datetime.now()
                    is_welcome = 1 if msg.get("is_welcome", False) else 0
                    from_mic = 1 if msg.get("from_mic", False) else 0
                    ti = msg.get("token_info") or {}
                    total_tok = int(ti.get("total_tokens", 0) or 0)
                    prompt_tok = int(ti.get("prompt_tokens", 0) or 0)
                    cand_tok = int(ti.get("candidates_tokens", 0) or ti.get("completion_tokens", 0) or 0)
                    think_tok = int(ti.get("thinking_tokens", 0) or 0)
                    cursor.execute(insert_msg_sql, (
                        session_key, role, content, msg_dt, is_welcome, from_mic,
                        total_tok, prompt_tok, cand_tok, think_tok
                    ))

            def _upsert_session(s_id, s_provider, s_model, s_token_total):
                """Upsert a session row and return its session_key."""
                s_id = s_id[:4000]
                s_provider = (s_provider or "unknown")[:255]
                s_model = (s_model or "unknown")[:255]
                s_token_total = int(s_token_total or 0)
                cursor.execute("SELECT session_key FROM sessions WHERE session_id = ?", (s_id,))
                row = cursor.fetchone()
                if row:
                    sk = row[0]
                    cursor.execute("""
                        UPDATE sessions
                        SET session_provider = ?, session_model = ?,
                            session_created_at = ?, session_updated_at = ?,
                            session_token_total = ?, LastUpdate = GETDATE()
                        WHERE session_key = ?
                    """, (s_provider, s_model, created_at, updated_at, s_token_total, sk))
                else:
                    cursor.execute("""
                        SET NOCOUNT ON;
                        INSERT INTO sessions (
                            session_id, session_provider, session_model,
                            session_created_at, session_updated_at,
                            session_token_total, CreationDate, LastUpdate
                        ) OUTPUT INSERTED.session_key
                        VALUES (?, ?, ?, ?, ?, ?, GETDATE(), GETDATE())
                    """, (s_id, s_provider, s_model, created_at, updated_at, s_token_total))
                    row = cursor.fetchone()
                    if row and row[0] is not None:
                        sk = int(row[0])
                    else:
                        cursor.execute("SELECT session_key FROM sessions WHERE session_id = ?", (s_id,))
                        fallback_row = cursor.fetchone()
                        sk = int(fallback_row[0]) if fallback_row else 0
                return sk

            # ─── GROUP SESSION ────────────────────────────────────────────────────────
            if provider.startswith("group_"):
                # Collect unique AI participants (get the latest model used by each provider)
                participants = {}  # provider_name -> model_name
                for msg in messages:
                    if msg.get("role") == "assistant":
                        p = (msg.get("provider") or "").strip()
                        m = (msg.get("model") or "").strip()
                        if p and m:
                            participants[p] = m  # Overwrite to keep the latest one used


                if not participants:
                    # No provider info in messages yet — store a single generic session
                    sk = _upsert_session(session_id, "Group", provider, int(token_total or 0))
                    _insert_messages(sk, messages)
                else:
                    # One session row per AI participant
                    user_messages = [msg for msg in messages if msg.get("role") != "assistant"]
                    for p_name, p_model in participants.items():
                        # This participant's assistant messages only
                        ai_messages = [
                            msg for msg in messages
                            if msg.get("role") == "assistant"
                            and (msg.get("provider") or "").strip() == p_name
                        ]
                        participant_msgs = user_messages + ai_messages
                        participant_msgs.sort(key=lambda m: (m.get("date", ""), m.get("timestamp", "")))

                        participant_tokens = sum(
                            int((msg.get("token_info") or {}).get("total_tokens", 0) or 0)
                            for msg in ai_messages
                        )
                        participant_session_id = f"{session_id}::{p_name}"
                        sk = _upsert_session(participant_session_id, p_name, p_model, participant_tokens)
                        _insert_messages(sk, participant_msgs)

            # ─── INDIVIDUAL SESSION ───────────────────────────────────────────────────
            else:
                sk = _upsert_session(session_id, provider, model, int(token_total or 0))
                _insert_messages(sk, messages)

            conn.commit()
            logger.info(f"Successfully exported session {session_id} to SQL Server.")
            return True
        except Exception as e:
            logger.error(f"Error exporting session {session_id} to SQL Server: {e}", exc_info=True)
            return False

    def export_activity_log(self, file_path, provider, start_line_offset=0):
        """
        Parses an activity log file starting from a given line offset and inserts lines to SQL Server.
        Returns the number of lines successfully processed and the new line offset.
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
            # No new lines to process
            return 0, total_lines

        new_lines = lines[start_line_offset:]
        processed_count = 0

        parsed_records = []
        for line in new_lines:
            line = line.strip()
            if not line:
                continue

            match = LOG_LINE_REGEX.match(line)
            if match:
                time_str, level, msg = match.groups()
                # Parse log time format: '2026-06-14 13:05:30,522'
                try:
                    log_timestamp = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S,%f")
                except ValueError:
                    log_timestamp = datetime.now()

                parsed_records.append((provider, log_timestamp, level, msg))
            else:
                # Handle multi-line logs or lines that don't match the regex by appending to the previous log or creating a generic entry
                if parsed_records:
                    # Append to previous message
                    prev = list(parsed_records[-1])
                    prev[3] = prev[3] + "\n" + line
                    parsed_records[-1] = tuple(prev)
                else:
                    parsed_records.append((provider, datetime.now(), "INFO", line))

        if not parsed_records:
            return 0, total_lines

        if not PYODBC_AVAILABLE:
            logger.info(f"Dry Run (SQL Server): Prepared {len(parsed_records)} log entries for provider {provider}.")
            return len(parsed_records), total_lines

        try:
            conn = self._get_connection()
            if not conn:
                logger.error(f"Cannot export activity logs for {provider}: Connection is None.")
                return 0, start_line_offset
            cursor = conn.cursor()

            insert_log_sql = """
            INSERT INTO activity_logs (provider, log_timestamp, level, message)
            VALUES (?, ?, ?, ?)
            """

            # Execute batch insert
            cursor.executemany(insert_log_sql, parsed_records)
            conn.commit()

            logger.info(f"Successfully exported {len(parsed_records)} activity logs for {provider} to SQL Server.")
            return len(parsed_records), total_lines
        except Exception as e:
            logger.error(f"Error exporting activity logs for {provider} to SQL Server: {e}", exc_info=True)
            return 0, start_line_offset

    def _parse_datetime(self, dt_str):
        """Helper to parse local datetime strings from session log format."""
        if not dt_str:
            return datetime.now()

        # Formats to try:
        # 1. 2026-06-28 09:45:41 AM (standard format)
        # 2. 2026-06-28 09:45 AM (short format)
        formats = ["%Y-%m-%d %I:%M:%S %p", "%Y-%m-%d %I:%M %p", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"]
        for fmt in formats:
            try:
                return datetime.strptime(dt_str, fmt)
            except ValueError:
                continue
        logger.warning(f"Could not parse datetime string '{dt_str}'. Using current time.")
        return datetime.now()
