# Router module for backwards compatibility
# Import classes and functions for backwards compatibility
from backend.core.semaphore import AdjustableSemaphore, Semaphore
from backend.processors.alibabacloud_processor import AlibabaCloudChat
from backend.processors.anthropic_processor import AnthropicChat
from backend.processors.base_processor import (
    ALIBABACLOUD_PROFILE_PICTURE_PATH,
    ANTHROPIC_PROFILE_PICTURE_PATH,
    DEEPSEEK_BASE_URL,
    DEEPSEEK_PROFILE_PICTURE_PATH,
    GEMINI_PROFILE_PICTURE_PATH,
    GROK_BASE_URL,
    GROK_PROFILE_PICTURE_PATH,
    OPENAI_AVAILABLE_MODELS_DEFAULT,
    OPENAI_PROFILE_PICTURE_PATH,
    PERPLEXITY_BASE_URL,
    PERPLEXITY_PROFILE_PICTURE_PATH,
    USER_DESKTOP_PATH,
    USER_DOCUMENTS_PATH,
    USER_DOWNLOADS_PATH,
    USER_NAME,
    USER_PICTURES_PATH,
    USER_PROFILE_PICTURE_PATH,
    USER_SYSTEM_DARK_MODE,
    USER_SYSTEM_LANGUAGE,
    USER_SYSTEM_TIMEZONE,
    BaseChat,
    get_assistant_logger,
    get_current_date_and_time_strings,
    resolve_lang_name,
)
from backend.processors.deepseek_processor import DeepSeekChat
from backend.processors.gemini_processor import GeminiChat
from backend.processors.grok_processor import GrokChat
from backend.processors.openai_processor import OpenAIChat
from backend.processors.perplexity_processor import PerplexityChat

__all__ = [
    "BaseChat",
    "GeminiChat",
    "DeepSeekChat",
    "OpenAIChat",
    "AnthropicChat",
    "PerplexityChat",
    "GrokChat",
    "AlibabaCloudChat",
    "Semaphore",
    "AdjustableSemaphore",
    "USER_NAME",
    "USER_SYSTEM_LANGUAGE",
    "USER_SYSTEM_TIMEZONE",
    "USER_SYSTEM_DARK_MODE",
    "USER_DESKTOP_PATH",
    "USER_DOWNLOADS_PATH",
    "USER_DOCUMENTS_PATH",
    "USER_PICTURES_PATH",
    "USER_PROFILE_PICTURE_PATH",
    "GEMINI_PROFILE_PICTURE_PATH",
    "OPENAI_PROFILE_PICTURE_PATH",
    "OPENAI_AVAILABLE_MODELS_DEFAULT",
    "DEEPSEEK_BASE_URL",
    "DEEPSEEK_PROFILE_PICTURE_PATH",
    "ANTHROPIC_PROFILE_PICTURE_PATH",
    "PERPLEXITY_BASE_URL",
    "PERPLEXITY_PROFILE_PICTURE_PATH",
    "ALIBABACLOUD_PROFILE_PICTURE_PATH",
    "GROK_BASE_URL",
    "GROK_PROFILE_PICTURE_PATH",
    "resolve_lang_name",
    "get_current_date_and_time_strings",
    "get_assistant_logger",
]
