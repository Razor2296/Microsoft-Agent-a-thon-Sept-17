"""
app/backend/schemas.py
Pydantic V2 Data Transfer Objects (DTOs) for Ignite Chat.

This module defines the canonical data contracts for:
- Token usage tracking (TokenInfo)
- Chat message structure (ChatMessage)
- API request and response payloads
- Provider configuration

Any new field passed between backend processors and the main API
should be added here and validated through these models.

LLM Reference: See app/skills/01_coding_best_practices/SKILLS_CODING.md § 1.1
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional



from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Token Usage
# ---------------------------------------------------------------------------

class TokenInfo(BaseModel):
    """Immutable snapshot of token consumption for a single API call."""

    model_config = ConfigDict(frozen=True)

    prompt_tokens: int = Field(default=0, ge=0, description="Tokens used in the prompt/input")
    completion_tokens: int = Field(default=0, ge=0, description="Tokens generated in the response")
    thinking_tokens: int = Field(default=0, ge=0, description="Internal reasoning tokens (e.g. Claude extended-thinking)")
    total_tokens: int = Field(default=0, ge=0, description="Total tokens consumed in this call")
    cost_usd: float = Field(default=0.0, ge=0.0, description="Estimated USD cost of this API call")

    @model_validator(mode="after")
    def compute_total(self) -> "TokenInfo":
        """Auto-compute total_tokens from parts when it is 0 and parts sum > 0.
        Uses object.__setattr__ to bypass the frozen model restriction at validation time.
        """
        computed = self.prompt_tokens + self.completion_tokens + self.thinking_tokens
        if self.total_tokens == 0 and computed > 0:
            object.__setattr__(self, "total_tokens", computed)
        return self

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "TokenInfo":
        """Construct from the legacy dict format used in history messages."""
        if not data or not isinstance(data, dict):
            return cls()

        prompt = data.get("prompt_tokens")
        completion = data.get("candidates_tokens")
        if completion is None:
            completion = data.get("completion_tokens")
        thinking = data.get("thinking_tokens")
        total = data.get("total_tokens")
        cost = data.get("cost_usd")

        return cls(
            prompt_tokens=int(prompt) if prompt is not None else 0,
            completion_tokens=int(completion) if completion is not None else 0,
            thinking_tokens=int(thinking) if thinking is not None else 0,
            total_tokens=int(total) if total is not None else 0,
            cost_usd=float(cost) if cost is not None else 0.0,
        )

    def to_legacy_dict(self) -> dict:
        """Convert back to the dict format expected by the existing history/frontend."""
        return {
            "prompt_tokens": self.prompt_tokens,
            "candidates_tokens": self.completion_tokens,
            "thinking_tokens": self.thinking_tokens,
            "total_tokens": self.total_tokens,
            "cost_usd": round(self.cost_usd, 6),
        }



# ---------------------------------------------------------------------------
# Chat Message
# ---------------------------------------------------------------------------

def _get_time_str() -> str:
    return datetime.now().strftime("%I:%M %p")


def _get_iso_timestamp() -> str:
    return datetime.now().astimezone().isoformat()


def _get_date_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


class ChatMessage(BaseModel):
    """A single message in a chat conversation history."""

    model_config = ConfigDict(extra="allow")  # Allow extra fields for legacy compat

    role: Literal["user", "assistant", "system"]
    content: str
    provider: Optional[str] = None
    model: Optional[str] = None
    token_info: Optional[TokenInfo] = None
    timestamp: str = Field(default_factory=_get_time_str)
    iso_timestamp: Optional[str] = Field(default_factory=_get_iso_timestamp)
    date: str = Field(default_factory=_get_date_str)
    is_welcome: bool = False
    files: Optional[List[Dict[str, Any]]] = None

    @field_validator("content")
    @classmethod
    def content_must_not_be_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Chat message content cannot be empty")
        return v


# ---------------------------------------------------------------------------
# API Payloads
# ---------------------------------------------------------------------------

class APIRequestPayload(BaseModel):
    """Validated payload for a frontend → backend send_message call."""

    provider: str = Field(..., min_length=1, description="Active AI provider name")
    model: str = Field(..., min_length=1, description="Model version identifier")
    text: str = Field(default="", description="User text input")
    files: Optional[List[Dict[str, Any]]] = Field(default_factory=list)
    language: Optional[str] = Field(default="es-MX")
    from_mic: bool = Field(default=False)

    @field_validator("provider")
    @classmethod
    def provider_must_be_valid(cls, v: str) -> str:
        known = {"Gemini", "DeepSeek", "OpenAI", "Anthropic", "Perplexity", "Grok", "AlibabaCloud"}
        if v not in known and not v.startswith("group_"):
            # Allow group_ prefixed IDs and future providers
            pass
        return v


class APIResponsePayload(BaseModel):
    """Standard response envelope returned from backend to frontend."""

    status: Literal["success", "error", "done", "processing"]
    message: Optional[str] = None
    data: Optional[Dict[str, Any]] = None
    token_info: Optional[TokenInfo] = None
    request_id: Optional[str] = None


# ---------------------------------------------------------------------------
# Provider Configuration
# ---------------------------------------------------------------------------

class ProviderConfig(BaseModel):
    """Runtime configuration for a single AI provider, loaded from .env."""

    model_config = ConfigDict(frozen=True)

    name: str
    api_key: str = Field(default="", repr=False)  # Never log this
    model_version: str
    max_tokens: int = Field(default=4000, ge=1)
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    top_p: float = Field(default=0.9, ge=0.0, le=1.0)
    retry_sequence: List[int] = Field(default_factory=lambda: [1, 2, 3, 5, 8])

    @field_validator("api_key")
    @classmethod
    def api_key_not_placeholder(cls, v: str) -> str:
        if v in ("<your-key-here>", "your-key-here", ""):
            return ""
        return v


# ---------------------------------------------------------------------------
# Skill 2.8 — Plugin Store & Dynamic Plugin Loader DTOs
# ---------------------------------------------------------------------------

class PluginMetadata(BaseModel):
    """Metadata contract describing a dynamic plugin loaded at runtime."""

    model_config = ConfigDict(frozen=True)

    name: str = Field(..., min_length=1, description="Unique identifier name of the plugin")
    version: str = Field(default="1.0.0", description="SemVer string of the plugin")
    description: str = Field(..., min_length=1, description="Human-readable explanation of plugin capability")
    author: str = Field(default="Unknown", description="Creator or maintainer of the plugin")
    commands: List[str] = Field(default_factory=list, description="Trigger keywords or slash commands")
    enabled: bool = Field(default=True, description="Whether the plugin is currently active")


class PluginExecutionResult(BaseModel):
    """Execution envelope returned when a dynamic plugin is invoked."""

    success: bool = Field(..., description="True if plugin executed cleanly without uncaught errors")
    plugin_name: str = Field(..., description="Target plugin identifier")
    output: str = Field(default="", description="Text response or formatted string result")
    data: Optional[Dict[str, Any]] = Field(default=None, description="Optional structured data dict")
    execution_time_ms: float = Field(default=0.0, ge=0.0, description="Duration in milliseconds")
    error: Optional[str] = Field(default=None, description="Error message if execution failed")


# ---------------------------------------------------------------------------
# Skill 2.2 — Live Code Sandbox DTOs
# ---------------------------------------------------------------------------

class SandboxExecutionRequest(BaseModel):
    """Request payload for executing code in an isolated subprocess."""

    language: str = Field(default="python", description="Programming language (python, javascript)")
    code: str = Field(..., min_length=1, description="Code snippet to execute")
    timeout_seconds: float = Field(default=10.0, ge=1.0, le=60.0, description="Maximum execution timeout")


class SandboxExecutionResult(BaseModel):
    """Result envelope from live code execution."""

    success: bool = Field(..., description="True if code executed with exit code 0")
    stdout: str = Field(default="", description="Standard output captured")
    stderr: str = Field(default="", description="Standard error output captured")
    execution_time_ms: float = Field(default=0.0, ge=0.0, description="Execution time in milliseconds")
    base64_image: Optional[str] = Field(default=None, description="Optional Base64 data URI of generated Matplotlib figure")
    error: Optional[str] = Field(default=None, description="Error explanation if execution failed")


# ---------------------------------------------------------------------------
# Skill 2.3 — Web Automation Agent DTOs
# ---------------------------------------------------------------------------

class WebScrapeRequest(BaseModel):
    """Request payload for dynamic web scraping and page automation."""

    url: str = Field(..., min_length=5, description="Target Web URL")
    extract_links: bool = Field(default=True, description="Whether to parse and return page hyperlinks")
    max_length: int = Field(default=5000, ge=100, description="Maximum character count of extracted text")


class WebScrapeResult(BaseModel):
    """Result payload from web scraping agent."""

    success: bool = Field(..., description="True if target URL was fetched and parsed")
    url: str = Field(..., description="Target URL")
    title: str = Field(default="", description="Page HTML title")
    text_content: str = Field(default="", description="Clean extracted body text")
    links: List[Dict[str, str]] = Field(default_factory=list, description="Extracted links (text, href)")
    error: Optional[str] = Field(default=None, description="Error details if fetch failed")


# ---------------------------------------------------------------------------
# Skill 2.4 — Personal MCP Gateway DTOs
# ---------------------------------------------------------------------------

class MCPTool(BaseModel):
    """Representation of an MCP (Model Context Protocol) tool specification."""

    name: str = Field(..., min_length=1, description="Tool function identifier")
    description: str = Field(..., min_length=1, description="Tool functionality description")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="JSON Schema parameter properties")


class MCPRequest(BaseModel):
    """JSON-RPC 2.0 Request payload for MCP Tool execution."""

    jsonrpc: str = Field(default="2.0")
    id: str = Field(default_factory=lambda: datetime.now().strftime("%Y%m%d%H%M%S%f"))
    method: str = Field(..., description="MCP method name (e.g. tools/call)")
    params: Dict[str, Any] = Field(default_factory=dict, description="Method arguments")


class MCPResponse(BaseModel):
    """JSON-RPC 2.0 Response payload from MCP Gateway."""

    jsonrpc: str = Field(default="2.0")
    id: str = Field(...)
    result: Optional[Dict[str, Any]] = Field(default=None)
    error: Optional[Dict[str, Any]] = Field(default=None)


# ---------------------------------------------------------------------------
# Skill 2.5 — Instant Voice Cloning DTOs
# ---------------------------------------------------------------------------

class VoiceProfile(BaseModel):
    """Metadata profile describing a cloned voice model."""

    model_config = ConfigDict(frozen=True)

    profile_id: str = Field(..., description="Unique voice profile ID")
    name: str = Field(..., min_length=1, description="Human readable voice label")
    language: str = Field(default="es", description="Primary language code")
    sample_file_path: str = Field(..., description="Path to reference audio sample file")
    created_at: str = Field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


class VoiceCloneResult(BaseModel):
    """Result of custom voice synthesis."""

    success: bool = Field(..., description="True if voice synthesis succeeded")
    profile_id: str = Field(..., description="Voice profile used")
    audio_base64: Optional[str] = Field(default=None, description="Base64 encoded audio string")
    mime_type: str = Field(default="audio/wav")
    error: Optional[str] = Field(default=None)


# ---------------------------------------------------------------------------
# Skill 2.7 — Interactive Dashboards (Plotly) DTOs
# ---------------------------------------------------------------------------

class PlotlyChartRequest(BaseModel):
    """Request payload to construct an interactive Plotly chart."""

    chart_type: Literal["bar", "line", "pie", "scatter"] = Field(default="bar")
    title: str = Field(default="Chart", description="Chart header title")
    labels: List[str] = Field(..., min_length=1, description="X-axis category labels or slice titles")
    values: List[float] = Field(..., min_length=1, description="Y-axis numeric values")
    series_name: str = Field(default="Values")


class PlotlyChartResult(BaseModel):
    """Result payload containing standalone HTML widget for PyWebView."""

    success: bool = Field(..., description="True if chart HTML was rendered")
    chart_type: str = Field(...)
    title: str = Field(...)
    html_widget: str = Field(default="", description="Self-contained HTML snippet with Plotly JS")
    error: Optional[str] = Field(default=None)


# ---------------------------------------------------------------------------
# Skill 2.1 — Persistent Memory (Local RAG) DTOs
# ---------------------------------------------------------------------------

class RAGDocument(BaseModel):
    """A document or text snippet indexed in the local vector memory."""

    doc_id: str = Field(..., min_length=1, description="Unique identifier for the document")
    text: str = Field(..., min_length=1, description="Content text indexed for vector retrieval")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Metadata tags (source, session_id, timestamp)")
    created_at: str = Field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


class RAGSearchResult(BaseModel):
    """A ranked search result returned from the local RAG vector engine."""

    doc_id: str = Field(..., description="Matched document identifier")
    text: str = Field(..., description="Content text snippet")
    score: float = Field(..., description="Cosine similarity score (0.0 to 1.0)")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Document metadata")


class RAGQueryPayload(BaseModel):
    """Request payload for querying local RAG memory."""

    query: str = Field(..., min_length=1, description="Search query string")
    top_k: int = Field(default=3, ge=1, le=20, description="Number of top results to retrieve")


# ---------------------------------------------------------------------------
# Skill 2.6 Ext — Prompt Injection Shield DTOs
# ---------------------------------------------------------------------------

class InjectionDetectionResult(BaseModel):
    """Result payload from Prompt Injection Guard analysis."""

    is_suspicious: bool = Field(..., description="True if prompt injection or jailbreak patterns detected")
    risk_score: float = Field(default=0.0, ge=0.0, le=1.0, description="Heuristic risk score between 0.0 and 1.0")
    detected_patterns: List[str] = Field(default_factory=list, description="Matched injection or jailbreak signatures")
    sanitized_text: str = Field(..., description="Prompt text with injection patterns neutralized or masked")
    reason: Optional[str] = Field(default=None, description="Explanation if suspicious injection was detected")




