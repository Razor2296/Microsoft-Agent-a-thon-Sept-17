"""
app/backend
Modular subpackages for Ignite Chat:
- core: DTOs, library wrappers, concurrency, telemetry, runtime identity
- processors: AI model providers (Gemini, DeepSeek, OpenAI, Anthropic, Grok, Perplexity, AlibabaCloud)
- voice: Faster-Whisper STT, Cartesia TTS, voice profile helper (not neural cloning)
- integrations: Ignite API client, document extraction & RAG transformers
- tools: Local RAG, code sandbox, BeautifulSoup web agent, MCP gateway, guardrails, Plotly
- user: Windows user profile & avatar integration
"""

# Re-exports for backward compatibility
from backend.core import telemetry
from backend.core.libraries import get_assistant_logger, get_logger
from backend.core.schemas import ChatMessage, TokenInfo
from backend.processors.base_processor import BaseChat

__all__ = [
    "ChatMessage",
    "TokenInfo",
    "BaseChat",
    "get_assistant_logger",
    "get_logger",
    "telemetry",
]

