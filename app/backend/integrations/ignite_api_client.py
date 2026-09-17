"""
app/backend/ignite_api_client.py
Skill 3.1 — Async S2S HTTP Client for Ignite API Integration.

Handles robust multipart/form-data extraction calls to Ignite API, supporting:
- Synchronous direct responses (HTTP 200)
- Asynchronous jobs with polling (HTTP 202 -> GET /api/v1/jobs/{job_id})
- Defensive error handling and timeout protection

Sync vs async is decided by Ignite API when mode=auto (file-size thresholds).
Chat must always send mode=auto and handle both 200 and 202 paths.
"""

from __future__ import annotations
import asyncio
import concurrent.futures
import os
import time
import httpx

from typing import Any, Dict, Optional

from backend.core.libraries import get_assistant_logger

logger = get_assistant_logger("ignite_api_client")

# Defaults aligned with Ignite API MAX_SYNC_FILE_SIZE_*_MB (observability only)
_DEFAULT_MAX_SYNC_DOC_MB = 15
_DEFAULT_CONNECT_TIMEOUT = 30.0
_DEFAULT_WRITE_TIMEOUT = 60.0
_DEFAULT_MAX_WAIT = 300.0


class IgniteAPIClient:
    """
    Async HTTP client for calling Ignite API extraction services.
    """

    def __init__(
        self,
        api_url: Optional[str] = None,
        api_key: Optional[str] = None,
        enabled: Optional[bool] = None,
        poll_interval: Optional[float] = None,
        max_wait: Optional[float] = None,
        connect_timeout: Optional[float] = None,
        write_timeout: Optional[float] = None,
    ):
        self.api_url = (
            api_url
            or os.getenv("IGNITE_EXTRACTION_API_URL")
            or os.getenv("IGNITE_API_URL")
            or "https://ignite-api.azurecontainerapps.io"
        ).rstrip("/")
        self.api_key = api_key or os.getenv("IGNITE_EXTRACTION_API_KEY") or os.getenv("IGNITE_MASTER_API_KEY") or ""

        env_enabled = os.getenv("IGNITE_EXTRACTION_ENABLED", "true").lower() in ("true", "1", "yes")
        self.enabled = enabled if enabled is not None else env_enabled

        self.poll_interval = (
            poll_interval
            if poll_interval is not None
            else float(os.getenv("IGNITE_EXTRACTION_POLL_INTERVAL", "3"))
        )
        self.max_wait = (
            max_wait
            if max_wait is not None
            else float(os.getenv("IGNITE_EXTRACTION_MAX_WAIT", str(int(_DEFAULT_MAX_WAIT))))
        )
        self.connect_timeout = (
            connect_timeout
            if connect_timeout is not None
            else float(os.getenv("IGNITE_EXTRACTION_CONNECT_TIMEOUT", str(_DEFAULT_CONNECT_TIMEOUT)))
        )
        self.write_timeout = (
            write_timeout
            if write_timeout is not None
            else float(os.getenv("IGNITE_EXTRACTION_WRITE_TIMEOUT", str(_DEFAULT_WRITE_TIMEOUT)))
        )
        try:
            self._max_sync_doc_mb = int(
                os.getenv("IGNITE_MAX_SYNC_DOC_MB", str(_DEFAULT_MAX_SYNC_DOC_MB))
            )
        except (ValueError, TypeError):
            self._max_sync_doc_mb = _DEFAULT_MAX_SYNC_DOC_MB

        # Last failure reason for call-site messaging (timeout | http | network | disabled | empty | poll)
        self.last_error: Optional[str] = None

        if self.enabled and not self.api_key:
            logger.warning("IgniteAPIClient is enabled but IGNITE_EXTRACTION_API_KEY is not configured.")

    def _httpx_timeout(self) -> httpx.Timeout:
        """Split timeouts: short connect (ACA cold start), write for upload, read = sync/poll budget."""
        return httpx.Timeout(
            connect=self.connect_timeout,
            write=self.write_timeout,
            read=self.max_wait,
            pool=self.connect_timeout,
        )

    @staticmethod
    def detect_channel(filename: str) -> str:
        """
        Map a filename extension to the corresponding Ignite API channel.
        Returns: 'doc', 'audio', 'image', or 'video'.
        """
        ext = os.path.splitext(filename)[1].lower().strip(".")
        if ext in ("pdf", "docx", "doc", "xls", "xlsx", "xlsm", "csv", "txt", "pptx", "ppt"):
            return "doc"
        elif ext in ("mp3", "wav", "m4a", "ogg", "flac"):
            return "audio"
        elif ext in ("png", "jpg", "jpeg", "tiff", "bmp", "webp"):
            return "image"
        elif ext in ("mp4", "avi", "mov", "mkv", "webm"):
            return "video"
        return "doc"

    def _log_size_hint(self, filename: str, file_size_bytes: int) -> None:
        """Observability only — Ignite API decides sync/async; Chat never overrides mode."""
        channel = self.detect_channel(filename)
        size_mb = file_size_bytes / (1024 * 1024)
        if channel == "doc":
            expect = "sync" if file_size_bytes < self._max_sync_doc_mb * 1024 * 1024 else "async"
            logger.info(
                "Ignite extract mode=auto file=%s size=%.3fMB channel=%s "
                "(hint: doc threshold %sMB → expect %s; server is source of truth)",
                filename,
                size_mb,
                channel,
                self._max_sync_doc_mb,
                expect,
            )
        else:
            logger.info(
                "Ignite extract mode=auto file=%s size=%.3fMB channel=%s (server decides sync/async)",
                filename,
                size_mb,
                channel,
            )

    async def extract(
        self,
        file_bytes: bytes,
        filename: str,
        template_name: str,
        llm_provider: Optional[str] = None,
        model: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Send a file extraction request to Ignite API with mode=auto.

        Returns:
            Dictionary matching ExtractionResponse or None if request fails / disabled.
        """
        self.last_error = None

        if not self.enabled:
            self.last_error = "disabled"
            logger.info("IgniteAPIClient extraction disabled by configuration.")
            return None

        if not file_bytes:
            self.last_error = "empty"
            logger.warning("IgniteAPIClient: Empty file_bytes passed.")
            return None

        endpoint_url = f"{self.api_url}/api/v1/extract"
        headers: Dict[str, str] = {}
        if self.api_key:
            headers["X-API-Key"] = self.api_key

        data = {"template_name": template_name}
        if llm_provider:
            data["llm_provider"] = llm_provider
        if model:
            data["model"] = model

        mime_type = self._get_mime_type(filename)
        files = {"file": (filename, file_bytes, mime_type)}
        file_size = len(file_bytes)
        self._log_size_hint(filename, file_size)

        logger.info(
            "Sending extraction request to Ignite API: %s (file: %s, template: %s, bytes: %s, mode=auto)",
            endpoint_url,
            filename,
            template_name,
            file_size,
        )

        try:
            async with httpx.AsyncClient(timeout=self._httpx_timeout()) as client:
                response = await client.post(
                    endpoint_url,
                    headers=headers,
                    data=data,
                    files=files,
                    params={"mode": "auto"},
                )

                if response.status_code == 200:
                    result = response.json()
                    logger.info("Ignite API sync path (HTTP 200) succeeded for %s", filename)
                    return result

                if response.status_code == 202:
                    job_info = response.json()
                    job_id = (
                        job_info.get("job_id")
                        or job_info.get("id")
                        or self._extract_job_id_from_url(job_info.get("statusQueryGetUri") or "")
                    )
                    if not job_id:
                        self.last_error = "http"
                        logger.error("Ignite API 202 Accepted returned no job_id: %s", job_info)
                        return None

                    logger.info(
                        "Ignite API async path (HTTP 202) for %s. Job ID: %s. Polling...",
                        filename,
                        job_id,
                    )
                    return await self._poll_job(client, job_id, headers)

                self.last_error = "http"
                logger.error(
                    "Ignite API returned HTTP %s: %s",
                    response.status_code,
                    response.text[:300],
                )
                return None

        except httpx.TimeoutException as exc:
            self.last_error = "timeout"
            logger.error(
                "IgniteAPIClient timeout for %s (connect=%.0fs write=%.0fs read=%.0fs): %s",
                filename,
                self.connect_timeout,
                self.write_timeout,
                self.max_wait,
                exc,
            )
            return None
        except Exception as exc:
            self.last_error = "network"
            logger.error("IgniteAPIClient request exception for %s: %s", filename, exc, exc_info=True)
            return None

    def extract_sync(
        self,
        file_bytes: bytes,
        filename: str,
        template_name: str,
        llm_provider: Optional[str] = None,
        model: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Synchronous wrapper around extract() for call sites running in worker threads.
        Outer timeout covers connect + full sync read / async poll budget.
        """
        if not self.enabled:
            self.last_error = "disabled"
            logger.info("IgniteAPIClient extraction disabled by configuration.")
            return None

        # connect + sync read (or 202 + poll) + small margin
        outer_timeout = self.connect_timeout + self.max_wait + 30.0

        try:
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                loop = None

            if loop is not None and loop.is_running():
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(
                        asyncio.run,
                        self.extract(file_bytes, filename, template_name, llm_provider, model),
                    )
                    return future.result(timeout=outer_timeout)
            elif loop is not None and not loop.is_closed():
                return loop.run_until_complete(
                    self.extract(file_bytes, filename, template_name, llm_provider, model)
                )
            else:
                return asyncio.run(
                    self.extract(file_bytes, filename, template_name, llm_provider, model)
                )
        except concurrent.futures.TimeoutError:
            self.last_error = "timeout"
            logger.error(
                "IgniteAPIClient extract_sync outer timeout for %s after %.0fs",
                filename,
                outer_timeout,
            )
            return None
        except Exception as sync_exc:
            self.last_error = "network"
            logger.error("IgniteAPIClient extract_sync failed for %s: %s", filename, sync_exc, exc_info=True)
            return None

    async def _poll_job(
        self,
        client: httpx.AsyncClient,
        job_id: str,
        headers: Dict[str, str],
    ) -> Optional[Dict[str, Any]]:
        """
        Poll GET /api/v1/jobs/{job_id} until completed, failed, or timed out.
        Budget starts after the 202 Accept (not including the upload POST).
        """
        status_url = f"{self.api_url}/api/v1/jobs/{job_id}"
        start_time = time.monotonic()

        while (time.monotonic() - start_time) < self.max_wait:
            await asyncio.sleep(self.poll_interval)
            try:
                resp = await client.get(status_url, headers=headers)
                if resp.status_code in (200, 202):
                    body = resp.json()
                    job_status = (
                        body.get("status")
                        or body.get("runtimeStatus")
                        or ""
                    ).lower()

                    if job_status in ("completed", "success"):
                        logger.info("Ignite API job %s completed successfully.", job_id)
                        raw_res = body.get("result")
                        if isinstance(raw_res, dict):
                            return raw_res
                        return body

                    if job_status in ("failed", "canceled", "cancelled", "terminated"):
                        error_msg = body.get("error") or body.get("message") or "Unknown error"
                        self.last_error = "poll"
                        logger.error(
                            "Ignite API job %s ended with status '%s': %s",
                            job_id,
                            job_status,
                            error_msg,
                        )
                        return None

                    logger.debug("Job %s progress: %s", job_id, body.get("progress", job_status))
                else:
                    logger.warning("Polling job %s returned HTTP %s", job_id, resp.status_code)
            except httpx.TimeoutException as poll_exc:
                logger.warning("Timeout polling job %s: %s", job_id, poll_exc)
            except Exception as poll_exc:
                logger.warning("Error polling job %s: %s", job_id, poll_exc)

        self.last_error = "timeout"
        logger.error("Polling job %s timed out after %s seconds.", job_id, self.max_wait)
        return None

    @staticmethod
    def user_failure_hint(filename: str, last_error: Optional[str], lang: Optional[str] = None) -> str:
        """Safe chat bubble fragment — no stack traces or HTTP details. Localized chrome."""
        base = "en"
        if lang and isinstance(lang, str) and lang.strip():
            base = lang.strip().split("-")[0].lower()
        if last_error == "timeout":
            templates = {
                "es": (
                    f"\n\n⚠️ *(Extracción Ignite API agotó el tiempo para {filename}; "
                    f"reintenta en un momento cuando el servicio despierte)*"
                ),
                "fr": (
                    f"\n\n⚠️ *(L'extraction Ignite API a expiré pour {filename} ; "
                    f"réessayez dans un instant après le démarrage du service)*"
                ),
                "de": (
                    f"\n\n⚠️ *(Ignite-API-Extraktion für {filename} hat das Zeitlimit überschritten; "
                    f"bitte gleich erneut versuchen, sobald der Dienst wach ist)*"
                ),
                "it": (
                    f"\n\n⚠️ *(Estrazione Ignite API scaduta per {filename}; "
                    f"riprova tra un momento dopo l'avvio del servizio)*"
                ),
                "pt": (
                    f"\n\n⚠️ *(Extração Ignite API expirou para {filename}; "
                    f"tente de novo em instantes após o serviço despertar)*"
                ),
                "en": (
                    f"\n\n⚠️ *(Ignite API extraction timed out for {filename}; "
                    f"retry in a moment after the service wakes)*"
                ),
            }
            return templates.get(base, templates["en"])
        fail = {
            "es": f"\n\n⚠️ *(Falló la extracción Ignite API para {filename})*",
            "fr": f"\n\n⚠️ *(Échec de l'extraction Ignite API pour {filename})*",
            "de": f"\n\n⚠️ *(Ignite-API-Extraktion für {filename} fehlgeschlagen)*",
            "it": f"\n\n⚠️ *(Estrazione Ignite API non riuscita per {filename})*",
            "pt": f"\n\n⚠️ *(Falha na extração Ignite API para {filename})*",
            "en": f"\n\n⚠️ *(Ignite API extraction failed for {filename})*",
        }
        return fail.get(base, fail["en"])

    @staticmethod
    def _extract_job_id_from_url(url: str) -> Optional[str]:
        """Extract job_id from status query URI e.g. /api/v1/jobs/12345."""
        if not url:
            return None
        parts = url.rstrip("/").split("/")
        return parts[-1] if parts else None

    @staticmethod
    def _get_mime_type(filename: str) -> str:
        """Infer basic MIME type from filename."""
        ext = os.path.splitext(filename)[1].lower()
        mime_map = {
            ".pdf": "application/pdf",
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".doc": "application/msword",
            ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ".xls": "application/vnd.ms-excel",
            ".csv": "text/csv",
            ".txt": "text/plain",
            ".mp3": "audio/mpeg",
            ".wav": "audio/wav",
            ".m4a": "audio/mp4",
            ".ogg": "audio/ogg",
            ".flac": "audio/flac",
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".tiff": "image/tiff",
            ".bmp": "image/bmp",
            ".webp": "image/webp",
            ".mp4": "video/mp4",
            ".avi": "video/x-msvideo",
            ".mov": "video/quicktime",
            ".mkv": "video/x-matroska",
            ".webm": "video/webm",
        }
        return mime_map.get(ext, "application/octet-stream")
