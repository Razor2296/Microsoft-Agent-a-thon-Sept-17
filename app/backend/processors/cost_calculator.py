"""
app/backend/cost_calculator.py
Dynamic USD Cost Calculator per 1M tokens — fully driven by environment configuration (.env).
Strict anti-hardcoding compliance (Skill: buenas-practicas-coding § 2).
"""
import os
import re
from typing import Tuple


def get_model_pricing_from_env(model_name: str) -> Tuple[float, float]:
    """
    Dynamically retrieve (input_price_per_1m, output_price_per_1m) in USD for any model
    from environment variables loaded from .env.

    1. Checks MODEL_PRICE_<NORMALIZED_NAME>_INPUT and _OUTPUT
    2. Falls back to PROVIDER_DEFAULT_PRICING_<PROVIDER>_INPUT and _OUTPUT
    3. Default fallback if unconfigured: (1.00, 4.00)
    """
    if not model_name:
        return (0.0, 0.0)

    clean_name = model_name.strip()
    norm_key = re.sub(r'[^A-Za-z0-9]+', '_', clean_name).upper().strip('_')

    # 1. Direct env lookup for specific model override
    env_in = os.getenv(f"MODEL_PRICE_{norm_key}_INPUT")
    env_out = os.getenv(f"MODEL_PRICE_{norm_key}_OUTPUT")

    if env_in is not None and env_out is not None:
        try:
            return (float(env_in), float(env_out))
        except ValueError:
            pass

    # 2. Determine provider and lookup provider default from env
    clean_lower = clean_name.lower()
    provider = "OPENAI"
    if "gemini" in clean_lower:
        provider = "GEMINI"
    elif "claude" in clean_lower or "anthropic" in clean_lower:
        provider = "ANTHROPIC"
    elif "deepseek" in clean_lower:
        provider = "DEEPSEEK"
    elif "sonar" in clean_lower or "perplexity" in clean_lower:
        provider = "PERPLEXITY"
    elif "grok" in clean_lower or "xai" in clean_lower:
        provider = "GROK"
    elif "qwen" in clean_lower or "alibaba" in clean_lower:
        provider = "ALIBABACLOUD"

    prov_in = os.getenv(f"PROVIDER_DEFAULT_PRICING_{provider}_INPUT", "1.00")
    prov_out = os.getenv(f"PROVIDER_DEFAULT_PRICING_{provider}_OUTPUT", "4.00")

    try:
        return (float(prov_in), float(prov_out))
    except ValueError:
        return (1.00, 4.00)


def calculate_cost_usd(
    model_name: str,
    prompt_tokens: int,
    completion_tokens: int,
    thinking_tokens: int = 0
) -> float:
    """
    Calculate the estimated cost in USD for a given token breakdown.

    Args:
        model_name: The name or identifier of the LLM model.
        prompt_tokens: Number of prompt/input tokens.
        completion_tokens: Number of completion/output tokens.
        thinking_tokens: Internal reasoning tokens.

    Returns:
        float: Estimated cost in USD rounded to 6 decimal places.
    """
    if not model_name:
        return 0.0

    input_rate, output_rate = get_model_pricing_from_env(model_name)
    total_output_tokens = completion_tokens + thinking_tokens

    cost = (prompt_tokens * input_rate / 1_000_000.0) + (total_output_tokens * output_rate / 1_000_000.0)
    return round(max(0.0, cost), 6)


def calculate_media_cost_usd(model_name: str, count: int = 1) -> float:
    """Calculate media generation cost in USD from environment variable or fallback."""
    if not model_name:
        return 0.0
    clean_name = model_name.strip()
    norm_key = re.sub(r'[^A-Za-z0-9]+', '_', clean_name).upper().strip('_')

    env_media = os.getenv(f"MEDIA_PRICE_{norm_key}")
    if env_media is not None:
        try:
            return round(float(env_media) * count, 6)
        except ValueError:
            pass

    # Default per-unit media fallback from env
    default_media = float(os.getenv("DEFAULT_MEDIA_PRICE_USD", "0.03"))
    return round(default_media * count, 6)
