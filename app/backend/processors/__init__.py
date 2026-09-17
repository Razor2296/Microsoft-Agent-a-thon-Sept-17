"""AI model processor implementations and factory interface."""

# Base chat and constants from base_processor
from backend.processors.base_processor import (
    ALIBABACLOUD_PROFILE_PICTURE_PATH,
    ANTHROPIC_PROFILE_PICTURE_PATH,
    DEEPSEEK_PROFILE_PICTURE_PATH,
    GEMINI_PROFILE_PICTURE_PATH,
    GROK_PROFILE_PICTURE_PATH,
    OPENAI_AVAILABLE_MODELS_DEFAULT,
    OPENAI_PROFILE_PICTURE_PATH,
    PERPLEXITY_PROFILE_PICTURE_PATH,
    USER_PROFILE_PICTURE_PATH,
    USER_SYSTEM_LANGUAGE,
    BaseChat,
)
from backend.processors.cost_calculator import (
    calculate_cost_usd,
    calculate_media_cost_usd,
)

# Concrete AI model processor classes
from backend.processors.alibabacloud_processor import AlibabaCloudChat
from backend.processors.anthropic_processor import AnthropicChat
from backend.processors.deepseek_processor import DeepSeekChat
from backend.processors.gemini_processor import GeminiChat
from backend.processors.grok_processor import GrokChat
from backend.processors.openai_processor import OpenAIChat
from backend.processors.perplexity_processor import PerplexityChat

# List of all imports - makes imports more accessible in other modules
__all__ = [
    "BaseChat",
    "GeminiChat",
    "DeepSeekChat",
    "OpenAIChat",
    "AnthropicChat",
    "PerplexityChat",
    "GrokChat",
    "AlibabaCloudChat",
    "calculate_cost_usd",
    "calculate_media_cost_usd",
    "USER_PROFILE_PICTURE_PATH",
    "GEMINI_PROFILE_PICTURE_PATH",
    "OPENAI_PROFILE_PICTURE_PATH",
    "OPENAI_AVAILABLE_MODELS_DEFAULT",
    "DEEPSEEK_PROFILE_PICTURE_PATH",
    "ANTHROPIC_PROFILE_PICTURE_PATH",
    "PERPLEXITY_PROFILE_PICTURE_PATH",
    "ALIBABACLOUD_PROFILE_PICTURE_PATH",
    "GROK_PROFILE_PICTURE_PATH",
    "USER_SYSTEM_LANGUAGE",
]
