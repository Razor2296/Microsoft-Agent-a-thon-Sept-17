"""
Thin desktop proxy that forwards PyWebView API calls to the remote ACA backend.

Keeps the same method surface as PyWebViewApi so the existing frontend JS
(window.pywebview.api.*) continues to work unchanged.
"""

from __future__ import annotations

import base64
import logging
import os
import re
import threading
import time
import uuid
import webbrowser
from typing import Any

import requests

from backend.user.windows_user import (
    get_downloads_path,
    get_user_display_name,
    get_user_profile_picture,
)
from main.document_generator import generate_docx, generate_pptx, generate_xlsx

logger = logging.getLogger(__name__)

_GENERIC_NAME_RE = re.compile(
    r"\b(Hello|Hi|Hey|Hola)\s+User\b",
    re.IGNORECASE,
)


def _session_id_path() -> str:
    override = (os.getenv("IGNITE_SESSION_FILE") or "").strip()
    if override:
        return override
    return os.path.join(os.path.expanduser("~"), ".ignitechat_session_id")


def _load_or_create_session_id() -> str:
    env_sid = (os.getenv("IGNITE_SESSION_ID") or "").strip()
    if env_sid:
        return env_sid
    path = _session_id_path()
    try:
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as fh:
                existing = (fh.read() or "").strip()
            if len(existing) >= 8:
                return existing
    except Exception as exc:
        logger.warning("Could not read session id file %s: %s", path, exc)
    sid = f"sess_{uuid.uuid4().hex}"
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(sid)
    except Exception as exc:
        logger.warning("Could not persist session id to %s: %s", path, exc)
    return sid


def _persist_session_id(session_id: str) -> None:
    path = _session_id_path()
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(session_id)
    except Exception as exc:
        logger.warning("Could not persist session id to %s: %s", path, exc)


def _local_user_avatar_data_uri() -> str:
    """Read the Windows account picture on the desktop client (not available in ACA)."""
    try:
        path = get_user_profile_picture()
        if not path or not os.path.isfile(path):
            return ""
        ext = os.path.splitext(path)[1].lower().lstrip(".") or "png"
        mime = f"image/{'jpeg' if ext in {'jpg', 'jpeg'} else ext}"
        with open(path, "rb") as fh:
            encoded = base64.b64encode(fh.read()).decode("ascii")
        return f"data:{mime};base64,{encoded}"
    except Exception as exc:
        logger.warning("Could not load local Windows profile picture: %s", exc)
        return ""


def _local_user_display_name() -> str:
    try:
        name = (get_user_display_name() or "").strip()
        if name and name.lower() not in {"user", "ignite", "root"}:
            return name
    except Exception as exc:
        logger.warning("Could not load local Windows display name: %s", exc)
    # Prefer explicit override, then common Windows env vars.
    for key in ("IGNITE_USER_NAME", "USERNAME", "USER"):
        candidate = (os.getenv(key) or "").strip()
        if candidate and candidate.lower() not in {"user", "ignite", "root"}:
            return candidate.replace(".", " ").title()
    return ""


def _personalize_history(history: Any, display_name: str) -> Any:
    """Rewrite generic ACA 'Hello User' welcomes with the local Windows display name."""
    if not display_name or not isinstance(history, list):
        return history
    personalized: list[Any] = []
    for msg in history:
        if not isinstance(msg, dict):
            personalized.append(msg)
            continue
        item = dict(msg)
        content = str(item.get("content") or "")
        looks_welcome = bool(item.get("is_welcome")) or bool(_GENERIC_NAME_RE.search(content))
        if looks_welcome:
            item["is_welcome"] = True
            item["content"] = _GENERIC_NAME_RE.sub(
                lambda m: f"{m.group(1)} {display_name}",
                content,
            )
        personalized.append(item)
    return personalized


class RemotePyWebViewApi:
    """HTTP client facade compatible with the desktop PyWebView bridge."""

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout_seconds: float | None = None,
    ):
        self.base_url = (
            base_url
            or os.getenv("IGNITE_API_BASE_URL")
            or os.getenv("IGNITE_BASE_URL")
            or "http://127.0.0.1:8000"
        ).rstrip("/")
        self.api_key = (api_key if api_key is not None else os.getenv("IGNITE_API_KEY", "")).strip()
        self.timeout_seconds = float(
            timeout_seconds
            if timeout_seconds is not None
            else os.getenv("IGNITE_API_TIMEOUT", "300")
        )
        # ACA scale-to-zero cold starts: how long to wait for /health before invoking,
        # and how many transient-failure retries per invoke.
        self.warmup_timeout_seconds = float(os.getenv("IGNITE_WARMUP_TIMEOUT", "90"))
        self.transient_retries = int(os.getenv("IGNITE_API_RETRIES", "2"))
        self._connect_timeout = float(os.getenv("IGNITE_API_CONNECT_TIMEOUT", "10"))
        self._warm = False
        self._state_lock = threading.Lock()
        self._window = None
        self._local_user_name = _local_user_display_name()
        self._local_user_avatar = _local_user_avatar_data_uri()
        self._session_id = _load_or_create_session_id()
        logger.info(
            "RemotePyWebViewApi ready base_url=%s api_key_set=%s timeout=%ss local_user=%s avatar=%s session=%s",
            self.base_url,
            bool(self.api_key),
            self.timeout_seconds,
            self._local_user_name or "(none)",
            bool(self._local_user_avatar),
            self._session_id,
        )

    def set_window(self, window) -> None:
        self._window = window

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        if self._local_user_name:
            # So ACA model prompts know the real Windows display name.
            headers["X-Ignite-User-Name"] = self._local_user_name
        with self._state_lock:
            sid = self._session_id
        if sid:
            # Sticky per-desktop isolation key for multi-user ACA sessions.
            headers["X-Ignite-Session-Id"] = sid
        return headers

    def _capture_session_id(self, response: requests.Response) -> None:
        sid = (
            response.headers.get("X-Ignite-Session-Id")
            or response.headers.get("x-ignite-session-id")
            or ""
        ).strip()
        if not sid:
            try:
                body_sid = (response.json() or {}).get("session_id")
                if isinstance(body_sid, str):
                    sid = body_sid.strip()
            except Exception:
                sid = ""
        if sid and sid != self._session_id:
            with self._state_lock:
                self._session_id = sid
            _persist_session_id(sid)

    def _wait_until_warm(self) -> bool:
        """Poll /health until the ACA container is awake (scale-to-zero cold start)."""
        deadline = time.monotonic() + self.warmup_timeout_seconds
        delay = 2.0
        while time.monotonic() < deadline:
            try:
                response = requests.get(
                    f"{self.base_url}/health",
                    headers=self._headers(),
                    timeout=(self._connect_timeout, 15),
                )
                if response.status_code < 500:
                    with self._state_lock:
                        self._warm = True
                    return True
            except requests.RequestException:
                pass
            time.sleep(delay)
            delay = min(delay * 1.5, 10.0)
        logger.warning("Remote API still cold after %ss of /health polling", self.warmup_timeout_seconds)
        return False

    def _invoke(self, method: str, *args: Any, **kwargs: Any) -> Any:
        return self._invoke_with_timeout(self.timeout_seconds, method, *args, **kwargs)

    def _invoke_with_timeout(
        self, timeout_seconds: float, method: str, *args: Any, **kwargs: Any
    ) -> Any:
        url = f"{self.base_url}/api/invoke"
        payload: dict[str, Any] = {
            "method": method,
            "args": list(args),
            "kwargs": kwargs,
        }
        if self._local_user_name:
            payload["client_user_name"] = self._local_user_name

        # First call after startup: give a cold ACA replica time to boot.
        if not self._warm:
            self._wait_until_warm()

        response = None
        last_exc: Exception | None = None
        attempts = max(1, self.transient_retries + 1)
        for attempt in range(attempts):
            try:
                response = requests.post(
                    url,
                    json=payload,
                    headers=self._headers(),
                    timeout=(self._connect_timeout, float(timeout_seconds)),
                )
            except requests.RequestException as exc:
                last_exc = exc
                response = None
            else:
                if response.status_code not in (502, 503, 504):
                    break
            # Transient failure: the replica likely scaled down mid-flight. Re-warm and retry.
            if attempt < attempts - 1:
                logger.warning(
                    "Remote API transient failure calling %s (attempt %s/%s); re-warming",
                    method,
                    attempt + 1,
                    attempts,
                )
                with self._state_lock:
                    self._warm = False
                self._wait_until_warm()

        if response is None:
            logger.error(
                "Remote API transport error calling %s: %s", method, last_exc, exc_info=last_exc
            )
            return {"status": "error", "message": f"Remote API unavailable: {last_exc}"}

        self._capture_session_id(response)

        if response.status_code == 401:
            return {"status": "error", "message": "Unauthorized: check IGNITE_API_KEY"}
        if response.status_code >= 400:
            detail = response.text
            try:
                detail = response.json().get("detail", detail)
            except Exception:
                pass
            logger.error("Remote API HTTP %s for %s: %s", response.status_code, method, detail)
            return {"status": "error", "message": f"Remote API error ({response.status_code}): {detail}"}

        try:
            data = response.json()
        except Exception as exc:
            logger.error("Invalid JSON from remote API (%s): %s", method, exc, exc_info=True)
            return {"status": "error", "message": "Invalid JSON from remote API"}

        if data.get("status") == "error":
            return {"status": "error", "message": data.get("error") or "Remote method failed"}
        return data.get("result")

    # ---- Local-only helpers that should not round-trip ----
    def open_external_link(self, url: str):
        try:
            if str(url).startswith("http://") or str(url).startswith("https://"):
                webbrowser.open(url)
                return {"status": "success"}
            return {"status": "error", "message": "Invalid URL protocol"}
        except Exception as exc:
            logger.error("Failed to open external link %s: %s", url, exc, exc_info=True)
            return {"status": "error", "message": str(exc)}

    def open_file_path(self, filepath: str):
        # File paths on the server are not local Desktop paths; open remote download URLs only.
        if isinstance(filepath, str) and (
            filepath.startswith("http://") or filepath.startswith("https://")
        ):
            return self.open_external_link(filepath)
        return {
            "status": "error",
            "message": "Remote mode cannot open local server filesystem paths on the desktop.",
        }

    def set_theme_window_size(self, theme):
        # Title-bar coloring stays local in launcher_webview; no remote work needed.
        return {"status": "success"}

    # ---- Proxied surface ----
    def get_initial_state(self):
        result = self._invoke("get_initial_state")
        # Surface transport/auth failures clearly to the JS UI.
        if isinstance(result, dict) and result.get("status") == "error":
            message = result.get("message") or "Remote API error"
            logger.error("get_initial_state failed: %s", message)
            return {
                "status": "error",
                "message": message,
                "providers": [],
                "models": {},
                "history": [],
            }

        # Merge desktop-local Windows identity into remote state.
        if isinstance(result, dict):
            avatars = dict(result.get("avatars") or {})
            if self._local_user_avatar:
                avatars["user"] = self._local_user_avatar
                result["avatars"] = avatars
            if self._local_user_name:
                result["user_name"] = self._local_user_name
                result["history"] = _personalize_history(
                    result.get("history"), self._local_user_name
                )
                last_messages = result.get("last_messages")
                if isinstance(last_messages, dict):
                    rewritten = {}
                    for key, value in last_messages.items():
                        if isinstance(value, dict):
                            item = dict(value)
                            content = str(item.get("content") or "")
                            item["content"] = _GENERIC_NAME_RE.sub(
                                lambda m: f"{m.group(1)} {self._local_user_name}",
                                content,
                            )
                            rewritten[key] = item
                        else:
                            rewritten[key] = value
                    result["last_messages"] = rewritten
        return result

    def get_history(self, provider=None):
        result = self._invoke("get_history", provider)
        if isinstance(result, dict) and self._local_user_name:
            result = dict(result)
            result["history"] = _personalize_history(
                result.get("history"), self._local_user_name
            )
        return result

    def get_token_totals(self):
        return self._invoke("get_token_totals")

    def get_cost_totals(self):
        return self._invoke("get_cost_totals")

    def get_accumulated_cost_stats(self, language=None):
        if language is not None:
            return self._invoke("get_accumulated_cost_stats", language)
        return self._invoke("get_accumulated_cost_stats")

    def set_provider(self, provider):
        result = self._invoke("set_provider", provider)
        if isinstance(result, dict) and self._local_user_name:
            result = dict(result)
            result["history"] = _personalize_history(
                result.get("history"), self._local_user_name
            )
        return result

    def set_model(self, provider, model):
        return self._invoke("set_model", provider, model)

    def set_participant_model(self, group_id: str, participant: str, model: str):
        return self._invoke("set_participant_model", group_id, participant, model)

    def clear_history(self, provider=None):
        return self._invoke("clear_history", provider)

    def create_group(self, name, participants):
        return self._invoke("create_group", name, participants)

    def delete_group(self, group_id):
        return self._invoke("delete_group", group_id)

    def send_message_async(
        self,
        text,
        files=None,
        language=None,
        from_mic=False,
        temperature=None,
        top_p=None,
        max_tokens=None,
        provider=None,
    ):
        # Document attaches inflate the JSON payload; allow a longer round-trip
        # so the send button does not appear to hang/fail on Office files.
        file_count = len(files or [])
        timeout = self.timeout_seconds
        if file_count > 0:
            raw = os.getenv("IGNITE_DOCUMENT_API_TIMEOUT", "900")
            try:
                doc_timeout = float(raw if raw not in (None, "") else 900)
            except (TypeError, ValueError):
                doc_timeout = 900.0
            timeout = max(timeout, max(60.0, doc_timeout))
        return self._invoke_with_timeout(
            timeout,
            "send_message_async",
            text,
            files,
            language,
            from_mic,
            temperature,
            top_p,
            max_tokens,
            provider=provider,
        )

    def cancel_generation(self, request_id=None, provider=None):
        return self._invoke("cancel_generation", request_id, provider)

    def get_generation_status(self, request_id, since_reply_index=0):
        return self._invoke("get_generation_status", request_id, since_reply_index)

    def send_message(
        self,
        text,
        files=None,
        language=None,
        from_mic=False,
        temperature=None,
        top_p=None,
        max_tokens=None,
    ):
        return self._invoke(
            "send_message",
            text,
            files,
            language,
            from_mic,
            temperature,
            top_p,
            max_tokens,
        )

    def generate_image(self, prompt):
        return self._invoke("generate_image", prompt)

    def generate_audio(self, prompt):
        return self._invoke("generate_audio", prompt)

    def determine_voice_category(self, text):
        return self._invoke("determine_voice_category", text)

    def save_file_to_downloads(self, base64_data: str, filename: str):
        """Save base64 data directly to the user's Downloads folder on the local Windows system and open it."""
        try:
            downloads_dir = get_downloads_path()
            os.makedirs(downloads_dir, exist_ok=True)
            target_path = os.path.join(downloads_dir, filename)

            if "," in base64_data:
                base64_data = base64_data.split(",")[1]

            raw_bytes = base64.b64decode(base64_data)
            with open(target_path, "wb") as f:
                f.write(raw_bytes)

            if os.name == 'nt':
                try:
                    os.startfile(target_path)
                except Exception as open_err:
                    logger.warning(f"Could not open saved file: {open_err}")
            return {"status": "success", "filepath": target_path}
        except Exception as e:
            logger.error(f"Error saving file to downloads: {e}", exc_info=True)
            return {"status": "error", "message": str(e)}

    def export_message_to_file(self, content, file_type):
        """Generates Word, Excel, or PowerPoint document locally in Downloads and opens it."""
        try:
            file_type = file_type.lower()
            downloads_dir = get_downloads_path()
            os.makedirs(downloads_dir, exist_ok=True)
            filename = f"Documento_{int(time.time())}.{file_type}"
            target_path = os.path.join(downloads_dir, filename)

            if file_type == 'docx':
                generate_docx(content, target_path)
            elif file_type == 'xlsx':
                generate_xlsx(content, target_path)
            elif file_type == 'pptx':
                generate_pptx(content, target_path)
            else:
                return {"status": "error", "message": f"Unsupported file type: {file_type}"}

            if os.name == 'nt':
                try:
                    os.startfile(target_path)
                except Exception:
                    pass
            return {"status": "success", "filepath": target_path}
        except Exception as e:
            logger.error(f"Local export_message_to_file failed: {e}", exc_info=True)
            return {"status": "error", "message": str(e)}

    def translate_message(self, text, target_language):
        return self._invoke("translate_message", text, target_language)

    def summarize_chat(self, language="en"):
        return self._invoke("summarize_chat", language)

    def save_welcome_message(self, provider, text, msg_provider=None):
        return self._invoke("save_welcome_message", provider, text, msg_provider)

    def get_available_plugins(self):
        return self._invoke("get_available_plugins")

    def reload_plugins(self):
        return self._invoke("reload_plugins")

    def execute_plugin(self, name, user_input=""):
        return self._invoke("execute_plugin", name, user_input)

    def execute_sandbox_code(self, code, timeout_seconds=10.0):
        return self._invoke("execute_sandbox_code", code, timeout_seconds)

    def scrape_web_url(self, url, extract_links=True, max_length=5000):
        return self._invoke("scrape_web_url", url, extract_links, max_length)

    def handle_mcp_request(self, request_payload):
        return self._invoke("handle_mcp_request", request_payload)

    def synthesize_voice_clone(self, profile_id, text):
        return self._invoke("synthesize_voice_clone", profile_id, text)

    def generate_plotly_chart(
        self, labels, values, title="Chart", chart_type="bar", series_name="Values"
    ):
        return self._invoke(
            "generate_plotly_chart", labels, values, title, chart_type, series_name
        )

    def add_rag_document(self, doc_id, text, metadata=None):
        return self._invoke("add_rag_document", doc_id, text, metadata)

    def search_rag_memory(self, query, top_k=3):
        return self._invoke("search_rag_memory", query, top_k)

    def clear_rag_memory(self):
        return self._invoke("clear_rag_memory")
